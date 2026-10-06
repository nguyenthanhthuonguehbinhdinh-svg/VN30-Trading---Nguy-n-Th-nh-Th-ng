"""Chạy hằng ngày.

  python -m engine.run --mode auto      # tự chọn preview (trước 14:50) / close (sau 14:50)
  python -m engine.run --mode preview   # tín hiệu dự kiến trong phiên (để đặt lệnh ATC)
  python -m engine.run --mode close     # chốt sổ cuối ngày: khớp lệnh giấy giá đóng cửa
  python -m engine.run --demo           # dữ liệu mô phỏng (test giao diện, không cần mạng)
  python -m engine.run --reset-live     # xoá sổ live, bắt đầu lại với 100tr
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import pandas as pd

from . import data as D
from .core import Simulator, signal_board, performance, _f
from .indicators import add_stock_indicators, add_index_indicators, round_tick

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data"
STATE = ROOT / "state" / "portfolio.json"
PREVIEW_DECISION = ROOT / "state" / "preview_decision.json"
CLOSE_CUTOFF = (14, 50)   # sau giờ này coi nến ngày là đã đóng


def jdump(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_f), encoding="utf-8")


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def build_panel(raw: dict, vni_raw, cfg):
    panel = {t: add_stock_indicators(df, cfg) for t, df in raw.items() if len(df) > 60}
    vni = add_index_indicators(vni_raw, cfg) if vni_raw is not None else None
    if vni is not None:
        cal = list(vni.index)
    else:
        cal = sorted(set().union(*[set(df.index) for df in panel.values()]))
    return panel, vni, cal


def chart_payload(panel, vni, bars=260):
    out = {}
    for t, df in list(panel.items()) + ([("VNINDEX", vni)] if vni is not None else []):
        sub = df.tail(bars)
        rec = {"d": [str(x.date()) for x in sub.index]}
        for k in ["open", "high", "low", "close", "volume", "ma10", "ma50", "hh55", "ma200", "rsi"]:
            if k in sub.columns:
                rec[k[:5]] = [None if pd.isna(v) else round(float(v), 2) for v in sub[k]]
        out[t] = rec
    return out


def rt(x, mode="down"):
    return round_tick(x, mode) if x else None


def positions_view(sim: Simulator, date):
    rows = []
    for t, p in sim.positions.items():
        df = sim.panel.get(t)
        r = df.loc[:date].iloc[-1] if df is not None else None
        px = float(r["close"]) if r is not None else p.last_close
        lv = p.levels(sim.cfg, r["atr"] if r is not None else None)
        held = sim.bars_held(p, pd.Timestamp(date))
        value = p.qty * px
        net_exit = value * (1 - sim.cfg["fees"]["sell_fee"] - sim.cfg["fees"]["sell_tax"])
        rows.append({"ticker": t, "strategy": p.strategy, "entry_date": p.entry_date,
                     "entry_price": p.entry_price, "qty": p.qty, "cost": p.cost, "price": px,
                     "value": value, "pnl_gross": px / p.entry_price - 1,
                     "pnl_net": (net_exit - p.cost) / p.cost, "pnl_vnd": net_exit - p.cost,
                     "peak": p.peak, "bars": held, "sellable": held >= sim.cfg["settlement_days"],
                     "stop": _f(rt(lv["stop"])), "trail": _f(rt(lv["trail"])),
                     "exit_level": _f(rt(lv["exit_level"])), "take_profit": _f(rt(lv["take_profit"], "up")),
                     "dist_exit": (px / lv["exit_level"] - 1) if lv["exit_level"] else None,
                     "chg": _f(r["chg"]) if r is not None else None})
    rows.sort(key=lambda x: -x["value"])
    return rows


def run_backtest(cfg, panel, vni, cal):
    start = pd.Timestamp(cfg["backtest_start"])
    sim = Simulator(cfg, panel, vni, cal)
    days = [d for d in cal if d >= start]
    for d in days:
        sim.step(d)
    perf = performance(sim.nav_history, sim.trades, cfg["initial_capital"])
    return {"config": {k: cfg[k] for k in ["initial_capital", "backtest_start", "fees", "max_positions",
                                            "top_n_signals", "breakout", "sideway"]},
            "metrics": perf, "nav_history": sim.nav_history, "trades": sim.trades,
            "orders": sim.orders[-400:], "open_positions": positions_view(sim, days[-1]) if days else []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="auto", choices=["auto", "preview", "close"])
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--reset-live", action="store_true")
    ap.add_argument("--no-backtest", action="store_true")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    now = D.now_vn()
    today = pd.Timestamp(now.date())
    after_close = (now.hour, now.minute) >= CLOSE_CUTOFF
    mode = args.mode if args.mode != "auto" else ("close" if after_close or now.weekday() >= 5 else "preview")
    print(f"== VN30 engine | {now:%Y-%m-%d %H:%M} ICT | mode={mode} | demo={args.demo}")

    # ---------------------------------------------------------- dữ liệu
    fetch_start = min(pd.Timestamp(cfg["backtest_start"]),
                      pd.Timestamp(cfg.get("live_start_date") or today)) - timedelta(days=500)
    if args.demo:
        from .demo import make_demo
        symbols = sorted(cfg.get("vn30_override") or cfg["vn30_fallback"])
        raw, vni_raw = make_demo(symbols, fetch_start, today)
        sources, errors, list_src = {s: "DEMO" for s in symbols}, [], "demo"
    else:
        symbols, list_src = (sorted(cfg["vn30_override"]), "config") if cfg.get("vn30_override") \
            else D.fetch_vn30_list(cfg["vn30_fallback"])
        print(f"VN30 ({list_src}): {', '.join(symbols)}")
        raw, vni_raw, sources, errors = D.fetch_universe(symbols, fetch_start.to_pydatetime())
        if not raw:
            raise SystemExit("Không lấy được dữ liệu cổ phiếu nào -> dừng, giữ nguyên dữ liệu cũ.")

    # nến hôm nay có thể đang chạy (chưa đóng cửa)
    partial_today = (not after_close) and now.weekday() < 5
    if mode == "close" and partial_today:
        raw = {t: df[df.index < today] for t, df in raw.items()}
        vni_raw = vni_raw[vni_raw.index < today] if vni_raw is not None else None

    panel, vni, cal = build_panel(raw, vni_raw, cfg)
    if not cal:
        raise SystemExit("Không có lịch giao dịch.")
    last_bar = cal[-1]

    # ---------------------------------------------------------- live
    global STATE
    if args.demo:
        STATE = ROOT / "state" / "demo_portfolio.json"
    state = None if (args.reset_live or args.demo) else load_json(STATE)
    if not state:
        start = pd.Timestamp(cfg.get("live_start_date") or (last_bar if mode == "close" else today))
        if args.demo:
            start = cal[-130]
        state = {"start_date": str(start.date()), "initial_capital": cfg["initial_capital"],
                 "cash": cfg["initial_capital"]}
        print(f"Tạo sổ live mới, bắt đầu {state['start_date']} với {cfg['initial_capital']:,.0f}đ")
    live_start = pd.Timestamp(state["start_date"])
    sim = Simulator(cfg, panel, vni, cal, state)
    if not args.demo:
        sim.apply_corporate_actions()

    meta = {"generated_at": now.strftime("%Y-%m-%d %H:%M"), "mode": mode, "demo": args.demo,
            "last_bar": str(last_bar.date()), "symbols": list(panel.keys()), "list_source": list_src,
            "sources": sources, "errors": errors[:20]}

    if mode == "preview":
        decision = sim.decide(last_bar)
        board = signal_board(sim, last_bar, decision, None)
        preview = {**meta, "date": str(last_bar.date()), "is_today": last_bar == today,
                   "decision": decision, "board": board,
                   "positions": positions_view(sim, last_bar)}
        jdump(preview, OUT / "preview.json")
        if last_bar == today and not args.demo:
            jdump({"date": str(today.date()), "time": now.strftime("%H:%M"), "decision": decision},
                  PREVIEW_DECISION)
        print(f"Preview {last_bar.date()}: bán {[s['ticker'] for s in decision['sells']]} "
              f"mua {[b['ticker'] for b in decision['buys']]}")
        return

    # ---- close: xử lý mọi phiên chưa chốt (tự bù nếu lỡ ngày)
    done = pd.Timestamp(sim.last_date) if sim.last_date else None
    todo = [d for d in cal if d >= live_start and (done is None or d > done)]
    pre = load_json(PREVIEW_DECISION, {}) if cfg.get("use_preview_decisions") else {}
    reports = []
    for d in todo:
        dec = None
        if pre and pre.get("date") == str(d.date()):
            dec = pre["decision"]
            dec_auto = sim.decide(d)
            dec["candidates"] = dec_auto["candidates"]
            print(f"  {d.date()}: dùng quyết định lúc {pre.get('time')} (preview)")
        rep = sim.step(d, dec)
        reports.append(rep)
        for o in rep["orders"]:
            print(f"  {o['date']} {o['side']:<3} {o['ticker']:<4} {o['qty']:>6} @ {o['price']:>9,.0f}  {o['note']}")
    last_rep = reports[-1] if reports else None
    board_date = pd.Timestamp(sim.last_date) if sim.last_date else last_bar
    decision = last_rep["decision"] if last_rep else sim.decide(board_date)
    board = signal_board(sim, board_date, decision, last_rep["orders"] if last_rep else [])

    # kế hoạch phiên tới: danh sách theo dõi gần điểm kích hoạt
    watch = sorted([b for b in board if b["action"] == "CHỜ" and b.get("dist_breakout") is not None],
                   key=lambda x: x["dist_breakout"])[:8]

    state_out = {**state, **sim.to_state()}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state_out, ensure_ascii=False, indent=1, default=_f), encoding="utf-8")

    live = {**meta, "start_date": state["start_date"], "initial_capital": cfg["initial_capital"],
            "as_of": sim.last_date, "cash": sim.cash, "nav": sim.nav(board_date),
            "market": decision["market"], "today_orders": last_rep["orders"] if last_rep else [],
            "skipped": last_rep["skipped"] if last_rep else [],
            "positions": positions_view(sim, board_date), "board": board, "watch": watch,
            "orders": sim.orders[-300:], "trades": sim.trades, "nav_history": sim.nav_history,
            "events": sim.events[-50:],
            "metrics": performance(sim.nav_history, sim.trades, cfg["initial_capital"]),
            "fees": cfg["fees"], "max_positions": cfg["max_positions"]}
    jdump(live, OUT / "live.json")
    jdump(chart_payload(panel, vni), OUT / "charts.json")
    if PREVIEW_DECISION.exists() and load_json(PREVIEW_DECISION, {}).get("date", "") <= str(board_date.date()):
        PREVIEW_DECISION.unlink()

    if not args.no_backtest:
        bt = run_backtest(cfg, panel, vni, cal)
        bt.update({"generated_at": meta["generated_at"], "demo": args.demo})
        jdump(bt, OUT / "backtest.json")
        m = bt["metrics"]
        if m:
            print(f"Backtest {m['start']}→{m['end']}: lợi nhuận {m['total_return']:.1%} | VNINDEX "
                  f"{(m['benchmark_return'] or 0):.1%} | MDD {m['max_drawdown']:.1%} | {m['n_trades']} lệnh")
    print(f"Live NAV {sim.nav(board_date):,.0f}đ | tiền mặt {sim.cash:,.0f}đ | {len(sim.positions)} mã")


if __name__ == "__main__":
    main()

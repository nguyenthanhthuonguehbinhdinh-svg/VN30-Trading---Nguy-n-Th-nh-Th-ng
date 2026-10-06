"""Luật chiến lược + mô phỏng khớp lệnh theo cơ chế thị trường chứng khoán Việt Nam.

Cơ chế khớp lệnh (giả định đặt lệnh ATC ~14:40, khớp giá đóng cửa):
  * Lô chẵn 100 cổ phiếu (HOSE).
  * Phí môi giới mua/bán (mặc định 0,15%) + thuế TNCN 0,1% trên giá trị bán.
  * T+2: cổ phiếu mua phiên T về tài khoản chiều T+2 -> chỉ bán được từ phiên T+2.
  * Tiền bán được dùng mua ngay trong phiên (sức mua ứng trước như các CTCK).
  * Bán trước, mua sau. Mã vừa bán trong ngày không mua lại cùng ngày.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from .indicators import rsi_trigger_price, round_tick


def _f(x):
    """float an toàn cho JSON."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(x) or math.isinf(x)) else x


# =========================================================== thị trường
def market_status(vni: pd.DataFrame | None, date) -> dict:
    if vni is None or date not in vni.index:
        return {"ok": False, "close": None, "ma50": None, "ma200": None,
                "breakout_ok": False, "sideway_ok": False, "chg": None,
                "note": "Không có dữ liệu VNINDEX -> không mở lệnh mới"}
    r = vni.loc[date]
    bo = bool(r["close"] > r["ma50"]) if not np.isnan(r["ma50"]) else False
    sw = bool(r["close"] > r["ma200"]) if not np.isnan(r["ma200"]) else False
    return {"ok": True, "close": _f(r["close"]), "ma50": _f(r["ma50"]), "ma200": _f(r["ma200"]),
            "chg": _f(r["chg"]), "breakout_ok": bo, "sideway_ok": sw, "note": ""}


# =========================================================== tín hiệu mua
def entry_signal(row: pd.Series, mkt: dict, cfg: dict) -> dict | None:
    s = cfg["sideway"]
    vals = [row.get(k) for k in ("close", "hh55", "ma10", "ma50")]
    if any(v is None or np.isnan(v) for v in vals):
        return None
    close = row["close"]
    if (close > row["hh55"] and close > row["ma50"] and row["ma10"] > row["ma50"]
            and mkt["breakout_ok"]):
        roc = row["roc60"] if not np.isnan(row["roc60"]) else 0.0
        return {"type": "BREAKOUT", "label": "BREAKOUT – NÊN MUA", "priority": "Cao",
                "score": 300 + roc * 100}
    if not np.isnan(row["rsi"]) and row["rsi"] <= s["rsi_buy"] and mkt["sideway_ok"]:
        if row["gap"] < s["flat_gap"]:
            return {"type": "SIDEWAY", "label": "SIDEWAY – NÊN MUA", "priority": "Cao",
                    "score": 100 + (s["rsi_buy"] - row["rsi"])}
        return {"type": "SIDEWAY_T", "label": "QUÁ BÁN – LƯỚT T+", "priority": "Thấp",
                "score": 50 + (s["rsi_buy"] - row["rsi"])}
    return None


# =========================================================== vị thế
@dataclass
class Position:
    ticker: str
    strategy: str            # BREAKOUT | SIDEWAY | SIDEWAY_T
    entry_date: str
    entry_price: float
    qty: int
    cost: float              # tổng tiền bỏ ra (gồm phí mua)
    buy_fee: float
    peak: float              # giá đóng cửa cao nhất từ khi mua
    last_close: float
    last_date: str
    score: float = 0.0
    adjustments: list = field(default_factory=list)

    def levels(self, cfg: dict, atr_val: float | None) -> dict:
        b, s = cfg["breakout"], cfg["sideway"]
        if self.strategy == "BREAKOUT":
            stop = self.entry_price * (1 - b["hard_stop"])
            trail = (self.peak - b["atr_mult"] * atr_val) if atr_val and not np.isnan(atr_val) else None
            exit_lv = max(stop, trail) if trail is not None else stop
            return {"stop": stop, "trail": trail, "exit_level": exit_lv, "take_profit": None}
        tp = self.entry_price * (1 + s["take_profit"])
        sl = self.entry_price * (1 - s["stop_loss"])
        return {"stop": sl, "trail": None, "exit_level": sl, "take_profit": tp}


def exit_reason(pos: Position, row: pd.Series, bars_held: int, cfg: dict) -> str | None:
    b, s = cfg["breakout"], cfg["sideway"]
    c = row["close"]
    if pos.strategy == "BREAKOUT":
        if c <= pos.entry_price * (1 - b["hard_stop"]) + 1e-9:
            return "STOP_8%"
        if not np.isnan(row["atr"]) and c <= pos.peak - b["atr_mult"] * row["atr"]:
            return "TRAILING_ATR"
        if bars_held >= b["max_hold_days"]:
            return "HET_HAN_365"
        return None
    ret = c / pos.entry_price - 1
    if ret >= s["take_profit"] - 1e-9:
        return "CHOT_LOI"
    if ret <= -s["stop_loss"] + 1e-9:
        return "CAT_LO"
    return None


REASON_VN = {
    "STOP_8%": "Cắt lỗ cứng -8%",
    "TRAILING_ATR": "Trailing stop 4×ATR",
    "HET_HAN_365": "Hết hạn 365 phiên",
    "CHOT_LOI": "Chốt lời +6,5%",
    "CAT_LO": "Cắt lỗ -5%",
}


# =========================================================== mô phỏng
class Simulator:
    def __init__(self, cfg: dict, panel: dict[str, pd.DataFrame], vni: pd.DataFrame | None,
                 calendar: list[pd.Timestamp], state: dict | None = None):
        self.cfg = cfg
        self.panel = panel
        self.vni = vni
        self.cal = calendar
        self.cal_idx = {d: i for i, d in enumerate(calendar)}
        st = state or {}
        self.cash = float(st.get("cash", cfg["initial_capital"]))
        self.positions: dict[str, Position] = {
            k: Position(**v) for k, v in st.get("positions", {}).items()}
        self.trades: list[dict] = st.get("trades", [])
        self.orders: list[dict] = st.get("orders", [])
        self.nav_history: list[dict] = st.get("nav_history", [])
        self.events: list[dict] = st.get("events", [])
        self.last_date: str | None = st.get("last_date")

    # ---------------------------------------------------------- helpers
    def bars_held(self, pos: Position, date) -> int:
        e = pd.Timestamp(pos.entry_date)
        if e in self.cal_idx and date in self.cal_idx:
            return self.cal_idx[date] - self.cal_idx[e]
        return len([d for d in self.cal if e < d <= date])

    def row(self, ticker, date):
        df = self.panel.get(ticker)
        if df is None or date not in df.index:
            return None
        return df.loc[date]

    def last_price(self, ticker, date) -> float | None:
        df = self.panel.get(ticker)
        if df is None:
            return None
        sub = df.loc[:date]
        return float(sub["close"].iloc[-1]) if len(sub) else None

    def nav(self, date) -> float:
        v = self.cash
        for t, p in self.positions.items():
            px = self.last_price(t, date) or p.last_close
            v += p.qty * px
        return v

    # ---------------------------------------------------------- điều chỉnh quyền
    def apply_corporate_actions(self):
        """Nguồn dữ liệu điều chỉnh giá quá khứ khi có cổ tức/chia tách.
        So giá đóng cửa đã lưu với giá mới tại cùng ngày -> điều chỉnh vị thế để không
        kích hoạt cắt lỗ giả."""
        for t, p in self.positions.items():
            df = self.panel.get(t)
            d = pd.Timestamp(p.last_date)
            if df is None or d not in df.index or not p.last_close:
                continue
            f = float(df.loc[d, "close"]) / p.last_close
            if abs(f - 1) > 0.003:
                old_qty = p.qty
                p.entry_price *= f
                p.peak *= f
                p.last_close *= f
                p.qty = int(round(p.qty / f))
                p.adjustments.append({"date": p.last_date, "factor": round(f, 5)})
                self.events.append({"date": str(d.date()), "ticker": t, "type": "DIEU_CHINH_QUYEN",
                                    "msg": f"Điều chỉnh quyền hệ số {f:.4f}: {old_qty}→{p.qty} cp"})

    # ---------------------------------------------------------- quyết định
    def decide(self, date, rows_override: dict | None = None) -> dict:
        """Tính danh sách bán / mua dự kiến tại `date` (không khớp lệnh)."""
        get = (lambda t: rows_override.get(t)) if rows_override else (lambda t: self.row(t, date))
        mkt = market_status(self.vni, date)
        sells, blocked = [], []
        for t, p in self.positions.items():
            r = get(t)
            if r is None:
                continue
            peak = max(p.peak, float(r["close"]))
            tmp = Position(**{**asdict(p), "peak": peak})
            reason = exit_reason(tmp, r, self.bars_held(p, date), self.cfg)
            if reason:
                if self.bars_held(p, date) < self.cfg["settlement_days"]:
                    blocked.append({"ticker": t, "reason": reason})
                else:
                    sells.append({"ticker": t, "reason": reason})
        sold = {s["ticker"] for s in sells}
        cands = []
        for t in self.panel:
            r = get(t)
            if r is None:
                continue
            sig = entry_signal(r, mkt, self.cfg)
            if sig:
                cands.append({"ticker": t, **sig, "price": float(r["close"])})
        cands.sort(key=lambda x: -x["score"])
        buys = [c for c in cands if c["ticker"] not in self.positions and c["ticker"] not in sold]
        buys = buys[: self.cfg["top_n_signals"]]
        return {"date": str(pd.Timestamp(date).date()), "market": mkt, "sells": sells,
                "blocked": blocked, "candidates": cands, "buys": buys}

    # ---------------------------------------------------------- khớp lệnh
    def step(self, date, decision: dict | None = None) -> dict:
        cfg, fees = self.cfg, self.cfg["fees"]
        ds = str(pd.Timestamp(date).date())
        auto = self.decide(date)
        decision = decision or auto
        today_orders = []

        # update peak cho các vị thế
        for t, p in self.positions.items():
            r = self.row(t, date)
            if r is not None:
                p.peak = max(p.peak, float(r["close"]))

        # ---- BÁN
        for s in decision["sells"]:
            t = s["ticker"]
            p = self.positions.get(t)
            r = self.row(t, date)
            if p is None or r is None or self.bars_held(p, date) < cfg["settlement_days"]:
                continue
            px = float(r["close"])
            value = p.qty * px
            fee = round(value * fees["sell_fee"])
            tax = round(value * fees["sell_tax"])
            proceeds = value - fee - tax
            self.cash += proceeds
            pnl = proceeds - p.cost
            trade = {"ticker": t, "strategy": p.strategy, "entry_date": p.entry_date,
                     "entry_price": p.entry_price, "exit_date": ds, "exit_price": px, "qty": p.qty,
                     "cost": round(p.cost), "proceeds": round(proceeds), "buy_fee": round(p.buy_fee),
                     "sell_fee": fee, "tax": tax, "pnl": round(pnl), "ret": pnl / p.cost,
                     "bars": self.bars_held(p, date), "reason": s["reason"],
                     "reason_vn": REASON_VN.get(s["reason"], s["reason"])}
            self.trades.append(trade)
            order = {"date": ds, "side": "BÁN", "ticker": t, "price": px, "qty": p.qty,
                     "value": round(value), "fee": fee, "tax": tax, "net": round(proceeds),
                     "strategy": p.strategy, "note": trade["reason_vn"], "pnl": round(pnl),
                     "ret": trade["ret"]}
            self.orders.append(order)
            today_orders.append(order)
            del self.positions[t]

        # ---- MUA
        nav_now = self.nav(date)
        slot_value = nav_now / cfg["max_positions"]
        skipped = []
        for c in decision["buys"]:
            if len(self.positions) >= cfg["max_positions"]:
                skipped.append({**c, "why": "Hết slot (tối đa 5 mã)"})
                continue
            t = c["ticker"]
            r = self.row(t, date)
            if t in self.positions or r is None:
                continue
            px = float(r["close"])
            budget = min(slot_value, self.cash)
            lot = cfg["lot_size"]
            qty = int(budget / (px * (1 + fees["buy_fee"])) // lot * lot)
            if qty <= 0:
                skipped.append({**c, "why": "Không đủ tiền cho 1 lô 100 cp"})
                continue
            value = qty * px
            fee = round(value * fees["buy_fee"])
            self.cash -= value + fee
            self.positions[t] = Position(ticker=t, strategy=c["type"], entry_date=ds, entry_price=px,
                                         qty=qty, cost=value + fee, buy_fee=fee, peak=px,
                                         last_close=px, last_date=ds, score=round(c["score"], 2))
            order = {"date": ds, "side": "MUA", "ticker": t, "price": px, "qty": qty,
                     "value": round(value), "fee": fee, "tax": 0, "net": -round(value + fee),
                     "strategy": c["type"], "note": c["label"], "score": round(c["score"], 2)}
            self.orders.append(order)
            today_orders.append(order)

        # ---- đánh giá cuối ngày
        for t, p in self.positions.items():
            px = self.last_price(t, date)
            if px:
                p.last_close, p.last_date = px, ds
        nav = self.nav(date)
        vni_close = _f(self.vni.loc[date, "close"]) if self.vni is not None and date in self.vni.index else None
        self.nav_history.append({"date": ds, "nav": round(nav), "cash": round(self.cash),
                                 "invested": round(nav - self.cash), "n_pos": len(self.positions),
                                 "vnindex": vni_close})
        self.last_date = ds
        return {"date": ds, "decision": decision, "orders": today_orders, "skipped": skipped, "nav": nav}

    # ---------------------------------------------------------- state
    def to_state(self) -> dict:
        return {"cash": self.cash, "positions": {k: asdict(v) for k, v in self.positions.items()},
                "trades": self.trades, "orders": self.orders, "nav_history": self.nav_history,
                "events": self.events, "last_date": self.last_date}


# =========================================================== báo cáo tín hiệu VN30
def signal_board(sim: Simulator, date, decision: dict, today_orders: list[dict] | None = None) -> list[dict]:
    """Bảng 30 mã: hành động (MUA/BÁN/GIỮ/CHỜ) + các mốc giá.
    today_orders=None  -> chế độ xem trước (chưa khớp): ước tính slot trống.
    today_orders=list  -> sau khi khớp lệnh cuối ngày."""
    cfg = sim.cfg
    cand = {c["ticker"]: c for c in decision["candidates"]}
    if today_orders is None:
        sell_map = {s["ticker"]: s for s in decision["sells"]}
        free = cfg["max_positions"] - len(sim.positions) + len(sell_map)
        buy_list = [b["ticker"] for b in decision["buys"]]
        bought = set(buy_list[:max(free, 0)])
        buy_set = set(buy_list)
    else:
        sell_map = {o["ticker"]: {"reason": None, "note": o["note"]} for o in today_orders if o["side"] == "BÁN"}
        bought = {o["ticker"] for o in today_orders if o["side"] == "MUA"}
        buy_set = {b["ticker"] for b in decision["buys"]} | bought
    executed = bought
    blocked = {b["ticker"]: b for b in decision.get("blocked", [])}
    out = []
    for t, df in sorted(sim.panel.items()):
        sub = df.loc[:date]
        if sub.empty:
            continue
        r = sub.iloc[-1]
        close = float(r["close"])
        item = {"ticker": t, "date": str(sub.index[-1].date()), "close": close, "chg": _f(r["chg"]),
                "ma10": _f(r["ma10"]), "ma50": _f(r["ma50"]), "rsi": _f(r["rsi"]), "atr": _f(r["atr"]),
                "roc60": _f(r["roc60"]), "gap": _f(r["gap"]), "hh55": _f(r["hh55"]),
                "volume": _f(r["volume"])}
        # mốc kích hoạt cho phiên tới
        bo_trigger = max(x for x in [_f(r["hh55_next"]) or 0, _f(r["ma50"]) or 0])
        item["breakout_trigger"] = round_tick(bo_trigger + 1, "up") if bo_trigger else None
        rsi_px = rsi_trigger_price(close, r["avg_gain"], r["avg_loss"], cfg["sideway"]["rsi_period"],
                                   cfg["sideway"]["rsi_buy"])
        item["rsi_trigger"] = round_tick(rsi_px, "down") if rsi_px else None
        item["dist_breakout"] = (item["breakout_trigger"] / close - 1) if item["breakout_trigger"] else None
        item["trend"] = ("Tăng" if (item["ma10"] or 0) > (item["ma50"] or 0) else "Giảm") if item["ma50"] else "—"
        item["regime"] = ("Đi ngang" if (item["gap"] is not None and item["gap"] < cfg["sideway"]["flat_gap"])
                          else "Có xu hướng")

        c = cand.get(t)
        item["signal"] = c["label"] if c else None
        item["score"] = round(c["score"], 1) if c else None

        if t in buy_set and t in executed:
            item["action"] = "MUA"
            item["action_price"] = close
            item["action_note"] = c["label"] if c else "Đã mua theo tín hiệu"
            p = sim.positions.get(t)
            if p is not None:
                lv = p.levels(cfg, r["atr"])
                item["position"] = {"strategy": p.strategy, "entry_price": p.entry_price, "qty": p.qty,
                                    "entry_date": p.entry_date, "pnl_pct": close / p.entry_price - 1,
                                    "stop": _f(lv["stop"]), "trail": _f(lv["trail"]),
                                    "exit_level": _f(lv["exit_level"]), "take_profit": _f(lv["take_profit"])}
        elif t in sim.positions or t in sell_map:
            p = sim.positions.get(t)
            if t in sell_map:
                item["action"] = "BÁN"
                sm = sell_map[t]
                item["action_note"] = sm.get("note") or REASON_VN.get(sm.get("reason"), "")
                item["action_price"] = close
            elif t in blocked:
                item["action"] = "GIỮ"
                item["action_note"] = f"Chạm điều kiện bán ({REASON_VN.get(blocked[t]['reason'])}) nhưng chưa đủ T+2"
            else:
                item["action"] = "GIỮ"
                item["action_note"] = "Đang nắm giữ"
            if p is not None:
                lv = p.levels(cfg, r["atr"])
                item["position"] = {"strategy": p.strategy, "entry_price": p.entry_price, "qty": p.qty,
                                    "entry_date": p.entry_date, "pnl_pct": close / p.entry_price - 1,
                                    "stop": _f(lv["stop"]), "trail": _f(lv["trail"]),
                                    "exit_level": _f(lv["exit_level"]), "take_profit": _f(lv["take_profit"])}
                if item["action"] == "GIỮ":
                    lvtxt = f"bán nếu đóng cửa ≤ {round_tick(lv['exit_level'], 'down'):,.0f}"
                    if lv["take_profit"]:
                        lvtxt += f" hoặc ≥ {round_tick(lv['take_profit'], 'up'):,.0f}"
                    item["action_note"] += " · " + lvtxt
        elif t in buy_set:
            item["action"] = "CHỜ"
            item["action_note"] = (c["label"] if c else "") + " · nằm top 5 nhưng hết slot/tiền"
        elif c:
            item["action"] = "CHỜ"
            item["action_note"] = "Có tín hiệu nhưng ngoài top 5 / danh mục đầy"
        else:
            item["action"] = "CHỜ"
            notes = []
            if item["breakout_trigger"]:
                notes.append(f"Breakout nếu đóng cửa > {item['breakout_trigger']:,.0f}")
            if item["rsi_trigger"]:
                notes.append(f"RSI≤30 nếu đóng cửa ≤ {item['rsi_trigger']:,.0f}")
            item["action_note"] = " · ".join(notes)
        out.append(item)
    return out


# =========================================================== chỉ số hiệu quả
def performance(nav_history: list[dict], trades: list[dict], initial: float) -> dict:
    if not nav_history:
        return {}
    nav = pd.Series([x["nav"] for x in nav_history],
                    index=pd.to_datetime([x["date"] for x in nav_history]), dtype=float)
    vni = pd.Series([x.get("vnindex") for x in nav_history], index=nav.index, dtype=float)
    ret = nav.pct_change().dropna()
    days = max((nav.index[-1] - nav.index[0]).days, 1)
    total = nav.iloc[-1] / initial - 1
    cagr = (nav.iloc[-1] / initial) ** (365.25 / days) - 1 if days > 30 else None
    dd = nav / nav.cummax() - 1
    sharpe = (ret.mean() / ret.std() * np.sqrt(252)) if len(ret) > 20 and ret.std() > 0 else None
    vni_valid = vni.dropna()
    bench = (vni_valid.iloc[-1] / vni_valid.iloc[0] - 1) if len(vni_valid) > 1 else None
    vni_dd = (vni_valid / vni_valid.cummax() - 1).min() if len(vni_valid) > 1 else None
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    by_strat = {}
    for t in trades:
        k = t["strategy"]
        d = by_strat.setdefault(k, {"n": 0, "wins": 0, "pnl": 0})
        d["n"] += 1
        d["wins"] += t["pnl"] > 0
        d["pnl"] += t["pnl"]
    by_reason = {}
    for t in trades:
        by_reason[t["reason_vn"]] = by_reason.get(t["reason_vn"], 0) + 1
    return {
        "nav": _f(nav.iloc[-1]), "total_return": _f(total), "cagr": _f(cagr),
        "max_drawdown": _f(dd.min()), "sharpe": _f(sharpe), "benchmark_return": _f(bench),
        "benchmark_max_dd": _f(vni_dd), "alpha": _f(total - bench) if bench is not None else None,
        "n_trades": len(trades), "win_rate": _f(len(wins) / len(trades)) if trades else None,
        "avg_win": _f(np.mean([t["ret"] for t in wins])) if wins else None,
        "avg_loss": _f(np.mean([t["ret"] for t in losses])) if losses else None,
        "profit_factor": _f(gross_win / gross_loss) if gross_loss > 0 else None,
        "realized_pnl": _f(sum(t["pnl"] for t in trades)),
        "total_fees": _f(sum(t["buy_fee"] + t["sell_fee"] for t in trades)),
        "total_tax": _f(sum(t["tax"] for t in trades)),
        "avg_bars": _f(np.mean([t["bars"] for t in trades])) if trades else None,
        "days": days, "start": str(nav.index[0].date()), "end": str(nav.index[-1].date()),
        "by_strategy": by_strat, "by_reason": by_reason,
    }

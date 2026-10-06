"""Kiểm tra luật giao dịch: python -m pytest -q  (hoặc python tests/test_rules.py)"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.core import Simulator, entry_signal, exit_reason, Position
from engine.indicators import add_stock_indicators, add_index_indicators, rsi_trigger_price, rsi

CFG = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))

def _df(close, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(close))
    c = np.asarray(close, float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6}, index=idx)

def _setup(closes, vni_closes=None):
    raw = _df(closes)
    vni = _df(vni_closes if vni_closes is not None else np.linspace(1000, 1300, len(closes)))
    panel = {"AAA": add_stock_indicators(raw, CFG)}
    v = add_index_indicators(vni, CFG)
    return Simulator(CFG, panel, v, list(v.index)), panel, v

def test_breakout_buy_fees_lot_and_t2():
    n = 260
    closes = list(np.full(n - 1, 20_000.0)) + [22_000.0]    # phá đỉnh phiên cuối
    closes[200:259] = np.linspace(20_000, 21_000, 59)      # MA10 > MA50
    sim, panel, v = _setup(closes)
    d = v.index[-1]
    rep = sim.step(d)
    o = rep["orders"][0]
    assert o["side"] == "MUA" and o["ticker"] == "AAA"
    assert o["qty"] % 100 == 0
    assert o["fee"] == round(o["qty"] * 22_000 * 0.0015)
    assert o["qty"] * 22_000 * 1.0015 <= 100_000_000 / 5 + 1
    print("mua:", o)

def test_t2_blocks_early_sell_then_stop():
    sim, panel, v = _setup(np.full(300, 10_000.0))
    dates = v.index
    sim.positions["AAA"] = Position("AAA", "SIDEWAY", str(dates[-3].date()), 10_000, 1000, 10_015_000, 15_000,
                                    10_000, 10_000, str(dates[-3].date()))
    df = panel["AAA"]
    df.loc[dates[-2], "close"] = 9_400     # -6% vào T+1 -> chưa được bán
    dec = sim.decide(dates[-2])
    assert dec["sells"] == [] and dec["blocked"][0]["reason"] == "CAT_LO"
    df.loc[dates[-1], "close"] = 9_400     # T+2 -> bán
    sim.cash = 0
    rep = sim.step(dates[-1])
    s = rep["orders"][0]
    assert s["side"] == "BÁN"
    value = 1000 * 9_400
    assert s["fee"] == round(value * 0.0015) and s["tax"] == round(value * 0.001)
    assert abs(sim.cash - (value - s["fee"] - s["tax"])) < 1
    print("bán:", s)

def test_breakout_exits():
    p = Position("AAA", "BREAKOUT", "2024-01-01", 100, 100, 1, 0, 130, 130, "2024-01-01")
    row = pd.Series({"close": 91.9, "atr": 1.0})
    assert exit_reason(p, row, 10, CFG) == "STOP_8%"
    row = pd.Series({"close": 125.9, "atr": 1.0})        # 130 - 4*1 = 126
    assert exit_reason(p, row, 10, CFG) == "TRAILING_ATR"
    row = pd.Series({"close": 128, "atr": 1.0})
    assert exit_reason(p, row, 10, CFG) is None
    assert exit_reason(p, row, 365, CFG) == "HET_HAN_365"

def test_sideway_exits_and_market_filter():
    p = Position("AAA", "SIDEWAY", "2024-01-01", 100, 100, 1, 0, 100, 100, "2024-01-01")
    assert exit_reason(p, pd.Series({"close": 106.5, "atr": 1}), 3, CFG) == "CHOT_LOI"
    assert exit_reason(p, pd.Series({"close": 95.0, "atr": 1}), 3, CFG) == "CAT_LO"
    assert exit_reason(p, pd.Series({"close": 104.0, "atr": 1}), 3, CFG) is None
    row = pd.Series({"close": 100, "hh55": 120, "ma10": 101, "ma50": 100, "rsi": 25, "gap": 0.01, "roc60": 0})
    mk = {"breakout_ok": True, "sideway_ok": True}
    sig = entry_signal(row, mk, CFG)
    assert sig["type"] == "SIDEWAY" and abs(sig["score"] - 105) < 1e-9
    row["gap"] = 0.08
    assert entry_signal(row, mk, CFG)["type"] == "SIDEWAY_T"
    assert entry_signal(row, {"breakout_ok": True, "sideway_ok": False}, CFG) is None
    row2 = pd.Series({"close": 130, "hh55": 120, "ma10": 110, "ma50": 100, "rsi": 70, "gap": 0.1, "roc60": 0.25})
    s2 = entry_signal(row2, mk, CFG)
    assert s2["type"] == "BREAKOUT" and abs(s2["score"] - 325) < 1e-9
    assert entry_signal(row2, {"breakout_ok": False, "sideway_ok": True}, CFG) is None

def test_rsi_trigger_price():
    c = pd.Series(100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 120)))
    r, ag, al = rsi(c, 14)
    p = rsi_trigger_price(c.iloc[-1], ag.iloc[-1], al.iloc[-1], 14, 30)
    r2, _, _ = rsi(pd.concat([c, pd.Series([p])], ignore_index=True), 14)
    assert abs(r2.iloc[-1] - 30) < 0.01, r2.iloc[-1]

if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("OK", k)

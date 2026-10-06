"""Chỉ báo kỹ thuật (Wilder RSI/ATR, MA, Donchian, ROC)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain, loss = d.clip(lower=0), -d.clip(upper=0)
    ag, al = wilder(gain, n), wilder(loss, n)
    rs = ag / al.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(al != 0, 100.0), ag, al


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return wilder(tr, n)


def add_stock_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    b, s = cfg["breakout"], cfg["sideway"]
    out = df.copy()
    c = out["close"]
    out["ma10"] = c.rolling(b["ma_fast"]).mean()
    out["ma50"] = c.rolling(b["ma_slow"]).mean()
    # đỉnh 55 phiên TRƯỚC (không tính phiên hiện tại)
    out["hh55"] = out["high"].shift(1).rolling(b["donchian"]).max()
    # đỉnh 55 phiên tính cả hôm nay -> mốc phá vỡ cho phiên kế tiếp
    out["hh55_next"] = out["high"].rolling(b["donchian"]).max()
    out["atr"] = atr(out, b["atr_period"])
    out["rsi"], out["avg_gain"], out["avg_loss"] = rsi(c, s["rsi_period"])
    out["roc60"] = c / c.shift(b["roc_period"]) - 1
    out["gap"] = (out["ma10"] - out["ma50"]).abs() / out["ma50"]
    out["chg"] = c.pct_change()
    return out


def add_index_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = df.copy()
    out["ma50"] = out["close"].rolling(cfg["breakout"]["market_ma"]).mean()
    out["ma200"] = out["close"].rolling(cfg["sideway"]["market_ma"]).mean()
    out["chg"] = out["close"].pct_change()
    return out


def rsi_trigger_price(close: float, avg_gain: float, avg_loss: float, n: int, level: float) -> float | None:
    """Giá đóng cửa phiên tới để RSI(n) chạm `level` (giả định phiên giảm)."""
    if any(map(lambda x: x is None or np.isnan(x), [close, avg_gain, avg_loss])):
        return None
    g_new = avg_gain * (n - 1) / n
    rs_target = level / (100 - level)
    l_new = g_new / rs_target
    drop = n * l_new - (n - 1) * avg_loss
    if drop <= 0:
        return close  # đã ở dưới ngưỡng
    p = close - drop
    return p if p > 0 else None


def tick_size(price: float) -> int:
    """Bước giá HOSE."""
    if price < 10_000:
        return 10
    if price < 50_000:
        return 50
    return 100


def round_tick(price: float, mode: str = "nearest") -> float:
    if price is None or np.isnan(price):
        return price
    t = tick_size(price)
    if mode == "up":
        return float(np.ceil(price / t) * t)
    if mode == "down":
        return float(np.floor(price / t) * t)
    return float(round(price / t) * t)

"""Dữ liệu MÔ PHỎNG để chạy thử giao diện khi không có mạng. KHÔNG phải giá thật."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _tick(p):
    t = np.where(p < 10_000, 10, np.where(p < 50_000, 50, 100))
    return np.round(p / t) * t


def make_demo(symbols, start, end, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    n = len(dates)
    # thị trường: chế độ tăng / giảm / đi ngang
    regime = np.repeat(rng.choice([0.0009, -0.0006, 0.0001], size=n // 60 + 1, p=[0.45, 0.25, 0.30]), 60)[:n]
    mkt_ret = regime + rng.normal(0, 0.011, n)
    vni = 1000 * np.exp(np.cumsum(mkt_ret))
    vdf = pd.DataFrame({"open": vni * (1 - rng.normal(0, .002, n)), "high": vni * (1 + abs(rng.normal(0, .006, n))),
                        "low": vni * (1 - abs(rng.normal(0, .006, n))), "close": vni,
                        "volume": rng.integers(4e8, 9e8, n)}, index=dates)
    vdf["high"] = vdf[["open", "high", "close"]].max(axis=1)
    vdf["low"] = vdf[["open", "low", "close"]].min(axis=1)
    data = {}
    for s in symbols:
        beta = rng.uniform(0.6, 1.4)
        drift = rng.normal(0.0002, 0.0005)
        r = beta * mkt_ret + drift + rng.normal(0, 0.015, n)
        p0 = rng.uniform(15_000, 120_000)
        c = _tick(p0 * np.exp(np.cumsum(r)))
        o = _tick(c * (1 + rng.normal(0, 0.006, n)))
        h = _tick(np.maximum(c, o) * (1 + abs(rng.normal(0, 0.008, n))))
        l = _tick(np.minimum(c, o) * (1 - abs(rng.normal(0, 0.008, n))))
        data[s] = pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                                "volume": rng.integers(1e6, 2e7, n)}, index=dates)
    return data, vdf

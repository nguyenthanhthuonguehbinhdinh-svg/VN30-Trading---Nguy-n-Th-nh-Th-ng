"""Lấy dữ liệu giá ngày (OHLCV) cho cổ phiếu VN30 và VNINDEX.

Không phụ thuộc thư viện bên thứ ba (vnstock...). Gọi thẳng API công khai,
thử lần lượt nhiều nguồn: VCI (Vietcap) -> KBS -> VNDirect.
Giá cổ phiếu luôn được chuẩn hoá về đơn vị VND (vd 25.300), chỉ số giữ nguyên điểm.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

VN_TZ = timezone(timedelta(hours=7))
INDEX_SYMBOLS = {"VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _headers(origin: str) -> dict:
    return {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Referer": origin,
        "Origin": origin.rstrip("/"),
    }


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


# ----------------------------------------------------------------- helpers
def _to_frame(t, o, h, l, c, v) -> pd.DataFrame:
    df = pd.DataFrame({"t": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
    if df.empty:
        return df
    ts = df["t"]
    if pd.api.types.is_numeric_dtype(ts) or str(ts.iloc[0]).isdigit():
        ts = pd.to_numeric(ts)
        unit = "ms" if ts.iloc[0] > 1e11 else "s"
        dt = pd.to_datetime(ts, unit=unit, utc=True).dt.tz_convert("Asia/Ho_Chi_Minh")
    else:
        dt = pd.to_datetime(ts, errors="coerce")
        if dt.dt.tz is not None:
            dt = dt.dt.tz_convert("Asia/Ho_Chi_Minh")
    df["date"] = dt.dt.tz_localize(None).dt.normalize() if dt.dt.tz is not None else dt.dt.normalize()
    df = df.drop(columns="t")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).drop_duplicates("date", keep="last")
    return df.set_index("date").sort_index()


def _normalize(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Giá cổ phiếu về VND. Nguồn trả đơn vị nghìn đồng (25.3) -> nhân 1000."""
    if df.empty or symbol in INDEX_SYMBOLS:
        return df
    if df["close"].median() < 500:
        df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]] * 1000
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].round(0)
    # fill missing OHLC with close (một số nguồn thiếu open)
    for col in ["open", "high", "low"]:
        df[col] = df[col].fillna(df["close"])
    return df


# ----------------------------------------------------------------- sources
def _vci(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    url = "https://trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart"
    count_back = int(len(pd.bdate_range(start, end)) + 5)
    payload = {"timeFrame": "ONE_DAY", "symbols": [symbol],
               "to": int((end + timedelta(days=1)).timestamp()), "countBack": count_back}
    r = requests.post(url, json=payload, headers=_headers("https://trading.vietcap.com.vn/"), timeout=30)
    r.raise_for_status()
    js = r.json()
    if isinstance(js, dict) and "data" in js:
        js = js["data"]
    if not js:
        return pd.DataFrame()
    d = js[0]
    return _to_frame(d["t"], d["o"], d["h"], d["l"], d["c"], d.get("v", [0] * len(d["t"])))


def _kbs(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    kind = "index" if symbol in INDEX_SYMBOLS else "stocks"
    url = f"https://kbbuddywts.kbsec.com.vn/iis-server/investment/{kind}/{symbol}/data_day"
    params = {"sdate": start.strftime("%d-%m-%Y"), "edate": end.strftime("%d-%m-%Y")}
    r = requests.get(url, params=params, headers=_headers("https://kbbuddywts.kbsec.com.vn/"), timeout=30)
    r.raise_for_status()
    rows = r.json().get("data_day") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return _to_frame(df["t"], df.get("o"), df.get("h"), df.get("l"), df["c"], df.get("v", 0))


def _vnd(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    url = "https://dchart-api.vndirect.com.vn/dchart/history"
    params = {"resolution": "D", "symbol": symbol,
              "from": int(start.timestamp()), "to": int((end + timedelta(days=1)).timestamp())}
    r = requests.get(url, params=params, headers=_headers("https://dchart.vndirect.com.vn/"), timeout=30)
    r.raise_for_status()
    js = r.json()
    if js.get("s") != "ok" or not js.get("t"):
        return pd.DataFrame()
    return _to_frame(js["t"], js["o"], js["h"], js["l"], js["c"], js.get("v", [0] * len(js["t"])))


SOURCES = [("VCI", _vci), ("KBS", _kbs), ("VNDIRECT", _vnd)]


def fetch_history(symbol: str, start: datetime, end: datetime | None = None,
                  min_bars: int = 30, retries: int = 2) -> tuple[pd.DataFrame, str]:
    """Trả về (DataFrame index=date, cột open/high/low/close/volume, tên nguồn)."""
    end = end or now_vn().replace(tzinfo=None)
    errors = []
    for name, fn in SOURCES:
        for attempt in range(retries):
            try:
                df = _normalize(fn(symbol, start, end), symbol)
                if len(df) >= min_bars:
                    return df[df.index >= pd.Timestamp(start).normalize()], name
                errors.append(f"{name}: chỉ {len(df)} phiên")
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc.__class__.__name__} {str(exc)[:80]}")
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Không lấy được dữ liệu {symbol}: " + " | ".join(errors))


def fetch_vn30_list(fallback: list[str]) -> tuple[list[str], str]:
    try:
        url = "https://trading.vietcap.com.vn/api/price/symbols/getByGroup?group=VN30"
        r = requests.get(url, headers=_headers("https://trading.vietcap.com.vn/"), timeout=20)
        r.raise_for_status()
        syms = sorted({str(x["symbol"]).upper() for x in r.json() if x.get("symbol")})
        if 25 <= len(syms) <= 35:
            return syms, "VCI"
    except Exception:  # noqa: BLE001
        pass
    return sorted(fallback), "config"


def fetch_universe(symbols: list[str], start: datetime, sleep: float = 0.4, log=print):
    """Tải toàn bộ mã + VNINDEX. Trả về (dict mã->df, df VNINDEX hoặc None, dict nguồn, list lỗi)."""
    data, sources, errors = {}, {}, []
    vni = None
    try:
        vni, src = fetch_history("VNINDEX", start, min_bars=210)
        sources["VNINDEX"] = src
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        log(f"[!] {exc}")
    for sym in symbols:
        try:
            df, src = fetch_history(sym, start)
            data[sym], sources[sym] = df, src
            log(f"  {sym:<5} {len(df):>5} phiên  ({src})  close={df['close'].iloc[-1]:,.0f}")
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            log(f"[!] {exc}")
        time.sleep(sleep)
    return data, vni, sources, errors

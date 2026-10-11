"""
Market data layer (Yahoo Finance via yfinance).

Kept in its own file so it can later be swapped for a broker API (Fyers, Zerodha,
etc.) without touching strategy or trading logic. Everything returned here is
timezone-aware IST, and only COMPLETED 5-minute candles are ever used.
"""

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")
CANDLE_MINUTES = 5
OHLC = ["Open", "High", "Low", "Close"]


def now_ist() -> datetime:
    return datetime.now(IST)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Keep OHLC only, drop empty rows, force the index to IST."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if not all(c in df.columns for c in OHLC):
        return pd.DataFrame()
    df = df.dropna(subset=OHLC)
    if df.empty:
        return pd.DataFrame()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(IST)
    return df[OHLC]


def _split_batch(raw: pd.DataFrame, tickers: list) -> dict:
    """Turn a yfinance download result into {ticker: clean OHLC dataframe}."""
    out = {}
    if raw is None or raw.empty:
        return out
    cols = raw.columns
    if not isinstance(cols, pd.MultiIndex):           # flat columns, single ticker
        d = _clean(raw)
        if not d.empty and len(tickers) == 1:
            out[tickers[0]] = d
        return out

    level0 = set(cols.get_level_values(0))
    if "Close" in level0:                              # layout: (field, ticker)
        if len(tickers) == 1:
            d = _clean(raw)
            if not d.empty:
                out[tickers[0]] = d
        else:
            for t in tickers:
                try:
                    d = _clean(raw.xs(t, axis=1, level=1))
                except KeyError:
                    continue
                if not d.empty:
                    out[t] = d
    else:                                              # layout: (ticker, field)
        for t in tickers:
            if t in level0:
                d = _clean(raw[t])
                if not d.empty:
                    out[t] = d
    return out


def fetch_intraday(tickers: list, period: str = "1d", chunk: int = 25) -> dict:
    """5-minute candles for many tickers. Downloads in chunks, retries misses once."""
    result = {}
    for i in range(0, len(tickers), chunk):
        pending = list(tickers[i:i + chunk])
        for attempt in range(2):
            if not pending:
                break
            try:
                raw = yf.download(pending, period=period, interval="5m", group_by="ticker",
                                  progress=False, threads=True, auto_adjust=False)
                got = _split_batch(raw, pending)
                result.update(got)
                pending = [t for t in pending if t not in got]
            except Exception as e:
                print(f"  download error ({e}), retrying..." if attempt == 0 else f"  download failed: {e}")
                time.sleep(2)
        time.sleep(0.5)
    return result


def fetch_prev_closes(tickers: list, today, chunk: int = 50) -> dict:
    """Official previous-day close for each ticker (from daily data), {ticker: price}."""
    out = {}
    for i in range(0, len(tickers), chunk):
        part = list(tickers[i:i + chunk])
        try:
            raw = yf.download(part, period="10d", interval="1d", group_by="ticker",
                              progress=False, threads=True, auto_adjust=False)
            for t, d in _split_batch(raw, part).items():
                d = d[d.index.date < today]
                if not d.empty:
                    out[t] = float(d["Close"].iloc[-1])
        except Exception as e:
            print(f"  daily download error: {e}")
        time.sleep(0.5)
    return out


def market_traded_today(today) -> bool:
    """Cheap holiday/weekend check: did a big stock print any candle today?"""
    got = fetch_intraday(["RELIANCE.NS"], period="1d")
    df = got.get("RELIANCE.NS")
    return df is not None and not df.empty and bool((df.index.date == today).any())


def completed_candles(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Today's candles only, minus the one still forming (a candle starting at T
    isn't finished until T + 5 min). Acting on a half-built candle was a likely
    source of false signals before."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[df.index.date == now.date()]
    return df[df.index + pd.Timedelta(minutes=CANDLE_MINUTES) <= now]

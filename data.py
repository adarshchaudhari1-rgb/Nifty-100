"""
Market data layer.

Main source: Upstox (free, read-only "Analytics Token" stored as the GitHub secret
UPSTOX_ANALYTICS_TOKEN - valid for a year, no daily login, cannot place orders).
Backup: Yahoo Finance, used automatically if there is no token, the token is
rejected, or Upstox returns nothing.

Everything returned here is timezone-aware IST. Strategy and trading code never
know which source was used (data.LAST_SOURCE tells the report).
"""

import gzip
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import requests
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


def _yahoo_intraday(tickers: list, period: str = "1d", chunk: int = 25) -> dict:
    """Yahoo: 5-minute candles for many tickers. Downloads in chunks, retries misses once."""
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


def _yahoo_prev_closes(tickers: list, today, chunk: int = 50) -> dict:
    """Yahoo: previous-day close for each ticker (from daily data), {ticker: price}."""
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


# ======================================================================
# Upstox (main source)
# ======================================================================
UPSTOX_BASE = "https://api.upstox.com"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"

# ticker -> Upstox instrument key. RELIANCE is pre-filled so the holiday check never
# needs the big instrument file; the watchlist file seeds the rest between runs.
_KEYS = {"RELIANCE.NS": "NSE_EQ|INE002A01018"}
_UPSTOX_BROKEN = False
LAST_SOURCE = "Yahoo Finance"


class UpstoxAuthError(Exception):
    pass


def _token() -> str:
    return os.environ.get("UPSTOX_ANALYTICS_TOKEN", "").strip()


def upstox_enabled() -> bool:
    return bool(_token()) and not _UPSTOX_BROKEN


def _mark_broken(err) -> None:
    global _UPSTOX_BROKEN
    _UPSTOX_BROKEN = True
    print("!" * 60)
    print(f"UPSTOX TOKEN REJECTED ({err}).")
    print("Using Yahoo Finance for the rest of this run. Generate a new Analytics Token on")
    print("Upstox and update the UPSTOX_ANALYTICS_TOKEN secret in GitHub.")
    print("!" * 60)


def _bare(ticker: str) -> str:
    return ticker[:-3] if ticker.endswith(".NS") else ticker


def _upstox_get(path: str):
    """GET with retries. Returns parsed JSON, None for harmless misses, raises on bad token."""
    headers = {"Accept": "application/json", "Authorization": f"Bearer {_token()}"}
    for attempt in range(4):
        try:
            resp = requests.get(UPSTOX_BASE + path, headers=headers, timeout=20)
        except requests.RequestException:
            time.sleep(1.0 * (attempt + 1))
            continue
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return None
        if resp.status_code in (401, 403):
            raise UpstoxAuthError(f"HTTP {resp.status_code}: {resp.text[:120]}")
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(1.5 * (attempt + 1))
            continue
        return None                       # e.g. unknown instrument - skip this stock
    return None


def _fill_keys(tickers: list) -> None:
    """Make sure every ticker has an instrument key, downloading Upstox's instrument
    list (once) only if some are missing."""
    missing = [t for t in tickers if t not in _KEYS]
    if not missing:
        return
    print(f"  Downloading Upstox instrument list (need keys for {len(missing)} stocks)...")
    try:
        resp = requests.get(INSTRUMENTS_URL, timeout=90)
        resp.raise_for_status()
        raw = resp.content
        try:
            raw = gzip.decompress(raw)
        except OSError:                    # already decompressed by the HTTP layer
            pass
        rows = json.loads(raw)
    except Exception as e:
        print(f"  Could not load Upstox instrument list: {e}")
        return
    by_symbol = {}
    for row in rows:
        if row.get("segment") == "NSE_EQ" and row.get("instrument_type") == "EQ":
            sym, key = row.get("trading_symbol"), row.get("instrument_key")
            if sym and key:
                by_symbol[str(sym).upper()] = key
    for t in missing:
        key = by_symbol.get(_bare(t).upper())
        if key:
            _KEYS[t] = key


def get_instrument_keys(tickers: list) -> dict:
    """{ticker: instrument key} for the given tickers (used to save keys in the watchlist)."""
    _fill_keys(list(tickers))
    return {t: _KEYS[t] for t in tickers if t in _KEYS}


def seed_instrument_keys(mapping: dict) -> None:
    _KEYS.update(mapping or {})


def _candles_to_df(candles) -> pd.DataFrame:
    """Upstox candle rows [timestamp, open, high, low, close, volume, oi] (newest first)."""
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame([c[:5] for c in candles], columns=["ts"] + OHLC)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for col in OHLC:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return _clean(df.set_index("ts").sort_index())


def _upstox_intraday(tickers: list) -> dict:
    _fill_keys(tickers)

    def one(t):
        key = _KEYS.get(t)
        if not key:
            return t, None
        j = _upstox_get(f"/v3/historical-candle/intraday/{quote(key, safe='')}/minutes/5")
        return t, _candles_to_df(((j or {}).get("data") or {}).get("candles"))

    out = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for t, df in pool.map(one, tickers):
            if df is not None and not df.empty:
                out[t] = df
    return out


def _upstox_prev_closes(tickers: list, today) -> dict:
    _fill_keys(tickers)
    to_d = today.strftime("%Y-%m-%d")
    from_d = (today - timedelta(days=10)).strftime("%Y-%m-%d")

    def one(t):
        key = _KEYS.get(t)
        if not key:
            return t, None
        j = _upstox_get(f"/v3/historical-candle/{quote(key, safe='')}/days/1/{to_d}/{from_d}")
        best = None
        for c in ((j or {}).get("data") or {}).get("candles") or []:
            ts = pd.Timestamp(c[0])
            d = (ts.tz_convert(IST) if ts.tzinfo else ts).date()
            if d < today and (best is None or d > best[0]):
                best = (d, float(c[4]))
        return t, (best[1] if best else None)

    out = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for t, price in pool.map(one, tickers):
            if price:
                out[t] = price
    return out


# ======================================================================
# Public functions (route to Upstox, fall back to Yahoo)
# ======================================================================
def fetch_intraday(tickers: list, period: str = "1d", chunk: int = 25) -> dict:
    """5-minute candles for many tickers: {ticker: dataframe}."""
    global LAST_SOURCE
    tickers = list(tickers)
    if upstox_enabled():
        try:
            got = _upstox_intraday(tickers)
            if got:
                LAST_SOURCE = "Upstox"
                skipped = len(tickers) - len(got)
                if skipped:
                    print(f"  Upstox had no candles for {skipped} of {len(tickers)} stocks")
                return got
            print("  Upstox returned no candles - trying Yahoo Finance for this call")
        except UpstoxAuthError as e:
            _mark_broken(e)
    LAST_SOURCE = "Yahoo Finance"
    return _yahoo_intraday(tickers, period, chunk)


def fetch_prev_closes(tickers: list, today, chunk: int = 50) -> dict:
    """Previous trading day's close: {ticker: price}. Both sources give official daily closes,
    so any stock Upstox can't supply is filled from Yahoo."""
    tickers = list(tickers)
    out = {}
    if upstox_enabled():
        try:
            out = _upstox_prev_closes(tickers, today)
        except UpstoxAuthError as e:
            _mark_broken(e)
    missing = [t for t in tickers if t not in out]
    if missing:
        out.update(_yahoo_prev_closes(missing, today, chunk))
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

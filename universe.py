"""
Nifty 100 stock universe.

Primary source: the official constituent list published by NSE Indices
(downloaded fresh each morning, so index changes are picked up automatically).
Backup: a built-in list, used only if the download fails. The backup is
approximate (the index is reshuffled twice a year) — the scanner skips any
symbol Yahoo has no data for, so a slightly stale backup is safe, just less exact.
"""

import io

import pandas as pd
import requests

NIFTY100_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

FALLBACK = [
    # Nifty 50 (approx.)
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC", "JIOFIN", "JSWSTEEL",
    "KOTAKBANK", "LT", "M&M", "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA",
    "TATACONSUM", "TATASTEEL", "TCS", "TECHM", "TITAN", "TMPV", "TRENT",
    "ULTRACEMCO", "WIPRO",
    # Nifty Next 50 (approx.)
    "ABB", "ADANIENSOL", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM", "BAJAJHLDNG",
    "BANKBARODA", "BOSCHLTD", "BPCL", "BRITANNIA", "CANBK", "CGPOWER", "CHOLAFIN",
    "DABUR", "DIVISLAB", "DLF", "DMART", "GAIL", "GODREJCPG", "HAL", "HAVELLS",
    "HDFCAMC", "HINDZINC", "HYUNDAI", "ICICIGI", "INDHOTEL", "IOC", "IRFC",
    "JINDALSTEL", "JSWENERGY", "LICI", "LODHA", "LTIM", "MAZDOCK", "MOTHERSON",
    "NAUKRI", "PFC", "PIDILITIND", "PNB", "RECLTD", "SHREECEM", "SIEMENS", "SWIGGY",
    "TATAPOWER", "TORNTPHARM", "TVSMOTOR", "UNITDSPR", "VBL", "VEDL", "ZYDUSLIFE",
]


def get_nifty100():
    """Return (list of Yahoo tickers like 'RELIANCE.NS', description of source)."""
    try:
        resp = requests.get(NIFTY100_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        symbols = [f"{str(s).strip()}.NS" for s in df["Symbol"].dropna()]
        if len(symbols) >= 90:
            return symbols, f"official NSE list ({len(symbols)} stocks)"
        print(f"Official list looked incomplete ({len(symbols)} symbols) - using backup list")
    except Exception as e:
        print(f"Could not download official Nifty 100 list ({e}) - using backup list")
    return [f"{s}.NS" for s in FALLBACK], "built-in backup list (may be slightly outdated)"

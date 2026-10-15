"""
Morning scanner.

At 10:00 AM IST (prices as of exactly 10:00, even if the run starts a few
minutes late):
  1. Compare every Nifty 100 stock with its previous close -> green or red.
  2. Market nature: BULLISH if green share >= 55%, BEARISH if <= 45%, else NEUTRAL.
  3. Pick the 5 strongest stocks (bullish day) or 5 weakest (bearish day) by % change.
  4. Save everything to daily_watchlist.json so later runs just read it.
"""

import json
import os
from datetime import datetime

import pandas as pd

import config
import data
from universe import get_nifty100

WATCHLIST_FILE = "daily_watchlist.json"


def load_watchlist(date_str: str):
    """Today's saved watchlist, or None if there isn't one yet."""
    if not os.path.exists(WATCHLIST_FILE):
        return None
    try:
        with open(WATCHLIST_FILE) as f:
            wl = json.load(f)
        return wl if wl.get("date") == date_str else None
    except (json.JSONDecodeError, OSError):
        return None


def classify(green_pct: float) -> str:
    if green_pct >= config.BULLISH_MIN_GREEN_PCT:
        return "BULLISH"
    if green_pct <= config.BEARISH_MAX_GREEN_PCT:
        return "BEARISH"
    return "NEUTRAL"


def build_watchlist(rows: list, today_str: str, source: str, selected_at: str,
                    data_source: str = "Yahoo Finance", instrument_keys: dict = None) -> dict:
    """rows: [{symbol, pct_change, price, prev_close}] -> watchlist dict (pure logic)."""
    green = sum(1 for r in rows if r["pct_change"] > 0)
    red = sum(1 for r in rows if r["pct_change"] < 0)
    green_pct = round(green / (green + red) * 100, 1) if (green + red) else 0.0
    nature = classify(green_pct)

    ranked = sorted(rows, key=lambda r: r["pct_change"], reverse=True)
    if nature == "BULLISH":
        picks = [dict(r, side="LONG") for r in ranked[:config.TOP_N]]
    elif nature == "BEARISH":
        picks = [dict(r, side="SHORT") for r in list(reversed(ranked))[:config.TOP_N]]
    elif config.NEUTRAL_TRADES_BOTH_SIDES:
        # No clear direction: watch the strongest stocks for longs and the weakest for shorts
        longs = [dict(r, side="LONG") for r in ranked[:config.TOP_N]]
        shorts = [dict(r, side="SHORT") for r in list(reversed(ranked))[:config.TOP_N]]
        picks = longs + shorts
    else:
        picks = []

    return {
        "date": today_str,
        "selected_at": selected_at,
        "universe_source": source,
        "data_source": data_source,
        "instrument_keys": instrument_keys or {},
        "stocks_with_data": len(rows),
        "green": green,
        "red": red,
        "green_pct": green_pct,
        "nature": nature,
        "stocks": [{"symbol": r["symbol"], "side": r["side"], "pct_change": round(r["pct_change"], 2),
                    "price": round(r["price"], 2), "prev_close": round(r["prev_close"], 2)}
                   for r in picks],
    }


def run_selection(now: datetime):
    """Scan Nifty 100 and save the day's watchlist. Returns it, or None on failure."""
    today = now.date()
    today_str = today.strftime("%Y-%m-%d")
    symbols, source = get_nifty100()
    print(f"Scanning Nifty 100 - {source}")

    intraday = data.fetch_intraday(symbols, period="1d")
    prev_closes = data.fetch_prev_closes(symbols, today)

    cutoff = datetime.combine(today, config.SELECTION_TIME, tzinfo=data.IST)
    rows = []
    for sym, df in intraday.items():
        if sym not in prev_closes:
            continue
        d = df[df.index.date == today]
        d = d[d.index + pd.Timedelta(minutes=data.CANDLE_MINUTES) <= cutoff]
        if d.empty:
            continue
        price = float(d["Close"].iloc[-1])
        prev = prev_closes[sym]
        rows.append({"symbol": sym, "price": price, "prev_close": prev,
                     "pct_change": (price - prev) / prev * 100})

    missing = len(symbols) - len(rows)
    print(f"Got usable data for {len(rows)} of {len(symbols)} stocks"
          + (f" ({missing} skipped)" if missing else ""))
    if len(rows) < config.MIN_STOCKS_WITH_DATA:
        print(f"Only {len(rows)} stocks had data (need {config.MIN_STOCKS_WITH_DATA}) - "
              f"not selecting today, will retry on the next run")
        return None

    wl = build_watchlist(rows, today_str, source, now.strftime("%Y-%m-%d %H:%M:%S"),
                         data_source=data.LAST_SOURCE)
    if data.LAST_SOURCE == "Upstox":      # remember keys so later runs don't re-download the big file
        wl["instrument_keys"] = data.get_instrument_keys([s["symbol"] for s in wl["stocks"]])
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(wl, f, indent=2)
    return wl


def describe(wl: dict) -> str:
    head = (f"Market: {wl['nature']} - {wl['green']} green / {wl['red']} red "
            f"({wl['green_pct']}% green) as of {config.SELECTION_TIME.strftime('%H:%M')} "
            f"[data: {wl.get('data_source', 'Yahoo Finance')}]")
    if not wl["stocks"]:
        return head + " -> no trades today (market not clearly directional)"
    def fmt(side):
        return ", ".join(f"{x['symbol'].replace('.NS', '')} {x['pct_change']:+.2f}%"
                         for x in wl["stocks"] if x.get("side", "LONG" if wl["nature"] == "BULLISH" else "SHORT") == side)
    longs, shorts = fmt("LONG"), fmt("SHORT")
    if longs and shorts:
        return head + f"\nWatching for LONGS: {longs}\nWatching for SHORTS: {shorts}"
    return head + f"\nWatching: {longs or shorts}"

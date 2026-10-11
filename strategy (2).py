"""
Pullback / range breakout setup on 5-minute candles.

BULLISH day (LONG trades):
  1. A swing high ("peak") - its high is at least as high as the previous
     PEAK_LOOKBACK candles.
  2. A pullback or sideways range of 2-8 candles after it, none of which
     makes a higher high than the peak.
  3. A green candle that CLOSES above the highest high of that pullback/range
     -> entry at that close.
  4. Stop-loss = the pullback's lowest low, plus a small buffer.
  5. Target = 2 x the risk distance (1:2).

BEARISH day (SHORT trades) is the exact mirror: swing low, pullback/range
bounces, red candle closing below the range low, stop-loss = range high + buffer.

Only completed candles are passed in. Entries are only allowed for candles
that start between SELECTION_TIME and LAST_ENTRY_TIME.
"""

import pandas as pd

import config


def _detect(df: pd.DataFrame, i: int, direction: str):
    """Look for a setup whose breakout candle is df.iloc[i]. Returns a dict or None."""
    cand = df.iloc[i]
    long_side = direction == "LONG"

    # Breakout candle must be in the trade direction
    if long_side and not cand["Close"] > cand["Open"]:
        return None
    if not long_side and not cand["Close"] < cand["Open"]:
        return None

    for length in range(config.MIN_ZONE_CANDLES, config.MAX_ZONE_CANDLES + 1):
        zone_start = i - length
        peak_idx = zone_start - 1
        if peak_idx < 1:
            break
        zone = df.iloc[zone_start:i]
        peak = df.iloc[peak_idx]
        prior = df.iloc[max(0, peak_idx - config.PEAK_LOOKBACK):peak_idx]
        if len(prior) < 2:
            continue

        if long_side:
            if peak["High"] < prior["High"].max():          # peak must be a real swing high
                continue
            zone_high, zone_low = zone["High"].max(), zone["Low"].min()
            if zone_high > peak["High"]:                    # zone made a new high -> not a pullback
                continue
            if not cand["Close"] > zone_high:               # must close above the zone high
                continue
            entry = float(cand["Close"])
            sl = float(zone_low) * (1 - config.SL_BUFFER_PCT)
            risk = entry - sl
        else:
            if peak["Low"] > prior["Low"].min():            # trough must be a real swing low
                continue
            zone_high, zone_low = zone["High"].max(), zone["Low"].min()
            if zone_low < peak["Low"]:                      # zone made a new low -> not a bounce
                continue
            if not cand["Close"] < zone_low:                # must close below the zone low
                continue
            entry = float(cand["Close"])
            sl = float(zone_high) * (1 + config.SL_BUFFER_PCT)
            risk = sl - entry

        if risk <= 0:
            continue
        risk_pct = risk / entry
        if not (config.MIN_RISK_PCT <= risk_pct <= config.MAX_RISK_PCT):
            continue

        target = entry + config.RISK_REWARD * risk if long_side else entry - config.RISK_REWARD * risk
        candle_start = df.index[i]
        return {
            "index": i,
            "time": candle_start,                                        # candle start
            "entry_time": candle_start + pd.Timedelta(minutes=5),        # candle close = entry moment
            "direction": direction,
            "pattern": "Pullback Breakout" if length >= 3 else "Range Breakout",
            "entry": entry,
            "sl": sl,
            "target": float(target),
            "zone_candles": length,
            "risk_pct": round(risk_pct * 100, 2),
        }
    return None


def find_setups(df: pd.DataFrame, direction: str) -> list:
    """All setups today whose breakout candle starts inside the entry window."""
    setups = []
    if df is None or len(df) < config.MIN_ZONE_CANDLES + 3:
        return setups
    for i in range(len(df)):
        t = df.index[i].time()
        if t < config.SELECTION_TIME or t > config.LAST_ENTRY_TIME:
            continue
        s = _detect(df, i, direction)
        if s:
            setups.append(s)
    return setups

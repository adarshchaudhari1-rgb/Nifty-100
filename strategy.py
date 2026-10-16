"""
Pullback / range breakout setup on 5-minute candles.

BULLISH day (LONG trades):
  1. A swing high ("peak") - its high is at least as high as the previous
     PEAK_LOOKBACK candles.
  2. A pullback or sideways range of 2-8 candles after it, none of which
     makes a higher high than the peak.
  3. A green candle that CLOSES above the highest high of that pullback/range
     AND above the day's high so far (new day high = trend still intact)
     -> entry at that close.
  4. Stop-loss = the LATEST swing low / rejection wick inside the pullback
     (not its absolute lowest point), plus a small buffer.
  5. Target = 2 x the risk distance (1:2).

BEARISH day (SHORT trades) is the exact mirror: swing low, pullback/range
bounces, red candle closing below the range low AND below the day's low so far,
stop-loss = latest swing high /
rejection wick + buffer.

Only completed candles are passed in. Entries are only allowed for candles
that start between SELECTION_TIME and LAST_ENTRY_TIME.
"""

import pandas as pd

import config


REJECTION_WICK_RATIO = 0.5     # wick >= 50% of the candle's range counts as a "rejection wick"


def _sl_candidates(df: pd.DataFrame, zone_start: int, i: int, long_side: bool) -> list:
    """Possible stop-loss levels, nearest first: the latest swing / rejection wick
    inside the pullback, then (last resort) the full pullback extreme.

    SHORT: candle highs that are a swing high (>= both neighbours) or have a long
           upper wick (rejection).  LONG: mirror image with lows / lower wicks."""
    levels = []
    for j in range(i - 1, zone_start - 1, -1):          # latest candle first
        c = df.iloc[j]
        rng = float(c["High"] - c["Low"])
        if rng <= 0:
            continue
        prev_c = df.iloc[j - 1] if j - 1 >= 0 else None
        next_c = df.iloc[j + 1]
        if long_side:
            swing = (prev_c is None or c["Low"] <= prev_c["Low"]) and c["Low"] <= next_c["Low"]
            wick = (min(c["Open"], c["Close"]) - c["Low"]) / rng >= REJECTION_WICK_RATIO
            if swing or wick:
                levels.append(float(c["Low"]))
        else:
            swing = (prev_c is None or c["High"] >= prev_c["High"]) and c["High"] >= next_c["High"]
            wick = (c["High"] - max(c["Open"], c["Close"])) / rng >= REJECTION_WICK_RATIO
            if swing or wick:
                levels.append(float(c["High"]))
    zone = df.iloc[zone_start:i]
    levels.append(float(zone["Low"].min()) if long_side else float(zone["High"].max()))
    return levels


def _detect(df: pd.DataFrame, i: int, direction: str):
    """Look for a setup whose breakout candle is df.iloc[i]. Returns a dict or None."""
    cand = df.iloc[i]
    long_side = direction == "LONG"

    # Breakout candle must be in the trade direction
    if long_side and not cand["Close"] > cand["Open"]:
        return None
    if not long_side and not cand["Close"] < cand["Open"]:
        return None

    # Trend filter: the breakout must make a NEW DAY EXTREME in the trade direction.
    # SHORT: close below the lowest low of the day so far (all candles before this one).
    # LONG:  close above the highest high of the day so far.
    # This skips entries after the market has already reversed against the day's move.
    earlier = df.iloc[:i]
    if earlier.empty:
        return None
    if long_side and not cand["Close"] > earlier["High"].max():
        return None
    if not long_side and not cand["Close"] < earlier["Low"].min():
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
            sl, risk = None, 0.0
            for lvl in _sl_candidates(df, zone_start, i, True):
                s_ = lvl * (1 - config.SL_BUFFER_PCT)
                if s_ > cand["Low"] or s_ >= entry:             # must sit beyond the breakout candle
                    continue
                if (entry - s_) / entry >= config.MIN_RISK_PCT:   # not so tight it gets noise-stopped
                    sl, risk = s_, entry - s_
                    break
            if sl is None:
                continue
        else:
            if peak["Low"] > prior["Low"].min():            # trough must be a real swing low
                continue
            zone_high, zone_low = zone["High"].max(), zone["Low"].min()
            if zone_low < peak["Low"]:                      # zone made a new low -> not a bounce
                continue
            if not cand["Close"] < zone_low:                # must close below the zone low
                continue
            entry = float(cand["Close"])
            sl, risk = None, 0.0
            for lvl in _sl_candidates(df, zone_start, i, False):
                s_ = lvl * (1 + config.SL_BUFFER_PCT)
                if s_ < cand["High"] or s_ <= entry:
                    continue
                if (s_ - entry) / entry >= config.MIN_RISK_PCT:
                    sl, risk = s_, s_ - entry
                    break
            if sl is None:
                continue

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

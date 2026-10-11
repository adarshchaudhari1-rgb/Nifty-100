"""
All tunable settings in one place. Edit numbers here, nothing else needs to change.
All times are IST (Indian Standard Time).
"""

from datetime import time as dtime

# ---------------- Money management ----------------
STARTING_CAPITAL = 50_000      # virtual capital (Rs)
RISK_PER_TRADE = 1_000         # Rs lost if a trade hits its stop-loss
LEVERAGE = 5                   # total open position value is capped at capital x leverage

# ---------------- Daily risk limits ----------------
DAILY_LOSS_LIMIT = 2_000       # stop opening new trades once the day's realized loss hits this
PROFIT_TRAIL_TRIGGER = 2_000   # once the day's profit reaches this, start trailing it
PROFIT_TRAIL_RISK = 500        # ...and stop for the day if profit falls this far below its peak

# ---------------- Daily timeline ----------------
SELECTION_TIME = dtime(10, 0)   # market-nature scan + top-5 selection uses prices as of this time
LAST_ENTRY_TIME = dtime(14, 45) # no new entries from candles starting after this
SQUARE_OFF_TIME = dtime(15, 15) # any trade still open is closed at this time (intraday leverage)

# ---------------- Market nature (Nifty 100 breadth) ----------------
BULLISH_MIN_GREEN_PCT = 55      # green stocks >= this % of (green + red)  -> BULLISH day
BEARISH_MAX_GREEN_PCT = 45      # green stocks <= this %                    -> BEARISH day
                                # anything in between                      -> NEUTRAL, no trades
TOP_N = 5                       # how many stocks to watch
MIN_STOCKS_WITH_DATA = 80       # abort selection if fewer than this many stocks returned data

# ---------------- Pullback / range breakout setup (5-min candles) ----------------
MIN_ZONE_CANDLES = 2            # pullback / consolidation must be at least this many candles
MAX_ZONE_CANDLES = 8            # ...and at most this many
PEAK_LOOKBACK = 5               # the high before the pullback must beat this many earlier candles
SL_BUFFER_PCT = 0.0005          # stop-loss sits this far (0.05%) beyond the pullback low/high
MIN_RISK_PCT = 0.0015           # skip setups whose stop-loss is closer than 0.15% (noise)
MAX_RISK_PCT = 0.015            # skip setups whose stop-loss is further than 1.5% (too wide)
RISK_REWARD = 2.0               # target = 2 x risk (1:2)
SIGNAL_GRACE_CANDLES = 1        # GitHub runs can start late; accept a setup up to this many
                                # candles old (entry still uses that setup candle's close)

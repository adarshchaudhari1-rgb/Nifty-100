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
RISK_AFTER_TARGET = 500        # once the day's profit has reached PROFIT_TRAIL_TRIGGER, risk only this much per trade
MONTHLY_DEPOSIT = 2_000        # paper money added to capital on the first trading day of each month (0 = off)
COMPOUNDING = True             # scale ALL the Rs amounts above with capital (at the start of each day):
                               # Rs 1,000 risk on Rs 50,000 = 2% of capital, so at Rs 75,000 it becomes
                               # Rs 1,500; the daily loss limit (4%), profit trail (4% / 1%) and
                               # after-target risk (1%) scale the same way. False = fixed rupee amounts.

# ---------------- Daily timeline ----------------
SELECTION_TIME = dtime(10, 0)   # market-nature scan + top-5 selection uses prices as of this time
FIRST_ENTRY_TIME = dtime(10, 30) # no entries from candles starting before this (skips the noisy first half hour)
LAST_ENTRY_TIME = dtime(13, 55) # last candle that may trigger an entry starts 1:55 PM (closes 2:00 PM) -> no new trades after 2 PM
SQUARE_OFF_TIME = dtime(15, 15) # any trade still open is closed at this time (intraday leverage)

# ---------------- Market nature (Nifty 100 breadth) ----------------
BULLISH_MIN_GREEN_PCT = 55      # green stocks >= this % of (green + red)  -> BULLISH day
BEARISH_MAX_GREEN_PCT = 45      # green stocks <= this %                    -> BEARISH day
                                # anything in between                      -> NEUTRAL, no trades
TOP_N = 5                       # how many stocks to watch (per side)
NEUTRAL_TRADES_BOTH_SIDES = False # on a NEUTRAL day, watch the TOP_N gainers (longs) AND the TOP_N losers (shorts)
TRADE_ON_BULLISH = True         # take longs on BULLISH days
TRADE_ON_BEARISH = True         # take shorts on BEARISH days (backtest: +Rs 1.04 lakh over 3 years with the current rules)
MIN_STOCKS_WITH_DATA = 80       # abort selection if fewer than this many stocks returned data

# ---------------- Pullback / range breakout setup (5-min candles) ----------------
MIN_ZONE_CANDLES = 2            # pullback / consolidation must be at least this many candles
MAX_ZONE_CANDLES = 8            # ...and at most this many
PEAK_LOOKBACK = 5               # the high before the pullback must beat this many earlier candles
SL_BUFFER_PCT = 0.0005          # stop-loss sits this far (0.05%) beyond the pullback low/high
MIN_RISK_PCT = 0.005            # skip setups whose stop-loss is closer than 0.5% (tight stops = huge positions = heavy charges)
MAX_RISK_PCT = 0.015            # skip setups whose stop-loss is further than 1.5% (too wide)
TRAIL_BE_R = 1.5               # move SL to entry only once price reaches 1.5R (not 1R) - gives trades room
TRAIL_LOCK_R = 2.0             # lock 1R profit at 2R (same level as the target, so in practice: breakeven at 1.5R)
RISK_REWARD = 2.0               # target = 2 x risk (1:2)
SIGNAL_GRACE_CANDLES = 1        # GitHub runs can start late; accept a setup up to this many
                                # candles old (entry still uses that setup candle's close)

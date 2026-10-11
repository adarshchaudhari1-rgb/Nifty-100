"""
Paper trading engine.

Position sizing: quantity is chosen so that hitting the stop-loss loses exactly
RISK_PER_TRADE, capped so total open position value never exceeds
capital x LEVERAGE.

Trailing stop-loss (same rules as before, R = entry-to-initial-SL distance):
  - price reaches 1R profit   -> SL moves to entry (breakeven)
  - price reaches 1.5R profit -> SL moves to lock in 1R profit
  - target stays at 2R

Candle-order rule (conservative): each candle is first tested against the SL as
it stood BEFORE that candle; only afterwards can the candle tighten the SL. If a
candle touches both SL and target, SL is assumed to hit first. This avoids
flattering the paper results.

Daily limits: new trades stop for the day at -DAILY_LOSS_LIMIT, or once profit
has reached PROFIT_TRAIL_TRIGGER and then falls PROFIT_TRAIL_RISK below its peak.
Open trades always run to their own exit.
"""

import json
import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import config

IST = ZoneInfo("Asia/Kolkata")
TRADE_LOG_FILE = "trade_log.json"


def calculate_quantity(entry: float, sl: float, capital: float = config.STARTING_CAPITAL,
                       risk_amount: float = config.RISK_PER_TRADE,
                       leverage: float = config.LEVERAGE,
                       max_position_value: float = None) -> int:
    """Shares to trade so an SL hit loses `risk_amount`, within the buying-power limit."""
    per_share_risk = abs(entry - sl)
    if per_share_risk <= 0 or entry <= 0:
        return 0
    limit_value = capital * leverage
    if max_position_value is not None:
        limit_value = min(limit_value, max_position_value)
    qty = min(risk_amount / per_share_risk, limit_value / entry)
    return max(0, math.floor(qty))


def _today_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


class PaperTrader:
    def __init__(self, log_file: str = TRADE_LOG_FILE):
        self.log_file = log_file
        self.open_trades = {}
        self.closed_trades = []
        self.capital = config.STARTING_CAPITAL
        self._load()

    # ---------- storage ----------
    def _load(self):
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file) as f:
                    d = json.load(f)
            except json.JSONDecodeError:
                d = {}
            self.closed_trades = d.get("closed", [])
            self.open_trades = d.get("open", {})
            self.capital = d.get("capital", config.STARTING_CAPITAL)

    def _save(self):
        with open(self.log_file, "w") as f:
            json.dump({"open": self.open_trades, "closed": self.closed_trades,
                       "capital": self.capital}, f, indent=2, default=str)

    # ---------- queries ----------
    def has_open_trade(self, symbol: str) -> bool:
        return symbol in self.open_trades

    def traded_today(self, symbol: str, date_str: str) -> bool:
        """True if this stock already had a trade (open or closed) today."""
        t = self.open_trades.get(symbol)
        if t and str(t.get("entry_time", "")).startswith(date_str):
            return True
        return any(c["symbol"] == symbol and str(c.get("entry_time", "")).startswith(date_str)
                   for c in self.closed_trades)

    def open_position_value(self) -> float:
        return sum(t.get("position_value", 0) for t in self.open_trades.values())

    # ---------- trade lifecycle ----------
    def open_trade(self, symbol: str, signal: dict, qty: int = None):
        entry, sl = signal["entry"], signal["sl"]
        if qty is None:
            qty = calculate_quantity(entry, sl, capital=self.capital)
        trade = {
            "symbol": symbol,
            "direction": signal["direction"],
            "pattern": signal["pattern"],
            "entry": entry,
            "initial_sl": sl,
            "sl": sl,
            "target": signal["target"],
            "risk": abs(entry - sl),
            "qty": qty,
            "position_value": round(qty * entry, 2),
            "trail_stage": "none",
            "entry_time": str(signal.get("entry_time", signal["time"])),
            "last_checked": str(signal["time"]),   # candles after this still need checking
        }
        self.open_trades[symbol] = trade
        self._save()
        return trade

    def _update_trailing_sl(self, trade: dict, candle) -> None:
        entry, risk = trade["entry"], trade["risk"]
        if risk <= 0:
            return
        if trade["direction"] == "LONG":
            profit_r = (candle["High"] - entry) / risk
            lock_level, be_level = entry + risk, entry
        else:
            profit_r = (entry - candle["Low"]) / risk
            lock_level, be_level = entry - risk, entry
        if profit_r >= 1.5 and trade["trail_stage"] != "locked_1r":
            trade["sl"], trade["trail_stage"] = lock_level, "locked_1r"
        elif profit_r >= 1.0 and trade["trail_stage"] == "none":
            trade["sl"], trade["trail_stage"] = be_level, "breakeven"

    def _close(self, symbol: str, exit_price: float, exit_time: str, outcome: str) -> dict:
        trade = self.open_trades[symbol]
        if trade["direction"] == "LONG":
            per_share = exit_price - trade["entry"]
        else:
            per_share = trade["entry"] - exit_price
        pnl_rupees = round(per_share * trade["qty"], 2)
        self.capital = round(self.capital + pnl_rupees, 2)
        result = {**trade, "exit_price": round(exit_price, 2), "exit_time": exit_time,
                  "outcome": outcome, "pnl_pct": round(per_share / trade["entry"] * 100, 2),
                  "pnl_rupees": pnl_rupees, "capital_after": self.capital}
        self.closed_trades.append(result)
        del self.open_trades[symbol]
        self._save()
        return result

    def check_exit(self, symbol: str, candle):
        """Test one completed candle against the open trade. Returns the closed trade or None."""
        trade = self.open_trades.get(symbol)
        if trade is None:
            return None
        high, low = candle["High"], candle["Low"]
        long_side = trade["direction"] == "LONG"

        hit_sl = (low <= trade["sl"]) if long_side else (high >= trade["sl"])
        hit_target = (high >= trade["target"]) if long_side else (low <= trade["target"])

        if hit_sl:                                  # SL wins ties (conservative)
            outcome = {"none": "SL", "breakeven": "BREAKEVEN", "locked_1r": "TRAILED_SL"}[trade["trail_stage"]]
            return self._close(symbol, trade["sl"], str(candle.name), outcome)
        if hit_target:
            return self._close(symbol, trade["target"], str(candle.name), "TARGET")

        self._update_trailing_sl(trade, candle)     # tighten SL for the NEXT candle
        trade["last_checked"] = str(candle.name)
        self._save()
        return None

    def force_close(self, symbol: str, price: float, time_str: str, outcome: str = "EOD"):
        """Square off at a given price (used at the end of the day)."""
        if symbol not in self.open_trades:
            return None
        return self._close(symbol, price, time_str, outcome)

    # ---------- daily stats ----------
    def daily_risk_status(self, date: str = None) -> dict:
        date = date or _today_str()
        todays = sorted((t for t in self.closed_trades if t["exit_time"].startswith(date)),
                        key=lambda t: t["exit_time"])
        running = peak = 0.0
        for t in todays:
            running += t["pnl_rupees"]
            peak = max(peak, running)

        halted, reason = False, None
        if running <= -config.DAILY_LOSS_LIMIT:
            halted = True
            reason = f"Daily loss limit hit (Rs {running:.0f}, limit -Rs {config.DAILY_LOSS_LIMIT})"
        elif peak >= config.PROFIT_TRAIL_TRIGGER and running <= peak - config.PROFIT_TRAIL_RISK:
            halted = True
            reason = (f"Profit trail stop hit (peak Rs {peak:.0f}, now Rs {running:.0f}, "
                      f"trail level Rs {peak - config.PROFIT_TRAIL_RISK:.0f})")
        return {"date": date, "running_pnl": round(running, 2), "peak_pnl": round(peak, 2),
                "halted": halted, "reason": reason}

    def daily_summary(self, date: str = None) -> dict:
        date = date or _today_str()
        todays = [t for t in self.closed_trades if t["exit_time"].startswith(date)]
        wins = [t for t in todays if t["pnl_rupees"] > 0]
        return {
            "date": date,
            "total_trades": len(todays),
            "wins": len(wins),
            "losses": len(todays) - len(wins),
            "win_rate": round(len(wins) / len(todays) * 100, 1) if todays else 0,
            "total_pnl_rupees": round(sum(t["pnl_rupees"] for t in todays), 2),
            "total_pnl_pct": round(sum(t["pnl_pct"] for t in todays), 2),
            "current_capital": self.capital,
            "trades": todays,
        }

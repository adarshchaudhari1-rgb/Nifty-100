"""
Nifty 100 market-nature agent (paper trading).

GitHub Actions runs `python agent.py` every 5 minutes from 10:00 to 15:30 IST.
Each run does one pass:

  1. First run of the day: scan Nifty 100, decide BULLISH / BEARISH / NEUTRAL,
     pick the top 5 stocks in that direction, save them (daily_watchlist.json).
  2. Every run: for those 5 stocks, manage any open trade (SL / target / trailing
     SL / 3:15 PM square-off) and look for a fresh pullback/range breakout.

Other commands:
    python agent.py --report    print today's summary
    python agent.py --select    force a fresh Nifty 100 scan right now
"""

import argparse

import pandas as pd

import config
import data
import scanner
import strategy
from paper_trader import PaperTrader, calculate_quantity


def short(symbol: str) -> str:
    return symbol.replace(".NS", "")


def report_close(r: dict) -> None:
    print(f"[{short(r['symbol'])}] CLOSED {r['direction']} -> {r['outcome']} | "
          f"PnL Rs {r['pnl_rupees']} ({r['pnl_pct']}%) | Capital Rs {r['capital_after']}")


def manage_open_trade(trader: PaperTrader, symbol: str, df: pd.DataFrame, now):
    """Check every completed candle since the last check (so a delayed run can't
    miss an SL/target), then square off at the end of the day."""
    trade = trader.open_trades.get(symbol)
    if trade is None or df.empty:
        return None
    last = pd.Timestamp(trade.get("last_checked") or trade["entry_time"])
    for _, candle in df[df.index > last].iterrows():
        result = trader.check_exit(symbol, candle)
        if result:
            report_close(result)
            return result
    if now.time() >= config.SQUARE_OFF_TIME and trader.has_open_trade(symbol):
        result = trader.force_close(symbol, float(df["Close"].iloc[-1]), str(df.index[-1]), "EOD")
        report_close(result)
        return result
    return None


def run_once(now=None) -> None:
    now = now or data.now_ist()
    today, today_str = now.date(), now.strftime("%Y-%m-%d")
    print(f"=== Run at {now:%Y-%m-%d %H:%M} IST ===")

    if now.weekday() >= 5:
        print("Weekend - nothing to do")
        return
    if now.time() < config.SELECTION_TIME:
        print(f"Before {config.SELECTION_TIME:%H:%M} - nothing to do yet")
        return
    wl = scanner.load_watchlist(today_str)
    if wl:
        data.seed_instrument_keys(wl.get("instrument_keys"))   # saves re-downloading Upstox's list
    if not data.market_traded_today(today):
        print("No candles for today (market holiday or data problem) - skipping this run")
        return
    print(f"Data source: {data.LAST_SOURCE}")

    trader = PaperTrader()

    # A trade left open from an earlier day can't be tracked properly - reset it flat.
    for sym in list(trader.open_trades):
        if not str(trader.open_trades[sym]["entry_time"]).startswith(today_str):
            print(f"[{short(sym)}] stale open trade from an earlier day - closing flat")
            trader.force_close(sym, trader.open_trades[sym]["entry"], str(now), "STALE_RESET")

    # 1. Today's watchlist (created once, on the first run after 10:00)
    if wl is None:
        wl = scanner.run_selection(now)
        if wl is None:
            return
        print(scanner.describe(wl))
    else:
        print(scanner.describe(wl).split("\n")[0])

    symbols = [s["symbol"] for s in wl["stocks"]]
    for sym in trader.open_trades:
        if sym not in symbols:
            symbols.append(sym)
    if not symbols:
        return

    direction = "LONG" if wl["nature"] == "BULLISH" else "SHORT"
    status = trader.daily_risk_status(today_str)
    if status["halted"]:
        print(f"NO NEW TRADES TODAY: {status['reason']}")

    candles = data.fetch_intraday(symbols, period="1d")

    # 2. Manage open trades and look for entries
    for sym in symbols:
        name = short(sym)
        df = data.completed_candles(candles.get(sym), now)
        if df.empty:
            print(f"[{name}] no completed candles yet")
            continue

        if trader.has_open_trade(sym):
            manage_open_trade(trader, sym, df, now)
            continue

        if trader.daily_risk_status(today_str)["halted"]:
            continue
        if trader.traded_today(sym, today_str):
            print(f"[{name}] already traded today")
            continue
        if now.time() >= config.SQUARE_OFF_TIME:
            continue

        setups = strategy.find_setups(df, direction)
        print(f"[{name}] {len(setups)} {direction} setup(s) so far today "
              f"(last completed candle {df.index[-1]:%H:%M})")
        if not setups:
            continue
        setup = setups[-1]
        if setup["index"] < len(df) - 1 - config.SIGNAL_GRACE_CANDLES:
            continue                                   # too old to act on

        buying_power = trader.capital * config.LEVERAGE - trader.open_position_value()
        qty = calculate_quantity(setup["entry"], setup["sl"], capital=trader.capital,
                                 max_position_value=buying_power)
        if qty <= 0:
            print(f"[{name}] setup found but quantity is 0 (no buying power / SL too wide) - skipped")
            continue

        trade = trader.open_trade(sym, setup, qty=qty)
        print(f"[{name}] OPENED {trade['direction']} ({trade['pattern']}, {setup['zone_candles']}-candle zone) "
              f"qty {trade['qty']} @ {trade['entry']:.2f} (Rs {trade['position_value']:.0f}) | "
              f"SL {trade['sl']:.2f} ({setup['risk_pct']}%) | Target {trade['target']:.2f}")
        manage_open_trade(trader, sym, df, now)        # catch up on candles after the setup candle


def print_report(trader: PaperTrader) -> None:
    today_str = data.now_ist().strftime("%Y-%m-%d")
    summary = trader.daily_summary(today_str)
    status = trader.daily_risk_status(today_str)
    wl = scanner.load_watchlist(today_str)

    print("\n===== DAILY SUMMARY:", summary["date"], "=====")
    print(scanner.describe(wl) if wl else "No watchlist today (holiday, data problem, or too early)")
    print(f"Trades: {summary['total_trades']}  |  Wins: {summary['wins']}  |  "
          f"Losses: {summary['losses']}  |  Win rate: {summary['win_rate']}%")
    print(f"Today's PnL: Rs {summary['total_pnl_rupees']} ({summary['total_pnl_pct']}%)")
    print(f"Current Capital: Rs {summary['current_capital']} (started at Rs {config.STARTING_CAPITAL})")
    if status["halted"]:
        print(f"Trading halted today: {status['reason']}")
    for t in summary["trades"]:
        entered = str(t["entry_time"])[11:16]
        exited = str(t["exit_time"])[11:16]
        print(f"  {short(t['symbol']):<12} {t['direction']:<5} qty {t['qty']:<5} "
              f"{entered} @ {t['entry']:.2f} -> {exited} @ {t['exit_price']:.2f} "
              f"[{t['outcome']}] Rs {t['pnl_rupees']} ({t['pnl_pct']}%)")
    for sym, t in trader.open_trades.items():
        print(f"  OPEN: {short(sym)} {t['direction']} qty {t['qty']} @ {t['entry']:.2f} "
              f"SL {t['sl']:.2f} Target {t['target']:.2f}")
    print("=" * 45)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="accepted for compatibility; every run is one pass")
    parser.add_argument("--report", action="store_true", help="print today's summary and exit")
    parser.add_argument("--select", action="store_true", help="force a fresh Nifty 100 scan now")
    args = parser.parse_args()

    if args.report:
        print_report(PaperTrader())
    elif args.select:
        wl = scanner.run_selection(data.now_ist())
        if wl:
            print(scanner.describe(wl))
    else:
        run_once()


if __name__ == "__main__":
    main()

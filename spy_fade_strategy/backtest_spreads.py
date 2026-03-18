"""
Credit Spread Backtest Engine
==============================
ABOVE VWAP (fade): Bear Call Spreads (short higher-delta call + long lower-delta call)
BELOW VWAP (buy):  Bull Put Spreads  (short higher-delta put + long lower-delta put)

All P&L from REAL Polygon market prices. Defined risk on every trade.

Spread P&L at time t:
  Credit received = short_entry - long_entry
  Cost to close   = short_t - long_t  (mark-to-market of the spread)
  P&L = credit - cost_to_close
  Max profit = credit received (both expire worthless)
  Max loss   = spread_width - credit (both expire ITM)
"""

import pandas as pd
import numpy as np
from itertools import product
import config


# ═══════════════════════════════════════════════════════════════════════════
#  SPREAD CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Delta pairs for spreads: (short_delta, long_delta)
# Short delta is closer to ATM (higher premium), long delta is further OTM (cheaper)
SPREAD_PAIRS = [
    # Wide spreads (more credit, more risk)
    (0.50, 0.30),
    (0.50, 0.35),
    (0.50, 0.40),
    # Medium spreads
    (0.40, 0.20),
    (0.40, 0.25),
    (0.40, 0.30),
    (0.35, 0.20),
    (0.35, 0.25),
    # Narrow spreads (less credit, less risk)
    (0.30, 0.15),
    (0.30, 0.20),
    (0.25, 0.15),
    (0.25, 0.10),
    (0.20, 0.10),
]

# Profit targets as % of MAX PROFIT (credit received)
# e.g., 0.50 = close when you've captured 50% of the credit
SPREAD_PROFIT_TARGETS = [0.25, 0.50, 0.75, 0.90, 1.0]

# Stop losses as multiple of credit received
# e.g., 1.0 = stop when you've lost 1x the credit (so total loss = 2x credit)
# 2.0 = stop when you've lost 2x credit (approaching max loss on narrow spread)
SPREAD_STOP_LOSSES = [0.5, 1.0, 1.5, 2.0, 3.0]

# Time exits
SPREAD_TIME_EXITS = [5, 10, 15, 30, 60, "EOD"]


# ═══════════════════════════════════════════════════════════════════════════
#  SPREAD TRADE SIMULATOR
# ═══════════════════════════════════════════════════════════════════════════

def simulate_credit_spread_trade(short_bars, long_bars, short_entry, long_entry,
                                  profit_target_pct, stop_loss_mult, time_exit_min,
                                  spread_width_dollars=None):
    """
    Simulate a credit spread trade using real market prices for both legs.

    Parameters
    ----------
    short_bars : DataFrame, intraday bars for the SHORT leg (higher delta, more premium)
    long_bars : DataFrame, intraday bars for the LONG leg (lower delta, less premium)
    short_entry : float, entry price of the short leg
    long_entry : float, entry price of the long leg
    profit_target_pct : float, close at this % of max profit (credit)
                        e.g., 0.50 = close when spread has captured 50% of credit
    stop_loss_mult : float, stop at this multiple of credit as loss
                     e.g., 1.0 = stop when loss = 1x credit received
    time_exit_min : int or "EOD", time-based exit
    spread_width_dollars : float or None, width between strikes in dollars
                          (used to calculate max loss; if None, estimated from bars)

    Returns
    -------
    dict with trade results
    """
    credit = short_entry - long_entry  # Net credit received

    if credit <= 0 or short_bars.empty or long_bars.empty:
        return _empty_spread_result(short_entry, long_entry, credit)

    # Calculate targets in dollar terms
    # Profit target: close when spread value has decayed to (1 - pct) * credit
    # i.e., we want to buy back the spread for less
    target_spread_value = credit * (1 - profit_target_pct)  # What we'd pay to close
    target_spread_value = max(target_spread_value, 0)

    # Stop loss: close when spread value has expanded by stop_loss_mult * credit
    stop_spread_value = credit + (stop_loss_mult * credit)  # Max we'd pay to close

    # Align bars by timestamp — use the short leg's timestamps as the driver
    # and find the closest long leg bar for each
    entry_ts = short_bars["timestamp"].iloc[0]

    # Create a merged view: for each short bar, find matching long bar
    long_bars_indexed = long_bars.set_index("timestamp").sort_index()

    for idx in range(len(short_bars)):
        short_bar = short_bars.iloc[idx]
        ts = short_bar["timestamp"]
        minutes_elapsed = (ts - entry_ts).total_seconds() / 60

        # Find the closest long bar at or before this timestamp
        long_match = long_bars_indexed.loc[:ts]
        if long_match.empty:
            continue
        long_bar = long_match.iloc[-1]

        # Current spread value (what it would cost to close both legs)
        # For a credit spread: spread_value = short_current - long_current
        # High spread_value = bad (costs more to close), low = good (cheaper to close)

        # Check using midpoints of the bar for more realistic fill
        # Worst case for us on the short leg: high (costs more to buy back)
        # Best case for us on the long leg: high (we sell for more)

        # Conservative P&L check using short high (worst for us) and long low (worst for us)
        worst_spread_value = short_bar["high"] - long_bar["low"]
        # Optimistic P&L check using short low (best for us) and long high (best for us)
        best_spread_value = short_bar["low"] - long_bar["high"]
        best_spread_value = max(best_spread_value, 0)  # Can't go below 0

        # Mark-to-market using close prices
        current_spread_value = short_bar["close"] - long_bar["close"]
        current_spread_value = max(current_spread_value, 0)

        # SKIP EXIT CHECKS ON ENTRY BAR — can't realistically open and close
        # a spread in the same 1-minute bar. Need at least 1 bar to pass.
        if idx == 0:
            continue

        # Time exit check
        if time_exit_min is not None:
            if time_exit_min == "EOD":
                if ts.hour == 15 and ts.minute >= 59:
                    pnl = credit - current_spread_value
                    return _build_spread_result(
                        short_entry, long_entry, credit, current_spread_value,
                        pnl, "time_eod", idx, minutes_elapsed, spread_width_dollars
                    )
            elif minutes_elapsed >= time_exit_min:
                pnl = credit - current_spread_value
                return _build_spread_result(
                    short_entry, long_entry, credit, current_spread_value,
                    pnl, f"time_{time_exit_min}m", idx, minutes_elapsed, spread_width_dollars
                )

        # Profit target: spread value dropped below target (we can close cheaply)
        if best_spread_value <= target_spread_value:
            close_value = max(target_spread_value, best_spread_value)
            pnl = credit - close_value
            return _build_spread_result(
                short_entry, long_entry, credit, close_value,
                pnl, "target", idx, minutes_elapsed, spread_width_dollars
            )

        # Stop loss: spread value expanded beyond stop (losing money)
        if worst_spread_value >= stop_spread_value:
            close_value = min(stop_spread_value, worst_spread_value)
            pnl = credit - close_value
            return _build_spread_result(
                short_entry, long_entry, credit, close_value,
                pnl, "stop_loss", idx, minutes_elapsed, spread_width_dollars
            )

    # End of data — close at last available prices
    last_short = short_bars.iloc[-1]
    long_match = long_bars_indexed.loc[:last_short["timestamp"]]
    if not long_match.empty:
        last_long = long_match.iloc[-1]
        final_spread = max(last_short["close"] - last_long["close"], 0)
    else:
        final_spread = max(last_short["close"] - long_bars.iloc[-1]["close"], 0)

    pnl = credit - final_spread
    minutes_elapsed = (last_short["timestamp"] - entry_ts).total_seconds() / 60

    return _build_spread_result(
        short_entry, long_entry, credit, final_spread,
        pnl, "end_of_data", len(short_bars) - 1, minutes_elapsed, spread_width_dollars
    )


# ═══════════════════════════════════════════════════════════════════════════
#  SPREAD BACKTEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_spread_backtest(options_data_dict, signals_df, spread_type, direction):
    """
    Run credit spread backtest across all delta pairs and exit combos.

    spread_type: "bear_call_spread" (above VWAP) or "bull_put_spread" (below VWAP)
    direction: "above" or "below"
    """
    is_call_spread = spread_type == "bear_call_spread"
    option_side = "calls" if is_call_spread else "puts"

    print(f"\n{'='*60}")
    print(f"{spread_type.upper().replace('_', ' ')} BACKTEST ({direction.upper()} VWAP)")
    print(f"{'='*60}")

    results = []

    for short_delta, long_delta in SPREAD_PAIRS:
        for pt, sl, te in product(SPREAD_PROFIT_TARGETS, SPREAD_STOP_LOSSES, SPREAD_TIME_EXITS):
            trades = []

            for _, signal in signals_df.iterrows():
                date_str = str(signal["date"])
                if date_str not in options_data_dict:
                    continue

                day_data = options_data_dict[date_str]
                opt_dict = getattr(day_data, option_side)

                # Need both deltas available for this day
                if short_delta not in opt_dict or long_delta not in opt_dict:
                    continue

                short_info = opt_dict[short_delta]
                long_info = opt_dict[long_delta]

                short_bars = short_info["bars"]
                long_bars = long_info["bars"]
                short_entry = short_info["entry_price"]
                long_entry = long_info["entry_price"]

                if short_entry <= 0 or long_entry <= 0 or short_bars.empty or long_bars.empty:
                    continue

                # Credit must be positive (short leg more expensive than long leg)
                if short_entry <= long_entry:
                    continue

                # Spread width in dollars
                spread_width = abs(short_info["strike"] - long_info["strike"])

                trade = simulate_credit_spread_trade(
                    short_bars, long_bars, short_entry, long_entry,
                    pt, sl, te, spread_width
                )
                trade["date"] = signal["date"]
                trade["short_delta"] = short_delta
                trade["long_delta"] = long_delta
                trade["short_strike"] = short_info["strike"]
                trade["long_strike"] = long_info["strike"]
                trade["spot_at_entry"] = signal["entry_price"]
                trade["direction"] = direction
                trades.append(trade)

            if not trades:
                continue

            trades_df = pd.DataFrame(trades)
            metrics = _compute_spread_metrics(trades_df)
            metrics["short_delta"] = short_delta
            metrics["long_delta"] = long_delta
            metrics["spread_pair"] = f"{short_delta:.2f}/{long_delta:.2f}"
            metrics["profit_target"] = pt
            metrics["stop_loss"] = sl
            metrics["time_exit"] = te
            metrics["spread_type"] = spread_type
            metrics["direction"] = direction
            results.append(metrics)

    if not results:
        print(f"  No {spread_type} trades executed (missing paired delta data)")
        return pd.DataFrame(), {}

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("sharpe", ascending=False)
    print(f"  Combos tested: {len(results_df)}")

    if not results_df.empty:
        best = results_df.iloc[0]
        print(f"  Best: {best['spread_pair']} spread, target={best['profit_target']}x, "
              f"stop={best['stop_loss']}x, time={best['time_exit']}")
        print(f"  Expectancy: {best['expectancy']:+.2f}%, WR: {best['win_rate']:.1f}%, "
              f"N={best['n_trades']}, Sharpe: {best['sharpe']:.3f}")

    return results_df, {}


# Convenience wrappers
def run_bear_call_spreads_backtest(options_data_dict, signals_df):
    """Bear call spreads for fading above VWAP."""
    return run_spread_backtest(options_data_dict, signals_df, "bear_call_spread", "above")

def run_bull_put_spreads_backtest(options_data_dict, signals_df):
    """Bull put spreads for buying dip below VWAP."""
    return run_spread_backtest(options_data_dict, signals_df, "bull_put_spread", "below")


# ═══════════════════════════════════════════════════════════════════════════
#  BEST PARAMS FINDER
# ═══════════════════════════════════════════════════════════════════════════

def get_best_spread_params(results_df, min_trades=15, min_credit=0.05):
    """
    Find best spread parameter combo scored by Sharpe.

    Filters:
      - min_trades: minimum sample size
      - min_credit: minimum avg net credit in $ (spread must collect meaningful premium)
    """
    if results_df.empty:
        return pd.DataFrame(), None

    filtered = results_df[results_df["n_trades"] >= min_trades].copy()
    if filtered.empty:
        filtered = results_df[results_df["n_trades"] >= max(3, min_trades // 2)].copy()
    if filtered.empty:
        filtered = results_df.copy()

    # Credit realism filter
    if "avg_credit" in filtered.columns:
        realistic = filtered[filtered["avg_credit"] >= min_credit]
        if not realistic.empty:
            filtered = realistic

    # Score by Sharpe × sqrt(N)
    filtered["score"] = filtered["sharpe"] * np.sqrt(filtered["n_trades"])

    # Prefer positive expectancy
    positive = filtered[filtered["expectancy"] > 0]
    if not positive.empty:
        filtered = positive

    if filtered.empty:
        return pd.DataFrame(), None

    best_per_pair = filtered.loc[filtered.groupby("spread_pair")["score"].idxmax()]
    overall_best = filtered.sort_values("score", ascending=False).iloc[0]

    return best_per_pair, overall_best


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _empty_spread_result(short_entry, long_entry, credit):
    return {
        "short_entry": short_entry, "long_entry": long_entry,
        "credit": credit, "exit_spread_value": credit,
        "pnl_dollar": 0, "pnl_pct": 0, "pnl_on_risk": 0,
        "exit_reason": "no_data", "bars_held": 0, "minutes_held": 0,
    }


def _build_spread_result(short_entry, long_entry, credit, exit_spread_value,
                          pnl_dollar, exit_reason, idx, minutes_elapsed,
                          spread_width=None):
    # P&L as % of credit received
    pnl_pct = (pnl_dollar / credit * 100) if credit > 0 else 0

    # P&L as % of max risk (spread_width - credit, i.e., capital at risk)
    if spread_width and spread_width > credit:
        max_risk = spread_width - credit
        pnl_on_risk = (pnl_dollar / max_risk * 100)
    else:
        pnl_on_risk = pnl_pct  # Fallback

    return {
        "short_entry": short_entry,
        "long_entry": long_entry,
        "credit": credit,
        "exit_spread_value": exit_spread_value,
        "pnl_dollar": pnl_dollar,
        "pnl_pct": pnl_pct,       # % of credit
        "pnl_on_risk": pnl_on_risk,  # % of max risk (capital efficiency)
        "exit_reason": exit_reason,
        "bars_held": idx + 1,
        "minutes_held": minutes_elapsed,
        "spread_width": spread_width,
    }


def _compute_spread_metrics(trades_df):
    n = len(trades_df)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0, "avg_pnl": 0, "median_pnl": 0,
            "total_pnl": 0, "expectancy": 0, "profit_factor": 0,
            "max_drawdown_pct": 0, "avg_winner": 0, "avg_loser": 0,
            "best_trade": 0, "worst_trade": 0, "avg_minutes_held": 0,
            "avg_credit": 0, "avg_pnl_dollar": 0, "sharpe": 0, "sortino": 0,
            "avg_pnl_on_risk": 0,
        }

    # Use pnl_on_risk for metrics (% return on capital at risk)
    pnl_col = "pnl_on_risk" if "pnl_on_risk" in trades_df.columns else "pnl_pct"

    winners = trades_df[trades_df[pnl_col] > 0]
    losers = trades_df[trades_df[pnl_col] < 0]
    total_wins = winners[pnl_col].sum() if len(winners) > 0 else 0
    total_losses = abs(losers[pnl_col].sum()) if len(losers) > 0 else 0

    cum_pnl = trades_df[pnl_col].cumsum()
    max_dd = (cum_pnl - cum_pnl.cummax()).min()

    # Sharpe and Sortino
    pnl_std = trades_df[pnl_col].std()
    sharpe = trades_df[pnl_col].mean() / pnl_std if pnl_std > 0 and n >= 3 else 0

    downside = trades_df[trades_df[pnl_col] < 0][pnl_col]
    downside_std = downside.std() if len(downside) >= 2 else pnl_std
    sortino = trades_df[pnl_col].mean() / downside_std if downside_std > 0 and n >= 3 else 0

    return {
        "n_trades": n,
        "win_rate": len(winners) / n * 100,
        "avg_pnl": trades_df[pnl_col].mean(),
        "median_pnl": trades_df[pnl_col].median(),
        "total_pnl": trades_df[pnl_col].sum(),
        "expectancy": trades_df[pnl_col].mean(),
        "profit_factor": total_wins / total_losses if total_losses > 0 else np.inf,
        "max_drawdown_pct": max_dd,
        "avg_winner": winners[pnl_col].mean() if len(winners) > 0 else 0,
        "avg_loser": losers[pnl_col].mean() if len(losers) > 0 else 0,
        "best_trade": trades_df[pnl_col].max(),
        "worst_trade": trades_df[pnl_col].min(),
        "avg_minutes_held": trades_df["minutes_held"].mean(),
        "avg_credit": trades_df["credit"].mean(),
        "avg_pnl_dollar": trades_df["pnl_dollar"].mean(),
        "avg_pnl_on_risk": trades_df["pnl_on_risk"].mean() if "pnl_on_risk" in trades_df.columns else 0,
        "sharpe": sharpe,
        "sortino": sortino,
        "exit_reasons": trades_df["exit_reason"].value_counts().to_dict(),
    }

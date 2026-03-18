"""
Options Backtest Engine: All Four Option Products
==================================================
ABOVE VWAP (fade): Long puts, Short calls
BELOW VWAP (buy):  Long calls, Short puts

All P&L from REAL Polygon market prices. No Black-Scholes.
"""

import pandas as pd
import numpy as np
from itertools import product
import config


# ═══════════════════════════════════════════════════════════════════════════
#  GENERIC OPTION TRADE SIMULATORS
# ═══════════════════════════════════════════════════════════════════════════

def simulate_long_option_trade(bars_df, entry_price, profit_target_pct,
                                stop_loss_pct, time_exit_min=None, label="long_option"):
    """
    Simulate buying an option (put or call). Works identically for both.
    Profit: option price rises. Loss: option price falls.
    """
    if bars_df.empty or entry_price <= 0:
        return _empty_options_result(entry_price)

    target_price = entry_price * (1 + profit_target_pct)
    stop_price = entry_price * (1 - stop_loss_pct)
    entry_ts = bars_df["timestamp"].iloc[0]

    for idx, bar in bars_df.iterrows():
        minutes_elapsed = (bar["timestamp"] - entry_ts).total_seconds() / 60

        if time_exit_min is not None:
            if time_exit_min == "EOD":
                if bar["timestamp"].hour == 15 and bar["timestamp"].minute >= 59:
                    return _build_options_result(entry_price, bar["close"], "time_eod",
                                                 idx, minutes_elapsed, bars_df, entry_ts, "long")
            elif minutes_elapsed >= time_exit_min:
                return _build_options_result(entry_price, bar["close"], f"time_{time_exit_min}m",
                                             idx, minutes_elapsed, bars_df, entry_ts, "long")

        if bar["high"] >= target_price:
            return _build_options_result(entry_price, min(target_price, bar["high"]), "target",
                                         idx, minutes_elapsed, bars_df, entry_ts, "long")

        if bar["low"] <= stop_price:
            return _build_options_result(entry_price, max(stop_price, bar["low"]), "stop_loss",
                                         idx, minutes_elapsed, bars_df, entry_ts, "long")

    last = bars_df.iloc[-1]
    minutes_elapsed = (last["timestamp"] - entry_ts).total_seconds() / 60
    return _build_options_result(entry_price, last["close"], "end_of_data",
                                 len(bars_df) - 1, minutes_elapsed, bars_df, entry_ts, "long")


def simulate_short_option_trade(bars_df, entry_price, profit_target_pct,
                                 stop_loss_pct, time_exit_min=None, label="short_option"):
    """
    Simulate selling an option (put or call). Works identically for both.
    Profit: option price falls. Loss: option price rises.
    """
    if bars_df.empty or entry_price <= 0:
        return _empty_options_result(entry_price)

    target_price = entry_price * (1 - profit_target_pct)
    target_price = max(target_price, 0.01)
    stop_price = entry_price * (1 + stop_loss_pct)
    entry_ts = bars_df["timestamp"].iloc[0]

    for idx, bar in bars_df.iterrows():
        minutes_elapsed = (bar["timestamp"] - entry_ts).total_seconds() / 60

        if time_exit_min is not None:
            if time_exit_min == "EOD":
                if bar["timestamp"].hour == 15 and bar["timestamp"].minute >= 59:
                    return _build_options_result(entry_price, bar["close"], "time_eod",
                                                 idx, minutes_elapsed, bars_df, entry_ts, "short")
            elif minutes_elapsed >= time_exit_min:
                return _build_options_result(entry_price, bar["close"], f"time_{time_exit_min}m",
                                             idx, minutes_elapsed, bars_df, entry_ts, "short")

        if bar["high"] >= stop_price:
            return _build_options_result(entry_price, max(stop_price, bar["open"]), "stop_loss",
                                         idx, minutes_elapsed, bars_df, entry_ts, "short")

        if bar["low"] <= target_price:
            return _build_options_result(entry_price, min(target_price, bar["open"]), "target",
                                         idx, minutes_elapsed, bars_df, entry_ts, "short")

    last = bars_df.iloc[-1]
    minutes_elapsed = (last["timestamp"] - entry_ts).total_seconds() / 60
    return _build_options_result(entry_price, last["close"], "end_of_data",
                                 len(bars_df) - 1, minutes_elapsed, bars_df, entry_ts, "short")


# Keep the old names as aliases for backward compat
simulate_long_put_trade = simulate_long_option_trade
simulate_short_call_trade = simulate_short_option_trade
simulate_long_call_trade = simulate_long_option_trade
simulate_short_put_trade = simulate_short_option_trade


# ═══════════════════════════════════════════════════════════════════════════
#  GENERIC OPTIONS BACKTEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_options_backtest(options_data_dict, signals_df, product_type, direction):
    """
    Unified options backtest for any product/direction combo.

    product_type: "long_put", "short_call", "long_call", "short_put"
    direction: "above" or "below" (determines which signal set this applies to)

    Product mapping:
        ABOVE VWAP (fade):  long_put, short_call
        BELOW VWAP (buy):   long_call, short_put
    """
    is_long = product_type.startswith("long")
    is_put = product_type.endswith("put")

    # Which options data to use
    option_side = "puts" if is_put else "calls"
    target_deltas = config.PUT_DELTAS if is_put else config.CALL_DELTAS
    sim_func = simulate_long_option_trade if is_long else simulate_short_option_trade

    print(f"\n{'='*60}")
    print(f"{product_type.upper().replace('_', ' ')} BACKTEST ({direction.upper()} VWAP)")
    print(f"{'='*60}")

    profit_targets = config.OPTIONS_PROFIT_TARGETS
    stop_losses = config.OPTIONS_STOP_LOSSES
    time_exits = config.OPTIONS_TIME_EXITS

    results = []

    for delta in target_deltas:
        for pt, sl, te in product(profit_targets, stop_losses, time_exits):
            trades = []

            for _, signal in signals_df.iterrows():
                date_str = str(signal["date"])
                if date_str not in options_data_dict:
                    continue

                day_data = options_data_dict[date_str]
                option_dict = getattr(day_data, option_side)  # .puts or .calls
                if delta not in option_dict:
                    continue

                opt_info = option_dict[delta]
                bars = opt_info["bars"]
                entry_price = opt_info["entry_price"]

                if entry_price <= 0 or bars.empty:
                    continue

                trade = sim_func(bars, entry_price, pt, sl, te, label=product_type)
                trade["date"] = signal["date"]
                trade["delta"] = delta
                trade["strike"] = opt_info["strike"]
                trade["spot_at_entry"] = signal["entry_price"]
                trade["vix_regime"] = signal.get("vix_regime", "unknown")
                trade["consecutive_up"] = signal.get("consecutive_up", 0)
                trade["time_bucket"] = signal.get("time_bucket", "unknown")
                trade["direction"] = direction
                trades.append(trade)

            if not trades:
                continue

            trades_df = pd.DataFrame(trades)
            metrics = _compute_options_metrics(trades_df)
            metrics["delta"] = delta
            metrics["profit_target"] = pt
            metrics["stop_loss"] = sl
            metrics["time_exit"] = te
            metrics["product"] = product_type
            metrics["direction"] = direction
            results.append(metrics)

    if not results:
        print(f"  No {product_type} trades executed (no options data)")
        return pd.DataFrame(), {}

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("expectancy", ascending=False)
    print(f"  {product_type} combos tested: {len(results_df)}")
    if not results_df.empty:
        best = results_df.iloc[0]
        print(f"  Best: delta={best['delta']}, target={best['profit_target']}x, "
              f"stop={best['stop_loss']}x, time={best['time_exit']}")
        print(f"  Expectancy: {best['expectancy']:.2f}%, WR: {best['win_rate']:.1f}%, "
              f"N={best['n_trades']}")

    return results_df, {}


# Convenience wrappers
def run_long_puts_backtest(options_data_dict, signals_df):
    return run_options_backtest(options_data_dict, signals_df, "long_put", "above")

def run_short_calls_backtest(options_data_dict, signals_df):
    return run_options_backtest(options_data_dict, signals_df, "short_call", "above")

def run_long_calls_backtest(options_data_dict, signals_df):
    return run_options_backtest(options_data_dict, signals_df, "long_call", "below")

def run_short_puts_backtest(options_data_dict, signals_df):
    return run_options_backtest(options_data_dict, signals_df, "short_put", "below")


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _empty_options_result(entry_price):
    return {
        "entry_premium": entry_price, "exit_premium": entry_price,
        "exit_reason": "no_data", "pnl_pct": 0, "pnl_dollar": 0,
        "bars_held": 0, "minutes_held": 0,
        "max_favorable_pct": 0, "max_adverse_pct": 0,
    }


def _build_options_result(entry_price, exit_price, exit_reason, idx,
                           minutes_elapsed, bars_df, entry_ts, long_or_short):
    bars_to_exit = bars_df.iloc[:idx + 1] if idx >= 0 else bars_df.iloc[:1]

    if long_or_short == "long":
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        pnl_dollar = exit_price - entry_price
        max_favorable = (bars_to_exit["high"].max() - entry_price) / entry_price * 100
        max_adverse = (entry_price - bars_to_exit["low"].min()) / entry_price * 100
    else:  # short
        pnl_pct = (entry_price - exit_price) / entry_price * 100
        pnl_dollar = entry_price - exit_price
        max_favorable = (entry_price - bars_to_exit["low"].min()) / entry_price * 100
        max_adverse = (bars_to_exit["high"].max() - entry_price) / entry_price * 100

    return {
        "entry_premium": entry_price, "exit_premium": exit_price,
        "exit_reason": exit_reason, "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar,
        "bars_held": idx + 1, "minutes_held": minutes_elapsed,
        "max_favorable_pct": max(0, max_favorable),
        "max_adverse_pct": max(0, max_adverse),
    }


def _compute_options_metrics(trades_df):
    n = len(trades_df)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0, "avg_pnl": 0, "median_pnl": 0,
            "total_pnl": 0, "expectancy": 0, "profit_factor": 0,
            "max_drawdown_pct": 0, "avg_winner": 0, "avg_loser": 0,
            "best_trade": 0, "worst_trade": 0, "avg_minutes_held": 0,
            "avg_max_favorable": 0, "avg_max_adverse": 0, "avg_entry_premium": 0,
            "sharpe": 0, "sortino": 0, "avg_dollar_pnl": 0,
        }

    winners = trades_df[trades_df["pnl_pct"] > 0]
    losers = trades_df[trades_df["pnl_pct"] < 0]
    total_wins = winners["pnl_pct"].sum() if len(winners) > 0 else 0
    total_losses = abs(losers["pnl_pct"].sum()) if len(losers) > 0 else 0

    cum_pnl = trades_df["pnl_pct"].cumsum()
    max_dd = (cum_pnl - cum_pnl.cummax()).min()

    # Sharpe ratio (per-trade, not annualized — more meaningful for intraday)
    pnl_std = trades_df["pnl_pct"].std()
    sharpe = trades_df["pnl_pct"].mean() / pnl_std if pnl_std > 0 and n >= 3 else 0

    # Sortino ratio (only penalizes downside volatility)
    downside = trades_df[trades_df["pnl_pct"] < 0]["pnl_pct"]
    downside_std = downside.std() if len(downside) >= 2 else pnl_std
    sortino = trades_df["pnl_pct"].mean() / downside_std if downside_std > 0 and n >= 3 else 0

    # Dollar P&L (for fill-realism: a $0.02 gain on a $0.08 option = 25% but unfillable)
    avg_dollar_pnl = trades_df["pnl_dollar"].mean() if "pnl_dollar" in trades_df.columns else 0

    return {
        "n_trades": n,
        "win_rate": len(winners) / n * 100,
        "avg_pnl": trades_df["pnl_pct"].mean(),
        "median_pnl": trades_df["pnl_pct"].median(),
        "total_pnl": trades_df["pnl_pct"].sum(),
        "expectancy": trades_df["pnl_pct"].mean(),
        "profit_factor": total_wins / total_losses if total_losses > 0 else np.inf,
        "max_drawdown_pct": max_dd,
        "avg_winner": winners["pnl_pct"].mean() if len(winners) > 0 else 0,
        "avg_loser": losers["pnl_pct"].mean() if len(losers) > 0 else 0,
        "best_trade": trades_df["pnl_pct"].max(),
        "worst_trade": trades_df["pnl_pct"].min(),
        "avg_minutes_held": trades_df["minutes_held"].mean(),
        "avg_max_favorable": trades_df["max_favorable_pct"].mean(),
        "avg_max_adverse": trades_df["max_adverse_pct"].mean(),
        "avg_entry_premium": trades_df["entry_premium"].mean(),
        "sharpe": sharpe,
        "sortino": sortino,
        "avg_dollar_pnl": avg_dollar_pnl,
        "exit_reasons": trades_df["exit_reason"].value_counts().to_dict(),
    }


def get_best_options_params(results_df, min_trades=20, min_premium=0.15,
                            min_dollar_gain=0.03, scoring="sharpe"):
    """
    Find the best parameter combo, scored by Sharpe ratio with fill-realism filters.

    Filters:
      - min_trades: minimum N to consider (avoids overfitting to 3-trade wonders)
      - min_premium: minimum avg entry premium in $ (filters out penny options
                     where spreads eat you alive — $0.15 minimum)
      - min_dollar_gain: minimum avg dollar P&L per contract (filters out
                         combos where you're "making 25%" on a $0.08 option
                         = $0.02 gain, which is inside the spread)

    Scoring options:
      - "sharpe": per-trade Sharpe ratio (consistency-focused)
      - "sortino": Sortino ratio (only penalizes downside variance)
      - "expectancy": raw average P&L % (old behavior)
    """
    if results_df.empty:
        return pd.DataFrame(), None

    filtered = results_df[results_df["n_trades"] >= min_trades].copy()
    if filtered.empty:
        # Relax to half the min
        filtered = results_df[results_df["n_trades"] >= max(3, min_trades // 2)].copy()
    if filtered.empty:
        filtered = results_df.copy()

    # Fill-realism filters
    if "avg_entry_premium" in filtered.columns:
        realistic = filtered[filtered["avg_entry_premium"] >= min_premium]
        if not realistic.empty:
            filtered = realistic

    if "avg_dollar_pnl" in filtered.columns and min_dollar_gain > 0:
        # For long options: avg_dollar_pnl should be positive and meaningful
        # For short options: any positive expectancy on decent premium is fine
        has_product = "product" in filtered.columns
        if has_product:
            long_mask = filtered["product"].str.startswith("long")
            short_mask = ~long_mask
            # Long options: filter by dollar gain (need to overcome spread)
            long_ok = filtered[long_mask & (filtered["avg_dollar_pnl"] >= min_dollar_gain)]
            # Short options: filter by entry premium only (premium decay is the edge)
            short_ok = filtered[short_mask]
            combined = pd.concat([long_ok, short_ok])
            if not combined.empty:
                filtered = combined

    # Score by selected metric
    if scoring == "sharpe" and "sharpe" in filtered.columns:
        # Sharpe × sqrt(N) gives credit for sample size while prioritizing consistency
        filtered["score"] = filtered["sharpe"] * np.sqrt(filtered["n_trades"])
    elif scoring == "sortino" and "sortino" in filtered.columns:
        filtered["score"] = filtered["sortino"] * np.sqrt(filtered["n_trades"])
    else:
        # Fallback: old scoring
        filtered["score"] = (
            filtered["expectancy"]
            * np.sqrt(filtered["n_trades"])
            / (1 + filtered["max_drawdown_pct"].abs())
        )

    # Only consider positive-expectancy combos for "best"
    positive = filtered[filtered["expectancy"] > 0]
    if not positive.empty:
        filtered = positive

    best_per_delta = filtered.loc[filtered.groupby("delta")["score"].idxmax()]
    overall_best = filtered.sort_values("score", ascending=False).iloc[0]

    return best_per_delta, overall_best

"""
Stock Backtest Engine: Both Directions + Scale-In
==================================================
ABOVE VWAP → Short stock (fade)
BELOW VWAP → Long stock (buy the dip)
Supports single entry and scale-in (two entries, averaged cost basis).
"""

import pandas as pd
import numpy as np
from itertools import product
import config


def simulate_stock_trade(remaining_bars, entry_price, stop_pct, target_pct,
                          trailing_pct=None, time_exit_min=None, direction="above"):
    """
    Simulate a single stock trade.

    direction="above" → SHORT (fade): profit when price drops
    direction="below" → LONG (buy dip): profit when price rises

    Parameters
    ----------
    remaining_bars : DataFrame of 1-min bars after entry
    entry_price : float
    stop_pct : float, % from entry
    target_pct : float, % from entry
    trailing_pct : float or None
    time_exit_min : int, "EOD", or None
    direction : "above" or "below"
    """
    if remaining_bars.empty:
        return _empty_result(entry_price)

    is_short = (direction == "above")

    if is_short:
        stop_price = entry_price * (1 + stop_pct / 100)
        target_price = entry_price * (1 - target_pct / 100)
    else:  # long
        stop_price = entry_price * (1 - stop_pct / 100)
        target_price = entry_price * (1 + target_pct / 100)

    best_price = entry_price
    trailing_stop_price = None
    entry_ts = remaining_bars["timestamp"].iloc[0]

    for idx, bar in remaining_bars.iterrows():
        minutes_elapsed = (bar["timestamp"] - entry_ts).total_seconds() / 60

        # Time exit
        if time_exit_min is not None:
            if time_exit_min == "EOD":
                if bar["timestamp"].hour == 15 and bar["timestamp"].minute >= 59:
                    return _build_result(entry_price, bar["close"], "time_eod",
                                         idx, minutes_elapsed, remaining_bars, entry_ts, is_short)
            elif minutes_elapsed >= time_exit_min:
                return _build_result(entry_price, bar["close"], f"time_{time_exit_min}m",
                                     idx, minutes_elapsed, remaining_bars, entry_ts, is_short)

        if is_short:
            # Stop: high exceeds stop
            if bar["high"] >= stop_price:
                exit_price = max(stop_price, bar["open"])
                return _build_result(entry_price, exit_price, "stop_loss",
                                     idx, minutes_elapsed, remaining_bars, entry_ts, is_short)
            # Target: low reaches target
            if bar["low"] <= target_price:
                exit_price = min(target_price, bar["open"])
                return _build_result(entry_price, exit_price, "target",
                                     idx, minutes_elapsed, remaining_bars, entry_ts, is_short)
            # Trailing stop
            if trailing_pct is not None:
                if bar["low"] < best_price:
                    best_price = bar["low"]
                    trailing_stop_price = best_price * (1 + trailing_pct / 100)
                if trailing_stop_price and bar["high"] >= trailing_stop_price:
                    exit_price = max(trailing_stop_price, bar["open"])
                    return _build_result(entry_price, exit_price, "trailing_stop",
                                         idx, minutes_elapsed, remaining_bars, entry_ts, is_short)
        else:  # LONG
            # Stop: low drops below stop
            if bar["low"] <= stop_price:
                exit_price = min(stop_price, bar["open"])
                return _build_result(entry_price, exit_price, "stop_loss",
                                     idx, minutes_elapsed, remaining_bars, entry_ts, is_short)
            # Target: high reaches target
            if bar["high"] >= target_price:
                exit_price = max(target_price, bar["open"])
                return _build_result(entry_price, exit_price, "target",
                                     idx, minutes_elapsed, remaining_bars, entry_ts, is_short)
            # Trailing stop
            if trailing_pct is not None:
                if bar["high"] > best_price:
                    best_price = bar["high"]
                    trailing_stop_price = best_price * (1 - trailing_pct / 100)
                if trailing_stop_price and bar["low"] <= trailing_stop_price:
                    exit_price = min(trailing_stop_price, bar["open"])
                    return _build_result(entry_price, exit_price, "trailing_stop",
                                         idx, minutes_elapsed, remaining_bars, entry_ts, is_short)

    last = remaining_bars.iloc[-1]
    minutes_elapsed = (last["timestamp"] - entry_ts).total_seconds() / 60
    return _build_result(entry_price, last["close"], "end_of_data",
                         len(remaining_bars) - 1, minutes_elapsed, remaining_bars, entry_ts, is_short)


def simulate_scalein_trade(remaining_bars_1, entry_price_1,
                            remaining_bars_2, entry_price_2,
                            stop_pct, target_pct, trailing_pct=None,
                            time_exit_min=None, direction="above"):
    """
    Simulate a scale-in trade: enter partial at price 1, add at price 2.
    Uses average cost basis. Both positions exit together.

    If entry 2 never triggers, it's treated as a single-entry trade at price 1.
    """
    has_entry2 = (remaining_bars_2 is not None and not remaining_bars_2.empty
                  and entry_price_2 is not None)

    if not has_entry2:
        # Just run as single entry
        result = simulate_stock_trade(remaining_bars_1, entry_price_1,
                                       stop_pct, target_pct, trailing_pct,
                                       time_exit_min, direction)
        result["scale_in"] = False
        result["entry_price_2"] = None
        result["avg_entry"] = entry_price_1
        return result

    # Average entry (50/50 weight for simplicity)
    avg_entry = (entry_price_1 + entry_price_2) / 2.0

    # Use remaining bars from entry 2 onward (both positions are live)
    result = simulate_stock_trade(remaining_bars_2, avg_entry,
                                   stop_pct, target_pct, trailing_pct,
                                   time_exit_min, direction)
    result["scale_in"] = True
    result["entry_price_1"] = entry_price_1
    result["entry_price_2"] = entry_price_2
    result["avg_entry"] = avg_entry

    # Recalculate P&L from entry_1 to exit for the first leg too
    is_short = (direction == "above")
    if is_short:
        leg1_pnl = (entry_price_1 - result["exit_price"]) / entry_price_1 * 100
        leg2_pnl = (entry_price_2 - result["exit_price"]) / entry_price_2 * 100
    else:
        leg1_pnl = (result["exit_price"] - entry_price_1) / entry_price_1 * 100
        leg2_pnl = (result["exit_price"] - entry_price_2) / entry_price_2 * 100

    result["pnl_pct"] = (leg1_pnl + leg2_pnl) / 2.0  # Average of both legs
    result["pnl_dollar"] = result["pnl_pct"] / 100 * avg_entry

    return result


def _empty_result(entry_price):
    return {
        "exit_price": entry_price, "exit_reason": "no_bars",
        "pnl_pct": 0, "pnl_dollar": 0, "bars_held": 0,
        "minutes_held": 0, "max_favorable": 0, "max_adverse": 0,
    }


def _build_result(entry_price, exit_price, exit_reason, idx, minutes_elapsed,
                  remaining_bars, entry_ts, is_short):
    if is_short:
        pnl_pct = (entry_price - exit_price) / entry_price * 100
    else:
        pnl_pct = (exit_price - entry_price) / entry_price * 100

    pnl_dollar = pnl_pct / 100 * entry_price

    bars_to_exit = remaining_bars.iloc[:idx + 1] if idx >= 0 else remaining_bars.iloc[:1]
    if is_short:
        max_favorable = (entry_price - bars_to_exit["low"].min()) / entry_price * 100
        max_adverse = (bars_to_exit["high"].max() - entry_price) / entry_price * 100
    else:
        max_favorable = (bars_to_exit["high"].max() - entry_price) / entry_price * 100
        max_adverse = (entry_price - bars_to_exit["low"].min()) / entry_price * 100

    return {
        "exit_price": exit_price, "exit_reason": exit_reason,
        "pnl_pct": pnl_pct, "pnl_dollar": pnl_dollar,
        "bars_held": idx + 1, "minutes_held": minutes_elapsed,
        "max_favorable": max_favorable, "max_adverse": max_adverse,
    }


def run_stock_backtest(signals_df, intraday_data_dict, direction="above",
                        stop_losses=None, targets=None, time_exits=None,
                        trailing_stops=None):
    """
    Run full grid search over stock exit parameters for a given direction.
    """
    if stop_losses is None:
        stop_losses = config.STOCK_STOP_LOSSES
    if targets is None:
        targets = config.STOCK_TARGETS
    if time_exits is None:
        time_exits = config.STOCK_TIME_EXITS
    if trailing_stops is None:
        trailing_stops = [None] + config.STOCK_TRAILING_STOPS

    dir_label = "SHORT (fade)" if direction == "above" else "LONG (buy dip)"
    print(f"\nRunning stock backtest [{dir_label}] across {len(signals_df)} signals...")

    # Pre-compute remaining bars
    signal_bars = {}
    for _, signal in signals_df.iterrows():
        date_str = str(signal["date"])
        if date_str not in intraday_data_dict:
            continue
        intraday = intraday_data_dict[date_str]
        entry_time = signal["entry_time"]
        remaining = intraday[intraday["timestamp"] > entry_time].copy()
        signal_bars[date_str] = (signal, remaining)

    combos = list(product(stop_losses, targets, time_exits, trailing_stops))
    print(f"  Grid: {len(combos)} combinations")

    results = []
    for combo_idx, (stop, target, time_exit, trail) in enumerate(combos):
        if (combo_idx + 1) % 200 == 0:
            print(f"  Combo {combo_idx+1}/{len(combos)}...")

        trades = []
        for date_str, (signal, remaining_bars) in signal_bars.items():
            trade = simulate_stock_trade(
                remaining_bars, signal["entry_price"],
                stop, target, trail, time_exit, direction
            )
            trade["date"] = signal["date"]
            trade["entry_price"] = signal["entry_price"]
            trade["entry_time"] = signal["entry_time"]
            trade["vix_regime"] = signal.get("vix_regime", "unknown")
            trade["consecutive_up"] = signal.get("consecutive_up", 0)
            trade["consecutive_down"] = signal.get("consecutive_down", 0)
            trade["time_bucket"] = signal.get("time_bucket", "unknown")
            trade["dist_above_vwap_atr"] = signal.get("dist_above_vwap_atr", np.nan)
            trade["gap_pct"] = signal.get("gap_pct", 0)
            trade["bonds_up"] = signal.get("bonds_up", np.nan)
            trade["spy_5d_return"] = signal.get("spy_5d_return", np.nan)
            trade["direction"] = direction
            trades.append(trade)

        if not trades:
            continue

        trades_df = pd.DataFrame(trades)
        metrics = _compute_metrics(trades_df)
        metrics["stop_loss"] = stop
        metrics["target"] = target
        metrics["time_exit"] = time_exit
        metrics["trailing_stop"] = trail
        metrics["direction"] = direction
        results.append(metrics)

    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values("expectancy", ascending=False)
        print(f"  Best expectancy: {results_df['expectancy'].iloc[0]:.4f}%")
    else:
        print(f"  No trades executed")
    return results_df, signal_bars


def run_scalein_backtest(scalein_signals, intraday_data_dict, direction="above",
                          stop_losses=None, targets=None, time_exits=None):
    """
    Run backtest for scale-in trades.
    Uses a reduced grid (no trailing for simplicity).
    """
    if stop_losses is None:
        stop_losses = config.STOCK_STOP_LOSSES
    if targets is None:
        targets = config.STOCK_TARGETS
    if time_exits is None:
        time_exits = [30, 60, "EOD"]

    dir_label = "SHORT scale-in" if direction == "above" else "LONG scale-in"
    print(f"\nRunning {dir_label} backtest...")

    results = []
    for (dir_key, entry_mult, add_mult), pair_list in scalein_signals.items():
        if dir_key != direction or not pair_list:
            continue

        for stop, target, time_exit in product(stop_losses, targets, time_exits):
            trades = []
            for entry1_df, entry2_df in pair_list:
                if entry1_df.empty:
                    continue

                date_str = str(entry1_df["date"].iloc[0])
                if date_str not in intraday_data_dict:
                    continue
                intraday = intraday_data_dict[date_str]

                entry1_time = entry1_df["entry_time"].iloc[0]
                entry1_price = entry1_df["entry_price"].iloc[0]
                remaining1 = intraday[intraday["timestamp"] > entry1_time].copy()

                if not entry2_df.empty:
                    entry2_time = entry2_df["entry_time"].iloc[0]
                    entry2_price = entry2_df["entry_price"].iloc[0]
                    remaining2 = intraday[intraday["timestamp"] > entry2_time].copy()
                else:
                    remaining2 = None
                    entry2_price = None

                trade = simulate_scalein_trade(
                    remaining1, entry1_price,
                    remaining2, entry2_price,
                    stop, target, None, time_exit, direction
                )
                trade["date"] = entry1_df["date"].iloc[0]
                trade["entry_mult"] = entry_mult
                trade["add_mult"] = add_mult
                trades.append(trade)

            if not trades:
                continue

            trades_df = pd.DataFrame(trades)
            metrics = _compute_metrics(trades_df)
            metrics["entry_mult"] = entry_mult
            metrics["add_mult"] = add_mult
            metrics["stop_loss"] = stop
            metrics["target"] = target
            metrics["time_exit"] = time_exit
            metrics["direction"] = direction
            metrics["pct_scaled_in"] = trades_df["scale_in"].mean() * 100
            results.append(metrics)

    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values("expectancy", ascending=False)
        print(f"  Scale-in combos tested: {len(results_df)}")
        best = results_df.iloc[0]
        print(f"  Best: {best['entry_mult']}x→{best['add_mult']}x, "
              f"exp={best['expectancy']:.4f}%, {best['pct_scaled_in']:.0f}% got 2nd entry")
    return results_df


def _compute_metrics(trades_df):
    n = len(trades_df)
    if n == 0:
        return {
            "n_trades": 0, "win_rate": 0, "avg_pnl": 0, "median_pnl": 0,
            "total_pnl": 0, "expectancy": 0, "profit_factor": 0,
            "max_drawdown_pct": 0, "avg_winner": 0, "avg_loser": 0,
            "best_trade": 0, "worst_trade": 0, "avg_minutes_held": 0,
            "avg_max_favorable": 0, "avg_max_adverse": 0,
        }

    winners = trades_df[trades_df["pnl_pct"] > 0]
    losers = trades_df[trades_df["pnl_pct"] < 0]
    total_wins = winners["pnl_pct"].sum() if len(winners) > 0 else 0
    total_losses = abs(losers["pnl_pct"].sum()) if len(losers) > 0 else 0

    cum_pnl = trades_df["pnl_pct"].cumsum()
    max_dd = (cum_pnl - cum_pnl.cummax()).min()

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
        "avg_max_favorable": trades_df["max_favorable"].mean(),
        "avg_max_adverse": trades_df["max_adverse"].mean(),
        "exit_reasons": trades_df["exit_reason"].value_counts().to_dict(),
    }


def get_best_stock_params(results_df, min_trades=30):
    filtered = results_df[results_df["n_trades"] >= min_trades].copy()
    if filtered.empty:
        return results_df.iloc[0] if not results_df.empty else None
    filtered["score"] = (
        filtered["expectancy"]
        * np.sqrt(filtered["n_trades"])
        / (1 + filtered["max_drawdown_pct"].abs())
    )
    return filtered.sort_values("score", ascending=False).iloc[0]

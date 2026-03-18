#!/usr/bin/env python3
"""
Generate trades_data.json for the dashboard.
Reconstructs individual OPTIONS trades using the optimized parameters:

  ABOVE VWAP: Buy 0.15 delta put, target 100%, stop 25%, hold to EOD
  BELOW VWAP: Buy 0.25 delta call, target 100%, stop 75%, cut at 15 min

Uses cached options data from prior run_options.py pull.

Usage:
    python generate_dashboard_data.py
    python generate_dashboard_data.py --above-mult 0.5 --below-mult 0.7
"""

import sys
import os
import json
import argparse
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_options_for_signal_day, OptionsDayData
from backtest_options import simulate_long_option_trade


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", type=str, default="both", choices=["above","below","both"])
    # ATR levels to generate trades for
    parser.add_argument("--above-mults", type=str, default="0.5,0.6,0.7",
                        help="Comma-separated ATR mults for above VWAP")
    parser.add_argument("--below-mults", type=str, default="0.5,0.6,0.7",
                        help="Comma-separated ATR mults for below VWAP")
    # Optimized parameters
    parser.add_argument("--above-delta", type=float, default=0.15,
                        help="Put delta for above VWAP trades")
    parser.add_argument("--above-target", type=float, default=1.0,
                        help="Profit target as multiple of premium (1.0 = 100%)")
    parser.add_argument("--above-stop", type=float, default=0.25,
                        help="Stop loss as multiple of premium (0.25 = 25%)")
    parser.add_argument("--above-time", type=str, default="EOD")
    parser.add_argument("--below-delta", type=float, default=0.25,
                        help="Call delta for below VWAP trades")
    parser.add_argument("--below-target", type=float, default=1.0,
                        help="Profit target as multiple of premium")
    parser.add_argument("--below-stop", type=float, default=0.75,
                        help="Stop loss as multiple of premium")
    parser.add_argument("--below-time", type=str, default="15")
    return parser.parse_args()


def time_exit_val(s):
    if s == "EOD" or s == "None" or s is None:
        return "EOD"
    try:
        return int(s)
    except:
        return "EOD"


def timestamp_to_iso(ts):
    """Convert pandas Timestamp to ISO string for JSON."""
    if ts is None:
        return None
    if hasattr(ts, 'isoformat'):
        return ts.isoformat()
    return str(ts)


def timestamp_to_timestr(ts):
    if ts is None:
        return None
    if hasattr(ts, 'strftime'):
        return ts.strftime('%H:%M')
    return str(ts)


def main():
    args = parse_args()
    directions = ["above", "below"] if args.direction == "both" else [args.direction]
    atr_mults = config.ATR_MULTIPLIER_RANGE

    above_mults = [float(x.strip()) for x in args.above_mults.split(",")]
    below_mults = [float(x.strip()) for x in args.below_mults.split(",")]

    print("=" * 60)
    print("  GENERATING DASHBOARD TRADE DATA")
    print("=" * 60)
    print(f"\n  ABOVE VWAP: Buy {args.above_delta:.2f}d put, "
          f"tgt {args.above_target}x, stop {args.above_stop}x, time {args.above_time}")
    print(f"  BELOW VWAP: Buy {args.below_delta:.2f}d call, "
          f"tgt {args.below_target}x, stop {args.below_stop}x, time {args.below_time}")
    print()

    # Load base data
    print("Loading base data...")
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars(config.TICKER, config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars(config.TLT_TICKER, config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk(config.TICKER, valid_dates)

    # Generate signals
    print("Generating signals...")
    signals_by_key = generate_all_signals(enriched, intraday_data, atr_mults, directions)

    # Collect unique signal days
    selected_signals = {}
    for direction in directions:
        mults = above_mults if direction == "above" else below_mults
        for mult in mults:
            sig_df = signals_by_key.get((direction, mult), pd.DataFrame())
            if not sig_df.empty:
                selected_signals[(direction, mult)] = sig_df
                print(f"  {direction.upper()} {mult}x: {len(sig_df)} signals")

    # Deduplicate signal days for options pull
    unique_days = {}
    for (direction, mult), sig_df in selected_signals.items():
        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in unique_days:
                unique_days[date_str] = {
                    "spot": signal["entry_price"],
                    "entry_time": signal["entry_time"],
                }

    print(f"\n  Pulling options for {len(unique_days)} unique signal days (using cache)...")

    all_options_data = {}
    for i, (date_str, info) in enumerate(sorted(unique_days.items())):
        if (i + 1) % 20 == 0:
            print(f"    [{i+1}/{len(unique_days)}]...")
        try:
            day_data = pull_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options_data[date_str] = day_data
        except Exception as e:
            print(f"    ERROR {date_str}: {e}")
            all_options_data[date_str] = OptionsDayData(date_str, info["spot"], info["entry_time"])

    # Generate trades
    print("\nSimulating trades...")
    all_trades = []

    for (direction, mult), sig_df in selected_signals.items():
        if direction == "above":
            delta = args.above_delta
            target = args.above_target
            stop = args.above_stop
            time_exit = time_exit_val(args.above_time)
            option_side = "puts"
            product_label = f"long_put_{delta:.0%}d"
        else:
            delta = args.below_delta
            target = args.below_target
            stop = args.below_stop
            time_exit = time_exit_val(args.below_time)
            option_side = "calls"
            product_label = f"long_call_{delta:.0%}d"

        trade_count = 0
        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in all_options_data:
                continue

            day_data = all_options_data[date_str]
            opt_dict = getattr(day_data, option_side)

            if delta not in opt_dict:
                continue

            opt_info = opt_dict[delta]
            all_bars = opt_info.get("all_bars", opt_info["bars"])

            # CRITICAL: re-slice bars to start from THIS signal's entry time,
            # not the earliest entry time for this date (which may differ by ATR level)
            sig_entry_time = signal["entry_time"]
            bars = all_bars[all_bars["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)

            if bars.empty:
                continue

            entry_price = bars.iloc[0]["open"]

            # Fill-realism filter: skip penny options (SPY 0DTE liquid at $0.05+)
            if entry_price < 0.05:
                continue

            # Simulate trade
            result = simulate_long_option_trade(
                bars, entry_price, target, stop, time_exit
            )

            # Get exit time from bars (bars_held is 1-based count)
            bars_held = result.get("bars_held", 0)
            exit_idx = min(bars_held - 1, len(bars) - 1) if bars_held > 0 else 0
            exit_idx = max(0, exit_idx)
            exit_bar = bars.iloc[exit_idx]
            exit_time = timestamp_to_iso(exit_bar["timestamp"])
            entry_time_iso = timestamp_to_iso(bars.iloc[0]["timestamp"])

            # Get the option ticker for chart loading
            option_ticker = opt_info.get("ticker", None)

            trade_entry = {
                "date": date_str,
                "direction": direction,
                "product": "long_put" if direction == "above" else "long_call",
                "atr_mult": float(mult),
                "delta": float(delta),
                "strike": float(opt_info["strike"]),
                "option_ticker": option_ticker,
                # SPY prices
                "spy_entry_price": float(signal["entry_price"]),
                "entry_time": timestamp_to_timestr(signal["entry_time"]),
                "entry_time_iso": timestamp_to_iso(signal["entry_time"]),
                # Option prices
                "option_entry_price": float(entry_price),
                "option_exit_price": float(result.get("exit_premium", entry_price)),
                "exit_time": timestamp_to_timestr(exit_bar["timestamp"]) if exit_bar is not None else None,
                "exit_time_iso": exit_time,
                # P&L
                "pnl_pct": float(result.get("pnl_pct", 0)),
                "pnl_dollar": float(result.get("pnl_dollar", 0)),
                "exit_reason": result.get("exit_reason", "unknown"),
                "minutes_held": float(result.get("minutes_held", 0)),
                "max_favorable_pct": float(result.get("max_favorable_pct", 0)),
                "max_adverse_pct": float(result.get("max_adverse_pct", 0)),
                # Exit params used
                "target_pct": float(target),
                "stop_pct": float(stop),
                "time_exit": str(time_exit),
                # Regime info
                "vix": signal.get("vix_regime", None),
                "consecutive_up": int(signal.get("consecutive_up", 0)) if pd.notna(signal.get("consecutive_up", 0)) else 0,
                "gap_pct": float(signal.get("gap_pct", 0)) if pd.notna(signal.get("gap_pct", 0)) else None,
            }
            all_trades.append(trade_entry)
            trade_count += 1

        print(f"  {direction.upper()} {mult}x: {trade_count} trades generated")

    # Sort by date
    all_trades.sort(key=lambda t: t["date"])

    # Save
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades_data.json")
    with open(output_path, "w") as f:
        json.dump(all_trades, f, indent=2, default=str)

    print(f"\nSaved {len(all_trades)} trades to {output_path}")

    # Summary
    if all_trades:
        pnls = [t["pnl_pct"] for t in all_trades]
        wins = sum(1 for p in pnls if p > 0)
        print(f"\n  Total trades: {len(all_trades)}")
        print(f"  Win rate: {wins/len(all_trades)*100:.1f}%")
        print(f"  Avg P&L: {np.mean(pnls):+.2f}%")
        print(f"  Total P&L: {sum(pnls):+.2f}%")

        for d in ["above", "below"]:
            dt = [t for t in all_trades if t["direction"] == d]
            if dt:
                dp = [t["pnl_pct"] for t in dt]
                dw = sum(1 for p in dp if p > 0)
                print(f"  {d.upper():6s}: {len(dt)} trades, WR={dw/len(dt)*100:.1f}%, "
                      f"Avg={np.mean(dp):+.2f}%, Total={sum(dp):+.2f}%")


if __name__ == "__main__":
    main()

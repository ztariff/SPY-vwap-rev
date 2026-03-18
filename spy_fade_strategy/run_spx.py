#!/usr/bin/env python3
"""
SPX 0DTE VWAP Fade Backtest
============================
Same strategy as SPY but using SPX index options:
  - Signals still generated from SPY price vs SPY VWAP
  - Options traded are SPX 0DTE (10x notional, much better premiums)

Tests the same optimized parameters:
  ABOVE VWAP: Buy 0.15 delta SPX put, target 100%, stop 25%, hold to EOD
  BELOW VWAP: Buy 0.25 delta SPX call, target 100%, stop 75%, cut at 15 min

Usage:
    python run_spx.py
    python run_spx.py --min-premium 0.50
    python run_spx.py --above-delta 0.20 --below-delta 0.30
"""

import sys
import os
import json
import argparse
import time
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config_spx as config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import OptionsDayData
from options_data_spx import pull_spx_options_for_signal_day
from backtest_options import simulate_long_option_trade


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", default="both", choices=["above", "below", "both"])
    parser.add_argument("--above-mults", default="0.5,0.6,0.7",
                        help="Comma-separated ATR mults for above VWAP")
    parser.add_argument("--below-mults", default="0.5,0.6,0.7",
                        help="Comma-separated ATR mults for below VWAP")
    # Optimized parameters (same as SPY)
    parser.add_argument("--above-delta", type=float, default=0.15)
    parser.add_argument("--above-target", type=float, default=1.0)
    parser.add_argument("--above-stop", type=float, default=0.25)
    parser.add_argument("--above-time", default="EOD")
    parser.add_argument("--below-delta", type=float, default=0.25)
    parser.add_argument("--below-target", type=float, default=1.0)
    parser.add_argument("--below-stop", type=float, default=0.75)
    parser.add_argument("--below-time", default="15")
    # Fill realism
    parser.add_argument("--min-premium", type=float, default=0.50,
                        help="Min option premium for fill realism (SPX: $0.50 recommended)")
    return parser.parse_args()


def time_exit_val(s):
    if s in ("EOD", "None") or s is None:
        return "EOD"
    try:
        return int(s)
    except ValueError:
        return "EOD"


def ts_to_iso(ts):
    if ts is None:
        return None
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def ts_to_timestr(ts):
    if ts is None:
        return None
    return ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)


def main():
    args = parse_args()
    start_time = time.time()
    directions = ["above", "below"] if args.direction == "both" else [args.direction]

    above_mults = [float(x.strip()) for x in args.above_mults.split(",")]
    below_mults = [float(x.strip()) for x in args.below_mults.split(",")]

    print("=" * 60)
    print("  SPX 0DTE VWAP FADE BACKTEST")
    print("=" * 60)
    print(f"\n  ABOVE VWAP: Buy {args.above_delta:.2f}d SPX put, "
          f"tgt {args.above_target}x, stop {args.above_stop}x, time {args.above_time}")
    print(f"  BELOW VWAP: Buy {args.below_delta:.2f}d SPX call, "
          f"tgt {args.below_target}x, stop {args.below_stop}x, time {args.below_time}")
    print(f"  Min premium: ${args.min_premium:.2f}")
    print()

    # ── Load SPY base data (signals are still based on SPY VWAP) ──
    print("Loading SPY base data (for signal generation)...")
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars(config.TLT_TICKER, config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    # ── Generate signals (still based on SPY) ──
    print("Generating signals from SPY VWAP...")
    signals_by_key = generate_all_signals(
        enriched, intraday_data, config.ATR_MULTIPLIER_RANGE, directions
    )

    # ── Collect selected signals ──
    selected_signals = {}
    for direction in directions:
        mults = above_mults if direction == "above" else below_mults
        for mult in mults:
            sig_df = signals_by_key.get((direction, mult), pd.DataFrame())
            if not sig_df.empty:
                selected_signals[(direction, mult)] = sig_df
                print(f"  {direction.upper()} {mult}x: {len(sig_df)} signals")

    # ── Deduplicate signal days for SPX options pull ──
    unique_days = {}
    for (direction, mult), sig_df in selected_signals.items():
        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in unique_days:
                unique_days[date_str] = {
                    "spot": signal["entry_price"],
                    "entry_time": signal["entry_time"],
                }

    print(f"\n  Pulling SPX options for {len(unique_days)} unique signal days...")
    print("  (This will take a while on first run — data is cached for reruns)")

    all_options_data = {}
    for i, (date_str, info) in enumerate(sorted(unique_days.items())):
        if (i + 1) % 20 == 0:
            print(f"    [{i + 1}/{len(unique_days)}]...")
        try:
            day_data = pull_spx_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options_data[date_str] = day_data
        except Exception as e:
            print(f"    ERROR {date_str}: {e}")
            spx_spot = info["spot"] * 10
            all_options_data[date_str] = OptionsDayData(date_str, spx_spot, info["entry_time"])

    # ── Simulate trades ──
    print("\nSimulating SPX trades...")
    all_trades = []

    for (direction, mult), sig_df in selected_signals.items():
        if direction == "above":
            delta = args.above_delta
            target = args.above_target
            stop = args.above_stop
            time_exit = time_exit_val(args.above_time)
            option_side = "puts"
        else:
            delta = args.below_delta
            target = args.below_target
            stop = args.below_stop
            time_exit = time_exit_val(args.below_time)
            option_side = "calls"

        trade_count = 0
        skip_premium = 0
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

            # Re-slice bars to THIS signal's entry time
            sig_entry_time = signal["entry_time"]
            bars = all_bars[all_bars["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)

            if bars.empty:
                continue

            entry_price = bars.iloc[0]["open"]

            # Fill-realism filter (SPX options are 10x SPY, so $0.50 ≈ $0.05 SPY)
            if entry_price < args.min_premium:
                skip_premium += 1
                continue

            result = simulate_long_option_trade(
                bars, entry_price, target, stop, time_exit
            )

            bars_held = result.get("bars_held", 0)
            exit_idx = max(0, min(bars_held - 1, len(bars) - 1)) if bars_held > 0 else 0
            exit_bar = bars.iloc[exit_idx]

            trade_entry = {
                "date": date_str,
                "direction": direction,
                "product": "long_spx_put" if direction == "above" else "long_spx_call",
                "atr_mult": float(mult),
                "delta": float(delta),
                "strike": float(opt_info["strike"]),
                "option_ticker": opt_info.get("ticker"),
                # SPY prices (for reference)
                "spy_entry_price": float(signal["entry_price"]),
                "entry_time": ts_to_timestr(signal["entry_time"]),
                "entry_time_iso": ts_to_iso(signal["entry_time"]),
                # SPX option prices
                "option_entry_price": float(entry_price),
                "option_exit_price": float(result.get("exit_premium", entry_price)),
                "exit_time": ts_to_timestr(exit_bar["timestamp"]),
                "exit_time_iso": ts_to_iso(exit_bar["timestamp"]),
                # P&L
                "pnl_pct": float(result.get("pnl_pct", 0)),
                "pnl_dollar": float(result.get("pnl_dollar", 0)),
                "exit_reason": result.get("exit_reason", "unknown"),
                "minutes_held": float(result.get("minutes_held", 0)),
                "max_favorable_pct": float(result.get("max_favorable_pct", 0)),
                "max_adverse_pct": float(result.get("max_adverse_pct", 0)),
                # Params
                "target_pct": float(target),
                "stop_pct": float(stop),
                "time_exit": str(time_exit),
                # Regime
                "vix": signal.get("vix_regime", None),
                "consecutive_up": int(signal.get("consecutive_up", 0))
                    if pd.notna(signal.get("consecutive_up", 0)) else 0,
                "gap_pct": float(signal.get("gap_pct", 0))
                    if pd.notna(signal.get("gap_pct", 0)) else None,
            }
            all_trades.append(trade_entry)
            trade_count += 1

        print(f"  {direction.upper()} {mult}x: {trade_count} trades "
              f"({skip_premium} skipped < ${args.min_premium:.2f} premium)")

    all_trades.sort(key=lambda t: t["date"])

    # ── Save ──
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades_data_spx.json")
    with open(output_path, "w") as f:
        json.dump(all_trades, f, indent=2, default=str)

    elapsed = time.time() - start_time
    print(f"\nSaved {len(all_trades)} SPX trades to {output_path}")
    print(f"Elapsed: {elapsed / 60:.1f} minutes")

    # ── Summary ──
    if all_trades:
        pnls = [t["pnl_pct"] for t in all_trades]
        wins = sum(1 for p in pnls if p > 0)
        print(f"\n{'=' * 60}")
        print(f"  SPX RESULTS SUMMARY")
        print(f"{'=' * 60}")
        print(f"  Total trades: {len(all_trades)}")
        print(f"  Win rate: {wins / len(all_trades) * 100:.1f}%")
        print(f"  Avg P&L: {np.mean(pnls):+.2f}%")
        print(f"  Total P&L: {sum(pnls):+.2f}%")

        # Sharpe
        pnl_std = np.std(pnls)
        sharpe = np.mean(pnls) / pnl_std if pnl_std > 0 else 0
        print(f"  Sharpe: {sharpe:.3f}")

        # Dollar P&L (per-contract, multiply by 100 for actual)
        dollar_pnls = [t["pnl_dollar"] for t in all_trades]
        print(f"  Avg $ P&L per contract: ${np.mean(dollar_pnls):+.2f} "
              f"(x100 = ${np.mean(dollar_pnls) * 100:+.0f})")

        for d in ["above", "below"]:
            dt = [t for t in all_trades if t["direction"] == d]
            if dt:
                dp = [t["pnl_pct"] for t in dt]
                dd = [t["pnl_dollar"] for t in dt]
                dw = sum(1 for p in dp if p > 0)
                d_sharpe = np.mean(dp) / np.std(dp) if np.std(dp) > 0 else 0
                print(f"  {d.upper():6s}: {len(dt)} trades, WR={dw / len(dt) * 100:.1f}%, "
                      f"Avg={np.mean(dp):+.2f}%, Sharpe={d_sharpe:.3f}, "
                      f"Avg$={np.mean(dd):+.2f}")

        # Premium distribution
        prems = [t["option_entry_price"] for t in all_trades]
        print(f"\n  Premium distribution:")
        print(f"    Median: ${np.median(prems):.2f}")
        print(f"    p25-p75: ${np.percentile(prems, 25):.2f} - ${np.percentile(prems, 75):.2f}")
        print(f"    Min: ${min(prems):.2f}, Max: ${max(prems):.2f}")

    # ── Compare hint ──
    spy_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades_data.json")
    if os.path.exists(spy_path):
        with open(spy_path) as f:
            spy_trades = json.load(f)
        if spy_trades:
            spy_pnls = [t["pnl_pct"] for t in spy_trades]
            print(f"\n  --- SPY comparison (from trades_data.json) ---")
            print(f"  SPY trades: {len(spy_trades)}, Avg P&L: {np.mean(spy_pnls):+.2f}%")
            if all_trades:
                print(f"  SPX trades: {len(all_trades)}, Avg P&L: {np.mean(pnls):+.2f}%")
                print(f"  {'SPX WINS' if np.mean(pnls) > np.mean(spy_pnls) else 'SPY WINS'} "
                      f"on avg P&L")


if __name__ == "__main__":
    main()

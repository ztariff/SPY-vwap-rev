#!/usr/bin/env python3
"""
CREDIT SPREAD BACKTEST RUNNER
===============================
Tests defined-risk credit spreads across multiple ATR levels:
  ABOVE VWAP: Bear Call Spreads (short higher-delta call + long lower-delta call)
  BELOW VWAP: Bull Put Spreads  (short higher-delta put + long lower-delta put)

Uses CACHED options data from the prior run_options.py pull — no new API calls needed.

Usage:
    python run_spreads.py                      # Both directions, default ATR levels
    python run_spreads.py --direction above     # Just bear call spreads
    python run_spreads.py --direction below     # Just bull put spreads
    python run_spreads.py --atr-mults "0.5,0.7,0.9,1.0"  # Custom ATR levels
    python run_spreads.py --verbose
"""

import sys
import os
import argparse
import time
import pandas as pd
import numpy as np
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_options_for_signal_day, OptionsDayData
from backtest_spreads import (
    run_bear_call_spreads_backtest, run_bull_put_spreads_backtest,
    get_best_spread_params, SPREAD_PAIRS,
    SPREAD_PROFIT_TARGETS, SPREAD_STOP_LOSSES, SPREAD_TIME_EXITS,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Credit Spread Backtest Runner")
    parser.add_argument("--direction", type=str, default="both",
                        choices=["above", "below", "both"])
    parser.add_argument("--atr-mults", type=str, default=None,
                        help="Comma-separated ATR mults (e.g. '0.5,0.7,0.9,1.0')")
    parser.add_argument("--start", type=str, default=config.BACKTEST_START)
    parser.add_argument("--end", type=str, default=config.BACKTEST_END)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--max-days", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    start_time = time.time()

    directions = ["above", "below"] if args.direction == "both" else [args.direction]
    atr_mults = config.ATR_MULTIPLIER_RANGE

    # Default ATR levels to test (same as run_options.py)
    DEFAULT_ABOVE_MULTS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    DEFAULT_BELOW_MULTS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    print("=" * 70)
    print("  CREDIT SPREAD BACKTEST RUNNER")
    print("  Bear Call Spreads (above VWAP) + Bull Put Spreads (below VWAP)")
    print("  All P&L from REAL Polygon prices — defined risk only")
    print("=" * 70)
    print(f"\n  Period: {args.start} → {args.end}")
    print(f"  Directions: {', '.join(directions)}")
    print(f"  Spread pairs: {len(SPREAD_PAIRS)} delta combos")
    print(f"  Exit grid: {len(SPREAD_PROFIT_TARGETS)} targets × "
          f"{len(SPREAD_STOP_LOSSES)} stops × {len(SPREAD_TIME_EXITS)} time exits "
          f"= {len(SPREAD_PROFIT_TARGETS) * len(SPREAD_STOP_LOSSES) * len(SPREAD_TIME_EXITS)} combos/pair")
    print(f"  Total combos per ATR level: "
          f"{len(SPREAD_PAIRS) * len(SPREAD_PROFIT_TARGETS) * len(SPREAD_STOP_LOSSES) * len(SPREAD_TIME_EXITS)}")
    print()

    # ─── Step 1: Fetch base data ───────────────────────────────────────
    print("STEP 1: Fetching base data (using cache)...")
    print("-" * 50)

    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars(config.TICKER, args.start, args.end)
    tlt_daily = fetcher.get_daily_bars(config.TLT_TICKER, args.start, args.end)
    vix_daily = fetcher.get_vix_daily(args.start, args.end)

    if spy_daily.empty:
        print("FATAL: No SPY daily data.")
        sys.exit(1)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk(config.TICKER, valid_dates)

    # ─── Step 2: Generate signals ────────────────────────────────────
    print(f"\nSTEP 2: Generating signals...")
    print("-" * 50)

    signals_by_key = generate_all_signals(enriched, intraday_data, atr_mults, directions)

    selected_signals = {}

    for direction in directions:
        if args.atr_mults:
            mults_to_test = [float(x.strip()) for x in args.atr_mults.split(",")]
        else:
            mults_to_test = DEFAULT_ABOVE_MULTS if direction == "above" else DEFAULT_BELOW_MULTS

        print(f"\n  {direction.upper()}: Testing ATR levels {mults_to_test}")

        for mult in mults_to_test:
            sig_df = signals_by_key.get((direction, mult), pd.DataFrame())
            if sig_df.empty:
                print(f"    {mult}x: No signals, skipping")
                continue
            if args.max_days and len(sig_df) > args.max_days:
                sig_df = sig_df.head(args.max_days)
            print(f"    {mult}x: {len(sig_df)} signal days")
            selected_signals[(direction, mult)] = sig_df

    if not selected_signals:
        print("\nNo signals found. Exiting.")
        sys.exit(1)

    # ─── Step 3: Pull options data (cached from prior run) ───────────
    print(f"\nSTEP 3: Pulling 0DTE options data (using cache from prior run)...")
    print("-" * 50)

    # Deduplicate signal days
    unique_signal_days = {}
    for (direction, mult), sig_df in selected_signals.items():
        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in unique_signal_days:
                unique_signal_days[date_str] = {
                    "spot": signal["entry_price"],
                    "entry_time": signal["entry_time"],
                }

    print(f"  Unique signal days: {len(unique_signal_days)}")

    all_options_data = {}
    cached_count = 0
    api_count = 0

    sorted_days = sorted(unique_signal_days.keys())
    for i, date_str in enumerate(sorted_days):
        info = unique_signal_days[date_str]

        if args.verbose and (i + 1) % 10 == 0:
            print(f"    [{i+1}/{len(sorted_days)}] {date_str}")

        try:
            day_data = pull_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options_data[date_str] = day_data
        except Exception as e:
            print(f"    ERROR on {date_str}: {e}")
            all_options_data[date_str] = OptionsDayData(date_str, info["spot"], info["entry_time"])

    # Diagnostics
    days_with_both = sum(1 for d in all_options_data.values()
                         if len(d.puts) > 0 and len(d.calls) > 0)
    days_with_calls = sum(1 for d in all_options_data.values() if len(d.calls) > 0)
    days_with_puts = sum(1 for d in all_options_data.values() if len(d.puts) > 0)
    print(f"  Days with call data: {days_with_calls}")
    print(f"  Days with put data: {days_with_puts}")
    print(f"  Days with both: {days_with_both}")

    # Check which spread pairs are actually possible (both deltas available)
    print(f"\n  Spread pair availability check:")
    for short_d, long_d in SPREAD_PAIRS:
        call_days = sum(1 for d in all_options_data.values()
                        if short_d in d.calls and long_d in d.calls)
        put_days = sum(1 for d in all_options_data.values()
                       if short_d in d.puts and long_d in d.puts)
        if call_days > 0 or put_days > 0:
            print(f"    {short_d:.2f}/{long_d:.2f}: {call_days} call-spread days, "
                  f"{put_days} put-spread days")

    # ─── Step 4: Run spread backtests ─────────────────────────────────
    print(f"\nSTEP 4: Running credit spread backtests...")
    print("-" * 50)

    all_spread_results = {}

    for (direction, mult), sig_df in selected_signals.items():
        days_with_data = sum(1 for _, s in sig_df.iterrows()
                             if str(s["date"]) in all_options_data and
                             (len(all_options_data[str(s["date"])].puts) > 0 or
                              len(all_options_data[str(s["date"])].calls) > 0))

        if days_with_data == 0:
            print(f"\n  No options data for {direction.upper()} {mult}x, skipping")
            continue

        label = f"{direction.upper()} {mult}x"

        if direction == "above":
            print(f"\n  ── {label}: BEAR CALL SPREADS ({days_with_data} days with data) ──")
            spread_res, _ = run_bear_call_spreads_backtest(all_options_data, sig_df)
            if not spread_res.empty:
                spread_res["atr_mult"] = mult
            all_spread_results[("above", "bear_call_spread", mult)] = spread_res
        else:
            print(f"\n  ── {label}: BULL PUT SPREADS ({days_with_data} days with data) ──")
            spread_res, _ = run_bull_put_spreads_backtest(all_options_data, sig_df)
            if not spread_res.empty:
                spread_res["atr_mult"] = mult
            all_spread_results[("below", "bull_put_spread", mult)] = spread_res

    # ─── Step 5: Save results ─────────────────────────────────────────
    print(f"\nSTEP 5: Saving results...")
    print("-" * 50)

    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for key, results_df in all_spread_results.items():
        if results_df.empty:
            continue
        direction, spread_type, mult = key
        fname = f"spreads_{direction}_{spread_type}_{mult}x_{ts}.csv"
        path = os.path.join(config.RESULTS_DIR, fname)
        results_df.sort_values("sharpe", ascending=False).to_csv(path, index=False)
        print(f"  Saved: {path} ({len(results_df)} combos)")

    # Summary CSV
    summary_rows = []
    for key, results_df in all_spread_results.items():
        if results_df.empty:
            continue
        direction, spread_type, mult = key
        per_pair, overall = get_best_spread_params(results_df, min_trades=10)

        if overall is not None:
            row = overall.to_dict() if hasattr(overall, 'to_dict') else dict(overall)
            row["direction"] = direction
            row["spread_type"] = spread_type
            row["atr_mult"] = mult
            row["rank"] = "overall_best"
            summary_rows.append(row)

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_path = os.path.join(config.RESULTS_DIR, f"spreads_best_summary_{ts}.csv")
        summary_df.to_csv(summary_path, index=False)
        print(f"  Saved summary: {summary_path}")

    # ─── Print summary ─────────────────────────────────────────────
    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"  CREDIT SPREAD BACKTEST COMPLETE — {elapsed/60:.1f} minutes")
    print(f"{'='*70}")

    for key, results_df in sorted(all_spread_results.items(), key=lambda x: x[0]):
        if results_df.empty:
            continue
        direction, spread_type, mult = key
        per_pair, overall = get_best_spread_params(results_df, min_trades=10)

        label = f"{direction.upper()} {mult}x {spread_type.upper().replace('_', ' ')}"

        if overall is not None:
            print(f"\n  {label} — BEST OVERALL (scored by Sharpe):")
            print(f"    Spread: short {overall.get('short_delta', '?')}d / "
                  f"long {overall.get('long_delta', '?')}d")
            print(f"    Target: {overall.get('profit_target', '?')}x of credit | "
                  f"Stop: {overall.get('stop_loss', '?')}x of credit | "
                  f"Time: {overall.get('time_exit', '?')}")
            print(f"    Expectancy: {overall.get('expectancy', 0):+.2f}% of risk | "
                  f"Win Rate: {overall.get('win_rate', 0):.1f}% | "
                  f"N={overall.get('n_trades', 0)}")
            print(f"    Sharpe: {overall.get('sharpe', 0):.3f} | "
                  f"Sortino: {overall.get('sortino', 0):.3f}")
            print(f"    Avg credit: ${overall.get('avg_credit', 0):.2f} | "
                  f"Avg $ P&L: ${overall.get('avg_pnl_dollar', 0):.2f}")
            print(f"    Profit Factor: {overall.get('profit_factor', 0):.2f}")

        if per_pair is not None and not per_pair.empty:
            print(f"\n  {label} — BEST PER SPREAD PAIR:")
            for _, row in per_pair.iterrows():
                print(f"    {row.get('spread_pair', '?')}: "
                      f"exp={row.get('expectancy', 0):+.2f}%, "
                      f"sharpe={row.get('sharpe', 0):.3f}, "
                      f"WR={row.get('win_rate', 0):.1f}%, "
                      f"N={row.get('n_trades', 0)}, "
                      f"tgt={row.get('profit_target', '?')}x, "
                      f"stop={row.get('stop_loss', '?')}x, "
                      f"time={row.get('time_exit', '?')}, "
                      f"credit=${row.get('avg_credit', 0):.2f}")

    # Best overall across all directions
    best_key = None
    best_sharpe = -999
    for key, results_df in all_spread_results.items():
        if results_df.empty:
            continue
        _, overall = get_best_spread_params(results_df, min_trades=10)
        if overall is not None and overall.get("sharpe", -999) > best_sharpe:
            best_sharpe = overall.get("sharpe", -999)
            best_key = key

    if best_key:
        d, st, m = best_key
        print(f"\n  >>> BEST SPREAD STRATEGY: {d.upper()} {m}x "
              f"{st.upper().replace('_', ' ')} (Sharpe: {best_sharpe:.3f})")

    print(f"\n  Results saved to: {config.RESULTS_DIR}/")
    print()


if __name__ == "__main__":
    main()

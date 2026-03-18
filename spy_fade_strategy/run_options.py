#!/usr/bin/env python3
"""
OPTIONS-ONLY BACKTEST RUNNER
==============================
Focused script to pull 0DTE options data and run all four options products:
  ABOVE VWAP: Long puts + Short calls (fade)
  BELOW VWAP: Long calls + Short puts (buy dip)

Uses cached daily/intraday data from the main backtest, only makes new
API calls for options contracts and options intraday bars.

Usage:
    python run_options.py                  # Both directions
    python run_options.py --direction above  # Just the fade side
    python run_options.py --direction below  # Just the buy-dip side
    python run_options.py --atr-mult 0.7    # Specific ATR entry level
"""

import sys
import os
import argparse
import time
import pickle
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
from backtest_options import (
    run_long_puts_backtest, run_short_calls_backtest,
    run_long_calls_backtest, run_short_puts_backtest,
    get_best_options_params,
    simulate_long_option_trade, simulate_short_option_trade,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Options-Only Backtest Runner")
    parser.add_argument("--direction", type=str, default="both",
                        choices=["above", "below", "both"])
    parser.add_argument("--atr-mult", type=float, default=None,
                        help="Single ATR mult (default: test multiple levels)")
    parser.add_argument("--atr-mults", type=str, default=None,
                        help="Comma-separated ATR mults to test (e.g. '0.7,0.8,0.9,1.0')")
    parser.add_argument("--start", type=str, default=config.BACKTEST_START)
    parser.add_argument("--end", type=str, default=config.BACKTEST_END)
    parser.add_argument("--verbose", action="store_true",
                        help="Print detailed diagnostics for each signal day")
    parser.add_argument("--max-days", type=int, default=None,
                        help="Limit number of signal days to process PER ATR LEVEL (for testing)")
    return parser.parse_args()


def pick_primary_mult(signals_by_key, direction, atr_mults):
    """Pick ATR mult with good signal count, preferring near 0.7-1.0x."""
    # For above VWAP, prefer 0.7x (best from ATR scan)
    # For below VWAP, prefer 0.6x (best from ATR scan)
    if direction == "above":
        preferred = [0.7, 0.8, 0.9, 1.0, 0.6, 1.1]
    else:
        preferred = [0.6, 0.7, 0.5, 0.8, 0.9, 1.0]

    for m in preferred:
        if m in atr_mults:
            key = (direction, m)
            if key in signals_by_key and not signals_by_key[key].empty:
                if len(signals_by_key[key]) >= 10:
                    return m

    # Fallback: any with signals
    for m in atr_mults:
        key = (direction, m)
        if key in signals_by_key and not signals_by_key[key].empty:
            return m
    return None


def diagnose_options_data(options_data, direction):
    """Print detailed diagnostics about what we got."""
    total_days = len(options_data)
    days_with_puts = sum(1 for d in options_data.values() if len(d.puts) > 0)
    days_with_calls = sum(1 for d in options_data.values() if len(d.calls) > 0)
    days_with_both = sum(1 for d in options_data.values()
                         if len(d.puts) > 0 and len(d.calls) > 0)
    days_empty = sum(1 for d in options_data.values()
                     if len(d.puts) == 0 and len(d.calls) == 0)

    print(f"\n  OPTIONS DATA DIAGNOSTICS ({direction.upper()}):")
    print(f"    Total signal days:     {total_days}")
    print(f"    Days with put data:    {days_with_puts}")
    print(f"    Days with call data:   {days_with_calls}")
    print(f"    Days with both:        {days_with_both}")
    print(f"    Days with NO data:     {days_empty}")

    # Delta coverage
    put_delta_counts = Counter()
    call_delta_counts = Counter()
    for d in options_data.values():
        for delta in d.puts:
            put_delta_counts[delta] += 1
        for delta in d.calls:
            call_delta_counts[delta] += 1

    if put_delta_counts:
        print(f"\n    Put delta coverage (delta: N days with data):")
        for delta in sorted(put_delta_counts.keys()):
            print(f"      {delta:.2f}: {put_delta_counts[delta]}/{total_days}")

    if call_delta_counts:
        print(f"\n    Call delta coverage (delta: N days with data):")
        for delta in sorted(call_delta_counts.keys()):
            print(f"      {delta:.2f}: {call_delta_counts[delta]}/{total_days}")

    # Entry premium stats
    all_put_premiums = []
    all_call_premiums = []
    for d in options_data.values():
        for delta, info in d.puts.items():
            all_put_premiums.append((delta, info["entry_price"], info["strike"], d.spot))
        for delta, info in d.calls.items():
            all_call_premiums.append((delta, info["entry_price"], info["strike"], d.spot))

    if all_put_premiums:
        print(f"\n    Put entry premiums sample:")
        for delta, prem, strike, spot in all_put_premiums[:5]:
            print(f"      delta={delta:.2f}, strike={strike}, spot={spot:.2f}, "
                  f"premium=${prem:.2f}")

    if all_call_premiums:
        print(f"\n    Call entry premiums sample:")
        for delta, prem, strike, spot in all_call_premiums[:5]:
            print(f"      delta={delta:.2f}, strike={strike}, spot={spot:.2f}, "
                  f"premium=${prem:.2f}")


def run_individual_trades_diagnostic(options_data, signals_df, direction, verbose=False):
    """
    Run a quick diagnostic: simulate one trade per day per delta to see what happens.
    Uses middle-of-road params: 50% profit target, 50% stop, EOD exit.
    """
    print(f"\n  QUICK DIAGNOSTIC TRADES ({direction.upper()}):")
    is_above = (direction == "above")

    for option_side, side_name in [("puts", "PUT"), ("calls", "CALL")]:
        results_by_delta = {}

        for _, signal in signals_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in options_data:
                continue
            day_data = options_data[date_str]
            opt_dict = getattr(day_data, option_side)

            for delta, info in opt_dict.items():
                bars = info["bars"]
                entry_price = info["entry_price"]

                if bars.empty or entry_price <= 0:
                    continue

                # For above VWAP: long puts, short calls
                # For below VWAP: long calls, short puts
                if is_above:
                    if option_side == "puts":
                        trade = simulate_long_option_trade(bars, entry_price, 0.50, 0.50, "EOD")
                    else:
                        trade = simulate_short_option_trade(bars, entry_price, 0.50, 0.50, "EOD")
                else:
                    if option_side == "calls":
                        trade = simulate_long_option_trade(bars, entry_price, 0.50, 0.50, "EOD")
                    else:
                        trade = simulate_short_option_trade(bars, entry_price, 0.50, 0.50, "EOD")

                if delta not in results_by_delta:
                    results_by_delta[delta] = []
                results_by_delta[delta].append({
                    "date": date_str,
                    "pnl_pct": trade["pnl_pct"],
                    "exit_reason": trade["exit_reason"],
                    "entry_premium": entry_price,
                    "exit_premium": trade["exit_premium"],
                    "minutes_held": trade["minutes_held"],
                })

        if results_by_delta:
            product = "LONG" if (is_above and option_side == "puts") or \
                               (not is_above and option_side == "calls") else "SHORT"
            print(f"\n    {product} {side_name}s (50% tgt, 50% stop, EOD):")
            for delta in sorted(results_by_delta.keys()):
                trades = results_by_delta[delta]
                pnls = [t["pnl_pct"] for t in trades]
                wins = sum(1 for p in pnls if p > 0)
                exits = Counter(t["exit_reason"] for t in trades)
                avg_pnl = np.mean(pnls)
                print(f"      delta={delta:.2f}: N={len(trades)}, WR={wins/len(trades)*100:.0f}%, "
                      f"Avg={avg_pnl:+.1f}%, exits={dict(exits)}")

                if verbose:
                    for t in trades:
                        print(f"        {t['date']}: entry=${t['entry_premium']:.2f} → "
                              f"exit=${t['exit_premium']:.2f} ({t['pnl_pct']:+.1f}%, "
                              f"{t['exit_reason']}, {t['minutes_held']:.0f}min)")


def save_options_results(results_dict, output_dir):
    """Save options backtest results to CSV. Keys can be 2-tuple or 3-tuple."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for key, results_df in results_dict.items():
        if results_df.empty:
            continue
        # Key is (direction, product, atr_mult) or (direction, product)
        if len(key) == 3:
            direction, product, mult = key
            fname = f"options_{direction}_{product}_{mult}x_{ts}.csv"
        else:
            direction, product = key
            mult = None
            fname = f"options_{direction}_{product}_{ts}.csv"
        path = os.path.join(output_dir, fname)
        top = results_df.sort_values("expectancy", ascending=False)
        top.to_csv(path, index=False)
        print(f"  Saved: {path} ({len(top)} param combos)")

    # Also save a summary of the best params per product/delta/atr_mult
    summary_rows = []
    for key, results_df in results_dict.items():
        if results_df.empty:
            continue
        if len(key) == 3:
            direction, product, mult = key
        else:
            direction, product = key
            mult = None

        per_delta, overall = get_best_options_params(results_df, min_trades=3)

        if overall is not None:
            row = overall.to_dict() if hasattr(overall, 'to_dict') else dict(overall)
            row["direction"] = direction
            row["product"] = product
            row["atr_mult"] = mult
            row["rank"] = "overall_best"
            summary_rows.append(row)

        if not per_delta.empty:
            for _, r in per_delta.iterrows():
                row = r.to_dict()
                row["direction"] = direction
                row["product"] = product
                row["atr_mult"] = mult
                row["rank"] = f"best_at_delta_{row.get('delta', '?')}"
                summary_rows.append(row)

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_path = os.path.join(output_dir, f"options_best_summary_{ts}.csv")
        summary_df.to_csv(summary_path, index=False)
        print(f"  Saved summary: {summary_path}")


def main():
    args = parse_args()
    start_time = time.time()

    directions = ["above", "below"] if args.direction == "both" else [args.direction]
    atr_mults = config.ATR_MULTIPLIER_RANGE

    print("=" * 70)
    print("  OPTIONS-ONLY BACKTEST RUNNER")
    print("  Pulls 0DTE options data from Polygon & tests all products")
    print("=" * 70)
    print(f"\n  Period: {args.start} → {args.end}")
    print(f"  Directions: {', '.join(directions)}")
    print(f"  Put deltas: {config.PUT_DELTAS}")
    print(f"  Call deltas: {config.CALL_DELTAS}")
    print(f"  Options exit grid: {len(config.OPTIONS_PROFIT_TARGETS)} targets × "
          f"{len(config.OPTIONS_STOP_LOSSES)} stops × {len(config.OPTIONS_TIME_EXITS)} time exits")
    print()

    # ─── Step 1: Fetch base data ───────────────────────────────────────
    print("STEP 1: Fetching base data (using cache if available)...")
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

    # Determine which ATR mults to test per direction
    # Default: test 0.7, 0.8, 0.9, 1.0 for above; 0.5, 0.6, 0.7, 0.8 for below
    DEFAULT_ABOVE_MULTS = [0.7, 0.8, 0.9, 1.0]
    DEFAULT_BELOW_MULTS = [0.5, 0.6, 0.7, 0.8]

    selected_signals = {}  # key: (direction, mult) -> sig_df

    for direction in directions:
        if args.atr_mult:
            mults_to_test = [args.atr_mult]
        elif args.atr_mults:
            mults_to_test = [float(x.strip()) for x in args.atr_mults.split(",")]
        else:
            mults_to_test = DEFAULT_ABOVE_MULTS if direction == "above" else DEFAULT_BELOW_MULTS

        dir_label = direction.upper()
        print(f"\n  {dir_label}: Testing ATR levels {mults_to_test}")

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
        print("\nNo signals found for any direction/mult. Exiting.")
        sys.exit(1)

    # Deduplicate signal days for options data pull — many days appear across
    # multiple ATR levels, so we only need to pull options data ONCE per unique day
    unique_signal_days = {}  # date_str -> (spot, entry_time, direction)
    for (direction, mult), sig_df in selected_signals.items():
        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in unique_signal_days:
                unique_signal_days[date_str] = {
                    "spot": signal["entry_price"],
                    "entry_time": signal["entry_time"],
                    "direction": direction,
                }

    print(f"\n  Total unique signal days to pull options for: {len(unique_signal_days)}")

    # ─── Step 3: Pull options data (deduplicated across ATR levels) ──
    print(f"\nSTEP 3: Pulling 0DTE options data from Polygon...")
    print("-" * 50)
    print(f"  Unique signal days: {len(unique_signal_days)}")
    print("  Each day needs ~18 API calls (contracts + intraday bars)")
    total_calls_est = len(unique_signal_days) * 18
    print(f"  Estimated total API calls: ~{total_calls_est}")
    print(f"  Estimated time at {config.RATE_LIMIT_CALLS_PER_MIN}/min: "
          f"~{total_calls_est / config.RATE_LIMIT_CALLS_PER_MIN:.1f} min")
    print()

    # Single shared options data pool keyed by date
    all_options_data = {}

    sorted_days = sorted(unique_signal_days.keys())
    for i, date_str in enumerate(sorted_days):
        info = unique_signal_days[date_str]
        spot = info["spot"]
        entry_time = info["entry_time"]

        if (i + 1) % 5 == 0 or args.verbose:
            print(f"    [{i+1}/{len(sorted_days)}] {date_str} spot={spot:.2f}")

        try:
            day_data = pull_options_for_signal_day(fetcher, date_str, spot, entry_time)
            all_options_data[date_str] = day_data

            if args.verbose:
                n_p = len(day_data.puts)
                n_c = len(day_data.calls)
                print(f"      → {n_p} put deltas, {n_c} call deltas")
                if n_p == 0 and n_c == 0:
                    print(f"      ⚠ NO OPTIONS DATA for {date_str}")
        except Exception as e:
            print(f"    ERROR on {date_str}: {e}")
            all_options_data[date_str] = OptionsDayData(date_str, spot, entry_time)

    diagnose_options_data(all_options_data, "ALL")

    # ─── Step 4: Run diagnostic trades ─────────────────────────────
    print(f"\nSTEP 4: Running diagnostic trades...")
    print("-" * 50)

    for (direction, mult), sig_df in selected_signals.items():
        print(f"\n  ── {direction.upper()} {mult}x ATR ({len(sig_df)} signals) ──")
        run_individual_trades_diagnostic(
            all_options_data, sig_df, direction,
            verbose=args.verbose
        )

    # ─── Step 5: Full grid search across all ATR levels ──────────
    print(f"\nSTEP 5: Running full options grid search across ALL ATR levels...")
    print("-" * 50)

    all_options_results = {}

    for (direction, mult), sig_df in selected_signals.items():
        # Check how many signal days have options data
        days_with_data = sum(1 for _, s in sig_df.iterrows()
                             if str(s["date"]) in all_options_data and
                             (len(all_options_data[str(s["date"])].puts) > 0 or
                              len(all_options_data[str(s["date"])].calls) > 0))
        if days_with_data == 0:
            print(f"\n  ⚠ No options data for {direction.upper()} {mult}x, skipping")
            continue

        label = f"{direction.upper()} {mult}x"
        print(f"\n  ── {label} Grid Search ({days_with_data} days with data) ──")

        if direction == "above":
            # Fade: long puts + short calls
            print(f"\n    Running LONG PUTS backtest...")
            put_res, _ = run_long_puts_backtest(all_options_data, sig_df)
            if not put_res.empty:
                put_res["atr_mult"] = mult
            all_options_results[("above", "long_put", mult)] = put_res

            print(f"\n    Running SHORT CALLS backtest...")
            call_res, _ = run_short_calls_backtest(all_options_data, sig_df)
            if not call_res.empty:
                call_res["atr_mult"] = mult
            all_options_results[("above", "short_call", mult)] = call_res
        else:
            # Buy dip: long calls + short puts
            print(f"\n    Running LONG CALLS backtest...")
            call_res, _ = run_long_calls_backtest(all_options_data, sig_df)
            if not call_res.empty:
                call_res["atr_mult"] = mult
            all_options_results[("below", "long_call", mult)] = call_res

            print(f"\n    Running SHORT PUTS backtest...")
            put_res, _ = run_short_puts_backtest(all_options_data, sig_df)
            if not put_res.empty:
                put_res["atr_mult"] = mult
            all_options_results[("below", "short_put", mult)] = put_res

    # ─── Step 6: Save results ─────────────────────────────────────
    print(f"\nSTEP 6: Saving results...")
    print("-" * 50)

    save_options_results(all_options_results, config.RESULTS_DIR)

    # ─── Print summary ─────────────────────────────────────────────
    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"  OPTIONS BACKTEST COMPLETE — {elapsed/60:.1f} minutes")
    print(f"{'='*70}")

    for key, results_df in sorted(all_options_results.items(), key=lambda x: x[0]):
        if results_df.empty:
            continue
        if len(key) == 3:
            direction, product, mult = key
        else:
            direction, product = key
            mult = "?"
        per_delta, overall = get_best_options_params(results_df, min_trades=3)

        label = f"{direction.upper()} {mult}x {product.upper().replace('_', ' ')}"
        if overall is not None:
            print(f"\n  {label} — BEST OVERALL (scored by Sharpe):")
            print(f"    Delta: {overall.get('delta', '?')}")
            print(f"    Target: {overall.get('profit_target', '?')}x | "
                  f"Stop: {overall.get('stop_loss', '?')}x | "
                  f"Time: {overall.get('time_exit', '?')}")
            print(f"    Expectancy: {overall.get('expectancy', 0):+.2f}% | "
                  f"Win Rate: {overall.get('win_rate', 0):.1f}% | "
                  f"N={overall.get('n_trades', 0)}")
            print(f"    Sharpe: {overall.get('sharpe', 0):.3f} | "
                  f"Sortino: {overall.get('sortino', 0):.3f}")
            print(f"    Avg entry premium: ${overall.get('avg_entry_premium', 0):.2f} | "
                  f"Avg $ P&L: ${overall.get('avg_dollar_pnl', 0):.2f}")
            print(f"    Profit Factor: {overall.get('profit_factor', 0):.2f}")

        if not per_delta.empty:
            print(f"\n  {label} — BEST PER DELTA:")
            for _, row in per_delta.iterrows():
                print(f"    delta={row.get('delta', '?'):.2f}: "
                      f"exp={row.get('expectancy', 0):+.2f}%, "
                      f"sharpe={row.get('sharpe', 0):.3f}, "
                      f"WR={row.get('win_rate', 0):.1f}%, "
                      f"N={row.get('n_trades', 0)}, "
                      f"tgt={row.get('profit_target', '?')}x, "
                      f"stop={row.get('stop_loss', '?')}x, "
                      f"time={row.get('time_exit', '?')}, "
                      f"avg_prem=${row.get('avg_entry_premium', 0):.2f}")

    # Print which direction/product/mult combo has the highest edge
    best_key = None
    best_exp = -999
    for key, results_df in all_options_results.items():
        if results_df.empty:
            continue
        _, overall = get_best_options_params(results_df, min_trades=3)
        if overall is not None and overall.get("expectancy", -999) > best_exp:
            best_exp = overall.get("expectancy", -999)
            best_key = key

    if best_key:
        if len(best_key) == 3:
            d, p, m = best_key
            print(f"\n  >>> BEST OPTIONS PRODUCT: {d.upper()} {m}x {p.upper().replace('_', ' ')} "
                  f"(expectancy: {best_exp:+.2f}%)")
        else:
            d, p = best_key
            print(f"\n  >>> BEST OPTIONS PRODUCT: {d.upper()} {p.upper().replace('_', ' ')} "
                  f"(expectancy: {best_exp:+.2f}%)")

    print(f"\n  Results saved to: {config.RESULTS_DIR}/")
    print()


if __name__ == "__main__":
    main()

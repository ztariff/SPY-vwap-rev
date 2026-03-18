#!/usr/bin/env python3
"""
QQQ CREDIT SPREAD BACKTEST RUNNER
===================================
Runs bull put spreads (below VWAP) and bear call spreads (above VWAP)
on QQQ 0DTE options using cached Polygon data.

All P&L from REAL market prices. No Black-Scholes.

Usage:
    python run_qqq_spreads.py                    # Both directions, ATR 0.5-1.0
    python run_qqq_spreads.py --direction below   # Just bull put spreads
    python run_qqq_spreads.py --atr-mults "0.5,0.6,0.7"
"""

import sys
import os
import argparse
import time
import json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Patch config for QQQ BEFORE importing pipeline modules
import config_qqq
sys.modules["config"] = config_qqq

from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_options_for_signal_day, OptionsDayData
from backtest_spreads import (
    run_bear_call_spreads_backtest, run_bull_put_spreads_backtest,
    get_best_spread_params, SPREAD_PAIRS,
    SPREAD_PROFIT_TARGETS, SPREAD_STOP_LOSSES, SPREAD_TIME_EXITS,
)


def main():
    parser = argparse.ArgumentParser(description="QQQ Credit Spread Backtest")
    parser.add_argument("--direction", type=str, default="both",
                        choices=["above", "below", "both"])
    parser.add_argument("--atr-mults", type=str, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    start_time = time.time()
    directions = ["above", "below"] if args.direction == "both" else [args.direction]
    atr_mults = [float(x) for x in args.atr_mults.split(",")] if args.atr_mults else [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    print("=" * 70)
    print("  QQQ CREDIT SPREAD BACKTEST")
    print("  All P&L from REAL Polygon prices — no Black-Scholes")
    print("=" * 70)
    print(f"  Directions: {directions}")
    print(f"  ATR levels: {atr_mults}")
    print(f"  Spread pairs: {len(SPREAD_PAIRS)}")
    combos = len(SPREAD_PROFIT_TARGETS) * len(SPREAD_STOP_LOSSES) * len(SPREAD_TIME_EXITS)
    print(f"  Exit grid: {combos} combos per pair")
    print()

    # Step 1: Load cached data
    print("STEP 1: Loading cached data...")
    fetcher = PolygonFetcher(cache_only=True)
    qqq_daily = fetcher.get_daily_bars("QQQ", config_qqq.BACKTEST_START, config_qqq.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config_qqq.BACKTEST_START, config_qqq.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config_qqq.BACKTEST_START, config_qqq.BACKTEST_END)

    if qqq_daily.empty:
        print("FATAL: No QQQ daily data.")
        sys.exit(1)

    enriched = enrich_daily_data(qqq_daily, vix_daily, tlt_daily, 14)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk("QQQ", valid_dates)
    print(f"  QQQ: {len(qqq_daily)} daily, {len(intraday_data)} intraday dates")

    # Step 2: Generate signals
    print("\nSTEP 2: Generating signals...")
    signals_by_key = generate_all_signals(enriched, intraday_data, atr_mults, directions)

    selected_signals = {}
    for direction in directions:
        for mult in atr_mults:
            sig_df = signals_by_key.get((direction, mult), pd.DataFrame())
            if not sig_df.empty:
                selected_signals[(direction, mult)] = sig_df

    # Step 3: Load options data from cache
    print("\nSTEP 3: Loading 0DTE options from cache...")
    unique_days = {}
    for (direction, mult), sig_df in selected_signals.items():
        for _, s in sig_df.iterrows():
            d = str(s["date"])
            if d not in unique_days:
                unique_days[d] = {"spot": s["entry_price"], "entry_time": s["entry_time"]}

    print(f"  Unique signal days: {len(unique_days)}")

    all_options = {}
    t0 = time.time()
    for i, date_str in enumerate(sorted(unique_days.keys())):
        info = unique_days[date_str]
        try:
            day_data = pull_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options[date_str] = day_data
        except Exception as e:
            if args.verbose:
                print(f"    ERROR {date_str}: {e}")
            all_options[date_str] = OptionsDayData(date_str, info["spot"], info["entry_time"])

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"    [{i+1}/{len(unique_days)}] loaded ({elapsed:.0f}s)")

    days_with_puts = sum(1 for d in all_options.values() if len(d.puts) > 0)
    days_with_calls = sum(1 for d in all_options.values() if len(d.calls) > 0)
    print(f"  Days with puts: {days_with_puts}, calls: {days_with_calls}")

    # Step 4: Run spread backtests
    print("\nSTEP 4: Running credit spread backtests...")
    all_results = {}

    for (direction, mult), sig_df in sorted(selected_signals.items()):
        days_ok = sum(1 for _, s in sig_df.iterrows()
                      if str(s["date"]) in all_options and
                      (len(all_options[str(s["date"])].puts) > 0 or
                       len(all_options[str(s["date"])].calls) > 0))
        if days_ok == 0:
            continue

        t1 = time.time()
        if direction == "above":
            res, _ = run_bear_call_spreads_backtest(all_options, sig_df)
            if not res.empty:
                res["atr_mult"] = mult
            all_results[("above", "bear_call", mult)] = res
        else:
            res, _ = run_bull_put_spreads_backtest(all_options, sig_df)
            if not res.empty:
                res["atr_mult"] = mult
            all_results[("below", "bull_put", mult)] = res

        t2 = time.time()
        n = len(res) if not res.empty else 0
        print(f"  {direction.upper()} {mult}x: {n} combos ({t2-t1:.0f}s)")

    # Step 5: Save results
    print("\nSTEP 5: Saving results...")
    os.makedirs("results_qqq", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for key, res_df in all_results.items():
        if res_df.empty:
            continue
        direction, stype, mult = key
        fname = f"qqq_spreads_{direction}_{stype}_{mult}x_{ts}.csv"
        path = f"results_qqq/{fname}"
        res_df.sort_values("sharpe", ascending=False).to_csv(path, index=False)
        print(f"  {path}: {len(res_df)} combos")

    # Step 6: Summary
    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"  QQQ SPREAD BACKTEST COMPLETE — {elapsed/60:.1f} minutes")
    print(f"{'='*70}")

    best_overall_sharpe = -999
    best_overall_key = None

    for key, res_df in sorted(all_results.items()):
        if res_df.empty:
            continue
        direction, stype, mult = key
        per_pair, overall = get_best_spread_params(res_df, min_trades=10)
        label = f"{direction.upper()} {mult}x {stype.upper().replace('_', ' ')}"

        if overall is not None:
            print(f"\n  {label} — BEST (min 10 trades):")
            print(f"    Spread: {overall.get('spread_pair', '?')}")
            print(f"    Target: {overall.get('profit_target', '?')}x | "
                  f"Stop: {overall.get('stop_loss', '?')}x | "
                  f"Time: {overall.get('time_exit', '?')}")
            print(f"    Exp: {overall.get('expectancy', 0):+.2f}% | "
                  f"WR: {overall.get('win_rate', 0):.1f}% | "
                  f"N={overall.get('n_trades', 0)}")
            print(f"    Sharpe: {overall.get('sharpe', 0):.3f} | "
                  f"Sortino: {overall.get('sortino', 0):.3f} | "
                  f"PF: {overall.get('profit_factor', 0):.2f}")
            print(f"    Avg credit: ${overall.get('avg_credit', 0):.2f} | "
                  f"Avg $P&L: ${overall.get('avg_pnl_dollar', 0):.2f}")

            score = overall.get("sharpe", -999)
            if score > best_overall_sharpe:
                best_overall_sharpe = score
                best_overall_key = key

        # Top 5 per ATR level
        if per_pair is not None and not per_pair.empty:
            print(f"\n    Per spread pair:")
            for _, row in per_pair.head(5).iterrows():
                print(f"      {row.get('spread_pair', '?')}: "
                      f"Exp={row.get('expectancy', 0):+.2f}%, "
                      f"Sharpe={row.get('sharpe', 0):.3f}, "
                      f"WR={row.get('win_rate', 0):.1f}%, "
                      f"N={row.get('n_trades', 0)}, "
                      f"credit=${row.get('avg_credit', 0):.2f}")

    if best_overall_key:
        d, st, m = best_overall_key
        print(f"\n  >>> BEST OVERALL: {d.upper()} {m}x {st.upper()} "
              f"(Sharpe: {best_overall_sharpe:.3f})")

    # Save summary JSON
    summary = {}
    for key, res_df in all_results.items():
        if res_df.empty:
            continue
        direction, stype, mult = key
        _, overall = get_best_spread_params(res_df, min_trades=10)
        if overall is not None:
            summary[f"{direction}_{mult}x"] = {
                k: (v if not isinstance(v, (np.integer, np.floating)) else float(v))
                for k, v in dict(overall).items()
                if not isinstance(v, dict)
            }

    with open(f"results_qqq/qqq_spread_summary_{ts}.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  Summary: results_qqq/qqq_spread_summary_{ts}.json")
    print()


if __name__ == "__main__":
    main()

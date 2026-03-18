#!/usr/bin/env python3
"""
QQQ VWAP Deviation Strategy — Full Stock Backtest
====================================================
Runs the IDENTICAL pipeline as SPY but on QQQ data.
Patches config module to use QQQ ticker, then runs:
  1. Daily data fetch (from cache)
  2. Intraday data fetch (from cache)
  3. Signal generation (both directions, full ATR grid)
  4. Stock backtest grid search
  5. Scale-in analysis
  6. Regime analysis

Per CLAUDE.md: All data is REAL Polygon market data. No fabrication.

Usage:
    cd spy_fade_strategy
    python run_qqq_backtest.py                # Full stock backtest
    python run_qqq_backtest.py --skip-scalein # Skip scale-in
"""

import sys
import os
import argparse
import time
import json
import pickle
import pandas as pd
import numpy as np
from datetime import datetime

# Patch config BEFORE importing other modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_qqq
sys.modules['config'] = config_qqq

from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals, generate_scalein_signals
from backtest_stock import (
    run_stock_backtest, run_scalein_backtest, get_best_stock_params,
    simulate_stock_trade
)


def parse_args():
    parser = argparse.ArgumentParser(description="QQQ VWAP Deviation Strategy Backtester")
    parser.add_argument("--skip-scalein", action="store_true")
    parser.add_argument("--direction", type=str, default="both",
                        choices=["above", "below", "both"])
    parser.add_argument("--start", type=str, default=config_qqq.BACKTEST_START)
    parser.add_argument("--end", type=str, default=config_qqq.BACKTEST_END)
    return parser.parse_args()


def _pick_primary_mult(signals_by_key, direction, atr_mults):
    preferred = [1.0, 0.9, 1.1, 0.8, 1.2, 0.7, 1.3]
    for m in preferred:
        if m in atr_mults:
            key = (direction, m)
            if key in signals_by_key and not signals_by_key[key].empty:
                if len(signals_by_key[key]) >= 20:
                    return m
    for m in atr_mults:
        key = (direction, m)
        if key in signals_by_key and not signals_by_key[key].empty:
            return m
    return None


def main():
    args = parse_args()
    start_time = time.time()

    directions = ["above", "below"] if args.direction == "both" else [args.direction]
    atr_mults = config_qqq.ATR_MULTIPLIER_RANGE

    print("=" * 70)
    print("  QQQ VWAP DEVIATION STRATEGY — STOCK BACKTESTER")
    print("  Identical pipeline to SPY, applied to QQQ")
    print("  All P&L from REAL Polygon data (no fabrication)")
    print("=" * 70)
    print(f"\n  Period: {args.start} → {args.end}")
    print(f"  Directions: {', '.join(directions)}")
    print(f"  ATR grid: {atr_mults[0]}x → {atr_mults[-1]}x ({len(atr_mults)} levels)")
    print(f"  Scale-in: {'skip' if args.skip_scalein else f'{len(config_qqq.SCALE_IN_PAIRS)} pairs'}")
    print()

    # ═══════════════════════════════════════════════════════════════════
    #  PHASE 1: Fetch Base Data (from cache)
    # ═══════════════════════════════════════════════════════════════════
    print("PHASE 1: Fetching base data from cache...")
    print("-" * 50)

    fetcher = PolygonFetcher()
    qqq_daily = fetcher.get_daily_bars("QQQ", args.start, args.end)
    tlt_daily = fetcher.get_daily_bars("TLT", args.start, args.end)
    vix_daily = fetcher.get_vix_daily(args.start, args.end)

    if qqq_daily.empty:
        print("FATAL: No QQQ daily data. Run fetch_qqq_all.py first.")
        sys.exit(1)

    print(f"  QQQ daily bars: {len(qqq_daily)}")
    print(f"  QQQ price range: ${qqq_daily['close'].min():.2f} - ${qqq_daily['close'].max():.2f}")
    print(f"  TLT daily bars: {len(tlt_daily)}")
    print(f"  VIX daily bars: {len(vix_daily)}")

    # ═══════════════════════════════════════════════════════════════════
    #  PHASE 2: Enrich & Fetch Intraday
    # ═══════════════════════════════════════════════════════════════════
    print(f"\nPHASE 2: Enriching daily data & loading intraday bars...")
    print("-" * 50)

    enriched = enrich_daily_data(qqq_daily, vix_daily, tlt_daily, config_qqq.ATR_PERIOD)
    print(f"  Enriched: {len(enriched)} days")
    print(f"  ATR range: {enriched['atr'].min():.2f} - {enriched['atr'].max():.2f}")
    print(f"  Avg ATR: ${enriched['atr'].mean():.2f}")
    print(f"  VIX coverage: {enriched['vix_close'].notna().sum()}/{len(enriched)} "
          f"({enriched['vix_close'].notna().mean()*100:.1f}%)")

    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk("QQQ", valid_dates)

    # ═══════════════════════════════════════════════════════════════════
    #  PHASE 3: Generate Signals
    # ═══════════════════════════════════════════════════════════════════
    print(f"\nPHASE 3: Generating signals...")
    print("-" * 50)

    signals_by_key = generate_all_signals(enriched, intraday_data, atr_mults, directions)

    # ═══════════════════════════════════════════════════════════════════
    #  PHASE 4: Stock Backtest (Both Directions)
    # ═══════════════════════════════════════════════════════════════════
    print(f"\nPHASE 4: Running stock backtests...")
    print("-" * 50)

    all_stock_results = {}
    all_stock_best = {}
    all_stock_trades = {}
    best_signals = {}

    for direction in directions:
        primary_mult = _pick_primary_mult(signals_by_key, direction, atr_mults)
        if primary_mult is None:
            print(f"  No signals for {direction} direction, skipping")
            continue

        primary_signals = signals_by_key[(direction, primary_mult)]
        best_signals[direction] = primary_signals
        print(f"\n  {direction.upper()} primary mult: {primary_mult}x ({len(primary_signals)} signals)")

        results_df, signal_bars = run_stock_backtest(
            primary_signals, intraday_data, direction=direction
        )
        all_stock_results[direction] = results_df

        if not results_df.empty:
            best = get_best_stock_params(results_df)
            if best is not None:
                all_stock_best[direction] = best.to_dict()

                trades = []
                for date_str, (signal, remaining_bars) in signal_bars.items():
                    trade = simulate_stock_trade(
                        remaining_bars, signal["entry_price"],
                        best.to_dict().get("stop_loss", 1.0),
                        best.to_dict().get("target", 1.0),
                        best.to_dict().get("trailing_stop"),
                        best.to_dict().get("time_exit"),
                        direction,
                    )
                    trade["date"] = signal["date"]
                    trade["entry_price"] = signal["entry_price"]
                    trade["vix_regime"] = signal.get("vix_regime", "unknown")
                    trade["direction"] = direction
                    trades.append(trade)
                all_stock_trades[direction] = pd.DataFrame(trades) if trades else pd.DataFrame()

    # ─── ATR Level Scan ───
    print(f"\n  Scanning all ATR levels for optimal entry threshold...")
    atr_scan_results = {}
    for direction in directions:
        scan = []
        for mult in atr_mults:
            key = (direction, mult)
            if key not in signals_by_key or signals_by_key[key].empty:
                continue
            sig_df = signals_by_key[key]
            signal_bars_quick = {}
            for _, signal in sig_df.iterrows():
                ds = str(signal["date"])
                if ds not in intraday_data:
                    continue
                intra = intraday_data[ds]
                remaining = intra[intra["timestamp"] > signal["entry_time"]].copy()
                signal_bars_quick[ds] = (signal, remaining)

            pnls = []
            for ds, (signal, rem) in signal_bars_quick.items():
                trade = simulate_stock_trade(rem, signal["entry_price"],
                                             0.75, 0.50, None, "EOD", direction)
                pnls.append(trade["pnl_pct"])

            if pnls:
                scan.append({
                    "atr_mult": mult,
                    "n_signals": len(pnls),
                    "avg_pnl": np.mean(pnls),
                    "win_rate": sum(1 for p in pnls if p > 0) / len(pnls) * 100,
                    "total_pnl": sum(pnls),
                })

        if scan:
            scan_df = pd.DataFrame(scan).sort_values("avg_pnl", ascending=False)
            atr_scan_results[direction] = scan_df
            dir_label = "ABOVE (short)" if direction == "above" else "BELOW (long)"
            print(f"\n  {dir_label} ATR Scan (0.75% stop, 0.50% tgt, EOD):")
            for _, row in scan_df.iterrows():
                pfx = ">>>" if row["avg_pnl"] == scan_df["avg_pnl"].max() else "   "
                print(f"  {pfx} {row['atr_mult']:.1f}x: N={int(row['n_signals']):4d}  "
                      f"WR={row['win_rate']:5.1f}%  Avg={row['avg_pnl']:+7.4f}%  "
                      f"Total={row['total_pnl']:+7.2f}%")

    # ═══════════════════════════════════════════════════════════════════
    #  PHASE 4b: Scale-In Backtest
    # ═══════════════════════════════════════════════════════════════════
    scalein_results = {}
    if not args.skip_scalein:
        print(f"\nPHASE 4b: Running scale-in analysis...")
        print("-" * 50)

        scalein_signals = generate_scalein_signals(
            enriched, intraday_data,
            config_qqq.SCALE_IN_PAIRS, directions
        )

        for direction in directions:
            si_results = run_scalein_backtest(
                scalein_signals, intraday_data, direction=direction
            )
            if not si_results.empty:
                scalein_results[direction] = si_results

    # ═══════════════════════════════════════════════════════════════════
    #  RESULTS SUMMARY
    # ═══════════════════════════════════════════════════════════════════
    elapsed = time.time() - start_time

    print(f"\n{'='*70}")
    print(f"  QQQ BACKTEST COMPLETE — {elapsed/60:.1f} minutes")
    print(f"{'='*70}")

    # Save results
    os.makedirs("results_qqq", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    full_results = {
        "ticker": "QQQ",
        "period": f"{args.start} to {args.end}",
        "elapsed_min": round(elapsed/60, 1),
        "daily_bars": len(qqq_daily),
        "intraday_days": len(intraday_data),
        "directions": {},
    }

    for direction in directions:
        dir_data = {}

        # Signals summary
        signal_counts = {}
        for mult in atr_mults:
            key = (direction, mult)
            if key in signals_by_key and not signals_by_key[key].empty:
                signal_counts[str(mult)] = len(signals_by_key[key])
        dir_data["signal_counts_by_atr"] = signal_counts

        # ATR scan
        if direction in atr_scan_results:
            scan_df = atr_scan_results[direction]
            dir_data["atr_scan"] = scan_df.to_dict("records")
            dir_data["best_atr"] = scan_df.iloc[0].to_dict()

        # Stock best
        if direction in all_stock_best:
            b = all_stock_best[direction]
            dir_data["stock_best"] = {
                k: (v if not isinstance(v, (np.floating, np.integer)) else float(v))
                for k, v in b.items() if k != "exit_reasons"
            }

        # Stock grid results
        if direction in all_stock_results and not all_stock_results[direction].empty:
            res = all_stock_results[direction]
            dir_data["stock_grid_combos"] = len(res)
            dir_data["stock_grid_positive_exp"] = int((res["expectancy"] > 0).sum())

        # Scale-in
        if direction in scalein_results:
            si = scalein_results[direction]
            best_si = si.iloc[0]
            dir_data["scalein_best"] = {
                "entry_mult": float(best_si["entry_mult"]),
                "add_mult": float(best_si["add_mult"]),
                "expectancy": float(best_si["expectancy"]),
                "n_trades": int(best_si["n_trades"]),
                "win_rate": float(best_si["win_rate"]),
                "pct_scaled_in": float(best_si["pct_scaled_in"]),
            }

        full_results["directions"][direction] = dir_data

    # Save JSON results
    results_path = f"results_qqq/qqq_backtest_{ts}.json"
    with open(results_path, "w") as f:
        json.dump(full_results, f, indent=2, default=str)
    print(f"\n  Full results saved to: {results_path}")

    # Save CSV results
    for direction in directions:
        if direction in all_stock_results and not all_stock_results[direction].empty:
            csv_path = f"results_qqq/qqq_stock_{direction}_{ts}.csv"
            all_stock_results[direction].to_csv(csv_path, index=False)
            print(f"  Stock grid: {csv_path}")

    # Print key findings
    print(f"\n{'='*70}")
    print("  QQQ KEY FINDINGS")
    print(f"{'='*70}")

    for direction, label in [("above", "FADE (ABOVE VWAP → SHORT)"),
                              ("below", "BUY DIP (BELOW VWAP → LONG)")]:
        if direction in all_stock_best:
            b = all_stock_best[direction]
            print(f"\n  {label}:")
            print(f"    Stop: {b.get('stop_loss')}% | Target: {b.get('target')}% | "
                  f"Trail: {b.get('trailing_stop')} | Time: {b.get('time_exit')}")
            print(f"    Exp: {b.get('expectancy', 0):+.4f}% | WR: {b.get('win_rate', 0):.1f}% | "
                  f"PF: {b.get('profit_factor', 0):.2f} | N={b.get('n_trades', 0)}")

    for direction in ["above", "below"]:
        if direction in atr_scan_results and not atr_scan_results[direction].empty:
            best_row = atr_scan_results[direction].iloc[0]
            dir_label = "ABOVE" if direction == "above" else "BELOW"
            print(f"\n  {dir_label} ATR Sweet Spot: {best_row['atr_mult']:.1f}x "
                  f"(avg={best_row['avg_pnl']:+.4f}%, N={int(best_row['n_signals'])})")

    for direction in ["above", "below"]:
        if direction in scalein_results and not scalein_results[direction].empty:
            best = scalein_results[direction].iloc[0]
            dir_label = "ABOVE" if direction == "above" else "BELOW"
            print(f"\n  {dir_label} Best Scale-In: {best['entry_mult']}x→{best['add_mult']}x "
                  f"(exp={best['expectancy']:+.4f}%, {best['pct_scaled_in']:.0f}% got 2nd fill)")

    # ─── VIX regime breakdown for trade results ───
    for direction in directions:
        if direction in all_stock_trades and not all_stock_trades[direction].empty:
            trades = all_stock_trades[direction]
            dir_label = "ABOVE" if direction == "above" else "BELOW"
            print(f"\n  {dir_label} VIX Regime Breakdown:")
            for regime in sorted(trades["vix_regime"].unique()):
                subset = trades[trades["vix_regime"] == regime]
                if len(subset) >= 3:
                    wr = (subset["pnl_pct"] > 0).mean() * 100
                    avg = subset["pnl_pct"].mean()
                    print(f"    VIX {regime}: N={len(subset):3d}, WR={wr:5.1f}%, "
                          f"Avg={avg:+.4f}%")

    print(f"\n  Results saved to: results_qqq/")
    print()


if __name__ == "__main__":
    main()

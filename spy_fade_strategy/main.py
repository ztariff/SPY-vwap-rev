#!/usr/bin/env python3
"""
SPY VWAP Deviation Strategy — Full Backtester (v2)
=====================================================
Tests BOTH directions with fine-grained ATR grid + scale-in logic:
  ABOVE VWAP (fade): Short stock, long 0DTE puts, short 0DTE calls
  BELOW VWAP (buy):  Long stock, long 0DTE calls, short 0DTE puts

Usage:
    python main.py                     # Full backtest (all products, both dirs)
    python main.py --stock-only        # Stock only (much faster)
    python main.py --direction above   # Only test above VWAP
    python main.py --direction below   # Only test below VWAP
    python main.py --atr-mult 1.0      # Single ATR multiplier
    python main.py --skip-scalein      # Skip scale-in analysis
"""

import sys
import os
import argparse
import time
import pickle
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals, generate_scalein_signals
from backtest_stock import (
    run_stock_backtest, run_scalein_backtest, get_best_stock_params,
    simulate_stock_trade
)
from options_data import pull_all_options_data
from backtest_options import (
    run_long_puts_backtest, run_short_calls_backtest,
    run_long_calls_backtest, run_short_puts_backtest,
    get_best_options_params
)
from regime_analysis import (
    run_full_regime_analysis, compute_risk_sizing_recommendation,
    compare_directions
)
from report_generator import generate_report


def parse_args():
    parser = argparse.ArgumentParser(description="SPY VWAP Deviation Strategy Backtester v2")
    parser.add_argument("--stock-only", action="store_true",
                        help="Only run stock backtest (skip options)")
    parser.add_argument("--direction", type=str, default="both",
                        choices=["above", "below", "both"],
                        help="Which direction to test (default: both)")
    parser.add_argument("--atr-mult", type=float, default=None,
                        help="Single ATR multiplier (default: full grid 0.5-2.0)")
    parser.add_argument("--skip-scalein", action="store_true",
                        help="Skip scale-in analysis")
    parser.add_argument("--start", type=str, default=config.BACKTEST_START)
    parser.add_argument("--end", type=str, default=config.BACKTEST_END)
    parser.add_argument("--save-signals", action="store_true",
                        help="Save signals to pickle for reuse")
    parser.add_argument("--load-signals", type=str, default=None,
                        help="Load signals from pickle file")
    return parser.parse_args()


def main():
    args = parse_args()
    start_time = time.time()

    directions = ["above", "below"] if args.direction == "both" else [args.direction]
    atr_mults = [args.atr_mult] if args.atr_mult else config.ATR_MULTIPLIER_RANGE

    print("=" * 70)
    print("  SPY VWAP DEVIATION STRATEGY — v2 BACKTESTER")
    print("  Tests BOTH above & below VWAP with fine ATR grid + scale-in")
    print("  All options P&L from REAL Polygon data (no Black-Scholes)")
    print("=" * 70)
    print(f"\n  Period: {args.start} → {args.end}")
    print(f"  Directions: {', '.join(directions)}")
    print(f"  ATR grid: {atr_mults[0]}x → {atr_mults[-1]}x ({len(atr_mults)} levels)")
    print(f"  Scale-in: {'skip' if args.skip_scalein else f'{len(config.SCALE_IN_PAIRS)} pairs'}")
    print(f"  Products: Stock" + ("" if args.stock_only else " + 0DTE Options"))
    print()

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 1: Fetch Base Data
    # ═══════════════════════════════════════════════════════════════════════
    print("PHASE 1: Fetching base data from Polygon...")
    print("-" * 50)

    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars(config.TICKER, args.start, args.end)
    tlt_daily = fetcher.get_daily_bars(config.TLT_TICKER, args.start, args.end)
    vix_daily = fetcher.get_vix_daily(args.start, args.end)

    if spy_daily.empty:
        print("FATAL: No SPY daily data. Check API key and date range.")
        sys.exit(1)

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 2: Enrich & Fetch Intraday
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\nPHASE 2: Enriching daily data & fetching intraday bars...")
    print("-" * 50)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    print(f"  Enriched: {len(enriched)} days, ATR range: "
          f"{enriched['atr'].min():.2f}-{enriched['atr'].max():.2f}")

    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]

    if args.load_signals:
        print(f"  Loading cached data from {args.load_signals}...")
        with open(args.load_signals, "rb") as f:
            cached = pickle.load(f)
        intraday_data = cached["intraday_data"]
        print(f"  Loaded {len(intraday_data)} days of intraday data")
    else:
        intraday_data = fetcher.get_intraday_bars_bulk(config.TICKER, valid_dates)

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 3: Generate Signals (Both Directions, Full ATR Grid)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\nPHASE 3: Generating signals...")
    print("-" * 50)

    signals_by_key = generate_all_signals(enriched, intraday_data, atr_mults, directions)

    # Save if requested
    if args.save_signals:
        cache_path = os.path.join(config.RESULTS_DIR, "signals_cache.pkl")
        os.makedirs(config.RESULTS_DIR, exist_ok=True)
        with open(cache_path, "wb") as f:
            pickle.dump({"intraday_data": intraday_data, "signals": signals_by_key}, f)
        print(f"  Saved cache to {cache_path}")

    # Build signals summary
    signals_summary = {}
    for (direction, mult), sig_df in signals_by_key.items():
        if sig_df.empty:
            continue
        date_range = (sig_df["date"].max() - sig_df["date"].min()).days
        months = max(1, date_range / 30)
        key = f"{direction}_{mult}"
        signals_summary[key] = {
            "direction": direction,
            "multiplier": mult,
            "count": len(sig_df),
            "first_date": str(sig_df["date"].min()),
            "last_date": str(sig_df["date"].max()),
            "per_month": len(sig_df) / months,
        }

    # ─── ATR Level Heatmap: signal count by ATR multiplier ────────────
    print(f"\n  ATR Level Signal Counts:")
    for direction in directions:
        dir_label = "ABOVE" if direction == "above" else "BELOW"
        counts = [(m, len(signals_by_key.get((direction, m), pd.DataFrame())))
                  for m in atr_mults]
        print(f"    {dir_label}: " + " | ".join(f"{m:.1f}x:{c}" for m, c in counts))

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 4: Stock Backtest (Both Directions)
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\nPHASE 4: Running stock backtests...")
    print("-" * 50)

    # For detailed backtest, pick the best-populated multiplier near 1.0 for each direction
    all_stock_results = {}
    all_stock_best = {}
    all_stock_trades = {}
    best_signals = {}

    for direction in directions:
        # Find best multiplier (prefer ~1.0x with enough signals)
        primary_mult = _pick_primary_mult(signals_by_key, direction, atr_mults)
        if primary_mult is None:
            print(f"  No signals for {direction} direction, skipping stock backtest")
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

                # Rebuild individual trades for regime analysis
                trades = _rebuild_trades(best.to_dict(), signal_bars, direction)
                all_stock_trades[direction] = trades

    # ─── Also run a quick scan across ALL ATR levels to find the sweet spot ─
    print(f"\n  Scanning all ATR levels for optimal entry threshold...")
    atr_scan_results = {}
    for direction in directions:
        scan = []
        for mult in atr_mults:
            key = (direction, mult)
            if key not in signals_by_key or signals_by_key[key].empty:
                continue
            sig_df = signals_by_key[key]
            # Quick test with default params: 0.75% stop, 0.50% target, EOD exit
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

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 4b: Scale-In Backtest
    # ═══════════════════════════════════════════════════════════════════════
    scalein_results = {}
    if not args.skip_scalein:
        print(f"\nPHASE 4b: Running scale-in analysis...")
        print("-" * 50)

        scalein_signals = generate_scalein_signals(
            enriched, intraday_data,
            config.SCALE_IN_PAIRS, directions
        )

        for direction in directions:
            si_results = run_scalein_backtest(
                scalein_signals, intraday_data, direction=direction
            )
            if not si_results.empty:
                scalein_results[direction] = si_results

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 5: Options Backtest (Both Directions)
    # ═══════════════════════════════════════════════════════════════════════
    all_options_results = {}

    if not args.stock_only:
        print(f"\nPHASE 5: Options backtests...")
        print("-" * 50)

        for direction in directions:
            if direction not in best_signals or best_signals[direction].empty:
                continue

            signals = best_signals[direction]
            print(f"\n  Pulling 0DTE options for {direction.upper()} signals ({len(signals)} days)...")
            options_data = pull_all_options_data(fetcher, signals)

            if direction == "above":
                # Fade: long puts + short calls
                put_res, _ = run_long_puts_backtest(options_data, signals)
                call_res, _ = run_short_calls_backtest(options_data, signals)
                all_options_results[("above", "long_put")] = put_res
                all_options_results[("above", "short_call")] = call_res
            else:
                # Buy dip: long calls + short puts
                call_res, _ = run_long_calls_backtest(options_data, signals)
                put_res, _ = run_short_puts_backtest(options_data, signals)
                all_options_results[("below", "long_call")] = call_res
                all_options_results[("below", "short_put")] = put_res
    else:
        print("\n  Skipping options (--stock-only)")

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 6: Regime Analysis & Direction Comparison
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\nPHASE 6: Regime analysis & direction comparison...")
    print("-" * 50)

    regime_analyses = {}
    risk_recommendations = {}

    for direction in directions:
        if direction in all_stock_trades and not all_stock_trades[direction].empty:
            dir_label = "ABOVE (fade)" if direction == "above" else "BELOW (buy)"
            print(f"\n  ── {dir_label} ──")
            analyses = run_full_regime_analysis(all_stock_trades[direction],
                                                best_signals.get(direction, pd.DataFrame()))
            regime_analyses[direction] = analyses
            risk_recommendations[direction] = compute_risk_sizing_recommendation(analyses)

    # Cross-direction comparison
    direction_comparison = pd.DataFrame()
    if "above" in all_stock_trades and "below" in all_stock_trades:
        direction_comparison = compare_directions(
            all_stock_trades.get("above", pd.DataFrame()),
            all_stock_trades.get("below", pd.DataFrame())
        )

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 7: Generate Report
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\nPHASE 7: Generating report...")
    print("-" * 50)

    # Prepare options best params
    options_best = {}
    options_per_delta = {}
    for key, res_df in all_options_results.items():
        if not res_df.empty:
            per_delta, overall = get_best_options_params(res_df)
            options_best[key] = overall.to_dict() if overall is not None else None
            options_per_delta[key] = per_delta

    report_path = generate_report(
        stock_results=all_stock_results,
        stock_best=all_stock_best,
        put_results=all_options_results.get(("above", "long_put"), pd.DataFrame()),
        put_best_per_delta=options_per_delta.get(("above", "long_put"), pd.DataFrame()),
        put_best_overall=options_best.get(("above", "long_put")),
        call_results=all_options_results.get(("above", "short_call"), pd.DataFrame()),
        call_best_per_delta=options_per_delta.get(("above", "short_call"), pd.DataFrame()),
        call_best_overall=options_best.get(("above", "short_call")),
        regime_analyses=regime_analyses,
        risk_recommendations=risk_recommendations,
        signals_summary=signals_summary,
        output_dir=config.RESULTS_DIR,
        # v2 additions
        below_stock_results=all_stock_results.get("below"),
        below_stock_best=all_stock_best.get("below"),
        below_options_results=all_options_results,
        below_options_best=options_best,
        atr_scan_results=atr_scan_results,
        scalein_results=scalein_results,
        direction_comparison=direction_comparison,
    )

    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"  BACKTEST COMPLETE — {elapsed/60:.1f} minutes")
    print(f"  Report: {report_path}")
    print(f"{'='*70}")

    _print_key_findings(all_stock_best, options_best, risk_recommendations,
                        atr_scan_results, scalein_results, direction_comparison)


def _pick_primary_mult(signals_by_key, direction, atr_mults):
    """Pick the ATR multiplier near 1.0 with the most signals."""
    preferred = [1.0, 0.9, 1.1, 0.8, 1.2, 0.7, 1.3]
    for m in preferred:
        if m in atr_mults:
            key = (direction, m)
            if key in signals_by_key and not signals_by_key[key].empty:
                if len(signals_by_key[key]) >= 20:
                    return m
    # Fallback: any mult with signals
    for m in atr_mults:
        key = (direction, m)
        if key in signals_by_key and not signals_by_key[key].empty:
            return m
    return None


def _rebuild_trades(best_params, signal_bars, direction):
    """Re-run trades with best params for regime analysis."""
    trades = []
    for date_str, (signal, remaining_bars) in signal_bars.items():
        trade = simulate_stock_trade(
            remaining_bars, signal["entry_price"],
            best_params.get("stop_loss", 1.0),
            best_params.get("target", 1.0),
            best_params.get("trailing_stop"),
            best_params.get("time_exit"),
            direction,
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
    return pd.DataFrame(trades) if trades else pd.DataFrame()


def _print_key_findings(stock_best, options_best, risk_recs,
                        atr_scan, scalein_results, dir_comparison):
    """Print consolidated key findings."""
    print(f"\n{'='*70}")
    print("  KEY FINDINGS")
    print(f"{'='*70}")

    for direction, label in [("above", "FADE (ABOVE VWAP → SHORT)"),
                              ("below", "BUY DIP (BELOW VWAP → LONG)")]:
        if direction in stock_best:
            b = stock_best[direction]
            print(f"\n  {label}:")
            print(f"    Stop: {b.get('stop_loss')}% | Target: {b.get('target')}% | "
                  f"Trail: {b.get('trailing_stop')} | Time: {b.get('time_exit')}")
            print(f"    Exp: {b.get('expectancy', 0):+.4f}% | WR: {b.get('win_rate', 0):.1f}% | "
                  f"PF: {b.get('profit_factor', 0):.2f} | N={b.get('n_trades', 0)}")

    # ATR sweet spot
    for direction in ["above", "below"]:
        if direction in atr_scan and not atr_scan[direction].empty:
            best_row = atr_scan[direction].iloc[0]
            dir_label = "ABOVE" if direction == "above" else "BELOW"
            print(f"\n  {dir_label} ATR Sweet Spot: {best_row['atr_mult']:.1f}x "
                  f"(avg={best_row['avg_pnl']:+.4f}%, N={best_row['n_signals']})")

    # Scale-in
    for direction in ["above", "below"]:
        if direction in scalein_results and not scalein_results[direction].empty:
            best = scalein_results[direction].iloc[0]
            dir_label = "ABOVE" if direction == "above" else "BELOW"
            print(f"\n  {dir_label} Best Scale-In: {best['entry_mult']}x→{best['add_mult']}x "
                  f"(exp={best['expectancy']:+.4f}%, {best['pct_scaled_in']:.0f}% got 2nd fill)")

    # Options
    for key, label in [
        (("above", "long_put"), "ABOVE Long Puts"),
        (("above", "short_call"), "ABOVE Short Calls"),
        (("below", "long_call"), "BELOW Long Calls"),
        (("below", "short_put"), "BELOW Short Puts"),
    ]:
        if key in options_best and options_best[key]:
            b = options_best[key]
            print(f"\n  {label}: delta={b.get('delta')}, "
                  f"tgt={b.get('profit_target')}x, stop={b.get('stop_loss')}x | "
                  f"Exp={b.get('expectancy', 0):+.2f}%, WR={b.get('win_rate', 0):.1f}%")

    # Risk sizing highlights
    for direction in ["above", "below"]:
        if direction in risk_recs and risk_recs[direction]:
            dir_label = "ABOVE" if direction == "above" else "BELOW"
            sorted_recs = sorted(risk_recs[direction].items(),
                                 key=lambda x: x[1]["risk_multiplier"], reverse=True)
            if sorted_recs:
                top = sorted_recs[0]
                print(f"\n  {dir_label} Best Regime: {top[0]} → {top[1]['risk_multiplier']}x risk")


if __name__ == "__main__":
    main()

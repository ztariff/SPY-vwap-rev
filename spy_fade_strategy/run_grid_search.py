#!/usr/bin/env python3
"""
COMPREHENSIVE GRID SEARCH
==========================
Tests ALL combinations of:
  1. Higher delta long options (0.25-0.50 puts above, 0.25-0.50 calls below)
  2. Credit spreads (bear calls above, bull puts below)
  3. Tight ATR thresholds (0.7-1.2x)
  4. Full exit parameter grid

Scores by Sharpe ratio with fill-realism filters.
Outputs ranked results to results/grid_search_TIMESTAMP.csv

Usage:
    python run_grid_search.py
    python run_grid_search.py --atr-range 0.8,0.9,1.0
    python run_grid_search.py --min-premium 0.10
"""

import sys
import os
import json
import argparse
import time
import pandas as pd
import numpy as np
from datetime import datetime
from itertools import product as iterproduct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_options_for_signal_day, OptionsDayData
from backtest_options import simulate_long_option_trade
from backtest_spreads import simulate_credit_spread_trade


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--atr-range", default="0.7,0.8,0.9,1.0,1.1,1.2",
                   help="Comma-separated ATR multipliers to test")
    p.add_argument("--min-premium", type=float, default=0.10,
                   help="Minimum option premium for fill realism")
    p.add_argument("--min-trades", type=int, default=8,
                   help="Minimum trades for a combo to be scored")
    p.add_argument("--direction", default="both", choices=["above", "below", "both"])
    return p.parse_args()


def time_exit_val(s):
    if s in ("EOD", "None") or s is None:
        return "EOD"
    try:
        return int(s)
    except ValueError:
        return "EOD"


def compute_metrics(pnls):
    """Compute Sharpe, Sortino, and other stats from a list of P&L %."""
    n = len(pnls)
    if n < 3:
        return None
    arr = np.array(pnls)
    avg = arr.mean()
    std = arr.std()
    wins = (arr > 0).sum()
    wr = wins / n * 100
    sharpe = avg / std if std > 0 else 0

    downside = arr[arr < 0]
    ds_std = downside.std() if len(downside) >= 2 else std
    sortino = avg / ds_std if ds_std > 0 else 0

    total = arr.sum()
    gross_win = arr[arr > 0].sum() if wins > 0 else 0
    gross_loss = abs(arr[arr < 0].sum()) if (arr < 0).any() else 0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    return {
        "n_trades": n, "win_rate": wr, "avg_pnl": avg, "total_pnl": total,
        "sharpe": sharpe, "sortino": sortino, "profit_factor": pf,
        "score": sharpe * np.sqrt(n),  # Sharpe * sqrt(N) for ranking
    }


def main():
    args = parse_args()
    start_time = time.time()

    atr_mults = [float(x.strip()) for x in args.atr_range.split(",")]
    directions = ["above", "below"] if args.direction == "both" else [args.direction]

    # ── Parameter grids ──
    # Long options
    LONG_DELTAS = [0.25, 0.30, 0.35, 0.40, 0.50]
    LONG_TARGETS = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0]   # % gain on premium
    LONG_STOPS = [0.25, 0.50, 0.75, 1.0]                  # % loss on premium
    LONG_TIME_EXITS = [5, 10, 15, 30, 60, "EOD"]

    # Credit spreads
    SPREAD_PAIRS = [
        (0.50, 0.30), (0.50, 0.35), (0.50, 0.40),
        (0.40, 0.20), (0.40, 0.25), (0.40, 0.30),
        (0.35, 0.20), (0.35, 0.25),
        (0.30, 0.15), (0.30, 0.20),
        (0.25, 0.15), (0.25, 0.10),
    ]
    SPREAD_TARGETS = [0.25, 0.50, 0.75, 0.90, 1.0]  # % of credit captured
    SPREAD_STOPS = [0.5, 1.0, 1.5, 2.0, 3.0]         # multiple of credit
    SPREAD_TIME_EXITS = [5, 10, 15, 30, 60, "EOD"]

    n_long_combos = len(LONG_DELTAS) * len(LONG_TARGETS) * len(LONG_STOPS) * len(LONG_TIME_EXITS)
    n_spread_combos = len(SPREAD_PAIRS) * len(SPREAD_TARGETS) * len(SPREAD_STOPS) * len(SPREAD_TIME_EXITS)
    n_atr = len(atr_mults)
    n_dir = len(directions)

    print("=" * 70)
    print("  COMPREHENSIVE GRID SEARCH")
    print("=" * 70)
    print(f"  ATR levels: {atr_mults}")
    print(f"  Directions: {directions}")
    print(f"  Long options: {n_long_combos} combos x {n_atr} ATR x {n_dir} dir = {n_long_combos * n_atr * n_dir}")
    print(f"  Credit spreads: {n_spread_combos} combos x {n_atr} ATR x {n_dir} dir = {n_spread_combos * n_atr * n_dir}")
    print(f"  Min premium: ${args.min_premium:.2f}, Min trades: {args.min_trades}")
    print()

    # ── Load data ──
    print("Loading base data...")
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars(config.TICKER, config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars(config.TLT_TICKER, config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk(config.TICKER, valid_dates)

    # ── Generate signals ──
    print("Generating signals...")
    signals_by_key = generate_all_signals(
        enriched, intraday_data, config.ATR_MULTIPLIER_RANGE, directions
    )

    # Collect selected signals
    selected_signals = {}
    for direction in directions:
        for mult in atr_mults:
            sig_df = signals_by_key.get((direction, mult), pd.DataFrame())
            if not sig_df.empty:
                selected_signals[(direction, mult)] = sig_df
                print(f"  {direction.upper()} {mult}x: {len(sig_df)} signals")

    # ── Pull options data (using cache) ──
    unique_days = {}
    for (direction, mult), sig_df in selected_signals.items():
        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in unique_days:
                unique_days[date_str] = {
                    "spot": signal["entry_price"],
                    "entry_time": signal["entry_time"],
                }

    print(f"\nPulling options for {len(unique_days)} unique signal days...")
    all_options_data = {}
    for i, (date_str, info) in enumerate(sorted(unique_days.items())):
        if (i + 1) % 20 == 0:
            print(f"  [{i + 1}/{len(unique_days)}]...")
        try:
            day_data = pull_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options_data[date_str] = day_data
        except Exception as e:
            print(f"  ERROR {date_str}: {e}")
            all_options_data[date_str] = OptionsDayData(date_str, info["spot"], info["entry_time"])

    # ═══════════════════════════════════════════════════════════════════════
    #  GRID SEARCH: LONG OPTIONS
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  GRID SEARCH: LONG OPTIONS")
    print(f"{'='*70}")

    long_results = []
    combos_tested = 0

    for direction in directions:
        # Above VWAP = buy puts to fade; Below VWAP = buy calls to buy dip
        option_side = "puts" if direction == "above" else "calls"
        product_type = "long_put" if direction == "above" else "long_call"

        for mult in atr_mults:
            sig_df = selected_signals.get((direction, mult), pd.DataFrame())
            if sig_df.empty:
                continue

            for delta in LONG_DELTAS:
                # Pre-gather all valid bars for this delta across all signal days
                # to avoid repeated lookups in the inner loop
                day_bars = {}
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
                    sig_entry = signal["entry_time"]
                    bars = all_bars[all_bars["timestamp"] >= sig_entry].copy().reset_index(drop=True)
                    if bars.empty:
                        continue
                    ep = bars.iloc[0]["open"]
                    if ep < args.min_premium:
                        continue
                    day_bars[date_str + "_" + str(signal.get("entry_time", ""))] = (bars, ep)

                if len(day_bars) < args.min_trades:
                    continue

                for pt, sl, te in iterproduct(LONG_TARGETS, LONG_STOPS, LONG_TIME_EXITS):
                    pnls = []
                    for key, (bars, ep) in day_bars.items():
                        result = simulate_long_option_trade(bars, ep, pt, sl, te)
                        pnls.append(result.get("pnl_pct", 0))

                    metrics = compute_metrics(pnls)
                    if metrics is None:
                        continue

                    metrics.update({
                        "direction": direction, "atr_mult": mult,
                        "strategy": product_type, "delta": delta,
                        "target": pt, "stop": sl, "time_exit": str(te),
                        "spread_short_d": None, "spread_long_d": None,
                    })
                    long_results.append(metrics)
                    combos_tested += 1

                    if combos_tested % 500 == 0:
                        print(f"  Tested {combos_tested} long combos...")

    print(f"  Total long combos scored: {len(long_results)}")

    # ═══════════════════════════════════════════════════════════════════════
    #  GRID SEARCH: CREDIT SPREADS
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  GRID SEARCH: CREDIT SPREADS")
    print(f"{'='*70}")

    spread_results = []
    combos_tested = 0

    for direction in directions:
        # Above VWAP: bear call spread (short call + long call, higher strike)
        # Below VWAP: bull put spread (short put + long put, lower strike)
        if direction == "above":
            short_side = "calls"   # short the higher-delta call
            long_side = "calls"    # long the lower-delta call (further OTM)
            spread_type = "bear_call_spread"
        else:
            short_side = "puts"    # short the higher-delta put
            long_side = "puts"     # long the lower-delta put (further OTM)
            spread_type = "bull_put_spread"

        for mult in atr_mults:
            sig_df = selected_signals.get((direction, mult), pd.DataFrame())
            if sig_df.empty:
                continue

            for short_delta, long_delta in SPREAD_PAIRS:
                # Pre-gather spread data for all signal days
                day_spreads = {}
                for _, signal in sig_df.iterrows():
                    date_str = str(signal["date"])
                    if date_str not in all_options_data:
                        continue
                    day_data = all_options_data[date_str]
                    opt_dict = getattr(day_data, short_side)

                    if short_delta not in opt_dict or long_delta not in opt_dict:
                        continue

                    short_info = opt_dict[short_delta]
                    long_info = opt_dict[long_delta]

                    short_all = short_info.get("all_bars", short_info["bars"])
                    long_all = long_info.get("all_bars", long_info["bars"])

                    sig_entry = signal["entry_time"]
                    short_bars = short_all[short_all["timestamp"] >= sig_entry].copy().reset_index(drop=True)
                    long_bars = long_all[long_all["timestamp"] >= sig_entry].copy().reset_index(drop=True)

                    if short_bars.empty or long_bars.empty:
                        continue

                    short_ep = short_bars.iloc[0]["open"]
                    long_ep = long_bars.iloc[0]["open"]
                    credit = short_ep - long_ep

                    if credit <= 0.02:  # Minimum credit of $0.02
                        continue

                    spread_width = abs(short_info["strike"] - long_info["strike"])
                    key = date_str + "_" + str(signal.get("entry_time", ""))
                    day_spreads[key] = (short_bars, long_bars, short_ep, long_ep, spread_width)

                if len(day_spreads) < args.min_trades:
                    continue

                for spt, ssl, ste in iterproduct(SPREAD_TARGETS, SPREAD_STOPS, SPREAD_TIME_EXITS):
                    pnls = []
                    for key, (sb, lb, sep, lep, sw) in day_spreads.items():
                        result = simulate_credit_spread_trade(
                            sb, lb, sep, lep, spt, ssl, ste, sw
                        )
                        # P&L as % of capital at risk (max loss = spread_width - credit)
                        credit = sep - lep
                        capital_at_risk = sw - credit if sw > credit else credit
                        if capital_at_risk > 0:
                            pnl_pct = result.get("pnl_dollar", 0) / capital_at_risk * 100
                        else:
                            pnl_pct = result.get("pnl_pct", 0)
                        pnls.append(pnl_pct)

                    metrics = compute_metrics(pnls)
                    if metrics is None:
                        continue

                    metrics.update({
                        "direction": direction, "atr_mult": mult,
                        "strategy": spread_type,
                        "delta": None,
                        "spread_short_d": short_delta, "spread_long_d": long_delta,
                        "target": spt, "stop": ssl, "time_exit": str(ste),
                    })
                    spread_results.append(metrics)
                    combos_tested += 1

                    if combos_tested % 500 == 0:
                        print(f"  Tested {combos_tested} spread combos...")

    print(f"  Total spread combos scored: {len(spread_results)}")

    # ═══════════════════════════════════════════════════════════════════════
    #  COMBINE & RANK RESULTS
    # ═══════════════════════════════════════════════════════════════════════
    all_results = long_results + spread_results

    if not all_results:
        print("\nNo results! Check data availability.")
        return

    df = pd.DataFrame(all_results)
    df = df.sort_values("score", ascending=False)

    # Save full results
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(config.RESULTS_DIR, f"grid_search_{ts}.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} results to {out_path}")

    elapsed = time.time() - start_time
    print(f"Elapsed: {elapsed / 60:.1f} minutes")

    # ── Print top results ──
    print(f"\n{'='*90}")
    print("  TOP 20 STRATEGIES BY SHARPE*sqrt(N)")
    print(f"{'='*90}")
    print(f"{'Rank':>4} {'Dir':>5} {'ATR':>4} {'Strategy':<20} {'Delta':>5} {'Spread':>10} "
          f"{'Tgt':>5} {'Stop':>5} {'Time':>5} | {'N':>4} {'WR%':>5} {'AvgPnL':>7} {'Sharpe':>7} {'Score':>7}")
    print("-" * 110)

    for i, row in df.head(20).iterrows():
        delta_str = f"{row['delta']:.2f}" if pd.notna(row['delta']) else "-"
        spread_str = (f"{row['spread_short_d']:.2f}/{row['spread_long_d']:.2f}"
                      if pd.notna(row['spread_short_d']) else "-")
        print(f"{df.index.get_loc(i)+1:>4} {row['direction']:>5} {row['atr_mult']:>4.1f} "
              f"{row['strategy']:<20} {delta_str:>5} {spread_str:>10} "
              f"{row['target']:>5.2f} {row['stop']:>5.1f} {str(row['time_exit']):>5} | "
              f"{row['n_trades']:>4.0f} {row['win_rate']:>5.1f} {row['avg_pnl']:>+7.2f} "
              f"{row['sharpe']:>7.3f} {row['score']:>7.2f}")

    # ── Print top for each direction ──
    for d in directions:
        print(f"\n  --- TOP 10 {d.upper()} VWAP ---")
        sub = df[df["direction"] == d].head(10)
        for i, row in sub.iterrows():
            delta_str = f"{row['delta']:.2f}" if pd.notna(row['delta']) else "-"
            spread_str = (f"{row['spread_short_d']:.2f}/{row['spread_long_d']:.2f}"
                          if pd.notna(row['spread_short_d']) else "-")
            print(f"  {row['strategy']:<20} d={delta_str:>5} sp={spread_str:>10} "
                  f"tgt={row['target']:.2f} stop={row['stop']:.1f} te={str(row['time_exit']):>5} | "
                  f"N={row['n_trades']:.0f} WR={row['win_rate']:.1f}% "
                  f"avg={row['avg_pnl']:+.2f}% sharpe={row['sharpe']:.3f}")

    # ── Print best long vs best spread ──
    print(f"\n{'='*70}")
    print("  BEST LONG OPTION vs BEST CREDIT SPREAD")
    print(f"{'='*70}")

    for strat_type in ["long_put", "long_call", "bear_call_spread", "bull_put_spread"]:
        sub = df[df["strategy"] == strat_type]
        if sub.empty:
            continue
        best = sub.iloc[0]
        delta_str = f"d={best['delta']:.2f}" if pd.notna(best['delta']) else ""
        spread_str = (f"short={best['spread_short_d']:.2f}/long={best['spread_long_d']:.2f}"
                      if pd.notna(best['spread_short_d']) else "")
        print(f"\n  {strat_type.upper()}: ATR {best['atr_mult']}x {best['direction']}")
        print(f"    {delta_str} {spread_str}")
        print(f"    Target={best['target']:.2f}, Stop={best['stop']:.1f}, Time={best['time_exit']}")
        print(f"    N={best['n_trades']:.0f}, WR={best['win_rate']:.1f}%, "
              f"Avg={best['avg_pnl']:+.2f}%, Sharpe={best['sharpe']:.3f}, "
              f"PF={best['profit_factor']:.2f}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
GRID SEARCH V2 — Credit Spreads with Fill-Realism
===================================================
Key improvements over v1:
  1. Minimum credit filter ($0.25/contract = $25/contract real money)
  2. Entry-bar skip fix in backtest_spreads.py (no same-bar exits)
  3. Wider delta pairs that actually collect premium
  4. Reports credit/width ratio for each combo
  5. Scores by Sharpe*sqrt(N) with min 5 trades

Usage:
    python run_grid_search_v2.py
    python run_grid_search_v2.py --min-credit 0.50
    python run_grid_search_v2.py --atr-range 0.7,0.8,0.9,1.0
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
from backtest_spreads import simulate_credit_spread_trade


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--atr-range", default="0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5",
                   help="Comma-separated ATR multipliers to test")
    p.add_argument("--min-credit", type=float, default=0.25,
                   help="Minimum net credit per contract ($). Filters out penny spreads.")
    p.add_argument("--min-trades", type=int, default=5,
                   help="Minimum trades for a combo to be scored")
    p.add_argument("--direction", default="both", choices=["above", "below", "both"])
    return p.parse_args()


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
        "score": sharpe * np.sqrt(n),
    }


def main():
    args = parse_args()
    start_time = time.time()

    atr_mults = [float(x.strip()) for x in args.atr_range.split(",")]
    directions = ["above", "below"] if args.direction == "both" else [args.direction]

    # ── Delta pairs: focus on WIDE spreads that collect real premium ──
    # (short_delta, long_delta) — wider gap = more credit
    SPREAD_PAIRS = [
        # Very wide (most credit, most risk)
        (0.50, 0.10), (0.50, 0.15), (0.50, 0.20), (0.50, 0.25), (0.50, 0.30),
        (0.50, 0.35), (0.50, 0.40),
        # Wide
        (0.40, 0.10), (0.40, 0.15), (0.40, 0.20), (0.40, 0.25), (0.40, 0.30),
        # Medium
        (0.35, 0.10), (0.35, 0.15), (0.35, 0.20), (0.35, 0.25),
        (0.30, 0.10), (0.30, 0.15), (0.30, 0.20),
        # Narrow
        (0.25, 0.10), (0.25, 0.15),
        (0.20, 0.10),
    ]

    SPREAD_TARGETS = [0.25, 0.50, 0.75, 0.90, 1.0]  # % of credit captured
    SPREAD_STOPS = [0.5, 1.0, 1.5, 2.0, 3.0]         # multiple of credit
    SPREAD_TIME_EXITS = [5, 10, 15, 30, 60, "EOD"]

    n_combos = len(SPREAD_PAIRS) * len(SPREAD_TARGETS) * len(SPREAD_STOPS) * len(SPREAD_TIME_EXITS)
    n_atr = len(atr_mults)
    n_dir = len(directions)

    print("=" * 70)
    print("  GRID SEARCH V2 — CREDIT SPREADS WITH CREDIT FILTER")
    print("=" * 70)
    print(f"  ATR levels: {atr_mults}")
    print(f"  Directions: {directions}")
    print(f"  Delta pairs: {len(SPREAD_PAIRS)}")
    print(f"  Exit combos: {len(SPREAD_TARGETS)} × {len(SPREAD_STOPS)} × {len(SPREAD_TIME_EXITS)} = "
          f"{len(SPREAD_TARGETS)*len(SPREAD_STOPS)*len(SPREAD_TIME_EXITS)}")
    print(f"  Total combos: {n_combos} × {n_atr} ATR × {n_dir} dir = {n_combos * n_atr * n_dir}")
    print(f"  Min credit: ${args.min_credit:.2f}/contract")
    print(f"  Min trades: {args.min_trades}")
    print(f"  Entry-bar skip: ENABLED (no same-bar exits)")
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

    selected_signals = {}
    for direction in directions:
        for mult in atr_mults:
            sig_df = signals_by_key.get((direction, mult), pd.DataFrame())
            if not sig_df.empty:
                selected_signals[(direction, mult)] = sig_df
                print(f"  {direction.upper()} {mult}x: {len(sig_df)} signals")

    # ── Pull options data ──
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
    #  GRID SEARCH
    # ═══════════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  SEARCHING CREDIT SPREADS")
    print(f"{'='*70}")

    all_results = []
    combos_tested = 0
    credit_filtered = 0

    for direction in directions:
        if direction == "above":
            option_side = "calls"
            spread_type = "bear_call_spread"
        else:
            option_side = "puts"
            spread_type = "bull_put_spread"

        for mult in atr_mults:
            sig_df = selected_signals.get((direction, mult), pd.DataFrame())
            if sig_df.empty:
                continue

            for short_delta, long_delta in SPREAD_PAIRS:
                # Pre-gather spread data, applying credit filter
                day_spreads = {}
                credits_collected = []
                filtered_out = 0

                for _, signal in sig_df.iterrows():
                    date_str = str(signal["date"])
                    if date_str not in all_options_data:
                        continue
                    day_data = all_options_data[date_str]
                    opt_dict = getattr(day_data, option_side)

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

                    # MINIMUM CREDIT FILTER
                    if credit < args.min_credit:
                        filtered_out += 1
                        credit_filtered += 1
                        continue

                    spread_width = abs(short_info["strike"] - long_info["strike"])
                    key = date_str + "_" + str(signal.get("entry_time", ""))
                    day_spreads[key] = (short_bars, long_bars, short_ep, long_ep, spread_width, credit)
                    credits_collected.append(credit)

                if len(day_spreads) < args.min_trades:
                    continue

                avg_credit = np.mean(credits_collected)
                avg_credit_ratio = np.mean([c / sw for (_, _, _, _, sw, c) in day_spreads.values() if sw > 0])

                for spt, ssl, ste in iterproduct(SPREAD_TARGETS, SPREAD_STOPS, SPREAD_TIME_EXITS):
                    pnls = []
                    dollar_pnls = []
                    for key, (sb, lb, sep, lep, sw, cr) in day_spreads.items():
                        result = simulate_credit_spread_trade(
                            sb, lb, sep, lep, spt, ssl, ste, sw
                        )
                        capital_at_risk = sw - cr if sw > cr else cr
                        if capital_at_risk > 0:
                            pnl_pct = result.get("pnl_dollar", 0) / capital_at_risk * 100
                        else:
                            pnl_pct = result.get("pnl_pct", 0)
                        pnls.append(pnl_pct)
                        dollar_pnls.append(result.get("pnl_dollar", 0))

                    metrics = compute_metrics(pnls)
                    if metrics is None:
                        continue

                    metrics.update({
                        "direction": direction, "atr_mult": mult,
                        "strategy": spread_type,
                        "spread_short_d": short_delta, "spread_long_d": long_delta,
                        "target": spt, "stop": ssl, "time_exit": str(ste),
                        "avg_credit": avg_credit,
                        "avg_credit_ratio": avg_credit_ratio,
                        "avg_dollar_pnl": np.mean(dollar_pnls),
                    })
                    all_results.append(metrics)
                    combos_tested += 1

                    if combos_tested % 1000 == 0:
                        print(f"  Tested {combos_tested} combos... ({credit_filtered} filtered for low credit)")

    print(f"\n  Total combos scored: {len(all_results)}")
    print(f"  Trades filtered for credit < ${args.min_credit}: {credit_filtered}")

    if not all_results:
        print("\nNo results! All trades filtered out. Try lowering --min-credit.")
        return

    df = pd.DataFrame(all_results)
    df = df.sort_values("score", ascending=False)

    # Save
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(config.RESULTS_DIR, f"grid_search_v2_{ts}.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} results to {out_path}")

    elapsed = time.time() - start_time
    print(f"Elapsed: {elapsed / 60:.1f} minutes")

    # ── Print top results ──
    print(f"\n{'='*100}")
    print("  TOP 25 STRATEGIES BY SHARPE*sqrt(N)  [min credit ${:.2f}]".format(args.min_credit))
    print(f"{'='*100}")
    print(f"{'Rank':>4} {'Dir':>5} {'ATR':>4} {'Spread':>10} "
          f"{'Tgt':>5} {'Stop':>5} {'Time':>5} | {'N':>4} {'WR%':>5} {'AvgPnL':>7} "
          f"{'Sharpe':>7} {'Score':>7} {'AvgCr$':>7} {'Cr/W%':>6}")
    print("-" * 110)

    for rank, (i, row) in enumerate(df.head(25).iterrows(), 1):
        spread_str = f"{row['spread_short_d']:.2f}/{row['spread_long_d']:.2f}"
        print(f"{rank:>4} {row['direction']:>5} {row['atr_mult']:>4.1f} "
              f"{spread_str:>10} "
              f"{row['target']:>5.2f} {row['stop']:>5.1f} {str(row['time_exit']):>5} | "
              f"{row['n_trades']:>4.0f} {row['win_rate']:>5.1f} {row['avg_pnl']:>+7.2f} "
              f"{row['sharpe']:>7.3f} {row['score']:>7.2f} "
              f"${row['avg_credit']:>5.2f} {row['avg_credit_ratio']*100:>5.1f}%")

    # Per direction
    for d in directions:
        print(f"\n  --- TOP 10 {d.upper()} VWAP ---")
        sub = df[df["direction"] == d].head(10)
        for rank, (i, row) in enumerate(sub.iterrows(), 1):
            spread_str = f"{row['spread_short_d']:.2f}/{row['spread_long_d']:.2f}"
            print(f"  {rank:>2}. {spread_str:>10} ATR={row['atr_mult']:.1f} "
                  f"tgt={row['target']:.2f} stop={row['stop']:.1f} te={str(row['time_exit']):>5} | "
                  f"N={row['n_trades']:.0f} WR={row['win_rate']:.1f}% "
                  f"avg={row['avg_pnl']:+.2f}% sharpe={row['sharpe']:.3f} "
                  f"cr=${row['avg_credit']:.2f} cr/w={row['avg_credit_ratio']*100:.1f}%")

    # ── Dollar P&L summary for top strategies ──
    print(f"\n{'='*70}")
    print("  DOLLAR P&L AT $100K RISK PER TRADE (top 5)")
    print(f"{'='*70}")
    for rank, (i, row) in enumerate(df.head(5).iterrows(), 1):
        spread_str = f"{row['spread_short_d']:.2f}/{row['spread_long_d']:.2f}"
        avg_dollar = row.get('avg_dollar_pnl', 0)
        # Estimate contracts: $100k / (avg_risk * 100)
        # avg_risk ≈ avg_credit / avg_credit_ratio - avg_credit (rough)
        print(f"  {rank}. {row['direction']:>5} {row['atr_mult']:.1f}x {spread_str} "
              f"tgt={row['target']:.0%} stop={row['stop']:.1f}x te={row['time_exit']} "
              f"| N={row['n_trades']:.0f} avg$/trade={avg_dollar:+.2f} cr=${row['avg_credit']:.2f}")


if __name__ == "__main__":
    main()

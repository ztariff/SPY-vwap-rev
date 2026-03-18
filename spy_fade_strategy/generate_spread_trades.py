#!/usr/bin/env python3
"""
Generate trades_data.json for CREDIT SPREAD strategies.
Uses the winning parameters from grid search:

  ABOVE VWAP (0.9x ATR): Bear call spread 0.40/0.30 delta, take 25% of credit, hold to EOD
  BELOW VWAP (1.1x ATR): Bull put spread 0.40/0.20 delta, take 50% of credit, stop 1x, exit 5 min

Also includes secondary strategies:
  BELOW VWAP (0.8x ATR): Bull put spread 0.25/0.15 delta, take 25%, stop 1.5x, exit 15 min
  ABOVE VWAP (0.7x ATR): Bear call spread 0.35/0.25 delta, take 25%, hold to EOD

Outputs trades_data.json for embedding into dashboard.html.

Usage:
    python generate_spread_trades.py
    python generate_spread_trades.py --strategies top2    # only the top strategy per direction
    python generate_spread_trades.py --strategies all     # all 4 strategies
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

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_options_for_signal_day, OptionsDayData
from backtest_spreads import simulate_credit_spread_trade


# ═══════════════════════════════════════════════════════════════════════════
#  STRATEGY DEFINITIONS (from grid search winners)
# ═══════════════════════════════════════════════════════════════════════════

# Minimum credit per contract — skip trades that don't collect enough premium
MIN_CREDIT = 0.25  # $25/contract minimum

STRATEGIES = {
    # ── Put Credit Spreads: sell puts when SPY dips below VWAP ──
    # Best Sharpe: 17 trades, 94% WR, avg credit $0.79, Sharpe 0.64
    "put_credit_0.30_0.20_0.5x": {
        "direction": "below",
        "spread_type": "put_credit_spread",
        "atr_mult": 0.5,
        "short_delta": 0.30,
        "long_delta": 0.20,
        "target": 0.50,       # take 50% of credit
        "stop": 3.0,          # wide stop
        "time_exit": "EOD",
        "label": "Put Credit 0.30/0.20d @ 0.5x ATR",
        "rank": 1,
    },
    # Higher trade count: 41 trades, 85% WR, avg credit $0.77
    "put_credit_0.35_0.20_0.5x": {
        "direction": "below",
        "spread_type": "put_credit_spread",
        "atr_mult": 0.5,
        "short_delta": 0.35,
        "long_delta": 0.20,
        "target": 0.25,
        "stop": 1.5,
        "time_exit": "EOD",
        "label": "Put Credit 0.35/0.20d @ 0.5x ATR",
        "rank": 2,
    },
    # Highest trade count: 72 trades, 81% WR, avg credit $0.60
    "put_credit_0.40_0.30_0.5x": {
        "direction": "below",
        "spread_type": "put_credit_spread",
        "atr_mult": 0.5,
        "short_delta": 0.40,
        "long_delta": 0.30,
        "target": 0.25,
        "stop": 1.0,
        "time_exit": "EOD",
        "label": "Put Credit 0.40/0.30d @ 0.5x ATR",
        "rank": 3,
    },
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--strategies", default="all", choices=["top2", "all"],
                   help="'top2' = best per direction, 'all' = all 4 strategies")
    return p.parse_args()


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

    if args.strategies == "top2":
        strat_keys = ["bear_call_0.40_0.30_0.9x", "bull_put_0.40_0.20_1.1x"]
    else:
        strat_keys = list(STRATEGIES.keys())

    active_strats = {k: STRATEGIES[k] for k in strat_keys}

    # Determine which ATR mults and directions we need
    needed_atr_mults = sorted(set(s["atr_mult"] for s in active_strats.values()))
    needed_directions = sorted(set(s["direction"] for s in active_strats.values()))

    print("=" * 60)
    print("  GENERATING CREDIT SPREAD DASHBOARD DATA")
    print("=" * 60)
    for k, s in active_strats.items():
        print(f"\n  [{s['rank']}] {s['label']}")
        print(f"      Target: {s['target']*100:.0f}% of credit, "
              f"Stop: {s['stop']}x credit, Time: {s['time_exit']}")
    print()

    # ── Load base data ──
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
        enriched, intraday_data, config.ATR_MULTIPLIER_RANGE, needed_directions
    )

    # Collect selected signals per strategy
    strat_signals = {}
    for strat_key, strat in active_strats.items():
        mult = strat["atr_mult"]
        direction = strat["direction"]
        sig_df = signals_by_key.get((direction, mult), pd.DataFrame())
        if not sig_df.empty:
            strat_signals[strat_key] = sig_df
            print(f"  {strat['label']}: {len(sig_df)} signals")

    # ── Pull options data ──
    unique_days = {}
    for strat_key, sig_df in strat_signals.items():
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
            print(f"    [{i + 1}/{len(unique_days)}]...")
        try:
            day_data = pull_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options_data[date_str] = day_data
        except Exception as e:
            print(f"    ERROR {date_str}: {e}")
            all_options_data[date_str] = OptionsDayData(date_str, info["spot"], info["entry_time"])

    # ── Simulate spread trades ──
    print("\nSimulating credit spread trades...")
    all_trades = []

    for strat_key, strat in active_strats.items():
        if strat_key not in strat_signals:
            print(f"  {strat['label']}: NO SIGNALS")
            continue

        sig_df = strat_signals[strat_key]
        direction = strat["direction"]

        # For spreads: above = bear call (short calls), below = bull put (short puts)
        if direction == "above":
            option_side = "calls"
        else:
            option_side = "puts"

        short_delta = strat["short_delta"]
        long_delta = strat["long_delta"]
        target = strat["target"]
        stop = strat["stop"]
        time_exit = strat["time_exit"]

        trade_count = 0
        skip_count = 0

        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in all_options_data:
                continue

            day_data = all_options_data[date_str]
            opt_dict = getattr(day_data, option_side)

            # Need both deltas
            if short_delta not in opt_dict or long_delta not in opt_dict:
                skip_count += 1
                continue

            short_info = opt_dict[short_delta]
            long_info = opt_dict[long_delta]

            # Re-slice bars to THIS signal's entry time
            sig_entry_time = signal["entry_time"]

            short_all = short_info.get("all_bars", short_info["bars"])
            long_all = long_info.get("all_bars", long_info["bars"])

            short_bars = short_all[short_all["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)
            long_bars = long_all[long_all["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)

            if short_bars.empty or long_bars.empty:
                skip_count += 1
                continue

            short_entry = short_bars.iloc[0]["open"]
            long_entry = long_bars.iloc[0]["open"]
            credit = short_entry - long_entry

            if credit < MIN_CREDIT:
                skip_count += 1
                continue

            spread_width = abs(short_info["strike"] - long_info["strike"])

            result = simulate_credit_spread_trade(
                short_bars, long_bars, short_entry, long_entry,
                target, stop, time_exit, spread_width
            )

            # Get exit time
            bars_held = result.get("bars_held", 0)
            exit_idx = max(0, min(bars_held - 1, len(short_bars) - 1)) if bars_held > 0 else 0
            exit_bar = short_bars.iloc[exit_idx]

            trade_entry = {
                "date": date_str,
                "direction": direction,
                "product": strat["spread_type"],
                "strategy_key": strat_key,
                "strategy_label": strat["label"],
                "atr_mult": float(strat["atr_mult"]),
                # Spread deltas
                "short_delta": float(short_delta),
                "long_delta": float(long_delta),
                "short_strike": float(short_info["strike"]),
                "long_strike": float(long_info["strike"]),
                "spread_width": float(spread_width),
                # Tickers for charts
                "short_ticker": short_info.get("ticker"),
                "long_ticker": long_info.get("ticker"),
                # SPY at signal
                "spy_entry_price": float(signal["entry_price"]),
                "entry_time": ts_to_timestr(signal["entry_time"]),
                "entry_time_iso": ts_to_iso(signal["entry_time"]),
                # Spread pricing
                "short_entry_price": float(short_entry),
                "long_entry_price": float(long_entry),
                "credit_received": float(credit),
                "exit_spread_value": float(result.get("exit_spread_value", credit)),
                "exit_time": ts_to_timestr(exit_bar["timestamp"]),
                "exit_time_iso": ts_to_iso(exit_bar["timestamp"]),
                # P&L
                "pnl_pct": float(result.get("pnl_on_risk", result.get("pnl_pct", 0))),
                "pnl_dollar": float(result.get("pnl_dollar", 0)),
                "exit_reason": result.get("exit_reason", "unknown"),
                "minutes_held": float(result.get("minutes_held", 0)),
                # Exit params
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

        print(f"  {strat['label']}: {trade_count} trades "
              f"({skip_count} skipped, missing deltas or low credit)")

    all_trades.sort(key=lambda t: t["date"])

    # ── Save ──
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades_data.json")
    with open(output_path, "w") as f:
        json.dump(all_trades, f, indent=2, default=str)

    elapsed = time.time() - start_time
    print(f"\nSaved {len(all_trades)} spread trades to {output_path}")
    print(f"Elapsed: {elapsed / 60:.1f} minutes")

    # ── Summary ──
    if all_trades:
        pnls = [t["pnl_pct"] for t in all_trades]
        wins = sum(1 for p in pnls if p > 0)
        pnl_std = np.std(pnls)
        sharpe = np.mean(pnls) / pnl_std if pnl_std > 0 else 0

        print(f"\n{'=' * 60}")
        print(f"  CREDIT SPREAD RESULTS SUMMARY")
        print(f"{'=' * 60}")
        print(f"  Total trades: {len(all_trades)}")
        print(f"  Win rate: {wins / len(all_trades) * 100:.1f}%")
        print(f"  Avg P&L (on risk): {np.mean(pnls):+.2f}%")
        print(f"  Total P&L: {sum(pnls):+.2f}%")
        print(f"  Sharpe: {sharpe:.3f}")

        # Per-strategy breakdown
        for strat_key in strat_keys:
            st = [t for t in all_trades if t["strategy_key"] == strat_key]
            if st:
                sp = [t["pnl_pct"] for t in st]
                sw = sum(1 for p in sp if p > 0)
                s_std = np.std(sp)
                s_sharpe = np.mean(sp) / s_std if s_std > 0 else 0
                sd = [t["pnl_dollar"] for t in st]
                print(f"\n  [{STRATEGIES[strat_key]['rank']}] {STRATEGIES[strat_key]['label']}:")
                print(f"      N={len(st)}, WR={sw/len(st)*100:.1f}%, "
                      f"Avg={np.mean(sp):+.2f}%, Sharpe={s_sharpe:.3f}")
                print(f"      Avg credit: ${np.mean([t['credit_received'] for t in st]):.2f}, "
                      f"Avg $ P&L: ${np.mean(sd):+.2f}")

    # Embed into dashboard
    print(f"\n  Now run: python embed_dashboard.py trades_data.json")


if __name__ == "__main__":
    main()

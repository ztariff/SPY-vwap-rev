#!/usr/bin/env python3
"""
Multi-Signal Credit Spread Trade Generator
============================================
Runs ALL signal generators (VWAP, RSI(2), ORB Failure, Bollinger, Volume Spike)
through the SAME credit spread pipeline.

Per CLAUDE.md:
  - Never fabricate data — all prices from real Polygon bars
  - Never use theoretical pricing — all options P&L from real market data
  - Be thorough — test every signal type × every spread config
  - Surface problems — report skipped trades, missing data, attrition

Usage:
    python generate_spread_trades_multi.py
    python generate_spread_trades_multi.py --signal-only   # Just scan signals, no options
    python generate_spread_trades_multi.py --vwap-only     # Only VWAP signals (original behavior)
"""

import sys
import os
import json
import argparse
import time
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data, calculate_session_vwap
from signal_generator import generate_all_signals as generate_vwap_signals
from signal_generator_v2 import generate_all_v2_signals
from options_data import pull_options_for_signal_day, OptionsDayData
from backtest_spreads import simulate_credit_spread_trade


# ═══════════════════════════════════════════════════════════════════════════
#  SPREAD STRATEGY CONFIGS
# ═══════════════════════════════════════════════════════════════════════════

# Minimum credit per contract
MIN_CREDIT = 0.25

# Spread configs to test against ALL signal types
# These are the configs that showed edge on VWAP signals — testing if they
# generalize to other mean-reversion entry signals.
SPREAD_CONFIGS = [
    # ── Bull Put Spreads (for "below" / long signals) ──
    {
        "name": "put_credit_0.30_0.20",
        "direction": "below",
        "spread_type": "put_credit_spread",
        "short_delta": 0.30,
        "long_delta": 0.20,
        "target": 0.50,
        "stop": 3.0,
        "time_exit": "EOD",
    },
    {
        "name": "put_credit_0.35_0.20",
        "direction": "below",
        "spread_type": "put_credit_spread",
        "short_delta": 0.35,
        "long_delta": 0.20,
        "target": 0.25,
        "stop": 1.5,
        "time_exit": "EOD",
    },
    {
        "name": "put_credit_0.40_0.30",
        "direction": "below",
        "spread_type": "put_credit_spread",
        "short_delta": 0.40,
        "long_delta": 0.30,
        "target": 0.25,
        "stop": 1.0,
        "time_exit": "EOD",
    },
    # ── Bear Call Spreads (for "above" / short signals) ──
    {
        "name": "call_credit_0.35_0.25",
        "direction": "above",
        "spread_type": "bear_call_spread",
        "short_delta": 0.35,
        "long_delta": 0.25,
        "target": 0.25,
        "stop": 1.5,
        "time_exit": "EOD",
    },
    {
        "name": "call_credit_0.40_0.30",
        "direction": "above",
        "spread_type": "bear_call_spread",
        "short_delta": 0.40,
        "long_delta": 0.30,
        "target": 0.25,
        "stop": 1.0,
        "time_exit": "EOD",
    },
]


def parse_args():
    p = argparse.ArgumentParser(description="Multi-signal credit spread trade generator")
    p.add_argument("--signal-only", action="store_true",
                   help="Only scan signals, skip options/spread simulation")
    p.add_argument("--vwap-only", action="store_true",
                   help="Only use VWAP signals (original behavior)")
    p.add_argument("--v2-only", action="store_true",
                   help="Only use v2 signals (RSI, ORB, BB, VolSpike)")
    p.add_argument("--cache-only", action="store_true", default=True,
                   help="Only use cached data, never hit Polygon API (default: True)")
    p.add_argument("--fetch-new", action="store_true",
                   help="Allow fetching new data from Polygon API for uncached dates")
    p.add_argument("--output", default="trades_data_multi.json",
                   help="Output filename (default: trades_data_multi.json)")
    return p.parse_args()


def ts_to_iso(ts):
    if ts is None:
        return None
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def ts_to_timestr(ts):
    if ts is None:
        return None
    return ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)


def collect_all_signals(enriched_daily, intraday_data_dict, vwap_only=False, v2_only=False):
    """
    Run all signal generators and collect into a unified format.

    Returns list of (signal_type_label, direction, signal_df) tuples.
    """
    all_signal_sets = []

    if not v2_only:
        # ── VWAP Signals (original) ──
        print("\n" + "=" * 60)
        print("  VWAP DEVIATION SIGNALS (original)")
        print("=" * 60)
        vwap_signals = generate_vwap_signals(
            enriched_daily, intraday_data_dict,
            config.ATR_MULTIPLIER_RANGE, config.DIRECTIONS
        )
        for (direction, mult), sig_df in vwap_signals.items():
            if not sig_df.empty:
                sig_df = sig_df.copy()
                sig_df["signal_type"] = f"vwap_{mult}x"
                all_signal_sets.append((f"vwap_{mult}x", direction, sig_df))

    if not vwap_only:
        # ── v2 Signals (RSI, ORB, BB, VolSpike) ──
        v2_signals = generate_all_v2_signals(enriched_daily, intraday_data_dict)
        for (direction, label), sig_df in v2_signals.items():
            if not sig_df.empty:
                sig_df = sig_df.copy()
                if "signal_type" not in sig_df.columns:
                    sig_df["signal_type"] = label
                all_signal_sets.append((label, direction, sig_df))

    return all_signal_sets


def deduplicate_signals_by_date(signal_sets):
    """
    For the same direction on the same date, keep only ONE signal
    (the earliest entry_time). This prevents double-counting when
    multiple signal generators fire on the same day.

    Returns deduplicated list of (label, direction, sig_df).
    """
    # Group by (date, direction) → keep earliest
    seen = {}  # (date, direction) → (entry_time, label, row_dict)

    all_rows = []
    for label, direction, sig_df in signal_sets:
        for _, row in sig_df.iterrows():
            date = row["date"]
            entry_time = row["entry_time"]
            key = (str(date), direction)

            if key not in seen or entry_time < seen[key][0]:
                seen[key] = (entry_time, label, row.to_dict())
                # Track which label won
                seen[key] = (entry_time, label, row.to_dict())

    # Rebuild signal sets grouped by (direction, label)
    grouped = defaultdict(list)
    for (date_str, direction), (et, label, row_dict) in seen.items():
        grouped[(direction, label)].append(row_dict)

    result = []
    for (direction, label), rows in grouped.items():
        df = pd.DataFrame(rows)
        result.append((label, direction, df))

    return result


def run_spread_simulation(signal_sets, spread_configs, fetcher, enriched_daily):
    """
    For each signal set × compatible spread config, simulate credit spread trades.

    Returns list of trade dicts.
    """
    # First, collect ALL unique signal dates+times across all sets
    unique_days = {}
    for label, direction, sig_df in signal_sets:
        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in unique_days:
                unique_days[date_str] = {
                    "spot": signal["entry_price"],
                    "entry_time": signal["entry_time"],
                }
            else:
                # If multiple signals on same day, use earliest entry time
                if signal["entry_time"] < unique_days[date_str]["entry_time"]:
                    unique_days[date_str]["entry_time"] = signal["entry_time"]

    print(f"\n  Pulling options for {len(unique_days)} unique signal days...")
    all_options = {}
    for i, (date_str, info) in enumerate(sorted(unique_days.items())):
        if (i + 1) % 25 == 0:
            print(f"    [{i+1}/{len(unique_days)}]...")
        try:
            day_data = pull_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options[date_str] = day_data
        except Exception as e:
            print(f"    ERROR {date_str}: {e}")
            all_options[date_str] = OptionsDayData(date_str, info["spot"], info["entry_time"])

    # Now simulate trades
    print("\n  Simulating credit spread trades across all signal types...")
    all_trades = []
    stats = defaultdict(lambda: {"trades": 0, "skipped": 0, "signals": 0})

    for label, direction, sig_df in signal_sets:
        # Find compatible spread configs for this direction
        compatible_configs = [c for c in spread_configs if c["direction"] == direction]
        if not compatible_configs:
            continue

        for sc in compatible_configs:
            option_side = "calls" if direction == "above" else "puts"
            short_delta = sc["short_delta"]
            long_delta = sc["long_delta"]
            stat_key = f"{label} → {sc['name']}"

            for _, signal in sig_df.iterrows():
                stats[stat_key]["signals"] += 1
                date_str = str(signal["date"])

                if date_str not in all_options:
                    stats[stat_key]["skipped"] += 1
                    continue

                day_data = all_options[date_str]
                opt_dict = getattr(day_data, option_side)

                if short_delta not in opt_dict or long_delta not in opt_dict:
                    stats[stat_key]["skipped"] += 1
                    continue

                short_info = opt_dict[short_delta]
                long_info = opt_dict[long_delta]

                sig_entry_time = signal["entry_time"]
                short_all = short_info.get("all_bars", short_info["bars"])
                long_all = long_info.get("all_bars", long_info["bars"])

                short_bars = short_all[short_all["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)
                long_bars = long_all[long_all["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)

                if short_bars.empty or long_bars.empty:
                    stats[stat_key]["skipped"] += 1
                    continue

                short_entry = short_bars.iloc[0]["open"]
                long_entry = long_bars.iloc[0]["open"]
                credit = short_entry - long_entry

                if credit < MIN_CREDIT:
                    stats[stat_key]["skipped"] += 1
                    continue

                spread_width = abs(short_info["strike"] - long_info["strike"])

                # CR ≥ 15% filter — credit ratio is the strongest edge predictor
                # (see filter_impact.html analysis: Sharpe 3.3 → 7.5, losses -78%)
                if spread_width > 0 and (credit / spread_width) < 0.15:
                    stats[stat_key]["skipped"] += 1
                    continue

                result = simulate_credit_spread_trade(
                    short_bars, long_bars, short_entry, long_entry,
                    sc["target"], sc["stop"], sc["time_exit"], spread_width
                )

                bars_held = result.get("bars_held", 0)
                exit_idx = max(0, min(bars_held - 1, len(short_bars) - 1)) if bars_held > 0 else 0
                exit_bar = short_bars.iloc[exit_idx]

                trade = {
                    "date": date_str,
                    "direction": direction,
                    "product": sc["spread_type"],
                    "signal_type": label,
                    "strategy_key": f"{label}_{sc['name']}",
                    "strategy_label": f"{label} → {sc['name']}",
                    "atr_mult": 0,
                    "short_delta": float(short_delta),
                    "long_delta": float(long_delta),
                    "short_strike": float(short_info["strike"]),
                    "long_strike": float(long_info["strike"]),
                    "spread_width": float(spread_width),
                    "short_ticker": short_info.get("ticker"),
                    "long_ticker": long_info.get("ticker"),
                    "spy_entry_price": float(signal["entry_price"]),
                    "entry_time": ts_to_timestr(signal["entry_time"]),
                    "entry_time_iso": ts_to_iso(signal["entry_time"]),
                    "short_entry_price": float(short_entry),
                    "long_entry_price": float(long_entry),
                    "credit_received": float(credit),
                    "credit_ratio": float(credit / spread_width) if spread_width > 0 else 0,
                    "exit_spread_value": float(result.get("exit_spread_value", credit)),
                    "exit_time": ts_to_timestr(exit_bar["timestamp"]),
                    "exit_time_iso": ts_to_iso(exit_bar["timestamp"]),
                    "pnl_pct": float(result.get("pnl_on_risk", result.get("pnl_pct", 0))),
                    "pnl_dollar": float(result.get("pnl_dollar", 0)),
                    "exit_reason": result.get("exit_reason", "unknown"),
                    "minutes_held": float(result.get("minutes_held", 0)),
                    "target_pct": float(sc["target"]),
                    "stop_pct": float(sc["stop"]),
                    "time_exit": str(sc["time_exit"]),
                    "vix": signal.get("vix_regime", None),
                    "consecutive_up": int(signal.get("consecutive_up", 0))
                        if pd.notna(signal.get("consecutive_up", 0)) else 0,
                    "gap_pct": float(signal.get("gap_pct", 0))
                        if pd.notna(signal.get("gap_pct", 0)) else None,
                }
                all_trades.append(trade)
                stats[stat_key]["trades"] += 1

    # Print attrition stats
    print(f"\n  Pipeline Attrition Report:")
    for stat_key in sorted(stats.keys()):
        s = stats[stat_key]
        print(f"    {stat_key}: {s['signals']} signals → {s['trades']} trades "
              f"({s['skipped']} skipped)")

    return all_trades


def print_summary(all_trades):
    """Print comprehensive results summary."""
    if not all_trades:
        print("\n  NO TRADES GENERATED")
        return

    print(f"\n{'=' * 70}")
    print(f"  MULTI-SIGNAL CREDIT SPREAD RESULTS")
    print(f"{'=' * 70}")

    pnls = [t["pnl_pct"] for t in all_trades]
    wins = sum(1 for p in pnls if p > 0)
    pnl_std = np.std(pnls) if len(pnls) > 1 else 0
    sharpe = np.mean(pnls) / pnl_std if pnl_std > 0 else 0

    print(f"\n  OVERALL:")
    print(f"    Total trades: {len(all_trades)}")
    print(f"    Win rate: {wins / len(all_trades) * 100:.1f}%")
    print(f"    Avg P&L (on risk): {np.mean(pnls):+.2f}%")
    print(f"    Sharpe: {sharpe:.3f}")

    # Per signal type
    signal_types = sorted(set(t["signal_type"] for t in all_trades))
    print(f"\n  BY SIGNAL TYPE:")
    for st in signal_types:
        st_trades = [t for t in all_trades if t["signal_type"] == st]
        st_pnls = [t["pnl_pct"] for t in st_trades]
        st_wins = sum(1 for p in st_pnls if p > 0)
        st_std = np.std(st_pnls) if len(st_pnls) > 1 else 0
        st_sharpe = np.mean(st_pnls) / st_std if st_std > 0 else 0
        st_wr = st_wins / len(st_trades) * 100 if st_trades else 0
        print(f"    {st}: N={len(st_trades)}, WR={st_wr:.1f}%, "
              f"Avg={np.mean(st_pnls):+.2f}%, Sharpe={st_sharpe:.3f}")

    # Per direction
    print(f"\n  BY DIRECTION:")
    for direction in ["below", "above"]:
        dir_trades = [t for t in all_trades if t["direction"] == direction]
        if not dir_trades:
            continue
        dir_pnls = [t["pnl_pct"] for t in dir_trades]
        dir_wins = sum(1 for p in dir_pnls if p > 0)
        dir_std = np.std(dir_pnls) if len(dir_pnls) > 1 else 0
        dir_sharpe = np.mean(dir_pnls) / dir_std if dir_std > 0 else 0
        dir_label = "BELOW (bull puts)" if direction == "below" else "ABOVE (bear calls)"
        print(f"    {dir_label}: N={len(dir_trades)}, "
              f"WR={dir_wins / len(dir_trades) * 100:.1f}%, "
              f"Avg={np.mean(dir_pnls):+.2f}%, Sharpe={dir_sharpe:.3f}")

    # Credit ratio analysis
    print(f"\n  CREDIT RATIO ANALYSIS:")
    for threshold in [0.10, 0.12, 0.15, 0.20]:
        high_cr = [t for t in all_trades
                   if t["spread_width"] > 0 and t["credit_received"] / t["spread_width"] >= threshold]
        if high_cr:
            hc_pnls = [t["pnl_pct"] for t in high_cr]
            hc_wins = sum(1 for p in hc_pnls if p > 0)
            print(f"    CR ≥ {threshold*100:.0f}%: N={len(high_cr)}, "
                  f"WR={hc_wins / len(high_cr) * 100:.1f}%, "
                  f"Avg={np.mean(hc_pnls):+.2f}%")

    # Gap analysis
    print(f"\n  GAP ANALYSIS:")
    gap_down = [t for t in all_trades if t.get("gap_pct") is not None and t["gap_pct"] < -0.2]
    gap_other = [t for t in all_trades if t.get("gap_pct") is not None and t["gap_pct"] >= -0.2]
    if gap_down:
        gd_pnls = [t["pnl_pct"] for t in gap_down]
        gd_wins = sum(1 for p in gd_pnls if p > 0)
        print(f"    Gap < -0.2%: N={len(gap_down)}, WR={gd_wins/len(gap_down)*100:.1f}%, "
              f"Avg={np.mean(gd_pnls):+.2f}%")
    if gap_other:
        go_pnls = [t["pnl_pct"] for t in gap_other]
        go_wins = sum(1 for p in go_pnls if p > 0)
        print(f"    Gap >= -0.2%: N={len(gap_other)}, WR={go_wins/len(gap_other)*100:.1f}%, "
              f"Avg={np.mean(go_pnls):+.2f}%")


def main():
    args = parse_args()
    start_time = time.time()

    print("=" * 70)
    print("  MULTI-SIGNAL CREDIT SPREAD GENERATOR")
    print("=" * 70)
    mode = "VWAP only" if args.vwap_only else ("v2 only" if args.v2_only else "ALL signals")
    print(f"  Mode: {mode}")
    if args.signal_only:
        print(f"  Signal scan only (no options/spread sim)")
    print()

    # ── Determine cache mode ──
    use_cache_only = args.cache_only and not args.fetch_new
    if use_cache_only:
        print("  Mode: CACHE-ONLY (no Polygon API calls for uncached data)")

    # ── Load base data ──
    print("Loading base data...")
    fetcher = PolygonFetcher(cache_only=use_cache_only)
    spy_daily = fetcher.get_daily_bars(config.TICKER, config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars(config.TLT_TICKER, config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]

    print(f"  Loading intraday bars for {len(valid_dates)} trading days...")
    intraday_data = fetcher.get_intraday_bars_bulk(config.TICKER, valid_dates)
    print(f"  Loaded {len(intraday_data)} days of 1-min bars from cache")

    # ── Generate signals ──
    signal_sets = collect_all_signals(
        enriched, intraday_data,
        vwap_only=args.vwap_only,
        v2_only=args.v2_only
    )

    # Print signal summary
    total_signals = sum(len(df) for _, _, df in signal_sets)
    unique_dates = set()
    for _, _, df in signal_sets:
        unique_dates.update(str(d) for d in df["date"])
    print(f"\n  Total raw signals: {total_signals} across {len(unique_dates)} unique dates "
          f"(out of {len(intraday_data)} trading days)")

    if args.signal_only:
        # Save signal summary and exit
        signal_summary = []
        for label, direction, sig_df in signal_sets:
            signal_summary.append({
                "signal_type": label,
                "direction": direction,
                "count": len(sig_df),
                "first_date": str(sig_df["date"].min()) if not sig_df.empty else None,
                "last_date": str(sig_df["date"].max()) if not sig_df.empty else None,
            })
        summary_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "signal_summary_v2.json")
        with open(summary_path, "w") as f:
            json.dump(signal_summary, f, indent=2, default=str)
        print(f"\n  Signal summary saved to {summary_path}")
        elapsed = time.time() - start_time
        print(f"  Elapsed: {elapsed:.1f}s")
        return

    # ── Deduplicate signals (same date+direction → keep earliest) ──
    deduped = deduplicate_signals_by_date(signal_sets)
    deduped_total = sum(len(df) for _, _, df in deduped)
    print(f"\n  After dedup (1 signal per date×direction): {deduped_total} signals")

    # ── Simulate spreads ──
    all_trades = run_spread_simulation(deduped, SPREAD_CONFIGS, fetcher, enriched)
    all_trades.sort(key=lambda t: t["date"])

    # ── Save ──
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output)
    with open(output_path, "w") as f:
        json.dump(all_trades, f, indent=2, default=str)

    elapsed = time.time() - start_time
    print(f"\n  Saved {len(all_trades)} trades to {output_path}")
    print(f"  Elapsed: {elapsed / 60:.1f} minutes")

    # ── Summary ──
    print_summary(all_trades)

    print(f"\n  To embed in dashboard: python embed_dashboard.py {args.output}")


if __name__ == "__main__":
    main()

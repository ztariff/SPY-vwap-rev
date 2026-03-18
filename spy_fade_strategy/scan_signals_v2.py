#!/usr/bin/env python3
"""
Quick Signal Scanner: Count signals from ALL generators using cached data.
No options pulling, no spread simulation — just see how many signals each
generator produces and on which dates.

This is a fast diagnostic to run before the full pipeline.

Usage:
    python scan_signals_v2.py
"""

import sys
import os
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals as generate_vwap_signals
from signal_generator_v2 import generate_all_v2_signals


def main():
    start_time = time.time()

    print("=" * 60)
    print("  MULTI-SIGNAL SCANNER (signal counts only)")
    print("=" * 60)

    # Load base data
    print("\nLoading base data...")
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars(config.TICKER, config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars(config.TLT_TICKER, config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]

    print(f"Loading intraday bars for {len(valid_dates)} trading days...")
    intraday_data = fetcher.get_intraday_bars_bulk(config.TICKER, valid_dates)
    print(f"Loaded {len(intraday_data)} days of 1-min bars\n")

    total_days = len(intraday_data)

    # ── VWAP Signals ──
    print("=" * 60)
    print("  VWAP DEVIATION SIGNALS")
    print("=" * 60)
    vwap_signals = generate_vwap_signals(
        enriched, intraday_data,
        [0.5, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2],  # Key ATR levels only
        config.DIRECTIONS
    )

    vwap_dates = set()
    for (direction, mult), sig_df in vwap_signals.items():
        if not sig_df.empty:
            vwap_dates.update(str(d) for d in sig_df["date"])

    # ── v2 Signals ──
    v2_signals = generate_all_v2_signals(enriched, intraday_data)

    # ── Combined Summary ──
    print(f"\n{'=' * 60}")
    print(f"  COMBINED SIGNAL COVERAGE")
    print(f"{'=' * 60}")

    all_dates_below = set()
    all_dates_above = set()

    print(f"\n  BELOW VWAP / LONG signals:")
    for key, sig_df in sorted({**{k: v for k, v in vwap_signals.items()}, **v2_signals}.items(),
                               key=lambda x: -len(x[1]) if not x[1].empty else 0):
        direction = key[0]
        label = key[1] if isinstance(key[1], str) else f"vwap_{key[1]}x"
        if direction != "below" or sig_df.empty:
            continue
        dates = set(str(d) for d in sig_df["date"])
        if direction == "below":
            all_dates_below.update(dates)
        print(f"    {label}: {len(sig_df)} signals ({len(dates)} unique dates, "
              f"{len(dates)/total_days*100:.1f}% of days)")

    print(f"\n  ABOVE VWAP / SHORT signals:")
    for key, sig_df in sorted({**{k: v for k, v in vwap_signals.items()}, **v2_signals}.items(),
                               key=lambda x: -len(x[1]) if not x[1].empty else 0):
        direction = key[0]
        label = key[1] if isinstance(key[1], str) else f"vwap_{key[1]}x"
        if direction != "above" or sig_df.empty:
            continue
        dates = set(str(d) for d in sig_df["date"])
        if direction == "above":
            all_dates_above.update(dates)
        print(f"    {label}: {len(sig_df)} signals ({len(dates)} unique dates, "
              f"{len(dates)/total_days*100:.1f}% of days)")

    all_dates = all_dates_below | all_dates_above
    print(f"\n  COVERAGE:")
    print(f"    BELOW/LONG: {len(all_dates_below)} unique dates ({len(all_dates_below)/total_days*100:.1f}% of days)")
    print(f"    ABOVE/SHORT: {len(all_dates_above)} unique dates ({len(all_dates_above)/total_days*100:.1f}% of days)")
    print(f"    COMBINED: {len(all_dates)} unique dates ({len(all_dates)/total_days*100:.1f}% of days)")
    print(f"    Total trading days: {total_days}")

    # ── Date Overlap Analysis ──
    print(f"\n  OVERLAP ANALYSIS (dates with multiple signal types):")

    # For below direction
    below_by_date = defaultdict(list)
    for key, sig_df in {**{k: v for k, v in vwap_signals.items()}, **v2_signals}.items():
        direction = key[0]
        label = key[1] if isinstance(key[1], str) else f"vwap_{key[1]}x"
        if direction != "below" or sig_df.empty:
            continue
        for d in sig_df["date"]:
            below_by_date[str(d)].append(label)

    multi_signal_days = {d: sigs for d, sigs in below_by_date.items() if len(sigs) >= 2}
    print(f"    BELOW days with 2+ signal types: {len(multi_signal_days)}")
    if multi_signal_days:
        # Show most common combos
        combos = defaultdict(int)
        for d, sigs in multi_signal_days.items():
            combo = " + ".join(sorted(set(sigs)))
            combos[combo] += 1
        for combo, count in sorted(combos.items(), key=lambda x: -x[1])[:5]:
            print(f"      {combo}: {count} days")

    elapsed = time.time() - start_time
    print(f"\n  Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()

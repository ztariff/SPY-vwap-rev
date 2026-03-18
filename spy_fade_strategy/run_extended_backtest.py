#!/usr/bin/env python3
"""
EXTENDED BACKTEST — Two validation tasks:
1. SPY stock short-above-VWAP extended to 2018-2026 (was 2022-2026, only 13 trades)
2. IWM + DIA cross-instrument VWAP deviation for short-above and long-below

Uses the existing pipeline modules with config patching.
"""

import sys
import os
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime, date
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── CONFIG SETUP ────────────────────────────────────────────────────────
# We'll patch config dynamically for each ticker/date range

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from backtest_stock import run_stock_backtest, simulate_stock_trade

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_extended")
os.makedirs(RESULTS_DIR, exist_ok=True)


def compute_metrics(trades_df):
    """Compute standard metrics from a trades DataFrame."""
    if trades_df.empty:
        return {}
    n = len(trades_df)
    winners = trades_df[trades_df["pnl_pct"] > 0]
    losers = trades_df[trades_df["pnl_pct"] <= 0]
    wr = len(winners) / n * 100 if n > 0 else 0
    avg = trades_df["pnl_pct"].mean()
    med = trades_df["pnl_pct"].median()
    total = trades_df["pnl_pct"].sum()
    avg_w = winners["pnl_pct"].mean() if len(winners) > 0 else 0
    avg_l = losers["pnl_pct"].mean() if len(losers) > 0 else 0
    gross_w = winners["pnl_pct"].sum() if len(winners) > 0 else 0
    gross_l = abs(losers["pnl_pct"].sum()) if len(losers) > 0 else 0.0001
    pf = gross_w / gross_l if gross_l > 0 else float('inf')

    # Sharpe (per-trade)
    std = trades_df["pnl_pct"].std()
    sharpe = avg / std if std > 0 else 0

    return {
        "n": n, "win_rate": wr, "avg_pnl": avg, "median_pnl": med,
        "total_pnl": total, "sharpe": sharpe, "profit_factor": pf,
        "avg_winner": avg_w, "avg_loser": avg_l,
    }


def run_pipeline(ticker, start, end, directions, atr_mults):
    """Run the full data-fetch → enrich → signal pipeline for a ticker."""
    # Temporarily patch config
    orig_ticker = config.TICKER
    orig_start = config.BACKTEST_START
    orig_end = config.BACKTEST_END
    config.TICKER = ticker
    config.BACKTEST_START = start
    config.BACKTEST_END = end

    try:
        fetcher = PolygonFetcher()
        daily = fetcher.get_daily_bars(ticker, start, end)
        if daily.empty:
            print(f"  ERROR: No daily data for {ticker}")
            return None, None, None

        tlt_daily = fetcher.get_daily_bars("TLT", start, end)
        vix_daily = fetcher.get_vix_daily(start, end)

        enriched = enrich_daily_data(daily, vix_daily, tlt_daily, config.ATR_PERIOD)
        valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
        intraday_data = fetcher.get_intraday_bars_bulk(ticker, valid_dates)

        signals_by_key = generate_all_signals(enriched, intraday_data, atr_mults, directions)

        return signals_by_key, intraday_data, enriched
    finally:
        config.TICKER = orig_ticker
        config.BACKTEST_START = orig_start
        config.BACKTEST_END = orig_end


def stock_backtest_specific(signals_df, intraday_data, direction, stop, target, time_exit, trail=None):
    """Run a single stock backtest config and return trades DataFrame."""
    trades = []
    for _, signal in signals_df.iterrows():
        date_str = str(signal["date"])
        if date_str not in intraday_data:
            continue
        intraday = intraday_data[date_str]
        entry_time = signal["entry_time"]
        remaining = intraday[intraday["timestamp"] > entry_time].copy()
        if remaining.empty:
            continue
        trade = simulate_stock_trade(remaining, signal["entry_price"],
                                     stop, target, trail, time_exit, direction)
        trade["date"] = signal["date"]
        trade["entry_price"] = signal["entry_price"]
        trade["entry_time"] = signal["entry_time"]
        trade["vix_regime"] = signal.get("vix_regime", "unknown")
        trade["direction"] = direction
        trades.append(trade)

    if not trades:
        return pd.DataFrame()
    return pd.DataFrame(trades)


def walk_forward_test(trades_df, split_date):
    """Split trades by date and compare train vs test metrics."""
    if trades_df.empty:
        return None, None

    trades_df = trades_df.copy()
    trades_df["date_obj"] = pd.to_datetime(trades_df["date"]).dt.date

    if isinstance(split_date, str):
        split_date = datetime.strptime(split_date, "%Y-%m-%d").date()

    train = trades_df[trades_df["date_obj"] < split_date]
    test = trades_df[trades_df["date_obj"] >= split_date]
    return compute_metrics(train), compute_metrics(test)


# ═════════════════════════════════════════════════════════════════════════
#  TASK 1: EXTENDED SPY STOCK BACKTEST (2018-2026)
# ═════════════════════════════════════════════════════════════════════════
def run_spy_extended():
    print("=" * 70)
    print("  TASK 1: SPY ABOVE-VWAP SHORT — EXTENDED TO 2018-2026")
    print("  Previous: 2022-2026, only 13 trades at 1.0x ATR")
    print("  Goal: Get N > 30 for statistical significance")
    print("=" * 70)

    # Run pipeline for 2018-2021 (new data)
    print("\n--- Fetching 2018-2021 SPY data ---")
    sig_pre, intra_pre, enr_pre = run_pipeline("SPY", "2018-01-01", "2021-12-31",
                                                 ["above"], [0.7, 0.8, 0.9, 1.0])

    # Run pipeline for 2022-2026 (existing data)
    print("\n--- Fetching 2022-2026 SPY data ---")
    sig_post, intra_post, enr_post = run_pipeline("SPY", "2022-01-01", "2026-03-17",
                                                    ["above"], [0.7, 0.8, 0.9, 1.0])

    if sig_pre is None or sig_post is None:
        print("ERROR: Could not load data. Skipping.")
        return

    # The best config from original backtest: 1.0% stop, 0.75% target, 15min exit
    test_configs = [
        (1.0, 0.75, 15),
        (0.5, 2.0, "EOD"),
        (1.0, 1.0, 30),
        (0.75, 1.5, 60),
    ]

    for mult in [0.7, 0.8, 0.9, 1.0]:
        key = ("above", mult)
        sig_pre_df = sig_pre.get(key, pd.DataFrame())
        sig_post_df = sig_post.get(key, pd.DataFrame())

        n_pre = len(sig_pre_df) if not isinstance(sig_pre_df, type(None)) and not sig_pre_df.empty else 0
        n_post = len(sig_post_df) if not isinstance(sig_post_df, type(None)) and not sig_post_df.empty else 0

        print(f"\n  ABOVE {mult}x ATR: {n_pre} signals (2018-2021) + {n_post} signals (2022-2026) = {n_pre + n_post} total")

        for stop, target, t_exit in test_configs:
            # Run on each period separately
            trades_pre = stock_backtest_specific(sig_pre_df, intra_pre, "above",
                                                  stop, target, t_exit) if n_pre > 0 else pd.DataFrame()
            trades_post = stock_backtest_specific(sig_post_df, intra_post, "above",
                                                   stop, target, t_exit) if n_post > 0 else pd.DataFrame()

            # Combine
            trades_all = pd.concat([trades_pre, trades_post], ignore_index=True) if not trades_pre.empty or not trades_post.empty else pd.DataFrame()

            m_all = compute_metrics(trades_all) if not trades_all.empty else {"n": 0}
            m_pre = compute_metrics(trades_pre) if not trades_pre.empty else {"n": 0}
            m_post = compute_metrics(trades_post) if not trades_post.empty else {"n": 0}

            if m_all.get("n", 0) == 0:
                continue

            label = f"stop={stop}%, tgt={target}%, t={t_exit}"
            print(f"    {label}")
            print(f"      ALL:  N={m_all['n']:>3d}  WR={m_all.get('win_rate',0):>5.1f}%  "
                  f"Exp={m_all.get('avg_pnl',0):>+7.3f}%  Sharpe={m_all.get('sharpe',0):>6.3f}  "
                  f"PF={m_all.get('profit_factor',0):>5.2f}")
            print(f"      PRE:  N={m_pre.get('n',0):>3d}  WR={m_pre.get('win_rate',0):>5.1f}%  "
                  f"Exp={m_pre.get('avg_pnl',0):>+7.3f}%  Sharpe={m_pre.get('sharpe',0):>6.3f}")
            print(f"      POST: N={m_post.get('n',0):>3d}  WR={m_post.get('win_rate',0):>5.1f}%  "
                  f"Exp={m_post.get('avg_pnl',0):>+7.3f}%  Sharpe={m_post.get('sharpe',0):>6.3f}")

            # Walk-forward with mid-2021 split on combined data
            if not trades_all.empty and m_all["n"] >= 10:
                wf_train, wf_test = walk_forward_test(trades_all, "2022-01-01")
                if wf_train and wf_test and wf_train.get("n", 0) > 0 and wf_test.get("n", 0) > 0:
                    pass_fail = "PASS" if (wf_train["sharpe"] > 0 and wf_test["sharpe"] > 0) else "FAIL"
                    if wf_train["sharpe"] <= 0:
                        pass_fail = "FAIL (train negative)"
                    print(f"      W-F:  Train N={wf_train['n']:>3d} Sharpe={wf_train['sharpe']:>6.3f}  "
                          f"Test N={wf_test['n']:>3d} Sharpe={wf_test['sharpe']:>6.3f}  → {pass_fail}")


# ═════════════════════════════════════════════════════════════════════════
#  TASK 2: IWM + DIA CROSS-INSTRUMENT VALIDATION
# ═════════════════════════════════════════════════════════════════════════
def run_cross_instrument():
    print("\n\n" + "=" * 70)
    print("  TASK 2: CROSS-INSTRUMENT VALIDATION (IWM + DIA)")
    print("  Testing short-above-VWAP and long-below-VWAP signals")
    print("  Same ATR levels as SPY/QQQ validated edges")
    print("=" * 70)

    # Key configs to test (from validated edges)
    # Short above: stop=1.0%, tgt=0.75%, 15min (SPY 1.0x config)
    # Long below: stop=1.0%, tgt=0.75%, 15min (QQQ 0.6x config)
    above_configs = [
        (1.0, 0.75, 15),
        (0.5, 2.0, "EOD"),
    ]
    below_configs = [
        (1.0, 0.75, 15),
        (0.75, 0.50, 15),
    ]

    for ticker in ["IWM", "DIA"]:
        print(f"\n{'─'*60}")
        print(f"  {ticker} — 2022-01-01 to 2026-03-17")
        print(f"{'─'*60}")

        sig_dict, intra_data, enriched = run_pipeline(
            ticker, "2022-01-01", "2026-03-17",
            ["above", "below"], [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        )

        if sig_dict is None:
            print(f"  ERROR: Could not load data for {ticker}")
            continue

        # ── ABOVE (short) ──
        print(f"\n  === {ticker} ABOVE VWAP (short fade) ===")
        for mult in [0.5, 0.7, 0.8, 1.0]:
            key = ("above", mult)
            sigs = sig_dict.get(key, pd.DataFrame())
            if isinstance(sigs, pd.DataFrame) and sigs.empty:
                print(f"    {mult}x ATR: 0 signals")
                continue

            print(f"\n    {mult}x ATR: {len(sigs)} signals")
            for stop, target, t_exit in above_configs:
                trades = stock_backtest_specific(sigs, intra_data, "above", stop, target, t_exit)
                if trades.empty:
                    continue
                m = compute_metrics(trades)
                label = f"stop={stop}%, tgt={target}%, t={t_exit}"
                print(f"      {label}: N={m['n']:>3d}  WR={m['win_rate']:>5.1f}%  "
                      f"Exp={m['avg_pnl']:>+7.3f}%  Sharpe={m['sharpe']:>6.3f}  PF={m['profit_factor']:>5.2f}")

                # Walk-forward
                if m["n"] >= 10:
                    wf_train, wf_test = walk_forward_test(trades, "2024-07-01")
                    if wf_train and wf_test and wf_train.get("n", 0) > 2 and wf_test.get("n", 0) > 2:
                        pf = "PASS" if (wf_train["sharpe"] > 0 and wf_test["sharpe"] > 0) else "FAIL"
                        if wf_train["sharpe"] <= 0:
                            pf = "FAIL (train neg)"
                        print(f"        W-F: Train N={wf_train['n']} Sh={wf_train['sharpe']:.3f} | "
                              f"Test N={wf_test['n']} Sh={wf_test['sharpe']:.3f} → {pf}")

        # ── BELOW (long) ──
        print(f"\n  === {ticker} BELOW VWAP (long dip buy) ===")
        for mult in [0.5, 0.6, 0.7, 0.8]:
            key = ("below", mult)
            sigs = sig_dict.get(key, pd.DataFrame())
            if isinstance(sigs, pd.DataFrame) and sigs.empty:
                print(f"    {mult}x ATR: 0 signals")
                continue

            print(f"\n    {mult}x ATR: {len(sigs)} signals")
            for stop, target, t_exit in below_configs:
                trades = stock_backtest_specific(sigs, intra_data, "below", stop, target, t_exit)
                if trades.empty:
                    continue
                m = compute_metrics(trades)
                label = f"stop={stop}%, tgt={target}%, t={t_exit}"
                print(f"      {label}: N={m['n']:>3d}  WR={m['win_rate']:>5.1f}%  "
                      f"Exp={m['avg_pnl']:>+7.3f}%  Sharpe={m['sharpe']:>6.3f}  PF={m['profit_factor']:>5.2f}")

                # Walk-forward
                if m["n"] >= 10:
                    wf_train, wf_test = walk_forward_test(trades, "2024-07-01")
                    if wf_train and wf_test and wf_train.get("n", 0) > 2 and wf_test.get("n", 0) > 2:
                        pf = "PASS" if (wf_train["sharpe"] > 0 and wf_test["sharpe"] > 0) else "FAIL"
                        if wf_train["sharpe"] <= 0:
                            pf = "FAIL (train neg)"
                        print(f"        W-F: Train N={wf_train['n']} Sh={wf_train['sharpe']:.3f} | "
                              f"Test N={wf_test['n']} Sh={wf_test['sharpe']:.3f} → {pf}")


if __name__ == "__main__":
    print("=" * 70)
    print("  EXTENDED VALIDATION BACKTEST")
    print("  1. SPY stock short-above extended to 2018-2026")
    print("  2. IWM + DIA cross-instrument validation")
    print("  All data from real Polygon API — no fabrication")
    print("=" * 70)

    t0 = time.time()
    run_spy_extended()
    run_cross_instrument()

    elapsed = time.time() - t0
    print(f"\n\n{'='*70}")
    print(f"  ALL EXTENDED VALIDATION COMPLETE — {elapsed:.0f}s")
    print(f"{'='*70}")

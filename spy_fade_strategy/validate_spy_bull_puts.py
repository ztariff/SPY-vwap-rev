#!/usr/bin/env python3
"""
VALIDATION GAUNTLET for SPY Bull Put Spreads (below VWAP, 0.5x-0.9x ATR)

Tests:
1. Walk-forward: train pre-2024-07-01, test post-2024-07-01
2. VIX regime analysis per bucket
3. Parameter robustness: % of configs profitable
4. Slippage stress test (spread widening)

All data from real Polygon prices. No fabrication.
"""

import sys
import os
import json
import time
import numpy as np
import pandas as pd
from datetime import datetime, date
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_all_options_data, OptionsDayData
from backtest_spreads import (
    simulate_credit_spread_trade, SPREAD_PAIRS, SPREAD_PROFIT_TARGETS,
    SPREAD_STOP_LOSSES, SPREAD_TIME_EXITS
)

SPLIT_DATE = date(2024, 7, 1)


def compute_metrics(trades_df):
    """Standard metrics from trades."""
    if trades_df.empty or len(trades_df) == 0:
        return {"n": 0, "win_rate": 0, "avg_pnl": 0, "sharpe": 0, "profit_factor": 0}
    n = len(trades_df)
    pnl = trades_df["pnl_on_risk"] if "pnl_on_risk" in trades_df.columns else trades_df["pnl_pct"]
    winners = pnl[pnl > 0]
    losers = pnl[pnl <= 0]
    avg = pnl.mean()
    std = pnl.std()
    gross_w = winners.sum() if len(winners) > 0 else 0
    gross_l = abs(losers.sum()) if len(losers) > 0 else 0.0001
    return {
        "n": n,
        "win_rate": len(winners) / n * 100,
        "avg_pnl": avg,
        "sharpe": avg / std if std > 0 else 0,
        "profit_factor": gross_w / gross_l if gross_l > 0 else float('inf'),
        "avg_winner": winners.mean() if len(winners) > 0 else 0,
        "avg_loser": losers.mean() if len(losers) > 0 else 0,
        "total_pnl": pnl.sum(),
    }


def run_single_spread_config(options_data_dict, signals_df, short_delta, long_delta,
                              profit_target, stop_loss, time_exit, slippage_pct=0.0):
    """Run one spread config, return per-trade DataFrame."""
    trades = []
    for _, signal in signals_df.iterrows():
        date_str = str(signal["date"])
        if date_str not in options_data_dict:
            continue

        day_data = options_data_dict[date_str]
        opt_dict = day_data.puts  # Bull put = sell put spread

        if short_delta not in opt_dict or long_delta not in opt_dict:
            continue

        short_info = opt_dict[short_delta]
        long_info = opt_dict[long_delta]
        short_bars = short_info["bars"]
        long_bars = long_info["bars"]
        short_entry = short_info["entry_price"]
        long_entry = long_info["entry_price"]

        if short_entry <= 0 or long_entry <= 0 or short_bars.empty or long_bars.empty:
            continue
        if short_entry <= long_entry:
            continue

        spread_width = abs(short_info["strike"] - long_info["strike"])

        # Apply slippage: worse fill on both legs
        # Short leg: get less credit (lower fill)
        # Long leg: pay more (higher fill)
        adj_short = short_entry * (1 - slippage_pct)
        adj_long = long_entry * (1 + slippage_pct)
        if adj_short <= adj_long:
            continue  # Slippage ate the credit

        trade = simulate_credit_spread_trade(
            short_bars, long_bars, adj_short, adj_long,
            profit_target, stop_loss, time_exit, spread_width
        )
        trade["date"] = signal["date"]
        trade["short_delta"] = short_delta
        trade["long_delta"] = long_delta
        trade["spot"] = signal["entry_price"]
        trade["vix_regime"] = signal.get("vix_regime", "unknown")
        trades.append(trade)

    return pd.DataFrame(trades) if trades else pd.DataFrame()


def main():
    t0 = time.time()
    print("=" * 70)
    print("  SPY BULL PUT SPREAD VALIDATION GAUNTLET")
    print("  Walk-forward | VIX Regime | Parameter Robustness | Slippage")
    print("  All data from real Polygon prices")
    print("=" * 70)

    # ── Load data ──
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    atr_mults = [0.5, 0.6, 0.7, 0.8, 0.9]
    signals_by_key = generate_all_signals(enriched, intraday_data, atr_mults, ["below"])

    # Load options data for each ATR level
    print("\n--- Loading options data ---")
    options_by_mult = {}
    for mult in atr_mults:
        key = ("below", mult)
        sigs = signals_by_key.get(key, pd.DataFrame())
        if sigs.empty:
            print(f"  {mult}x: 0 signals")
            continue
        print(f"  {mult}x: {len(sigs)} signals — loading options...")
        opt_data = pull_all_options_data(fetcher, sigs)
        options_by_mult[mult] = (sigs, opt_data)
        print(f"    Got options for {len(opt_data)} days")

    # ══════════════════════════════════════════════════════════════════
    # ANALYSIS 1: WALK-FORWARD (best config per ATR level)
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 1: WALK-FORWARD — SPY BULL PUT SPREADS")
    print(f"  Train: pre-2024-07-01 | Test: 2024-07-01 onward")
    print(f"{'='*70}")

    # Best configs from original grid search
    best_configs = {
        0.5: (0.30, 0.20, 0.25, 2.0, 15),   # spread_pair, tgt, sl, time
        0.6: (0.20, 0.10, 0.25, 1.5, 60),
        0.7: (0.20, 0.10, 0.25, 0.5, 30),
        0.8: (0.20, 0.10, 0.25, 1.0, 15),
        0.9: (0.20, 0.10, 0.25, 1.0, 30),
    }

    # Also test a diverse set of configs for walk-forward breadth
    alt_configs = [
        (0.25, 0.10, 0.25, 2.0, 15),
        (0.25, 0.15, 0.25, 1.5, 30),
        (0.30, 0.20, 0.50, 1.5, 30),
        (0.20, 0.10, 0.50, 2.0, "EOD"),
        (0.35, 0.25, 0.25, 1.0, 15),
    ]

    for mult in atr_mults:
        if mult not in options_by_mult:
            continue
        sigs, opt_data = options_by_mult[mult]

        sd, ld, tgt, sl, te = best_configs[mult]
        print(f"\n  BELOW {mult}x ATR — Best: {sd}/{ld} tgt={tgt} sl={sl} t={te}")

        # Run best config
        trades = run_single_spread_config(opt_data, sigs, sd, ld, tgt, sl, te)
        if trades.empty:
            print("    No trades")
            continue

        trades["date_obj"] = pd.to_datetime(trades["date"]).dt.date

        train = trades[trades["date_obj"] < SPLIT_DATE]
        test = trades[trades["date_obj"] >= SPLIT_DATE]
        m_train = compute_metrics(train)
        m_test = compute_metrics(test)

        pass_fail = "PASS" if (m_train["sharpe"] > 0 and m_test["sharpe"] > 0) else "FAIL"
        if m_train["sharpe"] <= 0:
            pass_fail = "FAIL (train negative)"

        print(f"    TRAIN: N={m_train['n']:>3d} WR={m_train['win_rate']:>5.1f}% "
              f"Exp={m_train['avg_pnl']:>+7.3f}% Sharpe={m_train['sharpe']:>6.3f} PF={m_train['profit_factor']:>5.2f}")
        print(f"    TEST:  N={m_test['n']:>3d} WR={m_test['win_rate']:>5.1f}% "
              f"Exp={m_test['avg_pnl']:>+7.3f}% Sharpe={m_test['sharpe']:>6.3f} PF={m_test['profit_factor']:>5.2f}")
        print(f"    → {pass_fail}")

        # Run alt configs too
        print(f"\n    Alt configs walk-forward:")
        for asd, ald, atgt, asl, ate in alt_configs:
            alt_trades = run_single_spread_config(opt_data, sigs, asd, ald, atgt, asl, ate)
            if alt_trades.empty or len(alt_trades) < 5:
                continue
            alt_trades["date_obj"] = pd.to_datetime(alt_trades["date"]).dt.date
            alt_train = alt_trades[alt_trades["date_obj"] < SPLIT_DATE]
            alt_test = alt_trades[alt_trades["date_obj"] >= SPLIT_DATE]
            mt = compute_metrics(alt_train)
            ms = compute_metrics(alt_test)
            if mt["n"] < 3 or ms["n"] < 3:
                continue
            pf = "PASS" if (mt["sharpe"] > 0 and ms["sharpe"] > 0) else "FAIL"
            if mt["sharpe"] <= 0:
                pf = "FAIL(trn-)"
            print(f"      {asd}/{ald} tgt={atgt} sl={asl} t={ate:>3}: "
                  f"Train N={mt['n']:>3d} Sh={mt['sharpe']:>6.3f}  "
                  f"Test N={ms['n']:>3d} Sh={ms['sharpe']:>6.3f}  → {pf}")

    # ══════════════════════════════════════════════════════════════════
    # ANALYSIS 2: VIX REGIME
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 2: VIX REGIME — SPY BULL PUT SPREADS")
    print(f"{'='*70}")

    vix_buckets = [(0, 15, "Low"), (15, 20, "Normal"), (20, 25, "Elevated"),
                   (25, 35, "High"), (35, 100, "Extreme")]

    for mult in atr_mults:
        if mult not in options_by_mult:
            continue
        sigs, opt_data = options_by_mult[mult]
        sd, ld, tgt, sl, te = best_configs[mult]

        trades = run_single_spread_config(opt_data, sigs, sd, ld, tgt, sl, te)
        if trades.empty:
            continue

        print(f"\n  BELOW {mult}x — {sd}/{ld} tgt={tgt} sl={sl} t={te}")

        for vlo, vhi, vlabel in vix_buckets:
            vix_trades = trades[
                (trades["vix_regime"].str.contains(str(vlo)) if "vix_regime" in trades.columns
                 else pd.Series([False] * len(trades)))
            ]

            # Fallback: try to match VIX from signals
            # The vix_regime field format may vary, so let's match by date to enriched data
            pass

        # Simpler approach: merge trades with VIX data by date
        if not vix_daily.empty:
            vix_lookup = {}
            for _, vr in vix_daily.iterrows():
                vix_lookup[str(vr["date"])] = vr["vix_close"]

            trades["vix"] = trades["date"].astype(str).map(vix_lookup)
            trades_with_vix = trades.dropna(subset=["vix"])

            if len(trades_with_vix) > 0:
                for vlo, vhi, vlabel in vix_buckets:
                    bucket = trades_with_vix[
                        (trades_with_vix["vix"] >= vlo) & (trades_with_vix["vix"] < vhi)
                    ]
                    if bucket.empty:
                        print(f"    VIX {vlo:>2}-{vhi:<3} ({vlabel:>8}): N=  0")
                        continue
                    m = compute_metrics(bucket)
                    print(f"    VIX {vlo:>2}-{vhi:<3} ({vlabel:>8}): N={m['n']:>3d} "
                          f"WR={m['win_rate']:>5.1f}% Exp={m['avg_pnl']:>+7.3f}% "
                          f"Sharpe={m['sharpe']:>6.3f} PF={m['profit_factor']:>5.2f}")
            else:
                print("    (No VIX data available for regime analysis)")
        else:
            print("    (No VIX data available)")

    # ══════════════════════════════════════════════════════════════════
    # ANALYSIS 3: PARAMETER ROBUSTNESS (0.5x ATR, largest sample)
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 3: PARAMETER ROBUSTNESS — SPY BULL PUTS BELOW 0.5x")
    print(f"  Testing ALL 13 spread pairs × 5 exit combos (full sample)")
    print(f"{'='*70}")

    if 0.5 in options_by_mult:
        sigs_05, opt_05 = options_by_mult[0.5]

        # Diverse exit combos
        test_exits = [
            (1.0, 2.0, "EOD"),
            (0.5, 2.0, "EOD"),
            (0.25, 1.5, 5),
            (0.25, 2.0, 15),
            (0.75, 1.5, 30),
        ]

        profitable = 0
        total = 0
        sharpes = []

        print(f"\n  {'Spread':<12} {'Exit':<26} {'N':>4} {'WR':>6} {'Exp%':>8} {'Sharpe':>7} {'PF':>6} {'Credit':>7} {'$P&L':>7}")

        for short_d, long_d in SPREAD_PAIRS:
            for tgt, sl, te in test_exits:
                trades = run_single_spread_config(opt_05, sigs_05, short_d, long_d, tgt, sl, te)
                if trades.empty:
                    continue
                m = compute_metrics(trades)
                total += 1
                if m["avg_pnl"] > 0:
                    profitable += 1
                    sharpes.append(m["sharpe"])

                credit = trades["credit"].mean() if "credit" in trades.columns else 0
                pnl_dollar = trades["pnl_dollar"].mean() if "pnl_dollar" in trades.columns else 0

                print(f"  {short_d:.2f}/{long_d:.2f}    "
                      f"tgt={tgt} sl={sl} t={te:<3}    "
                      f"{m['n']:>4d} {m['win_rate']:>5.1f}% {m['avg_pnl']:>+7.2f}% "
                      f"{m['sharpe']:>6.3f} {m['profit_factor']:>5.1f} "
                      f"${credit:>.2f} ${pnl_dollar:>+.3f}")

        print(f"\n  Profitable configs: {profitable}/{total} ({100*profitable/total:.0f}%)" if total > 0 else "")
        if sharpes:
            print(f"  Avg Sharpe (profitable): {np.mean(sharpes):.3f}")

    # ══════════════════════════════════════════════════════════════════
    # ANALYSIS 4: SLIPPAGE STRESS TEST (best configs)
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  ANALYSIS 4: SLIPPAGE STRESS TEST — SPY BULL PUT SPREADS")
    print(f"  Testing credit erosion from wider fills")
    print(f"{'='*70}")

    slippage_levels = [0.0, 0.01, 0.02, 0.03, 0.05, 0.07, 0.10]

    for mult in [0.5, 0.7]:
        if mult not in options_by_mult:
            continue
        sigs, opt_data = options_by_mult[mult]
        sd, ld, tgt, sl, te = best_configs[mult]

        print(f"\n  BELOW {mult}x — {sd}/{ld} tgt={tgt} sl={sl} t={te}")
        print(f"  {'Slippage':>10} {'N':>5} {'WR':>6} {'Exp%':>8} {'Sharpe':>7} {'PF':>6}")

        for slip in slippage_levels:
            trades = run_single_spread_config(opt_data, sigs, sd, ld, tgt, sl, te,
                                               slippage_pct=slip)
            if trades.empty:
                print(f"  {slip*100:>9.2f}% {0:>5d}  (no trades — slippage ate all credits)")
                continue
            m = compute_metrics(trades)
            print(f"  {slip*100:>9.2f}% {m['n']:>5d} {m['win_rate']:>5.1f}% "
                  f"{m['avg_pnl']:>+7.3f}% {m['sharpe']:>6.3f} {m['profit_factor']:>5.2f}")

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"  ALL ANALYSES COMPLETE — {elapsed:.0f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

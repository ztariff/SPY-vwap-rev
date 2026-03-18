#!/usr/bin/env python3
"""
STOCK MEAN REVERSION — Comprehensive Grid Search
==================================================
Tests SPY (and QQQ if available) stock scalps/holds using VWAP deviation signals.

Advantages over options:
- Commission is trivial (~$2 RT on $100K = 0.002%)
- No spread width/credit issues
- Can test intraday scalps AND longer holds

Entry: VWAP deviation (0.5x–1.5x ATR, both directions)
Stops: tight (0.1-0.25%), medium (0.3-0.75%), wide (1-2%), VWAP cross, ATR-based
Targets: 0.1% to 3%
Holds: 5m to EOD
Trailing: 0.1% to 0.5%

All data from real Polygon 1-min bars. No fabrication.
"""

import sys, os, json, time
import pandas as pd
import numpy as np
from datetime import datetime, date
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data, calculate_session_vwap
from signal_generator import generate_all_signals
from backtest_stock import simulate_stock_trade

# Stock commission (IBKR)
# $0.005/share, $1 min. On $100K at ~$550 = ~182 shares = ~$1.82 RT = 0.002%
STOCK_COMM_PCT = 0.002  # percent of position, RT

# Grid
ATR_MULTS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5]
DIRECTIONS = ["above", "below"]

# Comprehensive stop/target/time grid
STOPS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.75, 1.0, 1.5, 2.0]
TARGETS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0]
TIME_EXITS = [5, 10, 15, 30, 60, 120, "EOD"]
TRAILING_STOPS = [None, 0.10, 0.15, 0.25, 0.50]

MIN_TRADES = 20
SPLIT_DATE = "2024-07-01"


def compute_metrics(pnls, dates=None):
    """Compute metrics from pnl array (already commission-adjusted)."""
    if len(pnls) < MIN_TRADES:
        return None

    a = np.array(pnls)
    s = np.std(a)
    if s == 0:
        return None

    sharpe = float(np.mean(a) / s)
    wr = float(np.sum(a > 0) / len(a) * 100)
    avg = float(np.mean(a))

    # Drawdown
    cum = np.cumsum(a)
    pk = np.maximum.accumulate(cum)
    mdd = float(np.min(cum - pk)) if len(cum) > 0 else 0

    # Profit factor
    wins = a[a > 0]
    losses = a[a < 0]
    tw = float(np.sum(wins)) if len(wins) > 0 else 0
    tl = float(abs(np.sum(losses))) if len(losses) > 0 else 0.0001

    # Sortino
    ds = np.std(losses) if len(losses) >= 2 else s
    sortino = float(np.mean(a) / ds) if ds > 0 else 0

    # Yearly
    ysh = {}
    if dates:
        yearly = defaultdict(list)
        for p, d in zip(pnls, dates):
            yr = str(d)[:4] if isinstance(d, str) else str(getattr(d, 'year', ''))
            yearly[yr].append(p)
        for yr, v in yearly.items():
            ya = np.array(v)
            ysh[yr] = float(np.mean(ya)/np.std(ya)) if np.std(ya) > 0 and len(ya) >= 3 else 0.0

    neg_yr = sum(1 for v in ysh.values() if v < 0)

    return {
        "n": len(a), "sharpe": sharpe, "sortino": sortino,
        "wr": wr, "avg": avg, "total": float(np.sum(a)),
        "mdd": mdd, "pf": tw/tl,
        "avg_win": float(np.mean(wins)) if len(wins) > 0 else 0,
        "avg_loss": float(np.mean(losses)) if len(losses) > 0 else 0,
        "best": float(np.max(a)), "worst": float(np.min(a)),
        "neg_yr": neg_yr, "ysh": ysh,
    }


def run_stock_search(ticker, enriched, intraday_data, label="SPY"):
    """Run comprehensive stock mean-reversion grid search."""

    print(f"\n{'='*70}")
    print(f"  STOCK MEAN REVERSION — {label}")
    print(f"  Commission: {STOCK_COMM_PCT}% RT (essentially free)")
    print(f"{'='*70}")

    # Generate signals
    signals_by_key = generate_all_signals(enriched, intraday_data, ATR_MULTS, DIRECTIONS)

    # Pre-compute remaining bars for each signal
    print("\n  Pre-computing signal bar data...")
    signal_cache = {}  # (direction, mult) -> list of (date, entry_price, remaining_bars, signal)

    for direction in DIRECTIONS:
        for mult in ATR_MULTS:
            key = (direction, mult)
            sig_df = signals_by_key.get(key, pd.DataFrame())
            if sig_df.empty:
                continue

            entries = []
            for _, signal in sig_df.iterrows():
                date_str = str(signal["date"])
                if date_str not in intraday_data:
                    continue
                intraday = intraday_data[date_str]
                entry_time = signal["entry_time"]
                remaining = intraday[intraday["timestamp"] > entry_time].copy().reset_index(drop=True)
                if remaining.empty:
                    continue
                entries.append({
                    "date": signal["date"],
                    "entry_price": signal["entry_price"],
                    "bars": remaining,
                    "vwap_at_entry": signal.get("entry_vwap", signal["entry_price"]),
                    "atr": signal.get("atr", 0),
                })

            if entries:
                signal_cache[key] = entries

    total_signals = sum(len(v) for v in signal_cache.values())
    print(f"  Cached {total_signals} signal entries across {len(signal_cache)} (dir, mult) combos")

    # Grid search
    # For efficiency: loop direction/mult first, then exit combos
    # Skip trailing stops for the initial sweep to reduce grid size
    # Phase 1: No trailing stops (fast)
    # Phase 2: Add trailing stops to top configs

    exit_combos_phase1 = [(s, t, te, None) for s in STOPS for t in TARGETS for te in TIME_EXITS]
    exit_combos_phase2 = [(s, t, te, tr) for s in [0.15, 0.25, 0.50, 0.75, 1.0]
                          for t in [0.50, 1.0, 1.5, 2.0, 3.0]
                          for te in [30, 60, 120, "EOD"]
                          for tr in [0.10, 0.15, 0.25, 0.50]]

    all_combos = exit_combos_phase1 + exit_combos_phase2
    total_tests = len(signal_cache) * len(all_combos)
    print(f"\n  Grid: {len(signal_cache)} signal combos × {len(all_combos)} exit combos = {total_tests} tests")

    all_results = []
    tested = 0

    for (direction, mult), entries in signal_cache.items():
        if len(entries) < 5:
            tested += len(all_combos)
            continue

        for stop, target, time_exit, trail in all_combos:
            tested += 1
            if tested % 10000 == 0:
                print(f"    [{tested}/{total_tests}] ({len(all_results)} passed)...", flush=True)

            pnls = []
            dates = []

            for e in entries:
                result = simulate_stock_trade(
                    e["bars"], e["entry_price"],
                    stop, target, trail, time_exit, direction
                )
                pnl = result["pnl_pct"] - STOCK_COMM_PCT  # subtract commission
                pnls.append(pnl)
                dates.append(e["date"])

            m = compute_metrics(pnls, dates)
            if m is None or m["avg"] <= 0:
                continue

            all_results.append({
                "ticker": ticker, "dir": direction, "mult": mult,
                "stop": stop, "target": target, "te": time_exit, "trail": trail,
                **m,
            })

    all_results.sort(key=lambda r: r["sharpe"], reverse=True)

    print(f"\n{'='*70}")
    print(f"  {label} GRID COMPLETE: {tested} tested, {len(all_results)} positive expectancy")
    print(f"{'='*70}")

    if not all_results:
        print(f"\n  *** NO CONFIGS WITH POSITIVE EXPECTANCY FOR {label} ***")
        return []

    # Top 50
    print(f"\n  TOP 50 (by Sharpe):")
    print(f"  {'#':>3} {'Dir':>5} {'ATR':>4} {'Stop':>5} {'Tgt':>5} {'T':>4} {'Trail':>5} "
          f"{'N':>4} {'Sharpe':>7} {'WR':>5} {'Avg':>7} {'Tot':>7} {'MDD':>7} {'PF':>5} {'NY':>3}")

    for i, r in enumerate(all_results[:50]):
        tr = f"{r['trail']:.2f}" if r['trail'] else "  -"
        print(f"  {i+1:>3} {r['dir']:>5} {r['mult']:>4.1f} {r['stop']:>5.2f} {r['target']:>5.2f} "
              f"{str(r['te']):>4} {tr:>5} "
              f"{r['n']:>4} {r['sharpe']:>7.3f} {r['wr']:>4.1f}% {r['avg']:>+6.3f}% "
              f"{r['total']:>+6.2f}% {r['mdd']:>+6.2f}% {r['pf']:>5.2f} {r['neg_yr']:>3}")

    # Walk-forward on top 100
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD (Train < {SPLIT_DATE} | Test >= {SPLIT_DATE})")
    print(f"{'='*70}")

    wf_results = []
    for i, r in enumerate(all_results[:100]):
        direction, mult = r["dir"], r["mult"]
        key = (direction, mult)
        entries = signal_cache.get(key, [])

        train_pnls, train_dates = [], []
        test_pnls, test_dates = [], []

        for e in entries:
            result = simulate_stock_trade(
                e["bars"], e["entry_price"],
                r["stop"], r["target"], r["trail"], r["te"], direction
            )
            pnl = result["pnl_pct"] - STOCK_COMM_PCT
            d = str(e["date"])

            if d < SPLIT_DATE:
                train_pnls.append(pnl)
                train_dates.append(d)
            else:
                test_pnls.append(pnl)
                test_dates.append(d)

        tm = compute_metrics(train_pnls, train_dates) if len(train_pnls) >= 5 else None
        sm = compute_metrics(test_pnls, test_dates) if len(test_pnls) >= 3 else None

        if tm and sm:
            tp = tm["sharpe"] > 0
            sp_bool = sm["sharpe"] > 0
            verdict = "PASS" if (tp and sp_bool) else "SOFT" if (tp and sm["sharpe"] > -0.15) else "FAIL"

            if verdict != "FAIL":
                tr = f"{r['trail']:.2f}" if r['trail'] else "-"
                print(f"  #{i+1:>2} {r['dir']:>5} {r['mult']:.1f}x s={r['stop']} t={r['target']} "
                      f"T={r['te']} tr={tr}")
                print(f"       Train: N={tm['n']:>3} Sh={tm['sharpe']:>+.3f} WR={tm['wr']:>5.1f}%")
                print(f"       Test:  N={sm['n']:>3} Sh={sm['sharpe']:>+.3f} WR={sm['wr']:>5.1f}%  → {verdict}")

                wf_results.append({
                    **r,
                    "train_sh": tm["sharpe"], "test_sh": sm["sharpe"],
                    "train_n": tm["n"], "test_n": sm["n"],
                    "wf": verdict,
                })

    print(f"\n  WF survivors: {len(wf_results)}")

    # Yearly stability on WF survivors
    if wf_results:
        print(f"\n{'='*70}")
        print(f"  YEARLY STABILITY")
        print(f"{'='*70}")

        final = []
        for s in wf_results:
            ysh = s.get("ysh", {})
            deep_neg = sum(1 for v in ysh.values() if v < -0.3)
            neg = sum(1 for v in ysh.values() if v < 0)
            stable = deep_neg <= 1

            verdict = "PROMOTED" if (s["wf"] == "PASS" and stable) else \
                      "BORDERLINE" if (neg <= 2) else "REJECTED"

            tr = f"{s['trail']:.2f}" if s['trail'] else "-"
            print(f"\n  {s['dir']} {s['mult']}x s={s['stop']} t={s['target']} T={s['te']} tr={tr}  WF={s['wf']}")
            for yr, sh in sorted(ysh.items()):
                flag = " ← NEG" if sh < 0 else ""
                print(f"    {yr}: Sh={sh:+.3f}{flag}")
            print(f"    → {verdict}")

            if verdict in ("PROMOTED", "BORDERLINE"):
                final.append({**s, "final_verdict": verdict})

        return final

    return []


def main():
    t0 = time.time()
    print("=" * 70)
    print("  STOCK MEAN REVERSION — COMPREHENSIVE SEARCH")
    print("  SPY + QQQ | VWAP deviation entries | All stop/target/hold combos")
    print("  Commission: ~0.002% (negligible)")
    print("  All data from real Polygon 1-min bars. No fabrication.")
    print("=" * 70)

    fetcher = PolygonFetcher()

    # ═══════════════════════════════════════════════════════════════════
    # SPY
    # ═══════════════════════════════════════════════════════════════════
    print("\n\n" + "█" * 70)
    print("  SPY ANALYSIS")
    print("█" * 70)

    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    spy_intraday = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    spy_results = run_stock_search("SPY", enriched, spy_intraday, "SPY")

    # ═══════════════════════════════════════════════════════════════════
    # QQQ
    # ═══════════════════════════════════════════════════════════════════
    print("\n\n" + "█" * 70)
    print("  QQQ ANALYSIS")
    print("█" * 70)

    try:
        qqq_daily = fetcher.get_daily_bars("QQQ", config.BACKTEST_START, config.BACKTEST_END)
        qqq_intraday = fetcher.get_intraday_bars_bulk("QQQ", valid_dates)

        # Need QQQ-specific enrichment (use SPY's VIX and TLT still)
        qqq_enriched = enrich_daily_data(qqq_daily, vix_daily, tlt_daily, config.ATR_PERIOD)

        qqq_results = run_stock_search("QQQ", qqq_enriched, qqq_intraday, "QQQ")
    except Exception as e:
        print(f"\n  QQQ data fetch error: {e}")
        print("  Continuing with SPY only...")
        qqq_results = []

    # ═══════════════════════════════════════════════════════════════════
    # SAVE RESULTS
    # ═══════════════════════════════════════════════════════════════════
    all_promoted = spy_results + qqq_results

    # Clean for JSON serialization
    def clean_result(r):
        return {k: (float(v) if isinstance(v, (np.floating, np.integer)) else
                    {kk: float(vv) for kk, vv in v.items()} if isinstance(v, dict) and k == "ysh" else
                    v)
                for k, v in r.items()}

    clean_promoted = [clean_result(r) for r in all_promoted]

    with open("stock_search_results.json", "w") as f:
        json.dump(clean_promoted, f, indent=2, default=str)

    elapsed = time.time() - t0
    print(f"\n\n{'='*70}")
    print(f"  ALL COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  SPY promoted: {len(spy_results)}")
    print(f"  QQQ promoted: {len(qqq_results)}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

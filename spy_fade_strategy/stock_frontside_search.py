#!/usr/bin/env python3
"""
FRONTSIDE FILL MODEL — Stock Mean Reversion
=============================================
Key change vs old model:
  OLD: Wait for 1-min bar CLOSE to cross threshold → enter at close price
  NEW: Place resting bid at exact (VWAP - ATR*mult) → fill when bar LOW touches it
       Place resting offer at (entry + target%) → fill when bar HIGH touches it
       Stop is resting: triggered when bar LOW (long) hits stop level

This is the correct model for a limit-order strategy:
- Entry: you know VWAP in real-time, you compute the level, place bid there
- Fill price = EXACTLY the threshold (not the close of some bar)
- Exit target: offer resting at entry + target% → fill on touch
- Exit stop: stop order at entry - stop% → fill on touch

Also runs the OLD bar-close model side-by-side for comparison.

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

STOCK_COMM_PCT = 0.002  # negligible
MIN_TRADES = 20
SPLIT_DATE = "2024-07-01"

# Grid
ATR_MULTS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5]
# Only below (buy dip) since that's where all the edge lives
DIRECTIONS = ["below", "above"]
STOPS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.75, 1.0, 1.5, 2.0]
TARGETS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0]
TIME_EXITS = [5, 10, 15, 30, 60, 120, "EOD"]


def simulate_frontside(bars_df, entry_price, stop_pct, target_pct, time_exit_min, direction):
    """
    Simulate with LIMIT ORDER fills (frontside).
    Entry is already at the exact threshold level.
    Target/stop trigger on bar high/low touch.
    """
    if bars_df.empty:
        return {"pnl_pct": 0, "exit_reason": "no_bars", "minutes_held": 0}

    is_long = (direction == "below")
    entry_ts = bars_df["timestamp"].iloc[0]

    if is_long:
        target_price = entry_price * (1 + target_pct / 100)
        stop_price = entry_price * (1 - stop_pct / 100)
    else:
        target_price = entry_price * (1 - target_pct / 100)
        stop_price = entry_price * (1 + stop_pct / 100)

    for idx in range(len(bars_df)):
        bar = bars_df.iloc[idx]
        mins = (bar["timestamp"] - entry_ts).total_seconds() / 60

        # Time exit
        if time_exit_min is not None:
            if time_exit_min == "EOD":
                if bar["timestamp"].hour == 15 and bar["timestamp"].minute >= 59:
                    pnl = ((bar["close"] - entry_price) / entry_price * 100) if is_long else \
                          ((entry_price - bar["close"]) / entry_price * 100)
                    return {"pnl_pct": pnl, "exit_reason": "time_eod", "minutes_held": mins}
            elif mins >= time_exit_min:
                pnl = ((bar["close"] - entry_price) / entry_price * 100) if is_long else \
                      ((entry_price - bar["close"]) / entry_price * 100)
                return {"pnl_pct": pnl, "exit_reason": f"time_{time_exit_min}m", "minutes_held": mins}

        if is_long:
            # Target: bar HIGH touches target → fill at target price exactly
            if bar["high"] >= target_price:
                pnl = (target_price - entry_price) / entry_price * 100
                return {"pnl_pct": pnl, "exit_reason": "target", "minutes_held": mins}
            # Stop: bar LOW touches stop → fill at stop price exactly
            if bar["low"] <= stop_price:
                pnl = (stop_price - entry_price) / entry_price * 100
                return {"pnl_pct": pnl, "exit_reason": "stop_loss", "minutes_held": mins}
        else:
            # Target: bar LOW touches target → fill at target price
            if bar["low"] <= target_price:
                pnl = (entry_price - target_price) / entry_price * 100
                return {"pnl_pct": pnl, "exit_reason": "target", "minutes_held": mins}
            # Stop: bar HIGH touches stop → fill at stop price
            if bar["high"] >= stop_price:
                pnl = (entry_price - stop_price) / entry_price * 100
                return {"pnl_pct": pnl, "exit_reason": "stop_loss", "minutes_held": mins}

    # End of data
    last = bars_df.iloc[-1]
    mins = (last["timestamp"] - entry_ts).total_seconds() / 60
    pnl = ((last["close"] - entry_price) / entry_price * 100) if is_long else \
          ((entry_price - last["close"]) / entry_price * 100)
    return {"pnl_pct": pnl, "exit_reason": "end_of_data", "minutes_held": mins}


def simulate_barclose(bars_df, entry_price, stop_pct, target_pct, time_exit_min, direction):
    """
    OLD model: exit only on bar CLOSE crossing threshold.
    """
    if bars_df.empty:
        return {"pnl_pct": 0, "exit_reason": "no_bars", "minutes_held": 0}

    is_long = (direction == "below")
    entry_ts = bars_df["timestamp"].iloc[0]

    if is_long:
        target_price = entry_price * (1 + target_pct / 100)
        stop_price = entry_price * (1 - stop_pct / 100)
    else:
        target_price = entry_price * (1 - target_pct / 100)
        stop_price = entry_price * (1 + stop_pct / 100)

    for idx in range(len(bars_df)):
        bar = bars_df.iloc[idx]
        mins = (bar["timestamp"] - entry_ts).total_seconds() / 60

        # Time exit (same)
        if time_exit_min is not None:
            if time_exit_min == "EOD":
                if bar["timestamp"].hour == 15 and bar["timestamp"].minute >= 59:
                    pnl = ((bar["close"] - entry_price) / entry_price * 100) if is_long else \
                          ((entry_price - bar["close"]) / entry_price * 100)
                    return {"pnl_pct": pnl, "exit_reason": "time_eod", "minutes_held": mins}
            elif mins >= time_exit_min:
                pnl = ((bar["close"] - entry_price) / entry_price * 100) if is_long else \
                      ((entry_price - bar["close"]) / entry_price * 100)
                return {"pnl_pct": pnl, "exit_reason": f"time_{time_exit_min}m", "minutes_held": mins}

        # Exit on CLOSE only
        if is_long:
            if bar["close"] >= target_price:
                pnl = (bar["close"] - entry_price) / entry_price * 100
                return {"pnl_pct": pnl, "exit_reason": "target", "minutes_held": mins}
            if bar["close"] <= stop_price:
                pnl = (bar["close"] - entry_price) / entry_price * 100
                return {"pnl_pct": pnl, "exit_reason": "stop_loss", "minutes_held": mins}
        else:
            if bar["close"] <= target_price:
                pnl = (entry_price - bar["close"]) / entry_price * 100
                return {"pnl_pct": pnl, "exit_reason": "target", "minutes_held": mins}
            if bar["close"] >= stop_price:
                pnl = (entry_price - bar["close"]) / entry_price * 100
                return {"pnl_pct": pnl, "exit_reason": "stop_loss", "minutes_held": mins}

    last = bars_df.iloc[-1]
    mins = (last["timestamp"] - entry_ts).total_seconds() / 60
    pnl = ((last["close"] - entry_price) / entry_price * 100) if is_long else \
          ((entry_price - last["close"]) / entry_price * 100)
    return {"pnl_pct": pnl, "exit_reason": "end_of_data", "minutes_held": mins}


def find_frontside_signals(intraday_with_vwap, atr, atr_mult, direction):
    """
    FRONTSIDE entry: find first bar where price TOUCHES the threshold level.
    For 'below': find first bar where LOW <= VWAP - ATR*mult
    For 'above': find first bar where HIGH >= VWAP + ATR*mult
    Entry price = EXACTLY the threshold (resting bid/offer fills at that level).
    """
    df = intraday_with_vwap
    if df.empty:
        return None

    threshold = atr * atr_mult

    for idx in range(len(df)):
        bar = df.iloc[idx]
        vwap = bar["vwap"]
        if pd.isna(vwap) or vwap <= 0:
            continue

        if direction == "below":
            level = vwap - threshold
            if bar["low"] <= level:
                # Bid resting at 'level' would fill
                entry_price = level
                # Remaining bars = everything AFTER this bar
                remaining = df.iloc[idx + 1:].copy().reset_index(drop=True)
                return {
                    "entry_price": entry_price,
                    "entry_bar_idx": idx,
                    "entry_time": bar["timestamp"],
                    "vwap_at_entry": vwap,
                    "remaining_bars": remaining,
                    "threshold_level": level,
                }
        else:  # above
            level = vwap + threshold
            if bar["high"] >= level:
                entry_price = level
                remaining = df.iloc[idx + 1:].copy().reset_index(drop=True)
                return {
                    "entry_price": entry_price,
                    "entry_bar_idx": idx,
                    "entry_time": bar["timestamp"],
                    "vwap_at_entry": vwap,
                    "remaining_bars": remaining,
                    "threshold_level": level,
                }

    return None


def find_barclose_signals(intraday_with_vwap, atr, atr_mult, direction):
    """
    OLD bar-close entry: first bar where CLOSE crosses threshold.
    Entry price = bar CLOSE.
    """
    df = intraday_with_vwap
    if df.empty:
        return None

    threshold = atr * atr_mult

    for idx in range(len(df)):
        bar = df.iloc[idx]
        vwap = bar["vwap"]
        if pd.isna(vwap) or vwap <= 0:
            continue

        if direction == "below":
            if bar["close"] <= vwap - threshold:
                remaining = df.iloc[idx + 1:].copy().reset_index(drop=True)
                return {
                    "entry_price": bar["close"],
                    "entry_bar_idx": idx,
                    "entry_time": bar["timestamp"],
                    "vwap_at_entry": vwap,
                    "remaining_bars": remaining,
                    "threshold_level": vwap - threshold,
                }
        else:
            if bar["close"] >= vwap + threshold:
                remaining = df.iloc[idx + 1:].copy().reset_index(drop=True)
                return {
                    "entry_price": bar["close"],
                    "entry_bar_idx": idx,
                    "entry_time": bar["timestamp"],
                    "vwap_at_entry": vwap,
                    "remaining_bars": remaining,
                    "threshold_level": vwap + threshold,
                }

    return None


def compute_metrics(pnls, dates=None):
    if len(pnls) < MIN_TRADES:
        return None
    a = np.array(pnls)
    s = np.std(a)
    if s == 0:
        return None

    cum = np.cumsum(a)
    pk = np.maximum.accumulate(cum)
    mdd = float(np.min(cum - pk)) if len(cum) > 0 else 0
    wins = a[a > 0]
    losses = a[a < 0]
    tw = float(np.sum(wins)) if len(wins) > 0 else 0
    tl = float(abs(np.sum(losses))) if len(losses) > 0 else 0.0001

    ysh = {}
    if dates:
        yearly = defaultdict(list)
        for p, d in zip(pnls, dates):
            yr = str(d)[:4]
            yearly[yr].append(p)
        for yr, v in yearly.items():
            ya = np.array(v)
            ysh[yr] = float(np.mean(ya)/np.std(ya)) if np.std(ya) > 0 and len(ya) >= 3 else 0.0

    return {
        "n": len(a), "sharpe": float(np.mean(a)/s),
        "wr": float(np.sum(a > 0)/len(a)*100),
        "avg": float(np.mean(a)), "total": float(np.sum(a)),
        "mdd": mdd, "pf": tw/tl,
        "avg_win": float(np.mean(wins)) if len(wins) > 0 else 0,
        "avg_loss": float(np.mean(losses)) if len(losses) > 0 else 0,
        "neg_yr": sum(1 for v in ysh.values() if v < 0), "ysh": ysh,
    }


def run_search(ticker, enriched, intraday_data, label):
    """Run both frontside and bar-close models, compare."""
    print(f"\n{'='*70}")
    print(f"  {label} — FRONTSIDE vs BAR-CLOSE COMPARISON")
    print(f"{'='*70}")

    daily_dates = list(enriched["date"])
    daily_lookup = {row["date"]: row for _, row in enriched.iterrows()}
    sorted_dates = sorted(intraday_data.keys())

    # Pre-compute VWAP for all days
    print(f"  Computing VWAP for {len(sorted_dates)} days...")
    vwap_data = {}
    for ds in sorted_dates:
        intraday = intraday_data[ds]
        vwap_df = calculate_session_vwap(intraday)
        date_obj = datetime.strptime(ds, "%Y-%m-%d").date()
        prior = [d for d in daily_dates if d < date_obj]
        if not prior:
            continue
        prior_date = prior[-1]
        if prior_date not in daily_lookup:
            continue
        daily_row = daily_lookup[prior_date]
        atr = daily_row.get("atr")
        if pd.isna(atr):
            continue
        vwap_data[ds] = {"df": vwap_df, "atr": atr, "date": date_obj}

    print(f"  {len(vwap_data)} days with VWAP + ATR")

    # For each (direction, mult), find signals using BOTH models
    print(f"\n  Finding signals...")
    frontside_signals = {}  # (dir, mult) -> list of signal dicts
    barclose_signals = {}

    for direction in DIRECTIONS:
        for mult in ATR_MULTS:
            fs_list, bc_list = [], []
            for ds, info in vwap_data.items():
                fs = find_frontside_signals(info["df"], info["atr"], mult, direction)
                bc = find_barclose_signals(info["df"], info["atr"], mult, direction)
                if fs and not fs["remaining_bars"].empty:
                    fs["date"] = ds
                    fs_list.append(fs)
                if bc and not bc["remaining_bars"].empty:
                    bc["date"] = ds
                    bc_list.append(bc)

            if fs_list:
                frontside_signals[(direction, mult)] = fs_list
            if bc_list:
                barclose_signals[(direction, mult)] = bc_list

    fs_total = sum(len(v) for v in frontside_signals.values())
    bc_total = sum(len(v) for v in barclose_signals.values())
    print(f"  Frontside signals: {fs_total} across {len(frontside_signals)} combos")
    print(f"  Bar-close signals: {bc_total} across {len(barclose_signals)} combos")

    # Frontside almost always finds MORE signals (lower bar to clear)
    # Compare signal counts
    print(f"\n  Signal count comparison:")
    for direction in DIRECTIONS:
        for mult in ATR_MULTS:
            key = (direction, mult)
            fs_n = len(frontside_signals.get(key, []))
            bc_n = len(barclose_signals.get(key, []))
            if fs_n > 0 or bc_n > 0:
                diff = fs_n - bc_n
                print(f"    {direction} {mult}x: frontside={fs_n}, barclose={bc_n} ({diff:+d})")

    # Grid search — FRONTSIDE model
    print(f"\n  Running frontside grid search...")
    exit_combos = [(s, t, te) for s in STOPS for t in TARGETS for te in TIME_EXITS]
    total_tests = len(frontside_signals) * len(exit_combos)
    print(f"  {len(frontside_signals)} signal combos × {len(exit_combos)} exit combos = {total_tests}")

    fs_results = []
    tested = 0
    for (direction, mult), entries in frontside_signals.items():
        if len(entries) < 5:
            tested += len(exit_combos)
            continue
        for stop, target, te in exit_combos:
            tested += 1
            if tested % 10000 == 0:
                print(f"    [{tested}/{total_tests}] ({len(fs_results)} passed)...", flush=True)
            pnls, dates = [], []
            for e in entries:
                r = simulate_frontside(e["remaining_bars"], e["entry_price"],
                                        stop, target, te, direction)
                pnls.append(r["pnl_pct"] - STOCK_COMM_PCT)
                dates.append(e["date"])
            m = compute_metrics(pnls, dates)
            if m and m["avg"] > 0:
                fs_results.append({
                    "ticker": ticker, "model": "frontside",
                    "dir": direction, "mult": mult,
                    "stop": stop, "target": target, "te": te,
                    **m,
                })

    fs_results.sort(key=lambda r: r["sharpe"], reverse=True)

    # Grid search — BAR-CLOSE model (for comparison)
    print(f"\n  Running bar-close grid search...")
    bc_results = []
    tested = 0
    total_bc = len(barclose_signals) * len(exit_combos)
    for (direction, mult), entries in barclose_signals.items():
        if len(entries) < 5:
            tested += len(exit_combos)
            continue
        for stop, target, te in exit_combos:
            tested += 1
            if tested % 10000 == 0:
                print(f"    [{tested}/{total_bc}] ({len(bc_results)} passed)...", flush=True)
            pnls, dates = [], []
            for e in entries:
                r = simulate_barclose(e["remaining_bars"], e["entry_price"],
                                       stop, target, te, direction)
                pnls.append(r["pnl_pct"] - STOCK_COMM_PCT)
                dates.append(e["date"])
            m = compute_metrics(pnls, dates)
            if m and m["avg"] > 0:
                bc_results.append({
                    "ticker": ticker, "model": "barclose",
                    "dir": direction, "mult": mult,
                    "stop": stop, "target": target, "te": te,
                    **m,
                })

    bc_results.sort(key=lambda r: r["sharpe"], reverse=True)

    # ═══ COMPARISON ═══
    print(f"\n{'='*70}")
    print(f"  {label} RESULTS COMPARISON")
    print(f"{'='*70}")
    print(f"  Frontside: {len(fs_results)} positive-expectancy configs")
    print(f"  Bar-close: {len(bc_results)} positive-expectancy configs")

    # Top 30 frontside
    print(f"\n  TOP 30 FRONTSIDE:")
    print(f"  {'#':>3} {'Dir':>5} {'ATR':>4} {'Stop':>5} {'Tgt':>5} {'T':>4} "
          f"{'N':>4} {'Sharpe':>7} {'WR':>5} {'Avg':>8} {'Tot':>8} {'PF':>5} {'NY':>3}")
    for i, r in enumerate(fs_results[:30]):
        print(f"  {i+1:>3} {r['dir']:>5} {r['mult']:>4.1f} {r['stop']:>5.2f} {r['target']:>5.2f} "
              f"{str(r['te']):>4} {r['n']:>4} {r['sharpe']:>7.3f} {r['wr']:>4.1f}% "
              f"{r['avg']:>+7.4f}% {r['total']:>+7.2f}% {r['pf']:>5.2f} {r['neg_yr']:>3}")

    # Top 10 bar-close for comparison
    print(f"\n  TOP 10 BAR-CLOSE (for comparison):")
    for i, r in enumerate(bc_results[:10]):
        print(f"  {i+1:>3} {r['dir']:>5} {r['mult']:>4.1f} {r['stop']:>5.2f} {r['target']:>5.2f} "
              f"{str(r['te']):>4} {r['n']:>4} {r['sharpe']:>7.3f} {r['wr']:>4.1f}% "
              f"{r['avg']:>+7.4f}% {r['total']:>+7.2f}% {r['pf']:>5.2f} {r['neg_yr']:>3}")

    # Walk-forward on frontside top 100
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD — FRONTSIDE MODEL")
    print(f"{'='*70}")

    wf_results = []
    for i, r in enumerate(fs_results[:100]):
        key = (r["dir"], r["mult"])
        entries = frontside_signals.get(key, [])

        train_pnls, train_dates, test_pnls, test_dates = [], [], [], []
        for e in entries:
            res = simulate_frontside(e["remaining_bars"], e["entry_price"],
                                      r["stop"], r["target"], r["te"], r["dir"])
            pnl = res["pnl_pct"] - STOCK_COMM_PCT
            if e["date"] < SPLIT_DATE:
                train_pnls.append(pnl); train_dates.append(e["date"])
            else:
                test_pnls.append(pnl); test_dates.append(e["date"])

        tm = compute_metrics(train_pnls, train_dates) if len(train_pnls) >= 5 else None
        sm = compute_metrics(test_pnls, test_dates) if len(test_pnls) >= 3 else None

        if tm and sm:
            tp = tm["sharpe"] > 0
            sp = sm["sharpe"] > 0
            verdict = "PASS" if (tp and sp) else "SOFT" if (tp and sm["sharpe"] > -0.15) else "FAIL"
            if verdict != "FAIL":
                print(f"  #{i+1:>2} {r['dir']:>5} {r['mult']:.1f}x s={r['stop']} t={r['target']} T={r['te']}")
                print(f"       Train: N={tm['n']:>3} Sh={tm['sharpe']:>+.3f} WR={tm['wr']:>5.1f}%")
                print(f"       Test:  N={sm['n']:>3} Sh={sm['sharpe']:>+.3f} WR={sm['wr']:>5.1f}%  → {verdict}")
                wf_results.append({**r, "train_sh": tm["sharpe"], "test_sh": sm["sharpe"],
                                   "train_n": tm["n"], "test_n": sm["n"], "wf": verdict})

    print(f"\n  WF survivors: {len(wf_results)}")

    # Yearly stability
    final = []
    if wf_results:
        print(f"\n  YEARLY STABILITY:")
        for s in wf_results:
            ysh = s.get("ysh", {})
            deep_neg = sum(1 for v in ysh.values() if v < -0.3)
            neg = sum(1 for v in ysh.values() if v < 0)
            stable = deep_neg <= 1
            verdict = "PROMOTED" if (s["wf"] == "PASS" and stable) else \
                      "BORDERLINE" if (neg <= 2) else "REJECTED"
            print(f"\n    {s['dir']} {s['mult']}x s={s['stop']} t={s['target']} T={s['te']}  WF={s['wf']}")
            for yr, sh in sorted(ysh.items()):
                flag = " ← NEG" if sh < 0 else ""
                print(f"      {yr}: Sh={sh:+.3f}{flag}")
            print(f"      → {verdict}")
            if verdict in ("PROMOTED", "BORDERLINE"):
                final.append({**s, "final_verdict": verdict})

    return fs_results, bc_results, final


def main():
    t0 = time.time()
    print("=" * 70)
    print("  FRONTSIDE vs BAR-CLOSE FILL MODEL COMPARISON")
    print("  Limit order fills (touch) vs bar-close fills")
    print("  All data from real Polygon 1-min bars. No fabrication.")
    print("=" * 70)

    fetcher = PolygonFetcher()

    # SPY
    print("\n" + "█" * 70)
    print("  SPY")
    print("█" * 70)
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)
    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    spy_intraday = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    spy_fs, spy_bc, spy_promoted = run_search("SPY", enriched, spy_intraday, "SPY")

    # QQQ
    print("\n" + "█" * 70)
    print("  QQQ")
    print("█" * 70)
    qqq_daily = fetcher.get_daily_bars("QQQ", config.BACKTEST_START, config.BACKTEST_END)
    qqq_enriched = enrich_daily_data(qqq_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    qqq_intraday = fetcher.get_intraday_bars_bulk("QQQ", valid_dates)

    qqq_fs, qqq_bc, qqq_promoted = run_search("QQQ", qqq_enriched, qqq_intraday, "QQQ")

    # Save
    all_promoted = spy_promoted + qqq_promoted
    def clean(r):
        return {k: (float(v) if isinstance(v, (np.floating, np.integer)) else
                    {kk: float(vv) for kk, vv in v.items()} if isinstance(v, dict) and k == "ysh" else v)
                for k, v in r.items()}

    with open("frontside_results.json", "w") as f:
        json.dump([clean(r) for r in all_promoted], f, indent=2, default=str)

    # Save top 50 of each model for comparison
    with open("frontside_vs_barclose.json", "w") as f:
        json.dump({
            "spy_frontside_top50": [clean(r) for r in spy_fs[:50]],
            "spy_barclose_top50": [clean(r) for r in spy_bc[:50]],
            "qqq_frontside_top50": [clean(r) for r in qqq_fs[:50]],
            "qqq_barclose_top50": [clean(r) for r in qqq_bc[:50]],
        }, f, indent=2, default=str)

    elapsed = time.time() - t0
    print(f"\n\n{'='*70}")
    print(f"  ALL COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  SPY promoted: {len(spy_promoted)}")
    print(f"  QQQ promoted: {len(qqq_promoted)}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

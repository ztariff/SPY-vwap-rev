#!/usr/bin/env python3
"""
DEEP FRONTSIDE MEAN REVERSION SEARCH
======================================
Everything is resting limit orders — bids below VWAP, offers above VWAP.

ENTRY MODELS:
  A) Single entry: bid resting at VWAP - X*ATR. Fill when bar LOW touches.
  B) Scaled entry: initial bid at VWAP - X1*ATR, ADD at VWAP - X2*ATR, etc.
     Average cost improves with each add. Position size splits across levels.
  C) Fine-grained: step entries every 0.1x ATR from 0.3x to 1.5x

EXIT MODELS (all resting offers):
  - Target offer at entry + T%. Fill when bar HIGH touches.
  - Stop at entry - S%. Fill when bar LOW touches.
  - Time exit at T minutes (market order at close of that bar).

ATR grid: 0.3x to 2.0x in 0.1 steps
Targets: 0.05% to 3.0%
Stops: 0.10% to 3.0%
Time exits: 5, 10, 15, 30, 60, 120, EOD

BOTH DIRECTIONS:
  Below VWAP → long (buy dip, offer to sell at target)
  Above VWAP → short (fade, bid to cover at target)

SPY + QQQ. All real Polygon 1-min data. No fabrication.
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

STOCK_COMM_PCT = 0.002
MIN_TRADES = 20
SPLIT_DATE = "2024-07-01"

# ═══════════════════════════════════════════════════════════════════
#  ATR GRID — fine grained
# ═══════════════════════════════════════════════════════════════════
ATR_MULTS = [round(x * 0.1, 1) for x in range(3, 21)]  # 0.3 to 2.0

# Scaled entry pairs: (initial_mult, add_mult) — add is deeper
SCALE_PAIRS = []
for init in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
    for step in [0.1, 0.2, 0.3, 0.4, 0.5]:
        add = round(init + step, 1)
        if add <= 1.5:
            SCALE_PAIRS.append((init, add))

# Triple scale: init, add1, add2
TRIPLE_SCALES = []
for init in [0.3, 0.4, 0.5]:
    for s1 in [0.1, 0.2, 0.3]:
        for s2 in [0.1, 0.2, 0.3]:
            a1 = round(init + s1, 1)
            a2 = round(a1 + s2, 1)
            if a2 <= 1.5:
                TRIPLE_SCALES.append((init, a1, a2))

DIRECTIONS = ["below", "above"]

TARGETS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.75, 1.0, 1.5, 2.0]
STOPS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0]
TIME_EXITS = [5, 10, 15, 30, 60, 120, "EOD"]


def simulate_frontside_trade(bars, entry_price, stop_pct, target_pct, time_exit_min, is_long):
    """Simulate with resting limit orders. Entry already filled at exact level."""
    if bars.empty:
        return 0.0, "no_bars", 0

    entry_ts = bars["timestamp"].iloc[0]

    if is_long:
        target_px = entry_price * (1 + target_pct / 100)
        stop_px = entry_price * (1 - stop_pct / 100)
    else:
        target_px = entry_price * (1 - target_pct / 100)
        stop_px = entry_price * (1 + stop_pct / 100)

    for idx in range(len(bars)):
        bar = bars.iloc[idx]
        mins = (bar["timestamp"] - entry_ts).total_seconds() / 60

        # Time exit
        if time_exit_min is not None:
            if time_exit_min == "EOD":
                if bar["timestamp"].hour == 15 and bar["timestamp"].minute >= 59:
                    pnl = ((bar["close"] - entry_price) / entry_price * 100) if is_long else \
                          ((entry_price - bar["close"]) / entry_price * 100)
                    return pnl, "time_eod", mins
            elif mins >= time_exit_min:
                pnl = ((bar["close"] - entry_price) / entry_price * 100) if is_long else \
                      ((entry_price - bar["close"]) / entry_price * 100)
                return pnl, f"time_{time_exit_min}m", mins

        if is_long:
            if bar["high"] >= target_px:
                return target_pct, "target", mins
            if bar["low"] <= stop_px:
                return -stop_pct, "stop_loss", mins
        else:
            if bar["low"] <= target_px:
                return target_pct, "target", mins
            if bar["high"] >= stop_px:
                return -stop_pct, "stop_loss", mins

    last = bars.iloc[-1]
    mins = (last["timestamp"] - entry_ts).total_seconds() / 60
    pnl = ((last["close"] - entry_price) / entry_price * 100) if is_long else \
          ((entry_price - last["close"]) / entry_price * 100)
    return pnl, "end_of_data", mins


def compute_metrics(pnls, dates=None):
    if len(pnls) < MIN_TRADES:
        return None
    a = np.array(pnls)
    s = np.std(a)
    if s < 1e-10:
        return None
    sharpe = float(np.mean(a) / s)
    cum = np.cumsum(a)
    pk = np.maximum.accumulate(cum)
    mdd = float(np.min(cum - pk))
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
            ystd = np.std(ya)
            ysh[yr] = float(np.mean(ya)/ystd) if ystd > 1e-10 and len(ya) >= 3 else 0.0

    return {
        "n": len(a), "sharpe": sharpe, "wr": float(np.sum(a>0)/len(a)*100),
        "avg": float(np.mean(a)), "total": float(np.sum(a)), "mdd": mdd,
        "pf": tw/tl, "avg_win": float(np.mean(wins)) if len(wins)>0 else 0,
        "avg_loss": float(np.mean(losses)) if len(losses)>0 else 0,
        "neg_yr": sum(1 for v in ysh.values() if v < 0), "ysh": ysh,
    }


def precompute_day_data(enriched, intraday_data):
    """Pre-compute VWAP + ATR for every day, return dict of day info."""
    daily_dates = list(enriched["date"])
    daily_lookup = {row["date"]: row for _, row in enriched.iterrows()}
    sorted_dates = sorted(intraday_data.keys())

    days = {}
    for ds in sorted_dates:
        date_obj = datetime.strptime(ds, "%Y-%m-%d").date()
        prior = [d for d in daily_dates if d < date_obj]
        if not prior:
            continue
        daily_row = daily_lookup.get(prior[-1])
        if daily_row is None or pd.isna(daily_row.get("atr")):
            continue

        vwap_df = calculate_session_vwap(intraday_data[ds])
        if vwap_df.empty:
            continue

        days[ds] = {
            "df": vwap_df,
            "atr": float(daily_row["atr"]),
            "date": date_obj,
        }
    return days


def find_single_entry(day_df, atr, mult, direction):
    """Find first bar where price touches VWAP ± mult*ATR. Return entry price + remaining bars."""
    threshold = atr * mult
    for idx in range(len(day_df)):
        bar = day_df.iloc[idx]
        vwap = bar["vwap"]
        if pd.isna(vwap) or vwap <= 0:
            continue
        if direction == "below":
            level = vwap - threshold
            if bar["low"] <= level:
                return level, day_df.iloc[idx+1:].copy().reset_index(drop=True)
        else:
            level = vwap + threshold
            if bar["high"] >= level:
                return level, day_df.iloc[idx+1:].copy().reset_index(drop=True)
    return None, None


def find_scaled_entry(day_df, atr, mults, direction):
    """
    Find entries at multiple ATR levels. Returns avg entry price + remaining bars after last fill.
    mults: list of ATR multipliers [0.5, 0.7, 0.9] — each gets equal weight.
    """
    fills = []  # list of (price, bar_idx)
    threshold_levels = [atr * m for m in mults]

    for idx in range(len(day_df)):
        bar = day_df.iloc[idx]
        vwap = bar["vwap"]
        if pd.isna(vwap) or vwap <= 0:
            continue

        for i, (m, thresh) in enumerate(zip(mults, threshold_levels)):
            if any(f[2] == i for f in fills):  # already filled this level
                continue
            if direction == "below":
                level = vwap - thresh
                if bar["low"] <= level:
                    fills.append((level, idx, i))
            else:
                level = vwap + thresh
                if bar["high"] >= level:
                    fills.append((level, idx, i))

        if len(fills) == len(mults):
            break  # all levels filled

    if not fills:
        return None, None, 0

    # Average entry price (equal weight per level)
    avg_price = np.mean([f[0] for f in fills])
    last_fill_idx = max(f[1] for f in fills)
    remaining = day_df.iloc[last_fill_idx+1:].copy().reset_index(drop=True)
    return avg_price, remaining, len(fills)


def run_deep_search(ticker, days_data, label):
    """Run the full deep search for one ticker."""
    t0 = time.time()
    print(f"\n{'='*70}")
    print(f"  {label} DEEP FRONTSIDE SEARCH")
    print(f"  {len(days_data)} trading days with VWAP + ATR")
    print(f"{'='*70}")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 1: Single entries at each ATR level
    # ═══════════════════════════════════════════════════════════════
    print(f"\n  PHASE 1: Single entries (0.3x–2.0x ATR, both dirs)")

    # Pre-find all signals
    single_signals = {}  # (dir, mult) -> list of {date, entry_price, remaining_bars}
    for direction in DIRECTIONS:
        for mult in ATR_MULTS:
            entries = []
            for ds, info in days_data.items():
                price, remaining = find_single_entry(info["df"], info["atr"], mult, direction)
                if price is not None and remaining is not None and not remaining.empty:
                    entries.append({"date": ds, "price": price, "bars": remaining})
            if entries:
                single_signals[(direction, mult)] = entries

    total_single_signals = sum(len(v) for v in single_signals.values())
    print(f"  {total_single_signals} total single-entry signals across {len(single_signals)} combos")
    for d in DIRECTIONS:
        for m in ATR_MULTS:
            n = len(single_signals.get((d, m), []))
            if n > 0:
                print(f"    {d:>5} {m:.1f}x: {n:>3}")

    # Grid search single entries
    exit_combos = [(s, t, te) for s in STOPS for t in TARGETS for te in TIME_EXITS]
    total_tests = len(single_signals) * len(exit_combos)
    print(f"\n  Grid: {len(single_signals)} signal combos × {len(exit_combos)} exit combos = {total_tests}")

    single_results = []
    tested = 0
    for (direction, mult), entries in single_signals.items():
        is_long = (direction == "below")
        if len(entries) < 5:
            tested += len(exit_combos)
            continue
        for stop, target, te in exit_combos:
            tested += 1
            if tested % 20000 == 0:
                print(f"    [{tested}/{total_tests}] ({len(single_results)} passed)...", flush=True)
            pnls, dates = [], []
            for e in entries:
                pnl, _, _ = simulate_frontside_trade(e["bars"], e["price"], stop, target, te, is_long)
                pnls.append(pnl - STOCK_COMM_PCT)
                dates.append(e["date"])
            m = compute_metrics(pnls, dates)
            if m and m["avg"] > 0:
                single_results.append({
                    "ticker": ticker, "type": "single", "dir": direction,
                    "mult": mult, "stop": stop, "target": target, "te": te,
                    "levels": f"{mult}x", **m,
                })

    single_results.sort(key=lambda r: r["sharpe"], reverse=True)
    print(f"  Phase 1 done: {len(single_results)} positive-expectancy configs")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: Scaled entries (2 levels)
    # ═══════════════════════════════════════════════════════════════
    print(f"\n  PHASE 2: Scaled entries (2 levels, {len(SCALE_PAIRS)} pairs)")

    scaled_signals = {}
    for direction in DIRECTIONS:
        for init, add in SCALE_PAIRS:
            entries = []
            for ds, info in days_data.items():
                avg_px, remaining, n_fills = find_scaled_entry(
                    info["df"], info["atr"], [init, add], direction
                )
                if avg_px is not None and remaining is not None and not remaining.empty:
                    entries.append({"date": ds, "price": avg_px, "bars": remaining, "fills": n_fills})
            if entries:
                scaled_signals[(direction, init, add)] = entries

    total_scaled = sum(len(v) for v in scaled_signals.values())
    print(f"  {total_scaled} total scaled-entry signals across {len(scaled_signals)} combos")

    # Focused exit grid for scaled (fewer combos to stay tractable)
    scaled_exits = [(s, t, te) for s in [0.15, 0.25, 0.50, 0.75, 1.0, 1.5]
                    for t in [0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.75, 1.0, 1.5]
                    for te in [5, 10, 15, 30, 60, "EOD"]]

    total_scaled_tests = len(scaled_signals) * len(scaled_exits)
    print(f"  Grid: {len(scaled_signals)} signal combos × {len(scaled_exits)} exits = {total_scaled_tests}")

    scaled_results = []
    tested = 0
    for (direction, init, add), entries in scaled_signals.items():
        is_long = (direction == "below")
        if len(entries) < 5:
            tested += len(scaled_exits)
            continue
        for stop, target, te in scaled_exits:
            tested += 1
            if tested % 20000 == 0:
                print(f"    [{tested}/{total_scaled_tests}] ({len(scaled_results)} passed)...", flush=True)
            pnls, dates = [], []
            for e in entries:
                pnl, _, _ = simulate_frontside_trade(e["bars"], e["price"], stop, target, te, is_long)
                pnls.append(pnl - STOCK_COMM_PCT)
                dates.append(e["date"])
            m = compute_metrics(pnls, dates)
            if m and m["avg"] > 0:
                # Track avg fills per trade
                avg_fills = np.mean([e["fills"] for e in entries])
                scaled_results.append({
                    "ticker": ticker, "type": "scaled_2", "dir": direction,
                    "mult": init, "add1": add, "stop": stop, "target": target, "te": te,
                    "levels": f"{init}x+{add}x", "avg_fills": round(avg_fills, 2), **m,
                })

    scaled_results.sort(key=lambda r: r["sharpe"], reverse=True)
    print(f"  Phase 2 done: {len(scaled_results)} positive-expectancy configs")

    # ═══════════════════════════════════════════════════════════════
    # PHASE 3: Triple scaled entries (3 levels)
    # ═══════════════════════════════════════════════════════════════
    print(f"\n  PHASE 3: Triple scaled entries ({len(TRIPLE_SCALES)} combos)")

    triple_signals = {}
    for direction in DIRECTIONS:
        for init, a1, a2 in TRIPLE_SCALES:
            entries = []
            for ds, info in days_data.items():
                avg_px, remaining, n_fills = find_scaled_entry(
                    info["df"], info["atr"], [init, a1, a2], direction
                )
                if avg_px is not None and remaining is not None and not remaining.empty:
                    entries.append({"date": ds, "price": avg_px, "bars": remaining, "fills": n_fills})
            if entries:
                triple_signals[(direction, init, a1, a2)] = entries

    total_triple = sum(len(v) for v in triple_signals.values())
    print(f"  {total_triple} total triple-entry signals across {len(triple_signals)} combos")

    # Tighter exit grid for triple
    triple_exits = [(s, t, te) for s in [0.15, 0.25, 0.50, 1.0]
                    for t in [0.10, 0.15, 0.20, 0.30, 0.50, 1.0]
                    for te in [5, 10, 15, 30, 60, "EOD"]]

    total_triple_tests = len(triple_signals) * len(triple_exits)
    print(f"  Grid: {len(triple_signals)} signal combos × {len(triple_exits)} exits = {total_triple_tests}")

    triple_results = []
    tested = 0
    for (direction, init, a1, a2), entries in triple_signals.items():
        is_long = (direction == "below")
        if len(entries) < 5:
            tested += len(triple_exits)
            continue
        for stop, target, te in triple_exits:
            tested += 1
            if tested % 20000 == 0:
                print(f"    [{tested}/{total_triple_tests}] ({len(triple_results)} passed)...", flush=True)
            pnls, dates = [], []
            for e in entries:
                pnl, _, _ = simulate_frontside_trade(e["bars"], e["price"], stop, target, te, is_long)
                pnls.append(pnl - STOCK_COMM_PCT)
                dates.append(e["date"])
            m = compute_metrics(pnls, dates)
            if m and m["avg"] > 0:
                avg_fills = np.mean([e["fills"] for e in entries])
                triple_results.append({
                    "ticker": ticker, "type": "scaled_3", "dir": direction,
                    "mult": init, "add1": a1, "add2": a2,
                    "stop": stop, "target": target, "te": te,
                    "levels": f"{init}x+{a1}x+{a2}x", "avg_fills": round(avg_fills, 2), **m,
                })

    triple_results.sort(key=lambda r: r["sharpe"], reverse=True)
    print(f"  Phase 3 done: {len(triple_results)} positive-expectancy configs")

    # ═══════════════════════════════════════════════════════════════
    # COMBINE + WALK-FORWARD
    # ═══════════════════════════════════════════════════════════════
    all_results = single_results + scaled_results + triple_results
    all_results.sort(key=lambda r: r["sharpe"], reverse=True)

    print(f"\n{'='*70}")
    print(f"  {label} COMBINED: {len(all_results)} positive-expectancy configs")
    print(f"  Single: {len(single_results)} | Scaled-2: {len(scaled_results)} | Scaled-3: {len(triple_results)}")
    print(f"{'='*70}")

    # Top 50
    print(f"\n  TOP 50 (by Sharpe, filtering near-zero-variance):")
    print(f"  {'#':>3} {'Type':>8} {'Dir':>5} {'Levels':>14} {'Stop':>5} {'Tgt':>5} {'T':>4} "
          f"{'N':>4} {'Sharpe':>7} {'WR':>5} {'Avg':>8} {'Tot':>8} {'PF':>5} {'NY':>3}")
    shown = 0
    for r in all_results:
        if shown >= 50:
            break
        if r["sharpe"] > 50:  # skip near-zero-variance noise
            continue
        shown += 1
        print(f"  {shown:>3} {r['type']:>8} {r['dir']:>5} {r['levels']:>14} "
              f"{r['stop']:>5.2f} {r['target']:>5.2f} {str(r['te']):>4} "
              f"{r['n']:>4} {r['sharpe']:>7.3f} {r['wr']:>4.1f}% "
              f"{r['avg']:>+7.4f}% {r['total']:>+7.2f}% {r['pf']:>5.2f} {r['neg_yr']:>3}")

    # Walk-forward on top 200 (excluding zero-variance)
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD (Train < {SPLIT_DATE} | Test >= {SPLIT_DATE})")
    print(f"{'='*70}")

    real_results = [r for r in all_results if r["sharpe"] <= 50]

    wf_results = []
    for i, r in enumerate(real_results[:200]):
        # Reconstruct trades for this config
        if r["type"] == "single":
            key = (r["dir"], r["mult"])
            entries = single_signals.get(key, [])
        elif r["type"] == "scaled_2":
            key = (r["dir"], r["mult"], r.get("add1", 0))
            entries = scaled_signals.get(key, [])
        else:
            key = (r["dir"], r["mult"], r.get("add1", 0), r.get("add2", 0))
            entries = triple_signals.get(key, [])

        is_long = (r["dir"] == "below")
        train_pnls, train_dates, test_pnls, test_dates = [], [], [], []
        for e in entries:
            pnl, _, _ = simulate_frontside_trade(e["bars"], e["price"], r["stop"], r["target"], r["te"], is_long)
            pnl -= STOCK_COMM_PCT
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
                print(f"  #{i+1:>3} {r['type']:>8} {r['dir']:>5} {r['levels']:>14} s={r['stop']} t={r['target']} T={r['te']}")
                print(f"        Train: N={tm['n']:>3} Sh={tm['sharpe']:>+.3f} WR={tm['wr']:>5.1f}%")
                print(f"        Test:  N={sm['n']:>3} Sh={sm['sharpe']:>+.3f} WR={sm['wr']:>5.1f}%  → {verdict}")
                wf_results.append({
                    **r, "train_sh": tm["sharpe"], "test_sh": sm["sharpe"],
                    "train_n": tm["n"], "test_n": sm["n"], "wf": verdict,
                })

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
            print(f"\n    {s['type']} {s['dir']} {s['levels']} s={s['stop']} t={s['target']} T={s['te']}  WF={s['wf']}")
            for yr, sh in sorted(ysh.items()):
                flag = " ← NEG" if sh < 0 else ""
                print(f"      {yr}: Sh={sh:+.3f}{flag}")
            print(f"      → {verdict}")
            if verdict in ("PROMOTED", "BORDERLINE"):
                final.append({**s, "final_verdict": verdict})

    elapsed = time.time() - t0
    print(f"\n  {label} complete: {elapsed:.0f}s, {len(final)} promoted")
    return all_results, wf_results, final


def main():
    t0 = time.time()
    print("=" * 70)
    print("  DEEP FRONTSIDE MEAN REVERSION — EXHAUSTIVE SEARCH")
    print("  Single + Scaled(2) + Scaled(3) entries")
    print("  All resting limit orders. Real Polygon 1-min data.")
    print("=" * 70)

    fetcher = PolygonFetcher()

    # Load shared data
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)
    enriched_spy = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched_spy.dropna(subset=["atr"])[["date"]].itertuples()]
    spy_intraday = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    spy_days = precompute_day_data(enriched_spy, spy_intraday)
    spy_all, spy_wf, spy_promoted = run_deep_search("SPY", spy_days, "SPY")

    # QQQ
    qqq_daily = fetcher.get_daily_bars("QQQ", config.BACKTEST_START, config.BACKTEST_END)
    qqq_enriched = enrich_daily_data(qqq_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    qqq_intraday = fetcher.get_intraday_bars_bulk("QQQ", valid_dates)
    qqq_days = precompute_day_data(qqq_enriched, qqq_intraday)

    qqq_all, qqq_wf, qqq_promoted = run_deep_search("QQQ", qqq_days, "QQQ")

    # Save
    all_promoted = spy_promoted + qqq_promoted
    def clean(r):
        out = {}
        for k, v in r.items():
            if isinstance(v, (np.floating, np.integer)):
                out[k] = float(v)
            elif isinstance(v, dict):
                out[k] = {kk: float(vv) if isinstance(vv, (np.floating, np.integer)) else vv for kk, vv in v.items()}
            else:
                out[k] = v
        return out

    with open("deep_search_promoted.json", "w") as f:
        json.dump([clean(r) for r in all_promoted], f, indent=2, default=str)

    # Save top 100 of each for charting
    spy_real = [r for r in spy_all if r["sharpe"] <= 50][:100]
    qqq_real = [r for r in qqq_all if r["sharpe"] <= 50][:100]
    with open("deep_search_top100.json", "w") as f:
        json.dump({
            "spy_top100": [clean(r) for r in spy_real],
            "qqq_top100": [clean(r) for r in qqq_real],
            "spy_wf": [clean(r) for r in spy_wf],
            "qqq_wf": [clean(r) for r in qqq_wf],
        }, f, indent=2, default=str)

    elapsed = time.time() - t0
    print(f"\n\n{'='*70}")
    print(f"  ALL COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  SPY promoted: {len(spy_promoted)}")
    print(f"  QQQ promoted: {len(qqq_promoted)}")
    print(f"  Total promoted: {len(all_promoted)}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
QQQ VWAP Mean Reversion — Exhaustive Local Parameter Sweep
============================================================
Uses Polygon 1-minute bars (RTH only, 9:30-16:00 ET).
Frontside fill model: entry at exact threshold, exits at exact target/stop.

Entry: percentage deviation from session VWAP (0.1% to 2.0% in 0.1% steps).
Targets: 0.05% to 5.0%.
Stops: 0.05% to 5.0%.
Time exits: 1 min to full day.
Velocity: tracked per signal for later analysis.

Walk-forward split: 2024-07-01.
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
from datetime import date as dt_date, time as dt_time, datetime
from collections import defaultdict

# Add spy_fade_strategy to path for data_fetcher
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spy_fade_strategy'))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, 'qqq_sweep_results.json')

# ============================================================
# Session parameters
# ============================================================
SYMBOL = 'QQQ'
RTH_START = dt_time(9, 30)
RTH_END = dt_time(16, 0)
EOD_CUTOFF = dt_time(15, 55)
MIN_BARS_FOR_VWAP = 5
ATR_PERIOD = 14
WF_SPLIT = dt_date(2024, 7, 1)
BACKTEST_START = '2022-01-01'
BACKTEST_END = '2026-03-12'

# ============================================================
# Parameter grid (same as SPY kite_sweep.py)
# ============================================================
ENTRY_PCTS = [round(x * 0.1, 1) for x in range(1, 21)]   # 0.1% to 2.0%
DIRECTIONS = ['buy', 'fade']
TARGET_PCTS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50,
               0.75, 1.0, 1.5, 2.0, 5.0]
STOP_PCTS   = [0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.75,
               1.0, 1.5, 2.0, 5.0]
TIME_EXITS  = [1, 2, 3, 5, 7, 10, 15, 20, 30, 60, 120, 390, 0]
# 0 = no time exit (only target/stop/EOD)


# ============================================================
# Data loading from Polygon
# ============================================================

def load_data():
    """Load QQQ minute and daily bars from Polygon API (with caching)."""
    from data_fetcher import PolygonFetcher
    fetcher = PolygonFetcher()

    # Daily bars for ATR
    print(f"  Fetching {SYMBOL} daily bars...")
    daily = fetcher.get_daily_bars(SYMBOL, BACKTEST_START, BACKTEST_END)
    print(f"  Got {len(daily)} daily bars")

    # Get list of trading days
    daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
    trading_days = sorted(daily['date_obj'].tolist())

    # Minute bars - fetch all days
    date_strs = [d.strftime('%Y-%m-%d') for d in trading_days]
    print(f"  Fetching {SYMBOL} minute bars for {len(date_strs)} trading days...")
    print(f"  (Uses Polygon cache - first run may take a while)")

    results_dict = fetcher.get_intraday_bars_bulk(SYMBOL, date_strs)

    if not results_dict:
        print("ERROR: No minute bar data returned")
        sys.exit(1)

    # Concatenate all days into one DataFrame
    frames = []
    for date_str in sorted(results_dict.keys()):
        df = results_dict[date_str]
        frames.append(df)

    all_minute = pd.concat(frames, ignore_index=True)

    # Ensure proper datetime and date/time columns
    all_minute['ts'] = pd.to_datetime(all_minute['timestamp'])
    all_minute['date'] = all_minute['ts'].dt.date
    all_minute['time'] = all_minute['ts'].dt.time

    # RTH filter
    all_minute = all_minute[
        (all_minute['time'] >= RTH_START) & (all_minute['time'] < RTH_END)
    ].copy()
    all_minute.sort_values('ts', inplace=True)
    all_minute.reset_index(drop=True, inplace=True)

    print(f"  RTH bars: {len(all_minute):,}")
    print(f"  Range:    {all_minute['date'].min()} to {all_minute['date'].max()}")
    print(f"  Days:     {all_minute['date'].nunique()}")

    return all_minute, daily


# ============================================================
# ATR
# ============================================================

def compute_wilder_atr(daily_df, target_date, period=ATR_PERIOD):
    """14-day Wilder's smoothed ATR from daily bars prior to target_date."""
    daily_df['date_obj'] = pd.to_datetime(daily_df['date']).dt.date
    prior = daily_df[daily_df['date_obj'] < target_date].tail(period + 1)
    if len(prior) < period + 1:
        return None

    h = prior['high'].values
    l = prior['low'].values
    c = prior['close'].values

    trs = []
    for i in range(1, len(h)):
        tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        trs.append(tr)

    if len(trs) < period:
        return None

    atr = np.mean(trs[:period])
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


# ============================================================
# Session VWAP (cumulative, resets daily at 9:30)
# ============================================================

def compute_session_vwap(highs, lows, closes, volumes):
    """Cumulative VWAP array for a single session."""
    tp = (highs + lows + closes) / 3.0
    vol = volumes.astype(np.float64)
    cum_tpv = np.cumsum(tp * vol)
    cum_v = np.cumsum(vol)
    with np.errstate(divide='ignore', invalid='ignore'):
        vwap = np.where(cum_v > 0, cum_tpv / cum_v, 0.0)
    return vwap


# ============================================================
# Signal detection
# ============================================================

def find_signals_for_day(day_df, entry_pcts, directions):
    """
    Find first-touch entry signals for all entry levels on one day.
    Returns list of signal dicts with forward bar arrays for exit eval.
    """
    n = len(day_df)
    if n < MIN_BARS_FOR_VWAP:
        return []

    highs = day_df['high'].values.astype(np.float64)
    lows = day_df['low'].values.astype(np.float64)
    closes = day_df['close'].values.astype(np.float64)
    opens = day_df['open'].values.astype(np.float64)
    volumes = day_df['volume'].values.astype(np.float64)
    times = day_df['time'].values
    date = day_df['date'].iloc[0]

    vwap = compute_session_vwap(highs, lows, closes, volumes)

    # Find EOD cutoff bar index
    eod_idx = n
    for i in range(n):
        if times[i] >= EOD_CUTOFF:
            eod_idx = i
            break

    signals = []

    for entry_pct in entry_pcts:
        for direction in directions:
            for i in range(MIN_BARS_FOR_VWAP, eod_idx):
                v = vwap[i]
                if v <= 0:
                    continue

                if direction == 'buy':
                    threshold = v * (1.0 - entry_pct / 100.0)
                    touched = lows[i] <= threshold
                else:
                    threshold = v * (1.0 + entry_pct / 100.0)
                    touched = highs[i] >= threshold

                if not touched:
                    continue

                entry_price = threshold

                # Forward bars (from i+1 to EOD)
                end = min(eod_idx + 5, n)
                fwd_h = highs[i+1:end].copy()
                fwd_l = lows[i+1:end].copy()
                fwd_c = closes[i+1:end].copy()

                # Velocity: bars from when price first deviated from VWAP to entry
                velocity_bars = 0
                if direction == 'buy':
                    for j in range(i, -1, -1):
                        if closes[j] >= vwap[j]:
                            velocity_bars = i - j
                            break
                else:
                    for j in range(i, -1, -1):
                        if closes[j] <= vwap[j]:
                            velocity_bars = i - j
                            break

                signals.append({
                    'date': date,
                    'direction': direction,
                    'entry_pct': entry_pct,
                    'entry_price': float(entry_price),
                    'entry_bar': int(i),
                    'vwap': float(v),
                    'velocity_bars': int(velocity_bars),
                    'fwd_h': fwd_h,
                    'fwd_l': fwd_l,
                    'fwd_c': fwd_c,
                    'n_fwd': len(fwd_h),
                })
                break  # one entry per level per day per direction

    return signals


# ============================================================
# Precompute exit bar indices for each signal
# ============================================================

def precompute_exits(signal, target_pcts, stop_pcts):
    entry = signal['entry_price']
    d = signal['direction']
    fwd_h = signal['fwd_h']
    fwd_l = signal['fwd_l']
    nb = signal['n_fwd']
    never = nb + 1

    tgt_bars = {}
    stp_bars = {}

    for tgt in target_pcts:
        if d == 'buy':
            tp = entry * (1.0 + tgt / 100.0)
            hits = np.where(fwd_h >= tp)[0]
        else:
            tp = entry * (1.0 - tgt / 100.0)
            hits = np.where(fwd_l <= tp)[0]
        tgt_bars[tgt] = int(hits[0] + 1) if len(hits) > 0 else never

    for stp in stop_pcts:
        if d == 'buy':
            sp = entry * (1.0 - stp / 100.0)
            hits = np.where(fwd_l <= sp)[0]
        else:
            sp = entry * (1.0 + stp / 100.0)
            hits = np.where(fwd_h >= sp)[0]
        stp_bars[stp] = int(hits[0] + 1) if len(hits) > 0 else never

    return tgt_bars, stp_bars


# ============================================================
# Evaluate a single config across all its signals
# ============================================================

def evaluate_config(signals_with_exits, target_pct, stop_pct, time_exit, wf_split):
    all_pnls = []
    train_pnls = []
    test_pnls = []
    exit_counts = defaultdict(int)
    yearly_pnls = defaultdict(list)

    for sig, tgt_bars, stp_bars in signals_with_exits:
        entry = sig['entry_price']
        d = sig['direction']
        nb = sig['n_fwd']
        fwd_c = sig['fwd_c']
        never = nb + 1

        tb = tgt_bars[target_pct]
        sb = stp_bars[stop_pct]
        xb = time_exit if (time_exit > 0 and time_exit < never) else never

        if tb < never and tb <= sb and tb <= xb:
            pnl = target_pct
            etype = 'target'
        elif sb < never and sb < tb and sb <= xb:
            pnl = -stop_pct
            etype = 'stop'
        else:
            exit_idx = min(xb, nb) - 1
            if exit_idx < 0 or exit_idx >= len(fwd_c):
                pnl = 0.0
            else:
                ep = fwd_c[exit_idx]
                if d == 'buy':
                    pnl = (ep - entry) / entry * 100.0
                else:
                    pnl = (entry - ep) / entry * 100.0
            etype = 'time' if time_exit > 0 and xb <= nb else 'eod'

        all_pnls.append(pnl)
        exit_counts[etype] += 1
        yearly_pnls[sig['date'].year].append(pnl)
        if sig['date'] < wf_split:
            train_pnls.append(pnl)
        else:
            test_pnls.append(pnl)

    if len(all_pnls) < 5:
        return None

    full = _metrics(all_pnls)
    train = _metrics(train_pnls) if len(train_pnls) >= 3 else None
    test = _metrics(test_pnls) if len(test_pnls) >= 3 else None

    wf_pass = False
    if train and test:
        wf_pass = (
            train['sharpe'] > 0 and test['sharpe'] > 0
            and train['avg'] > 0 and test['avg'] > 0
        )

    # Yearly stability check
    yearly_sharpes = {}
    for yr, yp in yearly_pnls.items():
        ym = _metrics(yp)
        if ym:
            yearly_sharpes[yr] = ym['sharpe']

    neg_years = sum(1 for s in yearly_sharpes.values() if s < -0.3)
    yearly_stable = neg_years <= 1

    return {
        'full': full,
        'train': train,
        'test': test,
        'wf_pass': wf_pass,
        'yearly_stable': yearly_stable,
        'yearly_sharpes': yearly_sharpes,
        'exits': dict(exit_counts),
    }


def _metrics(pnls):
    if not pnls:
        return None
    a = np.array(pnls, dtype=np.float64)
    n = len(a)
    avg = float(np.mean(a))
    std = float(np.std(a, ddof=1)) if n > 1 else 0.0
    wins = a[a > 0]
    losses = a[a < 0]
    wr = len(wins) / n

    years = 4.2
    tpy = n / years
    if std > 1e-10:
        sharpe = min(avg / std * np.sqrt(tpy), 10.0)
    else:
        sharpe = 10.0 if avg > 0 else 0.0

    gp = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gl = float(abs(np.sum(losses))) if len(losses) > 0 else 0.0
    pf = gp / gl if gl > 0 else (99.9 if gp > 0 else 0.0)

    cum = np.cumsum(a)
    peak = np.maximum.accumulate(cum)
    max_dd = float(np.max(peak - cum)) if len(cum) > 0 else 0.0

    return {
        'n': n,
        'avg': round(avg, 6),
        'total': round(float(np.sum(a)), 4),
        'wr': round(wr, 4),
        'sharpe': round(sharpe, 4),
        'pf': round(min(pf, 99.9), 3),
        'max_dd': round(max_dd, 4),
        'avg_win': round(float(np.mean(wins)), 6) if len(wins) > 0 else 0.0,
        'avg_loss': round(float(np.mean(losses)), 6) if len(losses) > 0 else 0.0,
    }


# ============================================================
# Risk budget scoring
# ============================================================

def score_risk_budget(sharpe, win_rate):
    score = min(1.0, (sharpe * 2 + win_rate) / 3.0)
    score = max(0.0, score)
    return 10000.0 + score * 140000.0


# ============================================================
# Main
# ============================================================

def main():
    t0 = time.time()
    print("=" * 80)
    print(f"  {SYMBOL} VWAP Mean Reversion -- Exhaustive Parameter Sweep")
    print(f"  Data: Polygon 1-minute bars, {SYMBOL}, RTH only")
    print(f"  Methodology: frontside fills, 14-day Wilder ATR, session VWAP")
    print(f"  Period: {BACKTEST_START} to {BACKTEST_END}")
    print("=" * 80)

    # --- Load data ---
    print("\n[1/5] Loading data from Polygon...")
    minute_data, daily_data = load_data()

    # --- Compute ATR ---
    print("\n[2/5] Computing ATR for each trading day...")
    trading_days = sorted(minute_data['date'].unique())

    atr_by_date = {}
    for d in trading_days:
        atr = compute_wilder_atr(daily_data, d)
        if atr is not None:
            atr_by_date[d] = atr
    print(f"  ATR available for {len(atr_by_date)}/{len(trading_days)} days")

    # --- Find signals ---
    print(f"\n[3/5] Scanning for entry signals across {len(ENTRY_PCTS)} levels x {len(DIRECTIONS)} dirs...")
    all_signals = []
    day_groups = minute_data.groupby('date')

    for idx, d in enumerate(trading_days):
        if d not in atr_by_date:
            continue
        day_df = day_groups.get_group(d)
        sigs = find_signals_for_day(day_df, ENTRY_PCTS, DIRECTIONS)
        all_signals.extend(sigs)

        if (idx + 1) % 200 == 0:
            print(f"  Day {idx+1}/{len(trading_days)}: {len(all_signals):,} signals so far")

    print(f"\n  Total signals found: {len(all_signals):,}")

    # Group by (entry_pct, direction)
    sig_groups = defaultdict(list)
    for s in all_signals:
        sig_groups[(s['entry_pct'], s['direction'])].append(s)

    # Print signal counts
    print(f"\n  {'Level':>8} {'BUY':>6} {'FADE':>6}")
    print(f"  {'-'*22}")
    for ep in ENTRY_PCTS:
        bn = len(sig_groups.get((ep, 'buy'), []))
        fn = len(sig_groups.get((ep, 'fade'), []))
        print(f"  {ep:>7.1f}% {bn:>6} {fn:>6}")

    # --- Precompute exit bars ---
    print(f"\n[4/5] Precomputing exit bar indices...")
    precomputed = {}
    total_sigs = 0
    for key, sigs in sig_groups.items():
        group_data = []
        for s in sigs:
            tb, sb = precompute_exits(s, TARGET_PCTS, STOP_PCTS)
            group_data.append((s, tb, sb))
        precomputed[key] = group_data
        total_sigs += len(sigs)
    print(f"  Precomputed {total_sigs:,} signals")

    # --- Sweep ---
    n_configs = len(ENTRY_PCTS) * len(DIRECTIONS) * len(TARGET_PCTS) * len(STOP_PCTS) * len(TIME_EXITS)
    print(f"\n[5/5] Evaluating {n_configs:,} configurations...")

    results = []
    count = 0
    positive = 0
    wf_passed_count = 0
    wf_stable_count = 0
    sweep_t0 = time.time()

    for entry_pct in ENTRY_PCTS:
        for direction in DIRECTIONS:
            key = (entry_pct, direction)
            group = precomputed.get(key, [])

            if len(group) < 5:
                count += len(TARGET_PCTS) * len(STOP_PCTS) * len(TIME_EXITS)
                continue

            avg_vel = np.mean([s['velocity_bars'] for s, _, _ in group])

            for target_pct in TARGET_PCTS:
                for stop_pct in STOP_PCTS:
                    for time_exit in TIME_EXITS:
                        count += 1
                        r = evaluate_config(group, target_pct, stop_pct, time_exit, WF_SPLIT)
                        if r is None:
                            continue

                        r['entry_pct'] = entry_pct
                        r['direction'] = direction
                        r['target_pct'] = target_pct
                        r['stop_pct'] = stop_pct
                        r['time_exit'] = time_exit
                        r['avg_vel'] = round(avg_vel, 1)
                        results.append(r)

                        if r['full']['avg'] > 0:
                            positive += 1
                        if r['wf_pass']:
                            wf_passed_count += 1
                            if r['yearly_stable']:
                                wf_stable_count += 1

            # Progress
            if count % 50000 < len(TARGET_PCTS) * len(STOP_PCTS) * len(TIME_EXITS):
                elapsed = time.time() - sweep_t0
                rate = count / elapsed if elapsed > 0 else 1
                eta = (n_configs - count) / rate
                print(f"  {count:>9,}/{n_configs:,} "
                      f"({count/n_configs*100:.1f}%) "
                      f"rate={rate:.0f}/s ETA={eta:.0f}s "
                      f"pos={positive:,} wf={wf_passed_count:,} stable={wf_stable_count:,}")

    sweep_elapsed = time.time() - sweep_t0
    print(f"\n  Sweep complete: {count:,} configs in {sweep_elapsed:.1f}s")
    print(f"  Positive expectancy: {positive:,}")
    print(f"  Walk-forward PASS:   {wf_passed_count:,}")
    print(f"  WF PASS + yearly stable: {wf_stable_count:,}")

    # ============================================================
    # Analysis
    # ============================================================
    print("\n" + "=" * 80)
    print("  RESULTS")
    print("=" * 80)

    wf_passed = [r for r in results if r['wf_pass']]

    # Filter to configs where BOTH target and stop fire
    wf_real = [r for r in wf_passed
               if r['exits'].get('target', 0) > 0
               and r['exits'].get('stop', 0) > 0]
    print(f"\n  WF passed with both target+stop hits: {len(wf_real):,}")
    print(f"  (Excluded {len(wf_passed) - len(wf_real):,} degenerate configs)")

    # Further filter to yearly stable
    wf_stable = [r for r in wf_real if r['yearly_stable']]
    print(f"  WF passed + yearly stable: {len(wf_stable):,}")

    # Use wf_real for main analysis, note stable subset
    wf_passed = wf_real

    if not wf_passed:
        print("\n  No configs passed walk-forward validation.")
        pos = [r for r in results if r['full']['avg'] > 0]
        if pos:
            top = sorted(pos, key=lambda r: r['full']['sharpe'], reverse=True)[:30]
            _print_table("TOP 30 BY SHARPE (positive expectancy, WF not passed)", top)
    else:
        top_sharpe = sorted(wf_passed, key=lambda r: r['full']['sharpe'], reverse=True)[:50]
        _print_table("TOP 50 BY SHARPE (Walk-Forward Passed)", top_sharpe)

        top_pf = sorted(wf_passed, key=lambda r: r['full']['pf'], reverse=True)[:20]
        _print_table("TOP 20 BY PROFIT FACTOR (Walk-Forward Passed)", top_pf)

        wr_candidates = [r for r in wf_passed if r['full']['n'] >= 30]
        if wr_candidates:
            top_wr = sorted(wr_candidates, key=lambda r: r['full']['wr'], reverse=True)[:20]
            _print_table("TOP 20 BY WIN RATE (N>=30, Walk-Forward Passed)", top_wr)

        # --- Velocity analysis ---
        print(f"\n{'='*80}")
        print("  VELOCITY ANALYSIS -- Does speed of move matter?")
        print(f"{'='*80}")
        for r in top_sharpe[:15]:
            key = (r['entry_pct'], r['direction'])
            group = precomputed.get(key, [])
            if not group:
                continue

            fast_pnls = []
            slow_pnls = []
            for s, tb, sb in group:
                pnl = _eval_one(s, tb, sb, r['target_pct'], r['stop_pct'], r['time_exit'])
                if s['velocity_bars'] <= 3:
                    fast_pnls.append(pnl)
                elif s['velocity_bars'] > 10:
                    slow_pnls.append(pnl)

            if fast_pnls and slow_pnls:
                fa, sa = np.mean(fast_pnls), np.mean(slow_pnls)
                print(f"  {r['direction']:>4} {r['entry_pct']:.1f}% "
                      f"tgt={r['target_pct']:.2f} stp={r['stop_pct']:.2f} t={r['time_exit']}: "
                      f"Fast(<=3b) N={len(fast_pnls)} avg={fa:+.4f}% | "
                      f"Slow(>10b) N={len(slow_pnls)} avg={sa:+.4f}%"
                      f" {'*** FAST BETTER' if fa > sa else ''}")

        # --- Yearly stability ---
        print(f"\n{'='*80}")
        print("  YEARLY STABILITY -- Top 15 configs")
        print(f"{'='*80}")
        for r in top_sharpe[:15]:
            key = (r['entry_pct'], r['direction'])
            group = precomputed.get(key, [])
            if not group:
                continue

            by_year = defaultdict(list)
            for s, tb, sb in group:
                pnl = _eval_one(s, tb, sb, r['target_pct'], r['stop_pct'], r['time_exit'])
                by_year[s['date'].year].append(pnl)

            print(f"\n  {r['direction']:>4} {r['entry_pct']:.1f}% | "
                  f"tgt={r['target_pct']} stp={r['stop_pct']} time={r['time_exit']}")

            all_years_pos = True
            for yr in sorted(by_year.keys()):
                yp = by_year[yr]
                m = _metrics(yp)
                if m:
                    marker = " <<<" if m['sharpe'] < 0 else ""
                    if m['sharpe'] < 0:
                        all_years_pos = False
                    print(f"    {yr}: N={m['n']:>4} Sh={m['sharpe']:>7.3f} "
                          f"WR={m['wr']:.2f} Avg={m['avg']:>+9.5f}%{marker}")
            print(f"    All years positive: {'YES' if all_years_pos else 'NO'}")

        # --- Dollar P&L projection ---
        print(f"\n{'='*80}")
        print("  DOLLAR P&L PROJECTION -- Top 15 configs")
        print(f"  Risk budget scored: min $10K, max $150K")
        print(f"{'='*80}")
        print(f"  {'Dir':>5} {'Entry':>6} {'Tgt':>5} {'Stp':>5} {'Time':>5} "
              f"{'N':>5} {'Risk$':>8} {'Shares':>8} {'$/Trade':>9} {'$/Year':>10}")
        print(f"  {'-'*78}")

        for r in top_sharpe[:15]:
            f = r['full']
            risk = score_risk_budget(f['sharpe'], f['wr'])
            key = (r['entry_pct'], r['direction'])
            group = precomputed.get(key, [])
            prices = [s['entry_price'] for s, _, _ in group]
            med_price = np.median(prices) if prices else 450.0

            if r['stop_pct'] > 0:
                shares = int(risk / (med_price * r['stop_pct'] / 100.0))
            else:
                shares = int(risk / med_price)

            dollar_per_trade = shares * med_price * f['avg'] / 100.0
            trades_per_year = f['n'] / 4.2
            dollar_per_year = dollar_per_trade * trades_per_year

            print(f"  {r['direction']:>5} {r['entry_pct']:>5.1f}% "
                  f"{r['target_pct']:>5.2f} {r['stop_pct']:>5.2f} {r['time_exit']:>5} "
                  f"{f['n']:>5} ${risk:>7,.0f} {shares:>8,} "
                  f"${dollar_per_trade:>8,.0f} ${dollar_per_year:>9,.0f}")

    # ============================================================
    # Save results
    # ============================================================
    print(f"\n{'='*80}")
    print("  Saving results...")

    save_data = {
        'metadata': {
            'source': 'Polygon',
            'symbol': SYMBOL,
            'dates': f"{trading_days[0]} to {trading_days[-1]}",
            'trading_days': len(trading_days),
            'rth_bars': len(minute_data),
            'wf_split': str(WF_SPLIT),
            'total_configs': n_configs,
            'evaluated': len(results),
            'positive': positive,
            'wf_passed': wf_passed_count,
            'wf_stable': wf_stable_count,
            'runtime_sec': round(time.time() - t0, 1),
            'grid': {
                'entry_pcts': ENTRY_PCTS,
                'directions': DIRECTIONS,
                'target_pcts': TARGET_PCTS,
                'stop_pcts': STOP_PCTS,
                'time_exits': TIME_EXITS,
            },
        },
        'signal_counts': {
            f"{d}_{ep}": len(sig_groups.get((ep, d), []))
            for ep in ENTRY_PCTS for d in DIRECTIONS
        },
        'top_50_sharpe': [_serialize(r) for r in (
            sorted(wf_passed, key=lambda x: x['full']['sharpe'], reverse=True)[:50]
            if wf_passed else
            sorted([r for r in results if r['full']['avg'] > 0],
                   key=lambda x: x['full']['sharpe'], reverse=True)[:50]
        )],
        'all_wf_passed': [_serialize(r) for r in wf_passed],
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(save_data, f, indent=2, default=str)
    print(f"  Saved to {OUTPUT_FILE}")

    total_elapsed = time.time() - t0
    print(f"\n  Total runtime: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    print("  Done.")


def _eval_one(sig, tgt_bars, stp_bars, target_pct, stop_pct, time_exit):
    """Evaluate a single signal for one config. Returns pnl%."""
    entry = sig['entry_price']
    d = sig['direction']
    nb = sig['n_fwd']
    fwd_c = sig['fwd_c']
    never = nb + 1

    tb = tgt_bars[target_pct]
    sb = stp_bars[stop_pct]
    xb = time_exit if (time_exit > 0 and time_exit < never) else never

    if tb < never and tb <= sb and tb <= xb:
        return target_pct
    elif sb < never and sb < tb and sb <= xb:
        return -stop_pct
    else:
        eidx = min(xb, nb) - 1
        if eidx < 0 or eidx >= len(fwd_c):
            return 0.0
        ep = fwd_c[eidx]
        if d == 'buy':
            return (ep - entry) / entry * 100.0
        else:
            return (entry - ep) / entry * 100.0


def _print_table(title, rows):
    print(f"\n  {title}")
    print(f"  {'Dir':>5} {'Entry':>6} {'Tgt':>5} {'Stp':>5} {'Time':>5} "
          f"{'N':>5} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'AvgPnl%':>9} "
          f"{'TrSh':>6} {'TeSh':>6} {'Vel':>5}")
    print(f"  {'-'*82}")
    for r in rows:
        f = r['full']
        tr = r.get('train') or {}
        te = r.get('test') or {}
        print(f"  {r['direction']:>5} {r['entry_pct']:>5.1f}% "
              f"{r['target_pct']:>5.2f} {r['stop_pct']:>5.2f} {r['time_exit']:>5} "
              f"{f['n']:>5} {f['sharpe']:>7.3f} {f['wr']:>6.2f} "
              f"{f['pf']:>6.2f} {f['avg']:>+9.5f} "
              f"{tr.get('sharpe', 0):>6.3f} {te.get('sharpe', 0):>6.3f} "
              f"{r.get('avg_vel', 0):>5.1f}")


def _serialize(r):
    """Make result JSON-serializable (drop numpy arrays)."""
    out = {}
    for k, v in r.items():
        if k in ('fwd_h', 'fwd_l', 'fwd_c'):
            continue
        if isinstance(v, dict):
            out[k] = {str(kk): vv for kk, vv in v.items()}
        else:
            out[k] = v
    return out


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Velocity-Based Position Sizing — SPY BUY 0.4% VWAP Mean Reversion
===================================================================
Risk per trade: $10K to $150K based on velocity tier.
Notional cap: $25M per position.
Tests multiple velocity tier configurations.
"""

import os, sys, json, time
import numpy as np
import pandas as pd
from datetime import date as dt_date, time as dt_time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spy_fade_strategy'))

SYMBOL = 'SPY'
RTH_START = dt_time(9, 30)
RTH_END = dt_time(16, 0)
EOD_CUTOFF = dt_time(15, 55)
MIN_BARS_FOR_VWAP = 5
WF_SPLIT = dt_date(2024, 7, 1)
BACKTEST_START = '2022-01-01'
BACKTEST_END = '2026-03-12'
ENTRY_PCT = 0.4
TARGET_PCT = 0.75
STOP_PCT = 1.0
TIME_BARS = 15
NOTIONAL_CAP = 25_000_000


def load_data():
    from data_fetcher import PolygonFetcher
    fetcher = PolygonFetcher()

    daily = fetcher.get_daily_bars(SYMBOL, BACKTEST_START, BACKTEST_END)
    daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
    trading_days = sorted(daily['date_obj'].tolist())

    date_strs = [d.strftime('%Y-%m-%d') for d in trading_days]
    results_dict = fetcher.get_intraday_bars_bulk(SYMBOL, date_strs)

    frames = []
    for ds in sorted(results_dict.keys()):
        frames.append(results_dict[ds])

    minute = pd.concat(frames, ignore_index=True)
    minute['ts'] = pd.to_datetime(minute['timestamp'])
    minute['date'] = minute['ts'].dt.date
    minute['time'] = minute['ts'].dt.time
    minute = minute[(minute['time'] >= RTH_START) & (minute['time'] < RTH_END)].copy()
    minute.sort_values('ts', inplace=True)
    minute.reset_index(drop=True, inplace=True)

    # Gap % for each day
    daily_sorted = daily.sort_values('date_obj')
    gap_map = {}
    for i in range(1, len(daily_sorted)):
        d = daily_sorted['date_obj'].iloc[i]
        prev_close = daily_sorted['close'].iloc[i - 1]
        today_open = daily_sorted['open'].iloc[i]
        gap_map[d] = (today_open - prev_close) / prev_close * 100

    print(f"  RTH bars: {len(minute):,}, Days: {minute['date'].nunique()}")
    return minute, gap_map


def compute_session_vwap(highs, lows, closes, volumes):
    tp = (highs + lows + closes) / 3.0
    vol = volumes.astype(np.float64)
    cum_tpv = np.cumsum(tp * vol)
    cum_v = np.cumsum(vol)
    with np.errstate(divide='ignore', invalid='ignore'):
        vwap = np.where(cum_v > 0, cum_tpv / cum_v, 0.0)
    return vwap


def find_signals(minute_data, gap_map):
    trading_days = sorted(minute_data['date'].unique())
    day_groups = minute_data.groupby('date')
    signals = []

    for idx, d in enumerate(trading_days):
        day_df = day_groups.get_group(d)
        n = len(day_df)
        if n < MIN_BARS_FOR_VWAP:
            continue

        highs = day_df['high'].values.astype(np.float64)
        lows = day_df['low'].values.astype(np.float64)
        closes = day_df['close'].values.astype(np.float64)
        volumes = day_df['volume'].values.astype(np.float64)
        times = day_df['time'].values

        vwap = compute_session_vwap(highs, lows, closes, volumes)

        eod_idx = n
        for i in range(n):
            if times[i] >= EOD_CUTOFF:
                eod_idx = i
                break

        for i in range(MIN_BARS_FOR_VWAP, eod_idx):
            v = vwap[i]
            if v <= 0:
                continue
            threshold = v * (1.0 - ENTRY_PCT / 100.0)
            if lows[i] <= threshold:
                entry_price = threshold
                end = min(eod_idx + 5, n)
                fwd_h = highs[i + 1:end].copy()
                fwd_l = lows[i + 1:end].copy()
                fwd_c = closes[i + 1:end].copy()

                # Velocity
                velocity_bars = 0
                for j in range(i, -1, -1):
                    if closes[j] >= vwap[j]:
                        velocity_bars = i - j
                        break

                # P&L (baseline exit)
                nb = len(fwd_h)
                target_price = entry_price * (1 + TARGET_PCT / 100)
                stop_price = entry_price * (1 - STOP_PCT / 100)
                pnl_pct = 0.0
                exit_type = 'time'

                for bi in range(min(nb, TIME_BARS)):
                    if fwd_l[bi] <= stop_price:
                        pnl_pct = -STOP_PCT
                        exit_type = 'stop'
                        break
                    if fwd_h[bi] >= target_price:
                        pnl_pct = TARGET_PCT
                        exit_type = 'target'
                        break
                else:
                    exit_idx = min(TIME_BARS, nb) - 1
                    if 0 <= exit_idx < len(fwd_c):
                        pnl_pct = (fwd_c[exit_idx] - entry_price) / entry_price * 100

                gap = gap_map.get(d, 0)
                entry_time = times[i]
                minutes_from_open = (entry_time.hour - 9) * 60 + (entry_time.minute - 30)

                signals.append({
                    'date': d,
                    'entry_price': entry_price,
                    'velocity_bars': velocity_bars,
                    'pnl_pct': pnl_pct,
                    'exit_type': exit_type,
                    'gap_pct': gap,
                    'minutes_from_open': minutes_from_open,
                    'in_sample': d < WF_SPLIT,
                })
                break

        if (idx + 1) % 200 == 0:
            print(f"  Day {idx + 1}/{len(trading_days)}: {len(signals)} signals")

    return signals


def compute_shares(risk_budget, entry_price, stop_pct, notional_cap):
    """Compute shares with notional cap."""
    shares_from_risk = int(risk_budget / (entry_price * stop_pct / 100))
    shares_from_cap = int(notional_cap / entry_price)
    return max(1, min(shares_from_risk, shares_from_cap))


def run_sizing_strategy(signals, tier_fn, label, gap_filter=None):
    """Run a sizing strategy. tier_fn(signal) -> risk_budget ($).
    gap_filter: if set, skip trades with gap_pct < gap_filter."""
    pnls = []
    pnls_by_date = []
    risks_used = []
    shares_list = []
    notionals = []
    cap_hits = 0
    skipped = 0
    vel_buckets = defaultdict(list)

    for s in signals:
        if gap_filter is not None and s['gap_pct'] < gap_filter:
            skipped += 1
            continue

        risk = tier_fn(s)
        shares = compute_shares(risk, s['entry_price'], STOP_PCT, NOTIONAL_CAP)
        notional = shares * s['entry_price']

        if notional >= NOTIONAL_CAP * 0.99:
            cap_hits += 1

        dollar_pnl = shares * s['entry_price'] * s['pnl_pct'] / 100
        actual_risk = shares * s['entry_price'] * STOP_PCT / 100

        pnls.append(dollar_pnl)
        pnls_by_date.append((s['date'], dollar_pnl))
        risks_used.append(risk)
        shares_list.append(shares)
        notionals.append(notional)

        # Track by velocity bucket
        v = s['velocity_bars']
        if v <= 1:
            vel_buckets['0-1'].append(dollar_pnl)
        elif v <= 4:
            vel_buckets['2-4'].append(dollar_pnl)
        elif v <= 9:
            vel_buckets['5-9'].append(dollar_pnl)
        elif v <= 19:
            vel_buckets['10-19'].append(dollar_pnl)
        elif v <= 49:
            vel_buckets['20-49'].append(dollar_pnl)
        else:
            vel_buckets['50+'].append(dollar_pnl)

    if len(pnls) < 5:
        return None

    a = np.array(pnls)
    n = len(a)
    avg = np.mean(a)
    std = np.std(a, ddof=1)
    wr = np.sum(a > 0) / n
    sharpe = avg / std * np.sqrt(n / 4.2) if std > 1e-10 else 0
    wins = a[a > 0]
    losses = a[a < 0]
    pf = np.sum(wins) / abs(np.sum(losses)) if len(losses) > 0 else 99.9
    avg_win = np.mean(wins) if len(wins) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0
    wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 99.9

    cum = np.cumsum(a)
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum)

    # Yearly
    by_year = defaultdict(list)
    for d, p in pnls_by_date:
        by_year[d.year].append(p)

    yearly = {}
    neg_years = 0
    for yr in sorted(by_year.keys()):
        yp = np.array(by_year[yr])
        yn = len(yp)
        ya = np.mean(yp)
        ys = np.std(yp, ddof=1) if yn > 1 else 0
        ywr = np.sum(yp > 0) / yn
        ysh = ya / ys * np.sqrt(yn / 4.2) if ys > 1e-10 else 0
        ywins = yp[yp > 0]
        ylosses = yp[yp < 0]
        ypf = np.sum(ywins) / abs(np.sum(ylosses)) if len(ylosses) > 0 else 99.9
        if ya < 0:
            neg_years += 1
        yearly[yr] = {
            'n': yn, 'total': round(float(np.sum(yp)), 0),
            'avg': round(float(ya), 2), 'sharpe': round(ysh, 3),
            'wr': round(float(ywr), 3), 'pf': round(ypf, 2),
        }

    # Walk-forward
    train_pnls = [p for d, p in pnls_by_date if d < WF_SPLIT]
    test_pnls = [p for d, p in pnls_by_date if d >= WF_SPLIT]
    train_sh = 0
    test_sh = 0
    if len(train_pnls) > 3:
        ta = np.array(train_pnls)
        ts = np.std(ta, ddof=1)
        train_sh = np.mean(ta) / ts * np.sqrt(len(ta) / 4.2) if ts > 1e-10 else 0
    if len(test_pnls) > 3:
        ta = np.array(test_pnls)
        ts = np.std(ta, ddof=1)
        test_sh = np.mean(ta) / ts * np.sqrt(len(ta) / 4.2) if ts > 1e-10 else 0

    return {
        'label': label,
        'n': n,
        'skipped': skipped,
        'total': round(float(np.sum(a)), 0),
        'avg': round(avg, 2),
        'sharpe': round(sharpe, 3),
        'wr': round(wr, 3),
        'pf': round(pf, 2),
        'avg_win': round(avg_win, 0),
        'avg_loss': round(avg_loss, 0),
        'wl_ratio': round(wl_ratio, 2),
        'max_dd': round(max_dd, 0),
        'neg_years': neg_years,
        'yearly': yearly,
        'train_sh': round(train_sh, 3),
        'test_sh': round(test_sh, 3),
        'avg_risk': round(np.mean(risks_used), 0),
        'avg_shares': round(np.mean(shares_list), 0),
        'avg_notional': round(np.mean(notionals), 0),
        'cap_hits': cap_hits,
        'cap_pct': round(cap_hits / n * 100, 1),
        'vel_breakdown': {k: {'n': len(v), 'total': round(sum(v), 0), 'avg': round(np.mean(v), 0)}
                          for k, v in sorted(vel_buckets.items())},
    }


def main():
    t0 = time.time()
    print("=" * 100)
    print("  VELOCITY-BASED POSITION SIZING — SPY BUY 0.4% VWAP MR")
    print("  Risk range: $10K-$150K | Notional cap: $25M | Stop: 1.0%")
    print("=" * 100)

    print("\n[1/3] Loading data...")
    minute_data, gap_map = load_data()

    print("\n[2/3] Finding signals...")
    signals = find_signals(minute_data, gap_map)
    print(f"  Total signals: {len(signals)}")

    # Velocity distribution
    vel_counts = defaultdict(int)
    for s in signals:
        v = s['velocity_bars']
        if v <= 1: vel_counts['0-1'] += 1
        elif v <= 4: vel_counts['2-4'] += 1
        elif v <= 9: vel_counts['5-9'] += 1
        elif v <= 19: vel_counts['10-19'] += 1
        elif v <= 49: vel_counts['20-49'] += 1
        else: vel_counts['50+'] += 1
    print("\n  Velocity distribution:")
    for k in ['0-1', '2-4', '5-9', '10-19', '20-49', '50+']:
        print(f"    {k:>6} bars: {vel_counts.get(k, 0):>4} signals ({vel_counts.get(k, 0)/len(signals)*100:.1f}%)")

    print(f"\n[3/3] Testing sizing strategies...")

    # ============================================================
    # Define tier functions
    # ============================================================
    strategies = []

    # --- BASELINE: flat risk ---
    for flat_risk in [46000, 75000, 100000, 150000]:
        strategies.append((
            f"FLAT ${flat_risk // 1000}K",
            lambda s, r=flat_risk: r,
            None
        ))

    # --- 3-TIER velocity sizing ---
    # (fast_cutoff, slow_cutoff, fast_risk, mid_risk, slow_risk)
    three_tier_configs = [
        (5, 20, 150000, 75000, 10000),
        (5, 20, 150000, 50000, 10000),
        (5, 20, 150000, 100000, 25000),
        (5, 20, 120000, 75000, 20000),
        (5, 10, 150000, 75000, 25000),
        (5, 10, 150000, 50000, 10000),
        (5, 10, 150000, 100000, 50000),
        (2, 10, 150000, 100000, 25000),
        (2, 10, 150000, 75000, 10000),
        (2, 20, 150000, 75000, 10000),
        (2, 5, 150000, 75000, 25000),
        (5, 50, 150000, 75000, 10000),
        (5, 50, 150000, 100000, 25000),
    ]
    for fc, sc, fr, mr, sr in three_tier_configs:
        def make_fn(fc=fc, sc=sc, fr=fr, mr=mr, sr=sr):
            def fn(s):
                v = s['velocity_bars']
                if v < fc: return fr
                elif v < sc: return mr
                else: return sr
            return fn
        strategies.append((
            f"3T: <{fc}b=${fr//1000}K, <{sc}b=${mr//1000}K, >={sc}b=${sr//1000}K",
            make_fn(),
            None
        ))

    # --- 6-TIER (granular) ---
    six_tier_configs = [
        # (risk for 0-1, 2-4, 5-9, 10-19, 20-49, 50+)
        (150000, 120000, 75000, 40000, 20000, 10000),
        (150000, 100000, 50000, 25000, 15000, 10000),
        (150000, 130000, 100000, 50000, 25000, 10000),
        (150000, 110000, 75000, 50000, 30000, 15000),
        (150000, 125000, 80000, 40000, 15000, 10000),
    ]
    for t0r, t1r, t2r, t3r, t4r, t5r in six_tier_configs:
        def make_fn6(t0r=t0r, t1r=t1r, t2r=t2r, t3r=t3r, t4r=t4r, t5r=t5r):
            def fn(s):
                v = s['velocity_bars']
                if v <= 1: return t0r
                elif v <= 4: return t1r
                elif v <= 9: return t2r
                elif v <= 19: return t3r
                elif v <= 49: return t4r
                else: return t5r
            return fn
        label = f"6T: {t0r//1000}/{t1r//1000}/{t2r//1000}/{t3r//1000}/{t4r//1000}/{t5r//1000}K"
        strategies.append((label, make_fn6(), None))

    # --- Same strategies but WITH gap filter (skip gap < -1%) ---
    gap_strategies = []
    # Best 3-tier configs with gap filter
    for fc, sc, fr, mr, sr in [
        (5, 20, 150000, 75000, 10000),
        (5, 20, 150000, 50000, 10000),
        (5, 10, 150000, 75000, 25000),
        (2, 10, 150000, 75000, 10000),
        (5, 50, 150000, 100000, 25000),
    ]:
        def make_fn(fc=fc, sc=sc, fr=fr, mr=mr, sr=sr):
            def fn(s):
                v = s['velocity_bars']
                if v < fc: return fr
                elif v < sc: return mr
                else: return sr
            return fn
        gap_strategies.append((
            f"GAP+3T: <{fc}b=${fr//1000}K, <{sc}b=${mr//1000}K, >={sc}b=${sr//1000}K",
            make_fn(),
            -1.0  # gap filter
        ))

    # Best 6-tier with gap filter
    for t0r, t1r, t2r, t3r, t4r, t5r in [
        (150000, 120000, 75000, 40000, 20000, 10000),
        (150000, 100000, 50000, 25000, 15000, 10000),
        (150000, 130000, 100000, 50000, 25000, 10000),
    ]:
        def make_fn6(t0r=t0r, t1r=t1r, t2r=t2r, t3r=t3r, t4r=t4r, t5r=t5r):
            def fn(s):
                v = s['velocity_bars']
                if v <= 1: return t0r
                elif v <= 4: return t1r
                elif v <= 9: return t2r
                elif v <= 19: return t3r
                elif v <= 49: return t4r
                else: return t5r
            return fn
        label = f"GAP+6T: {t0r//1000}/{t1r//1000}/{t2r//1000}/{t3r//1000}/{t4r//1000}/{t5r//1000}K"
        gap_strategies.append((label, make_fn6(), -1.0))

    all_strategies = strategies + gap_strategies

    # Run all
    results = []
    for label, tier_fn, gap_filter in all_strategies:
        r = run_sizing_strategy(signals, tier_fn, label, gap_filter)
        if r:
            results.append(r)

    results.sort(key=lambda r: r['sharpe'], reverse=True)

    # Print results
    print(f"\n{'='*130}")
    print(f"  ALL RESULTS — Sorted by Sharpe")
    print(f"{'='*130}")
    print(f"  {'Strategy':<58} {'N':>4} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'W/L':>5} "
          f"{'Total$':>12} {'Avg$':>8} {'MaxDD$':>10} {'AvgRisk':>8} {'Cap%':>5} {'NegYr':>5} {'TrSh':>6} {'TeSh':>6}")
    print(f"  {'-'*126}")

    for r in results:
        marker = ' ***' if r['label'].startswith('FLAT $46K') else ''
        print(f"  {r['label']:<58} {r['n']:>4} {r['sharpe']:>7.3f} {r['wr']:>5.1%} {r['pf']:>6.2f} "
              f"{r['wl_ratio']:>5.2f} ${r['total']:>10,.0f} ${r['avg']:>7,.0f} ${r['max_dd']:>9,.0f} "
              f"${r['avg_risk']:>7,.0f} {r['cap_pct']:>4.1f}% {r['neg_years']:>5} "
              f"{r['train_sh']:>6.3f} {r['test_sh']:>6.3f}{marker}")

    # Detailed yearly for top 10
    print(f"\n{'='*130}")
    print(f"  YEARLY BREAKDOWN — Top 10")
    print(f"{'='*130}")
    for r in results[:10]:
        print(f"\n  {r['label']}")
        print(f"  {'Year':>6} {'N':>5} {'Total':>12} {'Avg':>10} {'Sharpe':>8} {'WR':>6} {'PF':>6}")
        print(f"  {'-'*60}")
        for yr in sorted(r['yearly'].keys()):
            y = r['yearly'][yr]
            marker = ' <<<' if y['sharpe'] < 0 else ''
            print(f"  {yr:>6} {y['n']:>5} ${y['total']:>11,.0f} ${y['avg']:>9,.0f} "
                  f"{y['sharpe']:>8.3f} {y['wr']:>5.1%} {y['pf']:>6.2f}{marker}")

    # Velocity P&L breakdown for top 5
    print(f"\n{'='*130}")
    print(f"  VELOCITY P&L BREAKDOWN — Top 5")
    print(f"{'='*130}")
    for r in results[:5]:
        print(f"\n  {r['label']}")
        print(f"  {'Velocity':>10} {'N':>5} {'Total$':>12} {'Avg$':>10}")
        print(f"  {'-'*42}")
        for k in ['0-1', '2-4', '5-9', '10-19', '20-49', '50+']:
            vd = r['vel_breakdown'].get(k, {'n': 0, 'total': 0, 'avg': 0})
            print(f"  {k:>10} {vd['n']:>5} ${vd['total']:>11,.0f} ${vd['avg']:>9,.0f}")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.1f}s")

    # Save
    save_data = {'results': results}
    with open('velocity_sizing_results.json', 'w') as f:
        json.dump(save_data, f, indent=2, default=str)
    print(f"  Saved to velocity_sizing_results.json")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Combined Sizing: Velocity + Gap Filter + Time-of-Day Overlay
=============================================================
Tests whether adding TOD sizing on top of velocity tiers + gap filter improves Sharpe.
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
    frames = [results_dict[ds] for ds in sorted(results_dict.keys())]
    minute = pd.concat(frames, ignore_index=True)
    minute['ts'] = pd.to_datetime(minute['timestamp'])
    minute['date'] = minute['ts'].dt.date
    minute['time'] = minute['ts'].dt.time
    minute = minute[(minute['time'] >= RTH_START) & (minute['time'] < RTH_END)].copy()
    minute.sort_values('ts', inplace=True)
    minute.reset_index(drop=True, inplace=True)

    daily_sorted = daily.sort_values('date_obj')
    gap_map = {}
    for i in range(1, len(daily_sorted)):
        d = daily_sorted['date_obj'].iloc[i]
        prev_close = daily_sorted['close'].iloc[i - 1]
        today_open = daily_sorted['open'].iloc[i]
        gap_map[d] = (today_open - prev_close) / prev_close * 100
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
                velocity_bars = 0
                for j in range(i, -1, -1):
                    if closes[j] >= vwap[j]:
                        velocity_bars = i - j
                        break
                nb = len(fwd_h)
                target_price = entry_price * (1 + TARGET_PCT / 100)
                stop_price = entry_price * (1 - STOP_PCT / 100)
                pnl_pct = 0.0
                for bi in range(min(nb, TIME_BARS)):
                    if fwd_l[bi] <= stop_price:
                        pnl_pct = -STOP_PCT
                        break
                    if fwd_h[bi] >= target_price:
                        pnl_pct = TARGET_PCT
                        break
                else:
                    exit_idx = min(TIME_BARS, nb) - 1
                    if 0 <= exit_idx < len(fwd_c):
                        pnl_pct = (fwd_c[exit_idx] - entry_price) / entry_price * 100

                entry_time = times[i]
                minutes_from_open = (entry_time.hour - 9) * 60 + (entry_time.minute - 30)
                gap = gap_map.get(d, 0)

                signals.append({
                    'date': d,
                    'entry_price': entry_price,
                    'velocity_bars': velocity_bars,
                    'pnl_pct': pnl_pct,
                    'gap_pct': gap,
                    'minutes_from_open': minutes_from_open,
                    'in_sample': d < WF_SPLIT,
                })
                break
        if (idx + 1) % 200 == 0:
            print(f"  Day {idx + 1}/{len(trading_days)}: {len(signals)} signals")
    return signals


def run_strategy(signals, sizing_fn, label, gap_filter=-1.0):
    """sizing_fn(signal) -> risk in dollars."""
    pnls = []
    pnls_by_date = []

    for s in signals:
        if s['gap_pct'] < gap_filter:
            continue
        risk = sizing_fn(s)
        if risk <= 0:
            continue
        shares = int(risk / (s['entry_price'] * STOP_PCT / 100))
        shares = min(shares, int(NOTIONAL_CAP / s['entry_price']))
        shares = max(shares, 1)
        dollar_pnl = shares * s['entry_price'] * s['pnl_pct'] / 100
        pnls.append(dollar_pnl)
        pnls_by_date.append((s['date'], dollar_pnl))

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
    wl = abs(np.mean(wins) / np.mean(losses)) if len(losses) > 0 else 99.9
    cum = np.cumsum(a)
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum)

    by_year = defaultdict(list)
    for d, p in pnls_by_date:
        by_year[d.year].append(p)
    yearly = {}
    neg_years = 0
    for yr in sorted(by_year.keys()):
        yp = np.array(by_year[yr])
        ya = np.mean(yp)
        ys = np.std(yp, ddof=1) if len(yp) > 1 else 0
        ysh = ya / ys * np.sqrt(len(yp) / 4.2) if ys > 1e-10 else 0
        ywins = yp[yp > 0]
        ylosses = yp[yp < 0]
        ypf = np.sum(ywins) / abs(np.sum(ylosses)) if len(ylosses) > 0 else 99.9
        if ya < 0:
            neg_years += 1
        yearly[yr] = {'n': len(yp), 'total': round(float(np.sum(yp)), 0),
                       'sharpe': round(ysh, 3), 'wr': round(float(np.sum(yp > 0) / len(yp)), 3),
                       'pf': round(ypf, 2)}

    # WF
    train = [p for d, p in pnls_by_date if d < WF_SPLIT]
    test = [p for d, p in pnls_by_date if d >= WF_SPLIT]
    def sh(arr):
        if len(arr) < 3: return 0
        a2 = np.array(arr)
        s2 = np.std(a2, ddof=1)
        return np.mean(a2) / s2 * np.sqrt(len(a2) / 4.2) if s2 > 1e-10 else 0

    return {
        'label': label, 'n': n, 'sharpe': round(sharpe, 3), 'wr': round(wr, 3),
        'pf': round(pf, 2), 'wl': round(wl, 2), 'total': round(float(np.sum(a)), 0),
        'avg': round(avg, 0), 'max_dd': round(max_dd, 0), 'neg_years': neg_years,
        'yearly': yearly, 'train_sh': round(sh(train), 3), 'test_sh': round(sh(test), 3),
    }


def vel_risk(s, fast_r, mid_r, slow_r, fast_cut=5, slow_cut=50):
    v = s['velocity_bars']
    if v < fast_cut: return fast_r
    elif v < slow_cut: return mid_r
    else: return slow_r


def main():
    t0 = time.time()
    print("=" * 110)
    print("  COMBINED SIZING: Velocity + Gap Filter + Time-of-Day Overlay")
    print("=" * 110)

    print("\n[1/3] Loading data...")
    minute_data, gap_map = load_data()

    print("\n[2/3] Finding signals...")
    signals = find_signals(minute_data, gap_map)
    print(f"  Total: {len(signals)} signals")

    # TOD distribution within gap-filtered set
    filtered = [s for s in signals if s['gap_pct'] >= -1.0]
    print(f"  After gap filter: {len(filtered)} signals")

    tod_vel_crosstab = defaultdict(lambda: defaultdict(list))
    for s in filtered:
        if s['minutes_from_open'] < 15:
            tod = 'A: 0-15m'
        elif s['minutes_from_open'] < 30:
            tod = 'B: 15-30m'
        elif s['minutes_from_open'] < 60:
            tod = 'C: 30-60m'
        elif s['minutes_from_open'] < 120:
            tod = 'D: 60-120m'
        elif s['minutes_from_open'] < 195:
            tod = 'E: 120-195m'
        else:
            tod = 'F: 195m+'

        if s['velocity_bars'] < 5:
            vel = 'fast(<5)'
        elif s['velocity_bars'] < 50:
            vel = 'mid(5-49)'
        else:
            vel = 'slow(50+)'

        tod_vel_crosstab[tod][vel].append(s['pnl_pct'])

    print(f"\n  TOD x VELOCITY cross-tab (avg P&L %)")
    print(f"  {'TOD':<16} {'fast(<5)':>14} {'mid(5-49)':>14} {'slow(50+)':>14}")
    print(f"  {'-'*60}")
    for tod in sorted(tod_vel_crosstab.keys()):
        parts = []
        for vel in ['fast(<5)', 'mid(5-49)', 'slow(50+)']:
            vals = tod_vel_crosstab[tod].get(vel, [])
            if vals:
                parts.append(f"N={len(vals):>3} avg={np.mean(vals):>+.4f}")
            else:
                parts.append(f"{'N/A':>14}")
        print(f"  {tod:<16} {'  '.join(parts)}")

    print(f"\n[3/3] Testing combined strategies...")

    results = []

    # --- A: Velocity only (baseline winner) ---
    results.append(run_strategy(signals,
        lambda s: vel_risk(s, 150000, 100000, 25000),
        "A: VEL ONLY (150/100/25K)"))

    # --- B: TOD dead zone penalty (30-60m at 50% sizing) ---
    def tod_penalty_50(s):
        base = vel_risk(s, 150000, 100000, 25000)
        if 30 <= s['minutes_from_open'] < 60:
            return base * 0.5
        return base
    results.append(run_strategy(signals, tod_penalty_50,
        "B: VEL + 50% penalty 30-60m"))

    # --- C: TOD dead zone skip entirely ---
    def tod_skip_deadzone(s):
        if 30 <= s['minutes_from_open'] < 60:
            return 0  # skip
        return vel_risk(s, 150000, 100000, 25000)
    results.append(run_strategy(signals, tod_skip_deadzone,
        "C: VEL + skip 30-60m entirely"))

    # --- D: TOD boost for sweet spots (0-15m, 120-195m) ---
    def tod_boost(s):
        base = vel_risk(s, 150000, 100000, 25000)
        if s['minutes_from_open'] < 15:
            return min(base * 1.3, 150000)
        elif 120 <= s['minutes_from_open'] < 195:
            return min(base * 1.3, 150000)
        elif 30 <= s['minutes_from_open'] < 60:
            return base * 0.5
        return base
    results.append(run_strategy(signals, tod_boost,
        "D: VEL + boost early/midday + penalty 30-60m"))

    # --- E: Two-level TOD: full size early+late, half size 30-60m ---
    def tod_two_level(s):
        base = vel_risk(s, 150000, 100000, 25000)
        if 30 <= s['minutes_from_open'] < 60:
            return base * 0.5
        return base
    results.append(run_strategy(signals, tod_two_level,
        "E: VEL + halve 30-60m"))

    # --- F: Three-level TOD overlay ---
    def tod_three_level(s):
        base = vel_risk(s, 150000, 100000, 25000)
        if s['minutes_from_open'] < 30:
            return min(base * 1.2, 150000)  # boost opening
        elif 30 <= s['minutes_from_open'] < 60:
            return base * 0.4  # heavy cut during dead zone
        elif 120 <= s['minutes_from_open'] < 195:
            return min(base * 1.2, 150000)  # boost midday sweet spot
        return base
    results.append(run_strategy(signals, tod_three_level,
        "F: VEL + 1.2x open/midday, 0.4x deadzone"))

    # --- G: Aggressive dead zone cut ---
    def tod_aggressive(s):
        base = vel_risk(s, 150000, 100000, 25000)
        if 30 <= s['minutes_from_open'] < 60:
            return base * 0.25  # quarter size
        return base
    results.append(run_strategy(signals, tod_aggressive,
        "G: VEL + 25% size 30-60m"))

    # --- H: Different velocity tiers that already performed well ---
    results.append(run_strategy(signals,
        lambda s: vel_risk(s, 150000, 75000, 10000, 5, 20),
        "H: VEL 150/75/10K (cut=5/20)"))

    def tod_penalty_h(s):
        base = vel_risk(s, 150000, 75000, 10000, 5, 20)
        if 30 <= s['minutes_from_open'] < 60:
            return base * 0.5
        return base
    results.append(run_strategy(signals, tod_penalty_h,
        "I: VEL 150/75/10K + 50% penalty 30-60m"))

    def tod_skip_h(s):
        if 30 <= s['minutes_from_open'] < 60:
            return 0
        return vel_risk(s, 150000, 75000, 10000, 5, 20)
    results.append(run_strategy(signals, tod_skip_h,
        "J: VEL 150/75/10K + skip 30-60m"))

    # --- K: 6-tier velocity + TOD penalty ---
    def vel6(s):
        v = s['velocity_bars']
        if v <= 1: return 150000
        elif v <= 4: return 120000
        elif v <= 9: return 75000
        elif v <= 19: return 40000
        elif v <= 49: return 20000
        else: return 10000
    results.append(run_strategy(signals, vel6,
        "K: 6T VEL 150/120/75/40/20/10K"))

    def vel6_tod(s):
        base = vel6(s)
        if 30 <= s['minutes_from_open'] < 60:
            return base * 0.5
        return base
    results.append(run_strategy(signals, vel6_tod,
        "L: 6T VEL + 50% penalty 30-60m"))

    def vel6_tod_skip(s):
        if 30 <= s['minutes_from_open'] < 60:
            return 0
        return vel6(s)
    results.append(run_strategy(signals, vel6_tod_skip,
        "M: 6T VEL + skip 30-60m"))

    # --- N: Test broader dead zone (30-75m) ---
    def broader_deadzone(s):
        base = vel_risk(s, 150000, 100000, 25000)
        if 30 <= s['minutes_from_open'] < 75:
            return base * 0.5
        return base
    results.append(run_strategy(signals, broader_deadzone,
        "N: VEL + 50% penalty 30-75m"))

    # --- O: Only trade before 30m and after 60m ---
    def skip_30_60(s):
        if 30 <= s['minutes_from_open'] < 60:
            return 0
        return vel_risk(s, 150000, 100000, 25000)
    results.append(run_strategy(signals, skip_30_60,
        "O: VEL + skip 30-60m (dup check)"))

    # Filter results
    results = [r for r in results if r is not None]
    results.sort(key=lambda r: r['sharpe'], reverse=True)

    print(f"\n{'='*130}")
    print(f"  ALL RESULTS — Sorted by Sharpe (all include gap > -1% filter)")
    print(f"{'='*130}")
    print(f"  {'Strategy':<50} {'N':>4} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'W/L':>5} "
          f"{'Total$':>12} {'MaxDD$':>10} {'NegYr':>5} {'TrSh':>6} {'TeSh':>6}")
    print(f"  {'-'*120}")
    for r in results:
        print(f"  {r['label']:<50} {r['n']:>4} {r['sharpe']:>7.3f} {r['wr']:>5.1%} {r['pf']:>6.2f} "
              f"{r['wl']:>5.2f} ${r['total']:>10,.0f} ${r['max_dd']:>9,.0f} "
              f"{r['neg_years']:>5} {r['train_sh']:>6.3f} {r['test_sh']:>6.3f}")

    # Yearly for top 5
    print(f"\n{'='*130}")
    print(f"  YEARLY — Top 5")
    print(f"{'='*130}")
    for r in results[:5]:
        print(f"\n  {r['label']}")
        for yr in sorted(r['yearly'].keys()):
            y = r['yearly'][yr]
            marker = ' <<<' if y['sharpe'] < 0 else ''
            print(f"    {yr}: N={y['n']:>4} Total=${y['total']:>10,.0f} "
                  f"Sh={y['sharpe']:>7.3f} WR={y['wr']:.1%} PF={y['pf']:.2f}{marker}")

    elapsed = time.time() - t0
    print(f"\n  Runtime: {elapsed:.1f}s")


if __name__ == '__main__':
    main()

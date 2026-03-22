#!/usr/bin/env python3
"""
Entry Filter & Sizing Analysis — SPY BUY 0.4% VWAP Mean Reversion
===================================================================
Studies whether time-of-day, VIX regime, velocity, day-of-week,
gap %, or prior-day trend can improve edge via sizing or filtering.

Uses the same 526 signals from the baseline config.
"""

import os, sys, json, time
import numpy as np
import pandas as pd
from datetime import date as dt_date, time as dt_time, datetime, timedelta
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


def load_data():
    from data_fetcher import PolygonFetcher
    fetcher = PolygonFetcher()

    print("  Loading daily bars...")
    daily = fetcher.get_daily_bars(SYMBOL, BACKTEST_START, BACKTEST_END)
    daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
    trading_days = sorted(daily['date_obj'].tolist())

    print("  Loading VIX data...")
    vix = fetcher.get_vix_daily(BACKTEST_START, BACKTEST_END)
    vix_map = {}
    if vix is not None and len(vix) > 0:
        vix['date_obj'] = pd.to_datetime(vix['date']).dt.date
        for _, row in vix.iterrows():
            vix_map[row['date_obj']] = {
                'vix_open': row.get('vix_open', 0),
                'vix_close': row.get('vix_close', 0),
            }
    print(f"  VIX data for {len(vix_map)} days")

    print(f"  Loading minute bars for {len(trading_days)} days...")
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

    # Build daily context: gap%, prior close, prior day return
    daily_context = {}
    daily_sorted = daily.sort_values('date_obj')
    closes = daily_sorted['close'].values
    opens = daily_sorted['open'].values
    highs = daily_sorted['high'].values
    lows = daily_sorted['low'].values
    dates = daily_sorted['date_obj'].values

    for i in range(1, len(dates)):
        d = dates[i]
        prev_close = closes[i-1]
        today_open = opens[i]
        gap_pct = (today_open - prev_close) / prev_close * 100
        prev_return = (closes[i-1] - closes[i-2]) / closes[i-2] * 100 if i >= 2 else 0
        prev_range = (highs[i-1] - lows[i-1]) / closes[i-1] * 100

        # 3-day trend
        if i >= 3:
            trend_3d = (closes[i-1] - closes[i-4]) / closes[i-4] * 100
        else:
            trend_3d = 0

        daily_context[pd.Timestamp(d).date() if hasattr(d, 'date') else d] = {
            'gap_pct': gap_pct,
            'prev_return': prev_return,
            'prev_range': prev_range,
            'trend_3d': trend_3d,
            'prev_close': prev_close,
        }

    print(f"  RTH bars: {len(minute):,}, Days: {minute['date'].nunique()}")
    return minute, daily, vix_map, daily_context


def compute_session_vwap(highs, lows, closes, volumes):
    tp = (highs + lows + closes) / 3.0
    vol = volumes.astype(np.float64)
    cum_tpv = np.cumsum(tp * vol)
    cum_v = np.cumsum(vol)
    with np.errstate(divide='ignore', invalid='ignore'):
        vwap = np.where(cum_v > 0, cum_tpv / cum_v, 0.0)
    return vwap


def find_signals(minute_data, vix_map, daily_context):
    """Find all entry signals with enriched context."""
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
        opens = day_df['open'].values.astype(np.float64)
        volumes = day_df['volume'].values.astype(np.float64)
        times = day_df['time'].values
        timestamps = day_df['ts'].values

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
                fwd_h = highs[i+1:end].copy()
                fwd_l = lows[i+1:end].copy()
                fwd_c = closes[i+1:end].copy()

                # Velocity
                velocity_bars = 0
                for j in range(i, -1, -1):
                    if closes[j] >= vwap[j]:
                        velocity_bars = i - j
                        break

                # Entry time
                entry_time = times[i]
                entry_hour = entry_time.hour
                entry_minute = entry_time.minute
                minutes_from_open = (entry_hour - 9) * 60 + (entry_minute - 30)

                # Volume context: ratio of entry bar volume to avg first 30 bars
                avg_vol_30 = np.mean(volumes[:min(30, i)]) if i > 0 else volumes[0]
                vol_ratio = volumes[i] / avg_vol_30 if avg_vol_30 > 0 else 1.0

                # VWAP deviation at entry (how far below)
                vwap_dev = (v - entry_price) / v * 100

                # Day of week
                if hasattr(d, 'weekday'):
                    dow = d.weekday()
                else:
                    dow = pd.Timestamp(d).weekday()

                # VIX
                vix_info = vix_map.get(d, {})
                vix_close = vix_info.get('vix_close', 0)

                # Daily context
                ctx = daily_context.get(d, {})

                # Compute P&L (baseline exit)
                nb = len(fwd_h)
                target_price = entry_price * (1 + TARGET_PCT / 100)
                stop_price = entry_price * (1 - STOP_PCT / 100)
                pnl = 0.0
                exit_type = 'time'
                bars_held = min(TIME_BARS, nb)

                for bi in range(min(nb, TIME_BARS)):
                    if fwd_l[bi] <= stop_price:
                        pnl = -STOP_PCT
                        exit_type = 'stop'
                        bars_held = bi + 1
                        break
                    if fwd_h[bi] >= target_price:
                        pnl = TARGET_PCT
                        exit_type = 'target'
                        bars_held = bi + 1
                        break
                else:
                    exit_idx = min(TIME_BARS, nb) - 1
                    if 0 <= exit_idx < len(fwd_c):
                        pnl = (fwd_c[exit_idx] - entry_price) / entry_price * 100

                signals.append({
                    'date': d,
                    'entry_price': entry_price,
                    'entry_time': entry_time,
                    'minutes_from_open': minutes_from_open,
                    'velocity_bars': velocity_bars,
                    'vol_ratio': vol_ratio,
                    'vwap_dev': vwap_dev,
                    'dow': dow,
                    'vix': vix_close,
                    'gap_pct': ctx.get('gap_pct', 0),
                    'prev_return': ctx.get('prev_return', 0),
                    'prev_range': ctx.get('prev_range', 0),
                    'trend_3d': ctx.get('trend_3d', 0),
                    'pnl': pnl,
                    'exit_type': exit_type,
                    'bars_held': bars_held,
                    'in_sample': d < WF_SPLIT,
                })
                break  # one signal per day

        if (idx + 1) % 200 == 0:
            print(f"  Day {idx+1}/{len(trading_days)}: {len(signals)} signals")

    return signals


def bucket_analysis(signals, field, buckets, bucket_labels):
    """Analyze P&L by buckets of a given field."""
    results = []
    for i, (lo, hi) in enumerate(buckets):
        group = [s for s in signals if lo <= s[field] < hi]
        if len(group) < 5:
            results.append(None)
            continue
        pnls = [s['pnl'] for s in group]
        a = np.array(pnls)
        n = len(a)
        avg = np.mean(a)
        std = np.std(a, ddof=1) if n > 1 else 0
        wr = np.sum(a > 0) / n
        tpy = n / 4.2
        sharpe = avg / std * np.sqrt(tpy) if std > 1e-10 else 0
        wins = a[a > 0]
        losses = a[a < 0]
        pf = np.sum(wins) / abs(np.sum(losses)) if len(losses) > 0 else 99.9
        results.append({
            'label': bucket_labels[i], 'n': n, 'avg': avg, 'wr': wr,
            'sharpe': round(sharpe, 3), 'pf': round(pf, 2), 'total': float(np.sum(a)),
        })
    return results


def print_bucket_table(title, results):
    print(f"\n  {title}")
    print(f"  {'Bucket':<25} {'N':>5} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'Avg%':>9} {'Total%':>9}")
    print(f"  {'-'*72}")
    for r in results:
        if r is None:
            continue
        print(f"  {r['label']:<25} {r['n']:>5} {r['sharpe']:>7.3f} {r['wr']:>5.1%} "
              f"{r['pf']:>6.2f} {r['avg']:>+8.5f} {r['total']:>+9.3f}")


def test_sizing_strategy(signals, field, thresholds, multipliers, base_risk=46000):
    """Test a sizing strategy where risk scales based on field value.
    thresholds: list of cutoffs, multipliers: list of multipliers (len = thresholds+1).
    Returns metrics."""
    pnls_weighted = []
    pnls_with_dates = []

    for s in signals:
        val = s[field]
        # Find which bucket
        mult = multipliers[0]
        for i, t in enumerate(thresholds):
            if val >= t:
                mult = multipliers[i + 1]
        risk = base_risk * mult
        # P&L in dollars (using risk as position sizing basis)
        # shares = risk / (entry * stop_pct/100)
        shares = risk / (s['entry_price'] * STOP_PCT / 100)
        dollar_pnl = shares * s['entry_price'] * s['pnl'] / 100
        pnls_weighted.append(dollar_pnl)
        pnls_with_dates.append((s['date'], dollar_pnl))

    a = np.array(pnls_weighted)
    n = len(a)
    avg = np.mean(a)
    std = np.std(a, ddof=1)
    wr = np.sum(a > 0) / n
    sharpe = avg / std * np.sqrt(n / 4.2) if std > 1e-10 else 0
    wins = a[a > 0]
    losses = a[a < 0]
    pf = np.sum(wins) / abs(np.sum(losses)) if len(losses) > 0 else 99.9

    cum = np.cumsum(a)
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum)

    # Yearly
    by_year = defaultdict(list)
    for d, p in pnls_with_dates:
        by_year[d.year].append(p)
    neg_years = 0
    for yr, yp in by_year.items():
        ya = np.array(yp)
        if np.mean(ya) < 0:
            neg_years += 1

    return {
        'n': n, 'sharpe': round(sharpe, 3), 'wr': round(wr, 3),
        'pf': round(pf, 2), 'total': round(float(np.sum(a)), 0),
        'avg': round(avg, 2), 'max_dd': round(max_dd, 0),
        'neg_years': neg_years,
    }


def main():
    t0 = time.time()
    print("=" * 90)
    print("  ENTRY FILTER & SIZING ANALYSIS")
    print("  SPY BUY 0.4% below VWAP | tgt=0.75% | stp=1.0% | 15min")
    print("=" * 90)

    print("\n[1/4] Loading data...")
    minute_data, daily, vix_map, daily_context = load_data()

    print("\n[2/4] Finding signals with enriched context...")
    signals = find_signals(minute_data, vix_map, daily_context)
    print(f"  Total signals: {len(signals)}")

    # Split IS/OOS
    is_signals = [s for s in signals if s['in_sample']]
    oos_signals = [s for s in signals if not s['in_sample']]
    print(f"  In-sample (< 2024-07-01): {len(is_signals)}")
    print(f"  Out-of-sample: {len(oos_signals)}")

    # ============================================================
    print(f"\n{'='*90}")
    print("  [3/4] FACTOR ANALYSIS — Which factors predict P&L?")
    print(f"{'='*90}")

    # --- TIME OF DAY ---
    tod_buckets = [(0, 15), (15, 30), (30, 60), (60, 120), (120, 195), (195, 390)]
    tod_labels = ['0-15m (9:30-9:45)', '15-30m (9:45-10:00)', '30-60m (10:00-10:30)',
                  '60-120m (10:30-11:30)', '120-195m (11:30-12:45)', '195m+ (12:45+)']
    print_bucket_table("TIME OF DAY (minutes from open)", bucket_analysis(signals, 'minutes_from_open', tod_buckets, tod_labels))

    # Finer early morning
    tod_fine = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 45), (45, 60)]
    tod_fine_labels = ['0-5m', '5-10m', '10-15m', '15-20m', '20-30m', '30-45m', '45-60m']
    print_bucket_table("FIRST HOUR DETAIL", bucket_analysis(signals, 'minutes_from_open', tod_fine, tod_fine_labels))

    # --- VIX REGIME ---
    vix_buckets = [(0, 13), (13, 16), (16, 20), (20, 25), (25, 30), (30, 100)]
    vix_labels = ['VIX < 13', 'VIX 13-16', 'VIX 16-20', 'VIX 20-25', 'VIX 25-30', 'VIX 30+']
    print_bucket_table("VIX REGIME", bucket_analysis(signals, 'vix', vix_buckets, vix_labels))

    # --- VELOCITY ---
    vel_buckets = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 50), (50, 500)]
    vel_labels = ['0-1 bars (instant)', '2-4 bars (fast)', '5-9 bars', '10-19 bars',
                  '20-49 bars', '50+ bars (slow grind)']
    print_bucket_table("VELOCITY (bars to reach threshold)", bucket_analysis(signals, 'velocity_bars', vel_buckets, vel_labels))

    # --- GAP % ---
    gap_buckets = [(-10, -1.0), (-1.0, -0.5), (-0.5, -0.1), (-0.1, 0.1), (0.1, 0.5), (0.5, 1.0), (1.0, 10)]
    gap_labels = ['Gap < -1%', 'Gap -1 to -0.5%', 'Gap -0.5 to -0.1%', 'Gap flat',
                  'Gap +0.1 to +0.5%', 'Gap +0.5 to +1%', 'Gap > +1%']
    print_bucket_table("OPENING GAP", bucket_analysis(signals, 'gap_pct', gap_buckets, gap_labels))

    # --- DAY OF WEEK ---
    dow_buckets = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]
    dow_labels = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    print_bucket_table("DAY OF WEEK", bucket_analysis(signals, 'dow', dow_buckets, dow_labels))

    # --- VOLUME RATIO ---
    vr_buckets = [(0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.5), (2.5, 100)]
    vr_labels = ['Low vol (<0.5x avg)', 'Normal (0.5-1x)', 'Elevated (1-1.5x)',
                 'High (1.5-2.5x)', 'Spike (>2.5x)']
    print_bucket_table("VOLUME RATIO (entry bar vs 30-bar avg)", bucket_analysis(signals, 'vol_ratio', vr_buckets, vr_labels))

    # --- PRIOR DAY RETURN ---
    pdr_buckets = [(-10, -1.5), (-1.5, -0.5), (-0.5, 0), (0, 0.5), (0.5, 1.5), (1.5, 10)]
    pdr_labels = ['Prior day < -1.5%', '-1.5 to -0.5%', '-0.5 to 0%', '0 to +0.5%', '+0.5 to +1.5%', 'Prior day > +1.5%']
    print_bucket_table("PRIOR DAY RETURN", bucket_analysis(signals, 'prev_return', pdr_buckets, pdr_labels))

    # --- 3-DAY TREND ---
    trend_buckets = [(-20, -2), (-2, -0.5), (-0.5, 0.5), (0.5, 2), (2, 20)]
    trend_labels = ['3d trend < -2%', '-2 to -0.5%', 'Flat (-0.5 to +0.5%)',
                    '+0.5 to +2%', '3d trend > +2%']
    print_bucket_table("3-DAY TREND", bucket_analysis(signals, 'trend_3d', trend_buckets, trend_labels))

    # --- VWAP DEVIATION ---
    dev_buckets = [(0.35, 0.42), (0.42, 0.50), (0.50, 0.60), (0.60, 0.80), (0.80, 5.0)]
    dev_labels = ['Tight 0.35-0.42%', 'Moderate 0.42-0.50%', 'Wide 0.50-0.60%',
                  'Deep 0.60-0.80%', 'Very deep 0.80%+']
    print_bucket_table("VWAP DEVIATION AT ENTRY", bucket_analysis(signals, 'vwap_dev', dev_buckets, dev_labels))

    # ============================================================
    print(f"\n{'='*90}")
    print("  [4/4] SIZING STRATEGY TESTS")
    print("  Testing risk multipliers based on strongest factors")
    print(f"{'='*90}")

    # Baseline: flat $46K risk
    baseline = test_sizing_strategy(signals, 'minutes_from_open', [], [1.0])
    print(f"\n  BASELINE (flat $46K risk): Sharpe={baseline['sharpe']}, PF={baseline['pf']}, "
          f"Total=${baseline['total']:,.0f}, MaxDD=${baseline['max_dd']:,.0f}")

    sizing_tests = []

    # --- TIME OF DAY SIZING ---
    # More risk in first 30 min, less later
    for early_mult, late_mult, cutoff in [
        (1.5, 0.7, 30), (2.0, 0.5, 30), (1.5, 0.7, 60),
        (2.0, 0.5, 60), (1.5, 1.0, 30), (2.0, 1.0, 30),
        (1.5, 0.5, 15), (2.0, 0.3, 30), (1.0, 0.5, 60),
        (3.0, 0.5, 30), (2.5, 0.5, 30),
    ]:
        r = test_sizing_strategy(signals, 'minutes_from_open', [cutoff], [early_mult, late_mult])
        sizing_tests.append((f"TOD: {early_mult}x if <{cutoff}m, {late_mult}x after", r))

    # --- VIX SIZING ---
    for lo_mult, hi_mult, vix_cutoff in [
        (0.5, 1.5, 20), (0.5, 2.0, 20), (1.0, 1.5, 20),
        (0.5, 1.5, 25), (0.7, 1.5, 18), (0.3, 2.0, 22),
        (1.0, 2.0, 25), (0.5, 1.5, 16),
    ]:
        r = test_sizing_strategy(signals, 'vix', [vix_cutoff], [lo_mult, hi_mult])
        sizing_tests.append((f"VIX: {lo_mult}x if VIX<{vix_cutoff}, {hi_mult}x if VIX>={vix_cutoff}", r))

    # --- VELOCITY SIZING ---
    for fast_mult, slow_mult, vel_cutoff in [
        (1.5, 0.7, 10), (2.0, 0.5, 10), (1.5, 0.7, 5),
        (2.0, 0.5, 5), (1.5, 1.0, 10), (2.0, 0.5, 20),
        (1.0, 0.5, 10), (2.0, 0.7, 15),
    ]:
        r = test_sizing_strategy(signals, 'velocity_bars', [vel_cutoff], [fast_mult, slow_mult])
        sizing_tests.append((f"VEL: {fast_mult}x if vel<{vel_cutoff}b, {slow_mult}x if >={vel_cutoff}b", r))

    # --- GAP SIZING ---
    for gap_dn_mult, gap_up_mult, gap_thresh in [
        (1.5, 0.7, 0), (2.0, 0.5, 0), (1.5, 0.7, -0.3),
        (2.0, 0.5, -0.5), (1.5, 1.0, -0.3),
    ]:
        r = test_sizing_strategy(signals, 'gap_pct', [gap_thresh], [gap_dn_mult, gap_up_mult])
        sizing_tests.append((f"GAP: {gap_dn_mult}x if gap<{gap_thresh}%, {gap_up_mult}x if >={gap_thresh}%", r))

    # --- COMBINED: TOD + VIX ---
    # Custom combined tests
    for s in signals:
        # Create combined score
        tod_score = 1.5 if s['minutes_from_open'] < 30 else 0.7
        vix_score = 1.5 if s['vix'] >= 20 else 0.7
        s['combined_tod_vix'] = tod_score * vix_score

    comb_buckets = [(0, 0.6), (0.6, 1.2), (1.2, 3.0)]
    comb_labels = ['Low (late + low VIX)', 'Medium', 'High (early + high VIX)']
    print_bucket_table("\n  COMBINED TOD x VIX SCORE", bucket_analysis(signals, 'combined_tod_vix', comb_buckets, comb_labels))

    # Test combined as sizing
    for base_mult in [0.5, 0.7, 1.0]:
        r = test_sizing_strategy(signals, 'combined_tod_vix', [0.6, 1.2], [base_mult * 0.5, base_mult, base_mult * 2.0])
        sizing_tests.append((f"COMBO TOD*VIX: low={base_mult*0.5}x mid={base_mult}x hi={base_mult*2}x", r))

    # --- COMBINED: TOD + VELOCITY ---
    for s in signals:
        tod_s = 1.5 if s['minutes_from_open'] < 30 else 0.7
        vel_s = 1.5 if s['velocity_bars'] < 10 else 0.7
        s['combined_tod_vel'] = tod_s * vel_s

    print_bucket_table("  COMBINED TOD x VELOCITY SCORE", bucket_analysis(signals, 'combined_tod_vel', comb_buckets, comb_labels))

    for base_mult in [0.5, 0.7, 1.0]:
        r = test_sizing_strategy(signals, 'combined_tod_vel', [0.6, 1.2], [base_mult * 0.5, base_mult, base_mult * 2.0])
        sizing_tests.append((f"COMBO TOD*VEL: low={base_mult*0.5}x mid={base_mult}x hi={base_mult*2}x", r))

    # --- BINARY FILTERS (skip trade entirely) ---
    print(f"\n{'='*90}")
    print("  BINARY FILTERS — Skip trade if condition met")
    print(f"{'='*90}")

    filter_tests = []
    for label, condition in [
        ('Skip if entry > 120m from open', lambda s: s['minutes_from_open'] <= 120),
        ('Skip if entry > 60m from open', lambda s: s['minutes_from_open'] <= 60),
        ('Skip if entry > 30m from open', lambda s: s['minutes_from_open'] <= 30),
        ('Skip if VIX < 15', lambda s: s['vix'] >= 15),
        ('Skip if VIX < 13', lambda s: s['vix'] >= 13),
        ('Skip if velocity > 50 bars', lambda s: s['velocity_bars'] <= 50),
        ('Skip if velocity > 20 bars', lambda s: s['velocity_bars'] <= 20),
        ('Skip if gap > +1%', lambda s: s['gap_pct'] <= 1.0),
        ('Skip if gap < -1%', lambda s: s['gap_pct'] >= -1.0),
        ('Skip if vol ratio < 0.5', lambda s: s['vol_ratio'] >= 0.5),
        ('Skip Fridays', lambda s: s['dow'] != 4),
        ('Only Mon-Wed', lambda s: s['dow'] <= 2),
        ('Skip if 3d trend > +2%', lambda s: s['trend_3d'] <= 2.0),
        ('Only entry < 60m AND VIX >= 16', lambda s: s['minutes_from_open'] <= 60 and s['vix'] >= 16),
        ('Only entry < 30m AND velocity < 10', lambda s: s['minutes_from_open'] <= 30 and s['velocity_bars'] < 10),
    ]:
        filtered = [s for s in signals if condition(s)]
        if len(filtered) >= 10:
            pnls = [s['pnl'] for s in filtered]
            a = np.array(pnls)
            avg = np.mean(a)
            std = np.std(a, ddof=1)
            wr = np.sum(a > 0) / len(a)
            sharpe = avg / std * np.sqrt(len(a) / 4.2) if std > 1e-10 else 0
            wins = a[a > 0]
            losses = a[a < 0]
            pf = np.sum(wins) / abs(np.sum(losses)) if len(losses) > 0 else 99.9
            filter_tests.append((label, len(filtered), round(sharpe, 3), round(wr, 3), round(pf, 2), round(avg, 5)))

    print(f"  {'Filter':<45} {'N':>5} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'Avg%':>9}")
    print(f"  {'-'*82}")
    print(f"  {'BASELINE (no filter)':<45} {len(signals):>5} {baseline['sharpe']:>7.3f} {baseline['wr']:>5.1%} {baseline['pf']:>6.2f} {np.mean([s['pnl'] for s in signals]):>+8.5f}")
    for label, n, sh, wr, pf, avg in sorted(filter_tests, key=lambda x: x[2], reverse=True):
        print(f"  {label:<45} {n:>5} {sh:>7.3f} {wr:>5.1%} {pf:>6.2f} {avg:>+8.5f}")

    # --- PRINT ALL SIZING RESULTS ---
    print(f"\n{'='*90}")
    print("  SIZING STRATEGY RESULTS — Sorted by Sharpe")
    print(f"{'='*90}")
    sizing_tests.sort(key=lambda x: x[1]['sharpe'], reverse=True)
    print(f"  {'Strategy':<55} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'Total$':>12} {'MaxDD$':>10} {'NegYr':>5}")
    print(f"  {'-'*105}")
    print(f"  {'BASELINE (flat $46K)':<55} {baseline['sharpe']:>7.3f} {baseline['wr']:>5.1%} {baseline['pf']:>6.2f} "
          f"${baseline['total']:>10,.0f} ${baseline['max_dd']:>9,.0f} {baseline['neg_years']:>5}")
    for name, r in sizing_tests:
        print(f"  {name:<55} {r['sharpe']:>7.3f} {r['wr']:>5.1%} {r['pf']:>6.2f} "
              f"${r['total']:>10,.0f} ${r['max_dd']:>9,.0f} {r['neg_years']:>5}")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.1f}s")

    # Save
    save_data = {
        'baseline': baseline,
        'sizing_tests': {name: r for name, r in sizing_tests},
        'filter_tests': filter_tests,
    }
    with open('entry_filters_results.json', 'w') as f:
        json.dump(save_data, f, indent=2, default=str)
    print(f"  Saved to entry_filters_results.json")


if __name__ == '__main__':
    main()

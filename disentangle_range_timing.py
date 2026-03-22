#!/usr/bin/env python3
"""
Disentangle today_range_pct from mins_from_open.
Is today_range_pct actually predictive WITHIN time buckets?
Or is it just a proxy for entry timing?
"""

import json
import numpy as np
from collections import defaultdict

with open('kite_deep_features.json') as f:
    trades = json.load(f)

# Filter to trades after 10m (matching V16b skip)
trades = [t for t in trades if t.get('mins_from_open', 0) >= 10]
print(f"Trades after 10m: {len(trades)}")

# ================================================================
# TEST 1: Is today_range_pct predictive WITHIN time buckets?
# ================================================================
print("\n" + "="*100)
print("  TEST 1: today_range_pct predictive power WITHIN time buckets")
print("="*100)

time_buckets = [
    (10, 45, "10-45m (early)"),
    (45, 120, "45-120m (mid-morning)"),
    (120, 240, "120-240m (afternoon)"),
    (240, 400, "240-390m (late)"),
]

for tlo, thi, label in time_buckets:
    bucket = [t for t in trades if tlo <= t.get('mins_from_open', 0) < thi]
    if len(bucket) < 20:
        print(f"\n  {label}: only {len(bucket)} trades, skipping")
        continue

    ranges = [t['today_range_pct'] for t in bucket]
    median_range = np.median(ranges)

    lo_range = [t for t in bucket if t['today_range_pct'] < median_range]
    hi_range = [t for t in bucket if t['today_range_pct'] >= median_range]

    def sharpe(group):
        pnls = [t['pnl'] for t in group]
        if len(pnls) < 5:
            return 0, 0, 0
        s = np.std(pnls, ddof=1)
        sh = np.mean(pnls) / s * np.sqrt(len(pnls)/4.2) if s > 0 else 0
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        return sh, wr, np.mean(pnls)

    sh_lo, wr_lo, avg_lo = sharpe(lo_range)
    sh_hi, wr_hi, avg_hi = sharpe(hi_range)

    print(f"\n  {label}: N={len(bucket)}, median_range={median_range:.3f}%")
    print(f"    Low range  (<{median_range:.2f}%): N={len(lo_range):3d}  Sharpe={sh_lo:.3f}  WR={wr_lo:.1%}  AvgPnL=${avg_lo:,.0f}")
    print(f"    High range (>{median_range:.2f}%): N={len(hi_range):3d}  Sharpe={sh_hi:.3f}  WR={wr_hi:.1%}  AvgPnL=${avg_hi:,.0f}")
    print(f"    Spread: {abs(sh_lo - sh_hi):.3f}")

# ================================================================
# TEST 2: Is timing predictive WITHIN range buckets?
# ================================================================
print("\n" + "="*100)
print("  TEST 2: Timing predictive power WITHIN range buckets")
print("="*100)

range_buckets = [
    (0, 1.0, "Low range (<1.0%)"),
    (1.0, 1.5, "Mid range (1.0-1.5%)"),
    (1.5, 20.0, "High range (>1.5%)"),
]

for rlo, rhi, label in range_buckets:
    bucket = [t for t in trades if rlo <= t['today_range_pct'] < rhi]
    if len(bucket) < 20:
        print(f"\n  {label}: only {len(bucket)} trades, skipping")
        continue

    mins = [t.get('mins_from_open', 100) for t in bucket]
    median_mins = np.median(mins)

    early = [t for t in bucket if t.get('mins_from_open', 100) < median_mins]
    late = [t for t in bucket if t.get('mins_from_open', 100) >= median_mins]

    def sharpe(group):
        pnls = [t['pnl'] for t in group]
        if len(pnls) < 5:
            return 0, 0, 0
        s = np.std(pnls, ddof=1)
        sh = np.mean(pnls) / s * np.sqrt(len(pnls)/4.2) if s > 0 else 0
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        return sh, wr, np.mean(pnls)

    sh_e, wr_e, avg_e = sharpe(early)
    sh_l, wr_l, avg_l = sharpe(late)

    print(f"\n  {label}: N={len(bucket)}, median_mins={median_mins:.0f}")
    print(f"    Early (<{median_mins:.0f}m): N={len(early):3d}  Sharpe={sh_e:.3f}  WR={wr_e:.1%}  AvgPnL=${avg_e:,.0f}")
    print(f"    Late  (>{median_mins:.0f}m): N={len(late):3d}  Sharpe={sh_l:.3f}  WR={wr_l:.1%}  AvgPnL=${avg_l:,.0f}")
    print(f"    Spread: {abs(sh_e - sh_l):.3f}")

# ================================================================
# TEST 3: Normalize range by time (range per bar)
# ================================================================
print("\n" + "="*100)
print("  TEST 3: Range-per-bar (time-normalized range)")
print("="*100)

for t in trades:
    bars = max(t.get('bars_into_session', 1), 1)
    t['range_per_bar'] = t['today_range_pct'] / bars

ranges_per_bar = [t['range_per_bar'] for t in trades]
print(f"  range_per_bar: min={min(ranges_per_bar):.4f}, max={max(ranges_per_bar):.4f}, "
      f"median={np.median(ranges_per_bar):.4f}")

# Tercile analysis
sorted_trades = sorted(trades, key=lambda t: t['range_per_bar'])
n = len(sorted_trades)
t1 = n // 3
t2 = 2 * n // 3

terciles = [sorted_trades[:t1], sorted_trades[t1:t2], sorted_trades[t2:]]
labels = ['Low range/bar', 'Mid range/bar', 'High range/bar']

print(f"\n  {'Tercile':<18s} {'N':>4s} {'Sharpe':>8s} {'WR':>7s} {'AvgPnL':>10s} {'AvgRange':>10s} {'AvgMins':>8s}")
print(f"  {'-'*70}")
for label, group in zip(labels, terciles):
    pnls = [t['pnl'] for t in group]
    std = np.std(pnls, ddof=1) if len(pnls) > 1 else 1
    sh = np.mean(pnls) / std * np.sqrt(len(pnls)/4.2) if std > 0 else 0
    wr = sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0
    avg_range = np.mean([t['today_range_pct'] for t in group])
    avg_mins = np.mean([t.get('mins_from_open', 0) for t in group])
    print(f"  {label:<18s} {len(group):>4d} {sh:>8.3f} {wr:>6.1%} ${np.mean(pnls):>9,.0f} {avg_range:>9.3f}% {avg_mins:>7.0f}m")

# ================================================================
# TEST 4: ATR-normalized range (range / prior_day ATR)
# ================================================================
print("\n" + "="*100)
print("  TEST 4: ATR-normalized intraday range")
print("="*100)

for t in trades:
    atr = t.get('daily_atr_pct', 1.0)
    t['range_atr_norm'] = t['today_range_pct'] / atr if atr > 0 else t['today_range_pct']

# Tercile
sorted_trades = sorted(trades, key=lambda t: t['range_atr_norm'])
terciles = [sorted_trades[:t1], sorted_trades[t1:t2], sorted_trades[t2:]]

print(f"\n  {'Tercile':<18s} {'N':>4s} {'Sharpe':>8s} {'WR':>7s} {'AvgPnL':>10s} {'AvgNormR':>10s} {'AvgMins':>8s}")
print(f"  {'-'*70}")
for label, group in zip(labels, terciles):
    pnls = [t['pnl'] for t in group]
    std = np.std(pnls, ddof=1) if len(pnls) > 1 else 1
    sh = np.mean(pnls) / std * np.sqrt(len(pnls)/4.2) if std > 0 else 0
    wr = sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0
    avg_norm = np.mean([t['range_atr_norm'] for t in group])
    avg_mins = np.mean([t.get('mins_from_open', 0) for t in group])
    print(f"  {label:<18s} {len(group):>4d} {sh:>8.3f} {wr:>6.1%} ${np.mean(pnls):>9,.0f} {avg_norm:>9.3f} {avg_mins:>7.0f}m")

# ================================================================
# TEST 5: Multivariate: time + range + dist_open all independent?
# ================================================================
print("\n" + "="*100)
print("  TEST 5: Multivariate independence check")
print("="*100)

# 8 octants: time x range x dist_open
time_med = np.median([t.get('mins_from_open', 100) for t in trades])
range_med = np.median([t['today_range_pct'] for t in trades])
open_med = 0  # above/below open

print(f"  Medians: time={time_med:.0f}m, range={range_med:.3f}%, open=0%")
print(f"\n  {'Time':<8s} {'Range':<8s} {'Open':<8s} {'N':>4s} {'Sharpe':>8s} {'WR':>7s} {'AvgPnL':>10s}")
print(f"  {'-'*60}")

for t_label, t_filter in [('early', lambda t: t.get('mins_from_open',100) < time_med),
                           ('late', lambda t: t.get('mins_from_open',100) >= time_med)]:
    for r_label, r_filter in [('lo_rng', lambda t: t['today_range_pct'] < range_med),
                               ('hi_rng', lambda t: t['today_range_pct'] >= range_med)]:
        for o_label, o_filter in [('below', lambda t: t.get('dist_from_open_pct',0) < 0),
                                   ('above', lambda t: t.get('dist_from_open_pct',0) >= 0)]:
            group = [t for t in trades if t_filter(t) and r_filter(t) and o_filter(t)]
            if len(group) < 10:
                continue
            pnls = [t['pnl'] for t in group]
            std = np.std(pnls, ddof=1) if len(pnls) > 1 else 1
            sh = np.mean(pnls) / std * np.sqrt(len(pnls)/4.2) if std > 0 else 0
            wr = sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0
            print(f"  {t_label:<8s} {r_label:<8s} {o_label:<8s} {len(group):>4d} {sh:>8.3f} {wr:>6.1%} ${np.mean(pnls):>9,.0f}")

# ================================================================
# TEST 6: Test grading WITH and WITHOUT today_range
# controlling for time
# ================================================================
print("\n" + "="*100)
print("  TEST 6: Grading with time-controlled range")
print("="*100)

def test_grading(trades, grade_fn, name):
    sized_pnls = []
    skipped = 0
    for t in trades:
        mult = grade_fn(t)
        if mult <= 0:
            skipped += 1
            continue
        sized_pnls.append(t['pnl'] * mult)
    n = len(sized_pnls)
    if n < 10:
        return None
    total = sum(sized_pnls)
    avg = np.mean(sized_pnls)
    std = np.std(sized_pnls, ddof=1)
    sharpe = avg / std * np.sqrt(n / 4.2) if std > 0 else 0
    wr = sum(1 for p in sized_pnls if p > 0) / n
    wins = [p for p in sized_pnls if p > 0]
    losses = [p for p in sized_pnls if p <= 0]
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 99
    cum = np.cumsum(sized_pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum)
    return {
        'name': name, 'n': n, 'skipped': skipped, 'total': total,
        'avg': avg, 'sharpe': sharpe, 'wr': wr, 'pf': pf, 'max_dd': max_dd,
    }

def v16b(t):
    s = 1.0
    if t['prior_day_range_pct'] > 1.20: s += 0.2
    if t['prior_day_range_pct'] < 0.80: s -= 0.6
    if t['prior_day_body_pct'] > 0.50: s += 0.2
    if t['prior_day_body_pct'] < 0.35: s -= 0.6
    if t['return_2d'] < -1.49: s += 0.2
    if t['return_2d'] > 1.18: s -= 0.6
    if t['daily_sma5_above_sma20'] == 1: s += 0.3
    else: s -= 0.3
    return max(s, 0.1)

# Range normalized by expected range at that time of day
# Expected range grows ~linearly with sqrt(time)
def time_adjusted_range(t):
    mins = max(t.get('mins_from_open', 10), 10)
    raw_range = t['today_range_pct']
    # Normalize: divide by sqrt(mins/390) to remove time dependency
    # At 390 mins (full day), factor = 1.0
    # At 30 mins, factor = sqrt(30/390) = 0.277
    time_factor = np.sqrt(mins / 390.0)
    return raw_range / time_factor if time_factor > 0 else raw_range

# Grade with time-adjusted range
def grade_time_adj(t):
    s = v16b(t)
    adj_range = time_adjusted_range(t)
    if adj_range > 2.5: s -= 1.0    # truly volatile for this time of day
    elif adj_range > 1.8: s -= 0.5
    if adj_range < 1.2: s += 0.3    # truly calm for this time of day

    dist_open = t.get('dist_from_open_pct', 0)
    if dist_open > 0: s -= 0.2

    dvr = t.get('daily_vol_ratio', 1.0)
    if dvr > 1.5: s -= 0.4

    return max(s, 0.1)

# Grade with raw range (for comparison)
def grade_raw_range(t):
    s = v16b(t)
    tr = t.get('today_range_pct', 0.5)
    if tr > 1.0: s -= 1.0
    if tr < 0.6: s += 0.3

    dist_open = t.get('dist_from_open_pct', 0)
    if dist_open > 0: s -= 0.2

    dvr = t.get('daily_vol_ratio', 1.0)
    if dvr > 1.5: s -= 0.4

    return max(s, 0.1)

# Grade with ONLY timing (no range)
def grade_timing_only(t):
    s = v16b(t)
    mins = t.get('mins_from_open', 100)
    if mins > 300: s -= 0.4
    if mins < 30: s += 0.2

    dist_open = t.get('dist_from_open_pct', 0)
    if dist_open > 0: s -= 0.2

    dvr = t.get('daily_vol_ratio', 1.0)
    if dvr > 1.5: s -= 0.4

    return max(s, 0.1)

# Grade with range_per_bar
def grade_range_per_bar(t):
    s = v16b(t)
    rpb = t.get('range_per_bar', 0.01)
    if rpb > 0.02: s -= 0.8      # high range per bar = truly volatile
    elif rpb > 0.01: s -= 0.3
    if rpb < 0.005: s += 0.2     # low range per bar = truly calm

    dist_open = t.get('dist_from_open_pct', 0)
    if dist_open > 0: s -= 0.2

    dvr = t.get('daily_vol_ratio', 1.0)
    if dvr > 1.5: s -= 0.4

    return max(s, 0.1)

# Grade with ATR-normalized range
def grade_atr_range(t):
    s = v16b(t)
    anr = t.get('range_atr_norm', 1.0)
    if anr > 1.3: s -= 0.8     # range exceeds ATR = extreme day
    elif anr > 0.9: s -= 0.3
    if anr < 0.5: s += 0.3     # range well below ATR = calm

    dist_open = t.get('dist_from_open_pct', 0)
    if dist_open > 0: s -= 0.2

    dvr = t.get('daily_vol_ratio', 1.0)
    if dvr > 1.5: s -= 0.4

    return max(s, 0.1)

graders = [
    (v16b, "V16b (no intraday)"),
    (grade_raw_range, "Raw range (champion)"),
    (grade_time_adj, "Time-adjusted range"),
    (grade_timing_only, "Timing only (no range)"),
    (grade_range_per_bar, "Range per bar"),
    (grade_atr_range, "ATR-normalized range"),
]

results = []
for fn, name in graders:
    r = test_grading(trades, fn, name)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)
v16b_sh = next(r['sharpe'] for r in results if 'V16b' in r['name'])

print(f"\n  {'Strategy':<30s} {'N':>5s} {'Sharpe':>8s} {'vs V16b':>8s} {'WR':>7s} {'PF':>6s} {'Total $':>13s} {'MaxDD $':>11s}")
print(f"  {'-'*95}")
for r in results:
    imp = (r['sharpe'] / v16b_sh - 1) * 100 if v16b_sh > 0 else 0
    sign = '+' if imp > 0 else ''
    print(f"  {r['name']:<30s} {r['n']:>5d} {r['sharpe']:>8.3f} {sign}{imp:>6.0f}% {r['wr']:>6.1%} {r['pf']:>6.2f} ${r['total']:>12,.0f} ${r['max_dd']:>10,.0f}")

# ================================================================
# TEST 7: Grid search on time-adjusted range thresholds
# ================================================================
print("\n" + "="*100)
print("  TEST 7: Grid search on time-adjusted range thresholds")
print("="*100)

best = []
for hi in [1.5, 1.8, 2.0, 2.5, 3.0]:
    for hi_p in [-0.5, -0.7, -0.8, -1.0, -1.2]:
        for lo in [0.8, 1.0, 1.2, 1.5]:
            for lo_r in [0, 0.1, 0.2, 0.3, 0.4]:
                def make_fn(h, hp, l, lr):
                    def fn(t):
                        s = v16b(t)
                        adj = time_adjusted_range(t)
                        if adj > h: s += hp
                        if adj < l: s += lr
                        dist_open = t.get('dist_from_open_pct', 0)
                        if dist_open > 0: s -= 0.2
                        dvr = t.get('daily_vol_ratio', 1.0)
                        if dvr > 1.5: s -= 0.4
                        return max(s, 0.1)
                    return fn
                fn = make_fn(hi, hi_p, lo, lo_r)
                r = test_grading(trades, fn, "grid")
                if r:
                    r['params'] = (hi, hi_p, lo, lo_r)
                    best.append(r)

best.sort(key=lambda x: x['sharpe'], reverse=True)
print(f"\n  Tested {len(best)} combos")
print(f"\n  Top 10:")
print(f"  {'Rank':>4s} {'Sharpe':>8s} {'vs V16b':>8s} {'N':>5s} {'PF':>6s} {'hi':>5s} {'hi_p':>6s} {'lo':>5s} {'lo_r':>6s}")
print(f"  {'-'*60}")
for i, r in enumerate(best[:10]):
    h, hp, l, lr = r['params']
    imp = (r['sharpe'] / v16b_sh - 1) * 100
    print(f"  {i+1:>4d} {r['sharpe']:>8.3f} {imp:>+7.0f}% {r['n']:>5d} {r['pf']:>6.2f} {h:>5.1f} {hp:>6.1f} {l:>5.1f} {lr:>6.2f}")

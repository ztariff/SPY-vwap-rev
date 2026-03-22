#!/usr/bin/env python3
"""Safe sizing strategies - zero hindsight, all features known at entry time."""

import json, numpy as np
from collections import defaultdict

with open('kite_deep_features.json') as f:
    trades = json.load(f)

FLAT_NOTIONAL = 15_000_000


def simulate(trades, name, size_fn, skip_fn=None):
    pnls, notionals, skipped = [], [], 0
    by_year = defaultdict(list)
    for t in trades:
        if skip_fn and skip_fn(t):
            skipped += 1
            continue
        mult = size_fn(t)
        if mult <= 0:
            skipped += 1
            continue
        nn = min(FLAT_NOTIONAL * mult, 25_000_000)
        pnl = t['ret_pct'] / 100.0 * nn
        pnls.append(pnl)
        notionals.append(nn)
        by_year[t['date'][:4]].append(pnl)
    if len(pnls) < 10:
        return None
    n = len(pnls)
    total = sum(pnls)
    avg = np.mean(pnls)
    std = np.std(pnls, ddof=1)
    sharpe = avg / std * np.sqrt(n / 4.2) if std > 0 else 0
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / n
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 99
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum)
    neg_years = sum(1 for yr in by_year if sum(by_year[yr]) < 0)
    return {
        'name': name, 'n': n, 'total': total, 'avg': avg, 'sharpe': sharpe,
        'wr': wr, 'pf': pf, 'max_dd': max_dd, 'neg_years': neg_years,
        'by_year': dict(by_year), 'skipped': skipped
    }


strategies = []

# BASELINES
strategies.append(('A: BASELINE flat', lambda t: 1.0, None))
strategies.append(('B: Gap only', lambda t: 1.0, lambda t: t['gap_pct'] < -1.0))
strategies.append(('B2: Gap + skip TOD30-45', lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45))

# SINGLE FACTOR SKIPS
strategies.append(('C1: Skip 2d_rally >1.18%', lambda t: 1.0,
    lambda t: t['return_2d'] > 1.18))
strategies.append(('C2: Skip small prior body <0.23%', lambda t: 1.0,
    lambda t: t['prior_day_body_pct'] < 0.23))
strategies.append(('C3: Skip narrow prior range <0.80%', lambda t: 1.0,
    lambda t: t['prior_day_range_pct'] < 0.80))
strategies.append(('C4: Skip TOD30-45m', lambda t: 1.0,
    lambda t: 30 <= t['mins_from_open'] < 45))

# SINGLE FACTOR SIZING
strategies.append(('D1: 1.5x wide prior, 0.5x narrow',
    lambda t: 1.5 if t['prior_day_range_pct'] > 1.43 else (0.5 if t['prior_day_range_pct'] < 0.80 else 1.0),
    None))
strategies.append(('D2: 1.5x big body, 0.5x tiny',
    lambda t: 1.5 if t['prior_day_body_pct'] > 0.79 else (0.5 if t['prior_day_body_pct'] < 0.23 else 1.0),
    None))
strategies.append(('D3: 1.5x 2d drop, 0.5x 2d rally',
    lambda t: 1.5 if t['return_2d'] < -1.49 else (0.5 if t['return_2d'] > 1.18 else 1.0),
    None))
strategies.append(('D4: 1.5x SMA5>SMA20, 0.7x below',
    lambda t: 1.5 if t['daily_sma5_above_sma20'] == 1 else 0.7,
    None))

# COMBINED SKIPS
strategies.append(('E1: Gap + 2d>1.18', lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or t['return_2d'] > 1.18))
strategies.append(('E2: Gap + body<0.23', lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or t['prior_day_body_pct'] < 0.23))
strategies.append(('E3: Gap + range<0.80', lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or t['prior_day_range_pct'] < 0.80))
strategies.append(('E4: Gap + TOD30-45 + 2d>1.18', lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45 or t['return_2d'] > 1.18))
strategies.append(('E5: Gap + TOD30-45 + body<0.23', lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45 or t['prior_day_body_pct'] < 0.23))
strategies.append(('E6: Gap+TOD+2d+body<0.23', lambda t: 1.0,
    lambda t: (t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45 or
               t['return_2d'] > 1.18 or t['prior_day_body_pct'] < 0.23)))
strategies.append(('E7: Gap+TOD+2d+range<0.80', lambda t: 1.0,
    lambda t: (t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45 or
               t['return_2d'] > 1.18 or t['prior_day_range_pct'] < 0.80)))

# COMBINED SIZING + SKIP
strategies.append(('F1: Skip(gap+TOD) + 1.5x wide prior',
    lambda t: 1.5 if t['prior_day_range_pct'] > 1.43 else 1.0,
    lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45))
strategies.append(('F2: Skip(gap+TOD) + 1.5x big body',
    lambda t: 1.5 if t['prior_day_body_pct'] > 0.79 else 1.0,
    lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45))
strategies.append(('F3: Skip(gap+TOD+2d) + 1.5x wide prior',
    lambda t: 1.5 if t['prior_day_range_pct'] > 1.43 else 1.0,
    lambda t: (t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45 or
               t['return_2d'] > 1.18)))
strategies.append(('F4: Skip(gap+TOD+2d) + 1.5x body+prior',
    lambda t: (1.5 if t['prior_day_range_pct'] > 1.43 else 1.0) *
              (1.3 if t['prior_day_body_pct'] > 0.79 else 1.0),
    lambda t: (t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45 or
               t['return_2d'] > 1.18)))
strategies.append(('F5: Skip(gap+TOD+body<0.23) + 1.5x prior',
    lambda t: 1.5 if t['prior_day_range_pct'] > 1.43 else 1.0,
    lambda t: (t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45 or
               t['prior_day_body_pct'] < 0.23)))
strategies.append(('F6: Skip(all4) + 1.67x prior + 1.2x trend',
    lambda t: (1.67 if t['prior_day_range_pct'] > 1.43 else 1.0) *
              (1.2 if t['daily_sma5_above_sma20'] == 1 else 0.8),
    lambda t: (t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45 or
               t['return_2d'] > 1.18 or t['prior_day_body_pct'] < 0.23)))

# COMPOSITE SCORES
def safe_composite_v1(t):
    score = 1.0
    if t['prior_day_range_pct'] > 1.43: score += 0.3
    if t['prior_day_range_pct'] < 0.80: score -= 0.3
    if t['prior_day_body_pct'] > 0.79: score += 0.3
    if t['prior_day_body_pct'] < 0.23: score -= 0.3
    if t['return_2d'] < -1.49: score += 0.2
    if t['return_2d'] > 1.18: score -= 0.3
    if t['daily_sma5_above_sma20'] == 1: score += 0.15
    return max(score, 0.3)

def safe_composite_v2(t):
    score = 1.0
    if t['prior_day_range_pct'] > 1.43: score += 0.4
    if t['prior_day_range_pct'] < 0.80: score -= 0.4
    if t['prior_day_body_pct'] > 0.79: score += 0.3
    if t['prior_day_body_pct'] < 0.23: score -= 0.4
    if t['return_2d'] < -1.49: score += 0.3
    if t['return_2d'] > 1.18: score -= 0.4
    if t['daily_sma5_above_sma20'] == 1: score += 0.2
    if t['prior_week_range_pct'] > 5.32: score += 0.2
    return max(score, 0.2)

strategies.append(('G1: Composite v1 (gap skip)',
    safe_composite_v1, lambda t: t['gap_pct'] < -1.0))
strategies.append(('G2: Composite v1 (gap+TOD skip)',
    safe_composite_v1, lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45))
strategies.append(('G3: Composite v2 (gap skip)',
    safe_composite_v2, lambda t: t['gap_pct'] < -1.0))
strategies.append(('G4: Composite v2 (gap+TOD skip)',
    safe_composite_v2, lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45))

# Run all
results = []
for name, size_fn, skip_fn in strategies:
    r = simulate(trades, name, size_fn, skip_fn)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)

print('=' * 125)
print('  SAFE SIZING STRATEGIES (zero hindsight) - sorted by Sharpe')
print('=' * 125)
hdr = f"  {'Strategy':<48s} {'N':>4s} {'Skip':>4s} {'Sharpe':>7s} {'WR':>6s} {'PF':>5s} {'Total':>12s} {'AvgPnL':>9s} {'MaxDD':>10s} {'NY':>3s}"
print(hdr)
print(f"  {'-' * 112}")

for r in results:
    print(f"  {r['name']:<48s} {r['n']:>4d} {r['skipped']:>4d} {r['sharpe']:>7.3f} {r['wr']:>5.1%} {r['pf']:>5.2f} ${r['total']:>11,.0f} ${r['avg']:>8,.0f} ${r['max_dd']:>9,.0f} {r['neg_years']:>3d}")

# Yearly for top 4 + baseline
print()
print('YEARLY - Top 4 + Baseline')
print('=' * 80)
baseline = next(r for r in results if 'BASELINE' in r['name'])
show = results[:4]
if baseline not in show:
    show.append(baseline)

for r in show:
    print(f"\n  {r['name']} (Sharpe={r['sharpe']:.3f})")
    for yr in sorted(r['by_year'].keys()):
        yp = r['by_year'][yr]
        yt = sum(yp)
        n = len(yp)
        yw = sum(1 for p in yp if p > 0)
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={yw/n:.1%}")

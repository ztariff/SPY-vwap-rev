#!/usr/bin/env python3
"""
Safe sizing V2 - builds on G3 with new discoveries from deep exploration.

Key findings:
  1. GRID OPTIMIZED G3 weights: range_up=0.2, range_dn=0.5, body_up=0.3, body_dn=0.5,
     2d_up=0.2, 2d_dn=0.5, trend=0.3, week=0.0 -> Sharpe 1.629
  2. Skip first 10m adds +7% Sharpe (1.622 standalone)
  3. Velocity sizing adds +6% (1.598)
  4. SMA5 slope adds +4% (1.567)
  5. Body threshold optimal at 0.50 up / 0.35 down (not 0.79/0.23)
  6. Range threshold optimal at 1.20 up (not 1.43)
  7. Best interactions: range x trend (Sharpe spread 2.835),
     range x return_3d (2.315), body x return_3d (2.245)

All features are safe (zero hindsight).
"""

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
    avg_n = np.mean(notionals)
    return {
        'name': name, 'n': n, 'total': total, 'avg': avg, 'sharpe': sharpe,
        'wr': wr, 'pf': pf, 'max_dd': max_dd, 'neg_years': neg_years,
        'by_year': dict(by_year), 'skipped': skipped, 'avg_notional': avg_n
    }

strategies = []

# ============================================================
# REFERENCE: G3 original
# ============================================================
def g3_orig(t):
    s = 1.0
    if t['prior_day_range_pct'] > 1.43: s += 0.4
    if t['prior_day_range_pct'] < 0.80: s -= 0.4
    if t['prior_day_body_pct'] > 0.79: s += 0.3
    if t['prior_day_body_pct'] < 0.23: s -= 0.4
    if t['return_2d'] < -1.49: s += 0.3
    if t['return_2d'] > 1.18: s -= 0.4
    if t['daily_sma5_above_sma20'] == 1: s += 0.2
    if t['prior_week_range_pct'] > 5.32: s += 0.2
    return max(s, 0.2)

strategies.append(('REF: G3 original', g3_orig, lambda t: t['gap_pct'] < -1.0))

# ============================================================
# V1: GRID-OPTIMIZED G3 WEIGHTS (from 46K combos search)
# ============================================================
def v1_grid_opt(t):
    s = 1.0
    if t['prior_day_range_pct'] > 1.43: s += 0.2
    if t['prior_day_range_pct'] < 0.80: s -= 0.5
    if t['prior_day_body_pct'] > 0.79: s += 0.3
    if t['prior_day_body_pct'] < 0.23: s -= 0.5
    if t['return_2d'] < -1.49: s += 0.2
    if t['return_2d'] > 1.18: s -= 0.5
    if t['daily_sma5_above_sma20'] == 1: s += 0.3
    return max(s, 0.2)

strategies.append(('V1: Grid-optimized weights', v1_grid_opt, lambda t: t['gap_pct'] < -1.0))

# ============================================================
# V2: OPTIMIZED THRESHOLDS (body 0.50/0.35, range 1.20)
# ============================================================
def v2_opt_thresh(t):
    s = 1.0
    if t['prior_day_range_pct'] > 1.20: s += 0.4
    if t['prior_day_range_pct'] < 0.80: s -= 0.5
    if t['prior_day_body_pct'] > 0.50: s += 0.4
    if t['prior_day_body_pct'] < 0.35: s -= 0.5
    if t['return_2d'] < -1.49: s += 0.2
    if t['return_2d'] > 1.18: s -= 0.5
    if t['daily_sma5_above_sma20'] == 1: s += 0.3
    return max(s, 0.2)

strategies.append(('V2: Optimized thresholds', v2_opt_thresh, lambda t: t['gap_pct'] < -1.0))

# ============================================================
# V3: V1 + SKIP FIRST 10 MINUTES (+7% Sharpe from exploration)
# ============================================================
strategies.append(('V3: V1 + skip first 10m', v1_grid_opt,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V4: V2 + SKIP FIRST 10 MINUTES
# ============================================================
strategies.append(('V4: V2 + skip first 10m', v2_opt_thresh,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V5: V1 + VELOCITY OVERLAY (intraday feature)
# ============================================================
def v5_velocity(t):
    s = v1_grid_opt(t)
    vel = t.get('velocity', 0)
    if vel > 15: s += 0.2
    if vel < 3: s -= 0.2
    return max(s, 0.2)

strategies.append(('V5: V1 + velocity', v5_velocity, lambda t: t['gap_pct'] < -1.0))

# ============================================================
# V6: V1 + VELOCITY + SKIP FIRST 10m
# ============================================================
strategies.append(('V6: V1 + velocity + skip10m', v5_velocity,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V7: V1 + SMA5 SLOPE (prior-day, +4% from exploration)
# ============================================================
def v7_slope(t):
    s = v1_grid_opt(t)
    slope = t.get('daily_sma5_slope', 0)
    if slope > 0.5: s += 0.2
    if slope < -0.5: s -= 0.2
    return max(s, 0.2)

strategies.append(('V7: V1 + SMA5 slope', v7_slope, lambda t: t['gap_pct'] < -1.0))

# ============================================================
# V8: V1 + SMA5 SLOPE + SKIP 10m
# ============================================================
strategies.append(('V8: V1 + slope + skip10m', v7_slope,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V9: V2 + VELOCITY + SMA5 SLOPE + SKIP 10m (kitchen sink)
# ============================================================
def v9_kitchen(t):
    s = v2_opt_thresh(t)
    vel = t.get('velocity', 0)
    if vel > 15: s += 0.15
    if vel < 3: s -= 0.15
    slope = t.get('daily_sma5_slope', 0)
    if slope > 0.5: s += 0.15
    if slope < -0.5: s -= 0.15
    return max(s, 0.2)

strategies.append(('V9: V2+vel+slope+skip10m', v9_kitchen,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V10: return_3d interaction (strong predictor from Part 4)
# ============================================================
def v10_3d(t):
    s = v1_grid_opt(t)
    r3 = t.get('return_3d', 0)
    if r3 < -1.5: s += 0.3
    if r3 > 1.5: s -= 0.3
    return max(s, 0.2)

strategies.append(('V10: V1 + return_3d', v10_3d, lambda t: t['gap_pct'] < -1.0))

# ============================================================
# V11: V10 + skip 10m
# ============================================================
strategies.append(('V11: V1+3d+skip10m', v10_3d,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V12: DOW sizing (Mon+, Fri-)
# ============================================================
def v12_dow(t):
    s = v1_grid_opt(t)
    dow = t.get('dow', 2)
    if dow == 0: s += 0.15   # Monday
    if dow == 4: s -= 0.15   # Friday
    return max(s, 0.2)

strategies.append(('V12: V1 + DOW', v12_dow, lambda t: t['gap_pct'] < -1.0))

# ============================================================
# V13: consec_below_vwap (intraday, +3%)
# ============================================================
def v13_consec(t):
    s = v1_grid_opt(t)
    cb = t.get('consec_below_vwap', 0)
    if cb > 10: s += 0.2
    if cb < 3: s -= 0.15
    return max(s, 0.2)

strategies.append(('V13: V1 + consec below VWAP', v13_consec, lambda t: t['gap_pct'] < -1.0))

# ============================================================
# V14: MEGA COMBO - best prior-day + best intraday + skip10m
# ============================================================
def v14_mega(t):
    s = 1.0
    # Optimized prior-day from grid
    if t['prior_day_range_pct'] > 1.20: s += 0.3
    if t['prior_day_range_pct'] < 0.80: s -= 0.5
    if t['prior_day_body_pct'] > 0.50: s += 0.3
    if t['prior_day_body_pct'] < 0.35: s -= 0.5
    if t['return_2d'] < -1.49: s += 0.2
    if t['return_2d'] > 1.18: s -= 0.5
    if t['daily_sma5_above_sma20'] == 1: s += 0.3
    # SMA5 slope
    slope = t.get('daily_sma5_slope', 0)
    if slope > 0.5: s += 0.15
    if slope < -0.5: s -= 0.15
    # return_3d
    r3 = t.get('return_3d', 0)
    if r3 < -1.5: s += 0.2
    if r3 > 1.5: s -= 0.2
    # Velocity (intraday)
    vel = t.get('velocity', 0)
    if vel > 15: s += 0.15
    if vel < 3: s -= 0.15
    return max(s, 0.2)

strategies.append(('V14: MEGA prior+intra+skip10m', v14_mega,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V15: MEGA without intraday (prior-day only, can pre-compute)
# ============================================================
def v15_mega_prior(t):
    s = 1.0
    if t['prior_day_range_pct'] > 1.20: s += 0.3
    if t['prior_day_range_pct'] < 0.80: s -= 0.5
    if t['prior_day_body_pct'] > 0.50: s += 0.3
    if t['prior_day_body_pct'] < 0.35: s -= 0.5
    if t['return_2d'] < -1.49: s += 0.2
    if t['return_2d'] > 1.18: s -= 0.5
    if t['daily_sma5_above_sma20'] == 1: s += 0.3
    slope = t.get('daily_sma5_slope', 0)
    if slope > 0.5: s += 0.15
    if slope < -0.5: s -= 0.15
    r3 = t.get('return_3d', 0)
    if r3 < -1.5: s += 0.2
    if r3 > 1.5: s -= 0.2
    return max(s, 0.2)

strategies.append(('V15: MEGA prior-day only', v15_mega_prior, lambda t: t['gap_pct'] < -1.0))
strategies.append(('V15b: MEGA prior + skip10m', v15_mega_prior,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V16: Penalize harder for bad conditions (asymmetric)
# ============================================================
def v16_asym(t):
    s = 1.0
    # Be aggressive on upside, conservative on downside
    if t['prior_day_range_pct'] > 1.20: s += 0.2
    if t['prior_day_range_pct'] < 0.80: s -= 0.6
    if t['prior_day_body_pct'] > 0.50: s += 0.2
    if t['prior_day_body_pct'] < 0.35: s -= 0.6
    if t['return_2d'] < -1.49: s += 0.2
    if t['return_2d'] > 1.18: s -= 0.6
    if t['daily_sma5_above_sma20'] == 1: s += 0.3
    else: s -= 0.3
    return max(s, 0.1)

strategies.append(('V16: Asymmetric (heavy penalty)', v16_asym, lambda t: t['gap_pct'] < -1.0))
strategies.append(('V16b: Asymm + skip10m', v16_asym,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# ============================================================
# V17: Skip after 1pm (from exploration: Sharpe 1.528, +1% but higher avg PnL)
# ============================================================
strategies.append(('V17: V1 + skip after 1pm', v1_grid_opt,
    lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] > 210))

# ============================================================
# V18: Skip 30-45m (the original TOD skip)
# ============================================================
strategies.append(('V18: V1 + skip 30-45m', v1_grid_opt,
    lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45))


# ============================================================
# RUN ALL
# ============================================================
results = []
for name, size_fn, skip_fn in strategies:
    r = simulate(trades, name, size_fn, skip_fn)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)

g3_sharpe = next(r['sharpe'] for r in results if 'G3 original' in r['name'])

print('=' * 130)
print('  SAFE SIZING V2 - ENHANCED STRATEGIES (sorted by Sharpe)')
print('=' * 130)
print(f"  {'Strategy':<40s} {'N':>4s} {'Skip':>4s} {'Sharpe':>7s} {'vs G3':>6s} {'WR':>6s} {'PF':>5s} {'Total$':>12s} {'AvgPnL':>9s} {'MaxDD':>10s} {'AvgNot':>11s} {'NY':>3s}")
print(f"  {'-'*125}")

for r in results:
    diff = (r['sharpe'] / g3_sharpe - 1) * 100
    sign = '+' if diff > 0 else ''
    print(f"  {r['name']:<40s} {r['n']:>4d} {r['skipped']:>4d} {r['sharpe']:>7.3f} {sign}{diff:>4.0f}% {r['wr']:>5.1%} {r['pf']:>5.2f} ${r['total']:>11,.0f} ${r['avg']:>8,.0f} ${r['max_dd']:>9,.0f} ${r['avg_notional']:>10,.0f} {r['neg_years']:>3d}")

# Yearly for top 5 + G3 ref
print('\n' + '=' * 80)
print('  YEARLY - Top 5 + G3 ref')
print('=' * 80)
g3_ref = next(r for r in results if 'G3 original' in r['name'])
show = results[:5]
if g3_ref not in show:
    show.append(g3_ref)

for r in show:
    diff = (r['sharpe'] / g3_sharpe - 1) * 100
    print(f"\n  {r['name']} (Sharpe={r['sharpe']:.3f}, {diff:+.0f}% vs G3)")
    for yr in sorted(r['by_year'].keys()):
        yp = r['by_year'][yr]
        yt = sum(yp)
        n = len(yp)
        yw = sum(1 for p in yp if p > 0)
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={yw/n:.1%}")

# Summary
print('\n' + '=' * 80)
print('  SUMMARY')
print('=' * 80)
best = results[0]
print(f"  Best: {best['name']}")
print(f"  Sharpe: {best['sharpe']:.3f} (vs G3 {g3_sharpe:.3f}, +{(best['sharpe']/g3_sharpe-1)*100:.0f}%)")
print(f"  Trades: {best['n']}, Skipped: {best['skipped']}")
print(f"  Total P&L: ${best['total']:,.0f}")
print(f"  Avg P&L: ${best['avg']:,.0f}")
print(f"  Neg years: {best['neg_years']}")
print(f"\n  Top 3 for KITE testing:")
for i, r in enumerate(results[:3]):
    has_intraday = any(kw in r['name'].lower() for kw in ['vel', 'consec', 'intra', 'momentum'])
    impl = 'needs code changes' if has_intraday else 'prior-day CSV only'
    print(f"    {i+1}. {r['name']} (Sharpe {r['sharpe']:.3f}) [{impl}]")

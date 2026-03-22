#!/usr/bin/env python3
"""
Build and test sizing strategies from KITE-validated features.
Replays the 519 real KITE trades at different position sizes.
"""

import json, csv
import numpy as np
from collections import defaultdict

# Load enriched trades
with open('kite_deep_features.json') as f:
    trades = json.load(f)

print(f"Loaded {len(trades)} enriched KITE trades")

FLAT_NOTIONAL = 15_000_000

# ---------------------------------------------------------------
# KEY FINDINGS FROM FEATURE ANALYSIS:
#
# Rank  Feature              |Corr|   Direction    Interpretation
# 1.  daily_vol_ratio       0.109    NEGATIVE     Low volume days = better trades
# 2.  today_range_pct       0.102    NEGATIVE     Tight range days = much better
# 3.  return_2d             0.092    NEGATIVE     After 2-day selloff = better
# 4.  prior_day_body_pct    0.092    POSITIVE     Big prior candle body = better
# 5.  prior_day_range_pct   0.091    POSITIVE     Wide prior day range = better
# 6.  velocity              0.089    POSITIVE     More bars below VWAP = better
# 7.  daily_sma5>sma20      0.070    POSITIVE     Uptrend = better
# 8.  hold_mins             0.069    NEGATIVE     Quick exits = better (obvious)
# 9.  momentum_3b           0.066    NEGATIVE     After sharp drop = better
# 10. momentum_5b           0.063    NEGATIVE     After 5-bar drop = better
#
# Strongest actionable findings (bucketed):
# - today_range_pct < 0.957%:  Sharpe 3.603, WR 70.2%, N=104
# - daily_vol_ratio < 0.838:   Sharpe 0.965, WR 57.7%, N=104
# - daily_vol_ratio 0.838-0.973: Sharpe 1.215, WR 59.6%, N=104
# - daily_vol_ratio > 1.353:  Sharpe -0.810, WR 45.2%, N=104
# - prior_day_range > 2.07%:  Sharpe 1.073, WR 57.7%, N=104
# - prior_day_body > 0.79%:   Sharpe 1.461, WR 55.8%, N=104
# - return_2d < -1.49%:       Sharpe 0.982, WR 52.9%, N=104
# - return_2d > +1.18%:       Sharpe -0.222, WR 49.0%, N=104
# ---------------------------------------------------------------


def simulate(trades, name, size_fn, skip_fn=None):
    """Replay trades with sizing function. Returns stats."""
    pnls = []
    notionals = []
    by_year = defaultdict(list)
    skipped = 0

    for t in trades:
        if skip_fn and skip_fn(t):
            skipped += 1
            continue

        mult = size_fn(t)
        if mult <= 0:
            skipped += 1
            continue

        new_notional = min(FLAT_NOTIONAL * mult, 25_000_000)
        new_pnl = t['ret_pct'] / 100.0 * new_notional
        pnls.append(new_pnl)
        notionals.append(new_notional)
        by_year[t['date'][:4]].append(new_pnl)

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
    avg_notional = np.mean(notionals)

    return {
        'name': name, 'n': n, 'total': total, 'avg': avg,
        'sharpe': sharpe, 'wr': wr, 'pf': pf, 'max_dd': max_dd,
        'neg_years': neg_years, 'by_year': dict(by_year),
        'avg_notional': avg_notional, 'skipped': skipped,
    }


# ---------------------------------------------------------------
# STRATEGY DEFINITIONS
# ---------------------------------------------------------------
strategies = []

# === BASELINES ===
strategies.append(("A: BASELINE flat $15M", lambda t: 1.0, None))
strategies.append(("B: Gap filter only", lambda t: 1.0, lambda t: t['gap_pct'] < -1.0))

# === SINGLE FACTOR SKIPS ===
strategies.append(("C1: Skip high vol days (>1.35x)",
    lambda t: 1.0,
    lambda t: t['daily_vol_ratio'] > 1.35))

strategies.append(("C2: Skip wide range days (>2.08%)",
    lambda t: 1.0,
    lambda t: t['today_range_pct'] > 2.08))

strategies.append(("C3: Skip 2d rally (>1.18%)",
    lambda t: 1.0,
    lambda t: t['return_2d'] > 1.18))

strategies.append(("C4: Skip tiny prior body (<0.23%)",
    lambda t: 1.0,
    lambda t: t['prior_day_body_pct'] < 0.23))

strategies.append(("C5: Skip narrow prior range (<0.80%)",
    lambda t: 1.0,
    lambda t: t['prior_day_range_pct'] < 0.80))

strategies.append(("C6: Skip TOD 30-45m",
    lambda t: 1.0,
    lambda t: 30 <= t['mins_from_open'] < 45))

# === SINGLE FACTOR SIZING ===
strategies.append(("D1: 1.5x low vol, 0.5x high vol",
    lambda t: 1.5 if t['daily_vol_ratio'] < 1.0 else (0.5 if t['daily_vol_ratio'] > 1.35 else 1.0),
    None))

strategies.append(("D2: 2x tight days, 0.5x wide days",
    lambda t: 2.0 if t['today_range_pct'] < 0.96 else (0.5 if t['today_range_pct'] > 2.08 else 1.0),
    None))

strategies.append(("D3: 1.5x wide prior, 0.5x narrow",
    lambda t: 1.5 if t['prior_day_range_pct'] > 1.43 else (0.5 if t['prior_day_range_pct'] < 0.80 else 1.0),
    None))

strategies.append(("D4: 1.5x after 2d drop, 0.5x after rally",
    lambda t: 1.5 if t['return_2d'] < -1.49 else (0.5 if t['return_2d'] > 1.18 else 1.0),
    None))

strategies.append(("D5: 1.5x big body, 0.5x tiny body",
    lambda t: 1.5 if t['prior_day_body_pct'] > 0.79 else (0.5 if t['prior_day_body_pct'] < 0.23 else 1.0),
    None))

# === COMBINED SKIP STRATEGIES ===
strategies.append(("E1: Skip gap<-1% + vol>1.35x",
    lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or t['daily_vol_ratio'] > 1.35))

strategies.append(("E2: Skip gap<-1% + range>2.08%",
    lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or t['today_range_pct'] > 2.08))

strategies.append(("E3: Skip gap<-1% + 2d_rally>1.18%",
    lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or t['return_2d'] > 1.18))

strategies.append(("E4: Skip gap<-1% + TOD30-45m",
    lambda t: 1.0,
    lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 45))

strategies.append(("E5: Skip gap + vol>1.35 + TOD30-45",
    lambda t: 1.0,
    lambda t: (t['gap_pct'] < -1.0 or t['daily_vol_ratio'] > 1.35 or
               30 <= t['mins_from_open'] < 45)))

strategies.append(("E6: Skip gap + range>2.08 + TOD30-45",
    lambda t: 1.0,
    lambda t: (t['gap_pct'] < -1.0 or t['today_range_pct'] > 2.08 or
               30 <= t['mins_from_open'] < 45)))

strategies.append(("E7: Skip gap + vol>1.35 + 2d>1.18",
    lambda t: 1.0,
    lambda t: (t['gap_pct'] < -1.0 or t['daily_vol_ratio'] > 1.35 or
               t['return_2d'] > 1.18)))

strategies.append(("E8: Skip gap+vol>1.35+2d>1.18+TOD",
    lambda t: 1.0,
    lambda t: (t['gap_pct'] < -1.0 or t['daily_vol_ratio'] > 1.35 or
               t['return_2d'] > 1.18 or 30 <= t['mins_from_open'] < 45)))

# === COMBINED SIZING STRATEGIES ===
strategies.append(("F1: Composite score v1",
    lambda t: (1.0
        + (0.3 if t['daily_vol_ratio'] < 1.0 else (-0.4 if t['daily_vol_ratio'] > 1.35 else 0))
        + (0.5 if t['today_range_pct'] < 0.96 else (-0.3 if t['today_range_pct'] > 2.08 else 0))
        + (0.2 if t['return_2d'] < -1.49 else (-0.3 if t['return_2d'] > 1.18 else 0))
        + (0.2 if t['prior_day_range_pct'] > 1.43 else (-0.2 if t['prior_day_range_pct'] < 0.80 else 0))
    ), None))

strategies.append(("F2: Composite score v2 (gap skip)",
    lambda t: (1.0
        + (0.3 if t['daily_vol_ratio'] < 1.0 else (-0.4 if t['daily_vol_ratio'] > 1.35 else 0))
        + (0.5 if t['today_range_pct'] < 0.96 else (-0.3 if t['today_range_pct'] > 2.08 else 0))
        + (0.2 if t['return_2d'] < -1.49 else (-0.3 if t['return_2d'] > 1.18 else 0))
        + (0.2 if t['prior_day_range_pct'] > 1.43 else (-0.2 if t['prior_day_range_pct'] < 0.80 else 0))
    ), lambda t: t['gap_pct'] < -1.0))

strategies.append(("F3: Skip bad + 2x on tight low-vol",
    lambda t: 2.0 if (t['daily_vol_ratio'] < 1.0 and t['today_range_pct'] < 1.23) else 1.0,
    lambda t: (t['gap_pct'] < -1.0 or t['daily_vol_ratio'] > 1.35 or
               30 <= t['mins_from_open'] < 45)))

strategies.append(("F4: Skip bad + 1.5x wide prior",
    lambda t: 1.5 if t['prior_day_range_pct'] > 1.43 else 1.0,
    lambda t: (t['gap_pct'] < -1.0 or t['daily_vol_ratio'] > 1.35 or
               30 <= t['mins_from_open'] < 45)))

strategies.append(("F5: Skip bad + 2x tight + 1.5x prior",
    lambda t: (2.0 if (t['daily_vol_ratio'] < 1.0 and t['today_range_pct'] < 1.23) else
               1.5 if t['prior_day_range_pct'] > 1.43 else 1.0),
    lambda t: (t['gap_pct'] < -1.0 or t['daily_vol_ratio'] > 1.35 or
               30 <= t['mins_from_open'] < 45)))

# === AGGRESSIVE COMBOS ===
strategies.append(("G1: Only tight+low-vol days",
    lambda t: 1.0,
    lambda t: t['today_range_pct'] > 1.23 or t['daily_vol_ratio'] > 1.0))

strategies.append(("G2: Only tight days (<0.96%)",
    lambda t: 1.0,
    lambda t: t['today_range_pct'] > 0.96))

strategies.append(("G3: Only low vol (<1.0x) + gap",
    lambda t: 1.0,
    lambda t: t['daily_vol_ratio'] > 1.0 or t['gap_pct'] < -1.0))

strategies.append(("G4: Tight(<1.23)+gap+!TOD30-45",
    lambda t: 1.0,
    lambda t: (t['today_range_pct'] > 1.23 or t['gap_pct'] < -1.0 or
               30 <= t['mins_from_open'] < 45)))

strategies.append(("G5: Best combined filter set",
    lambda t: 1.0,
    lambda t: (t['today_range_pct'] > 1.53 or t['daily_vol_ratio'] > 1.35 or
               t['return_2d'] > 1.18 or t['gap_pct'] < -1.0 or
               30 <= t['mins_from_open'] < 45)))

# ---------------------------------------------------------------
# RUN ALL STRATEGIES
# ---------------------------------------------------------------
print()
print("=" * 120)
print("  SIZING STRATEGY RESULTS (sorted by Sharpe)")
print("=" * 120)
print(f"  {'Strategy':<45s} {'N':>4s} {'Skip':>4s} {'Sharpe':>7s} {'WR':>6s} {'PF':>5s} {'Total $':>12s} {'AvgPnL':>9s} {'MaxDD$':>10s} {'NY':>3s} {'AvgNot$':>10s}")
print(f"  {'-' * 117}")

results = []
for name, size_fn, skip_fn in strategies:
    r = simulate(trades, name, size_fn, skip_fn)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)

for r in results:
    print(f"  {r['name']:<45s} {r['n']:>4d} {r['skipped']:>4d} {r['sharpe']:>7.3f} {r['wr']:>5.1%} {r['pf']:>5.2f} ${r['total']:>11,.0f} ${r['avg']:>8,.0f} ${r['max_dd']:>9,.0f} {r['neg_years']:>3d} ${r['avg_notional']:>9,.0f}")

# ---------------------------------------------------------------
# YEARLY BREAKDOWN for top 5
# ---------------------------------------------------------------
print()
print("=" * 80)
print("  YEARLY BREAKDOWN - Top 5 + Baseline")
print("=" * 80)

baseline = next(r for r in results if 'BASELINE' in r['name'])
top5 = results[:5]
if baseline not in top5:
    top5.append(baseline)

for r in top5:
    print(f"\n  {r['name']} (Sharpe={r['sharpe']:.3f})")
    for yr in sorted(r['by_year'].keys()):
        yp = r['by_year'][yr]
        yt = sum(yp)
        n = len(yp)
        yw = sum(1 for p in yp if p > 0)
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={yw/n:.1%}")

# ---------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------
print()
print("=" * 80)
print("  SUMMARY")
print("=" * 80)
best = results[0]
print(f"\n  Best strategy: {best['name']}")
print(f"  Sharpe: {best['sharpe']:.3f} (vs baseline {baseline['sharpe']:.3f})")
print(f"  Improvement: {(best['sharpe'] / baseline['sharpe'] - 1) * 100:+.1f}%")
print(f"  Trades: {best['n']} (skipped {best['skipped']})")
print(f"  Total P&L: ${best['total']:,.0f}")
print(f"  Neg years: {best['neg_years']}")

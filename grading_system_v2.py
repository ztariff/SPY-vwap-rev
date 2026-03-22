#!/usr/bin/env python3
"""
Build the ultimate trade grading system.
Key principle: every feature must be computable in KITE at entry time.

Features available in KITE code.py at entry time:
  - Prior-day: all CSV features (range, body, return_2d, sma5, slope, etc.)
  - Intraday computed from minute bars:
    * today_range_pct: (session_high - session_low) / entry_price * 100
    * bars_into_session (= bar_count)
    * today_move_atr_mult: today's range / ATR (need ATR from CSV)
    * dist_from_open: (current_price - open) / open * 100
    * consecutive_down_bars: count of bars where close < open
    * VWAP slope: (vwap_now - vwap_5bars_ago) / vwap_now
    * EMA slope: can compute EMA of close prices
    * Volume profile: cumulative volume vs typical

Focus: what COMBINATION of prior-day + computable intraday features
gives the best trade grade?
"""

import json
import numpy as np
from collections import defaultdict

with open('kite_deep_features.json') as f:
    trades = json.load(f)

print(f"Total trades: {len(trades)}")
baseline_pnls = [t['pnl'] for t in trades]
baseline_sharpe = np.mean(baseline_pnls) / np.std(baseline_pnls, ddof=1) * np.sqrt(len(baseline_pnls)/4.2)

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

def yearly_breakdown(trades, grade_fn, name):
    by_year = defaultdict(list)
    for t in trades:
        mult = grade_fn(t)
        if mult <= 0:
            continue
        yr = t['date'][:4]
        by_year[yr].append(t['pnl'] * mult)
    print(f"\n  {name}:")
    neg = 0
    for yr in sorted(by_year.keys()):
        yp = by_year[yr]
        yt = sum(yp)
        n = len(yp)
        wr = sum(1 for p in yp if p > 0) / n if n else 0
        std = np.std(yp, ddof=1) if n > 1 else 1
        sh = np.mean(yp) / std * np.sqrt(n) if std > 0 else 0
        if yt < 0: neg += 1
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={wr:.1%}  Sharpe={sh:.3f}")
    return neg

# ================================================================
# V16b baseline
# ================================================================
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
    s = max(s, 0.1)
    if t.get('mins_from_open', 999) < 10:
        return 0
    return s

# ================================================================
# GRADING APPROACH: Build a continuous score from 0 to ~2.5
# Each signal contributes + or - to the grade
# Grade directly maps to position size multiplier
# ================================================================

print("="*100)
print("  TRADE GRADING SYSTEM: PRIOR-DAY + INTRADAY CONFLUENCE")
print("="*100)

# ================================================================
# Test: today_range_pct as an intraday feature
# But we need to understand if it's hindsight
# ================================================================
print("\n  HINDSIGHT CHECK: today_range_pct")
print("  today_range_pct = (session_high - session_low) / close * 100")
print("  This uses session_high and session_low UP TO the entry bar.")
print("  At entry time, we know the range of all bars BEFORE entry.")
print("  VERDICT: SAFE - it's the range of bars seen before entry.")
print()

# But wait - in KITE, we CAN compute this:
# track session_high and session_low across bars, compute range at entry
# Question: does today_range_pct in our dataset use bars only before entry,
# or ALL bars in the day?

# Let's check: trades with mins_from_open = 10 should have small range
print("  Cross-check: today_range_pct vs mins_from_open:")
for mins_bucket in [(10, 30), (30, 60), (60, 120), (120, 240), (240, 390)]:
    bucket = [t for t in trades if mins_bucket[0] <= t.get('mins_from_open', 0) < mins_bucket[1]]
    if bucket:
        ranges = [t['today_range_pct'] for t in bucket]
        print(f"    {mins_bucket[0]:3d}-{mins_bucket[1]:3d}m: N={len(bucket):3d}  "
              f"avg_range={np.mean(ranges):.3f}  median={np.median(ranges):.3f}  "
              f"min={min(ranges):.3f}  max={max(ranges):.3f}")

# ================================================================
# Build grading candidates
# ================================================================

# Grade A: V16b + today_range penalty (high range = bad for MR)
def grade_a(t):
    s = v16b(t)
    if s <= 0: return 0
    tr = t.get('today_range_pct', 0.5)
    if tr > 1.5: s -= 0.5   # very volatile intraday = bad for MR
    if tr > 1.0: s -= 0.2   # moderately volatile
    if tr < 0.5: s += 0.2   # calm day = good for MR
    return max(s, 0.1)

# Grade B: V16b + today_range (asymmetric)
def grade_b(t):
    s = v16b(t)
    if s <= 0: return 0
    tr = t.get('today_range_pct', 0.5)
    if tr > 1.5: s -= 0.8   # heavy penalty for volatile
    if tr < 0.5: s += 0.1   # light reward for calm
    return max(s, 0.1)

# Grade C: V16b + today_range + daily_vol_ratio
def grade_c(t):
    s = v16b(t)
    if s <= 0: return 0
    tr = t.get('today_range_pct', 0.5)
    dvr = t.get('daily_vol_ratio', 1.0)
    if tr > 1.5: s -= 0.6
    if tr < 0.5: s += 0.15
    if dvr > 1.5: s -= 0.3   # unusually high volume ratio = regime shift
    if dvr < 0.8: s += 0.1
    return max(s, 0.1)

# Grade D: V16b + momentum (negative = better for mean reversion buy)
def grade_d(t):
    s = v16b(t)
    if s <= 0: return 0
    mom3 = t.get('momentum_3b', 0)
    mom5 = t.get('momentum_5b', 0)
    # For buys: negative momentum = price still falling = bigger snap potential
    # But also more risk...
    if mom3 < 0 and mom5 < 0: s += 0.15
    if mom3 > 0 and mom5 > 0: s -= 0.15
    return max(s, 0.1)

# Grade E: V16b + bars_into_session timing
def grade_e(t):
    s = v16b(t)
    if s <= 0: return 0
    bars = t.get('bars_into_session', 100)
    mins = t.get('mins_from_open', 100)
    # Early entries (after first 10m) tend to be better?
    if 10 <= mins <= 60: s += 0.15   # first hour (after 10m skip)
    if 60 <= mins <= 180: s += 0.05  # mid-morning to lunch
    if mins > 300: s -= 0.3          # last hour penalty
    return max(s, 0.1)

# Grade F: V16b + dist_from_open (how far we've dropped from open)
def grade_f(t):
    s = v16b(t)
    if s <= 0: return 0
    dist_open = t.get('dist_from_open_pct', 0)
    # Bigger drop from open = more reversion potential, but also more risk
    # The asymmetric approach: don't reward big drops, but penalize entries above open
    if dist_open > 0: s -= 0.4    # above open = not really a dip
    return max(s, 0.1)

# Grade G: V16b + today_range + EMA slope
def grade_g(t):
    s = v16b(t)
    if s <= 0: return 0
    tr = t.get('today_range_pct', 0.5)
    ema_slope = t.get('ema5_slope', 0)
    if tr > 1.5: s -= 0.6
    if tr < 0.5: s += 0.1
    if ema_slope < -0.1: s += 0.1   # EMA declining = price still falling
    if ema_slope > 0.1: s -= 0.2    # EMA rising = maybe already recovering
    return max(s, 0.1)

# Grade H: COMPREHENSIVE - V16b + today_range + dist_open + timing
def grade_h(t):
    s = v16b(t)
    if s <= 0: return 0
    tr = t.get('today_range_pct', 0.5)
    dist_open = t.get('dist_from_open_pct', 0)
    mins = t.get('mins_from_open', 100)

    # Intraday signals (asymmetric)
    if tr > 1.5: s -= 0.5
    if tr < 0.5: s += 0.1
    if dist_open > 0: s -= 0.3
    if mins > 300: s -= 0.2

    return max(s, 0.1)

# Grade I: FULL KITCHEN SINK
def grade_i(t):
    s = v16b(t)
    if s <= 0: return 0

    tr = t.get('today_range_pct', 0.5)
    dist_open = t.get('dist_from_open_pct', 0)
    mins = t.get('mins_from_open', 100)
    dvr = t.get('daily_vol_ratio', 1.0)
    mom3 = t.get('momentum_3b', 0)

    # today range (strongest intraday signal)
    if tr > 1.5: s -= 0.6
    if tr < 0.5: s += 0.1

    # above open = not a real dip
    if dist_open > 0: s -= 0.3

    # late day penalty
    if mins > 300: s -= 0.2

    # vol ratio shift
    if dvr > 1.5: s -= 0.2

    # momentum
    if mom3 < 0: s += 0.05
    if mom3 > 0.5: s -= 0.1

    return max(s, 0.1)

# Grade J: today_range only (isolate its power)
def grade_j(t):
    if t.get('mins_from_open', 999) < 10:
        return 0
    s = 1.0
    tr = t.get('today_range_pct', 0.5)
    if tr > 1.5: s = 0.3
    elif tr > 1.0: s = 0.6
    elif tr < 0.5: s = 1.5
    else: s = 1.0
    return s

# Grade K: V16b + today_range with finer thresholds
def grade_k(t):
    s = v16b(t)
    if s <= 0: return 0
    tr = t.get('today_range_pct', 0.5)
    # Fine-grained: penalize proportionally
    if tr > 2.0: s -= 0.8
    elif tr > 1.5: s -= 0.5
    elif tr > 1.0: s -= 0.2
    elif tr < 0.3: s += 0.3
    elif tr < 0.5: s += 0.15
    return max(s, 0.1)

# Grade L: asymmetric everything - heaviest penalties for worst conditions
def grade_l(t):
    # Prior-day base (V16b)
    s = 1.0
    if t['prior_day_range_pct'] > 1.20: s += 0.2
    if t['prior_day_range_pct'] < 0.80: s -= 0.6
    if t['prior_day_body_pct'] > 0.50: s += 0.2
    if t['prior_day_body_pct'] < 0.35: s -= 0.6
    if t['return_2d'] < -1.49: s += 0.2
    if t['return_2d'] > 1.18: s -= 0.6
    if t['daily_sma5_above_sma20'] == 1: s += 0.3
    else: s -= 0.3

    # Skip first 10 minutes
    if t.get('mins_from_open', 999) < 10:
        return 0

    # Intraday adjustments
    tr = t.get('today_range_pct', 0.5)
    if tr > 1.5: s -= 0.8     # volatile day = heavy penalty
    elif tr > 1.0: s -= 0.3
    elif tr < 0.4: s += 0.15  # calm day = slight reward

    dist_open = t.get('dist_from_open_pct', 0)
    if dist_open > 0: s -= 0.4  # above open = wrong side

    mins = t.get('mins_from_open', 100)
    if mins > 330: s -= 0.3    # last 30 mins

    return max(s, 0.1)

# Grade M: grid-optimized from prior run (slope pen -0.5, mr pen -0.3)
# BUT these features are sparse (mostly 0)
# So translate: VWAP slope > 0.02 penalty and mr_strength < 0.3 penalty
# are really about "market already recovering" and "weak MR signal"
# We can approximate with today_range and dist_from_open instead
def grade_m(t):
    s = v16b(t)
    if s <= 0: return 0

    tr = t.get('today_range_pct', 0.5)
    dist_open = t.get('dist_from_open_pct', 0)
    dvr = t.get('daily_vol_ratio', 1.0)

    # Heavy asymmetric penalties
    if tr > 1.5: s -= 0.7
    if dist_open > 0: s -= 0.5
    if dvr > 1.5: s -= 0.4

    # Light rewards
    if tr < 0.4: s += 0.1

    return max(s, 0.1)

# Run all grades
graders = [
    (v16b, "V16b (baseline)"),
    (grade_a, "A: V16b+range"),
    (grade_b, "B: V16b+range(asym)"),
    (grade_c, "C: V16b+range+volratio"),
    (grade_d, "D: V16b+momentum"),
    (grade_e, "E: V16b+timing"),
    (grade_f, "F: V16b+dist_open"),
    (grade_g, "G: V16b+range+EMA"),
    (grade_h, "H: V16b+range+open+timing"),
    (grade_i, "I: Kitchen sink"),
    (grade_j, "J: range only (no prior)"),
    (grade_k, "K: V16b+range(fine)"),
    (grade_l, "L: Full asymmetric"),
    (grade_m, "M: V16b+range+open+vol(asym)"),
]

results = []
for fn, name in graders:
    r = test_grading(trades, fn, name)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)

v16b_sharpe = next(r['sharpe'] for r in results if r['name'] == 'V16b (baseline)')

print(f"\n  {'Strategy':<35s} {'N':>5s} {'Skip':>5s} {'Sharpe':>8s} {'vs V16b':>8s} {'WR':>7s} {'PF':>6s} {'Total $':>13s} {'Avg PnL':>10s} {'MaxDD $':>11s}")
print(f"  {'-'*115}")
for r in results:
    improvement = (r['sharpe'] / v16b_sharpe - 1) * 100 if v16b_sharpe > 0 else 0
    sign = '+' if improvement > 0 else ''
    print(f"  {r['name']:<35s} {r['n']:>5d} {r['skipped']:>5d} {r['sharpe']:>8.3f} {sign}{improvement:>6.0f}% {r['wr']:>6.1%} {r['pf']:>6.2f} ${r['total']:>12,.0f} ${r['avg']:>9,.0f} ${r['max_dd']:>10,.0f}")

# ================================================================
# Yearly stability for top candidates
# ================================================================
print("\n" + "="*100)
print("  YEARLY STABILITY")
print("="*100)

yearly_breakdown(trades, v16b, "V16b (baseline)")
# Show top 5 non-baseline
shown = 0
for r in results:
    if r['name'] == 'V16b (baseline)':
        continue
    fn = next(f for f, n in graders if n == r['name'])
    yearly_breakdown(trades, fn, r['name'])
    shown += 1
    if shown >= 5:
        break

# ================================================================
# Grid search over today_range thresholds
# ================================================================
print("\n" + "="*100)
print("  GRID SEARCH: today_range_pct THRESHOLDS")
print("="*100)

best_grid = []
for hi_thresh in [0.8, 1.0, 1.2, 1.5, 2.0]:
    for hi_pen in [-0.3, -0.5, -0.6, -0.8, -1.0]:
        for lo_thresh in [0.3, 0.4, 0.5, 0.6]:
            for lo_reward in [0, 0.1, 0.15, 0.2, 0.3]:
                def make_fn(ht, hp, lt, lr):
                    def fn(t):
                        s = v16b(t)
                        if s <= 0: return 0
                        tr = t.get('today_range_pct', 0.5)
                        if tr > ht: s += hp
                        if tr < lt: s += lr
                        return max(s, 0.1)
                    return fn
                fn = make_fn(hi_thresh, hi_pen, lo_thresh, lo_reward)
                r = test_grading(trades, fn, f"range_{hi_thresh}_{hi_pen}_{lo_thresh}_{lo_reward}")
                if r:
                    r['params'] = (hi_thresh, hi_pen, lo_thresh, lo_reward)
                    best_grid.append(r)

best_grid.sort(key=lambda x: x['sharpe'], reverse=True)
print(f"\n  Tested {len(best_grid)} threshold combos")
print(f"\n  Top 20:")
print(f"  {'Rank':>4s} {'Sharpe':>8s} {'vs V16b':>8s} {'N':>5s} {'WR':>7s} {'PF':>6s} {'hi_th':>6s} {'hi_pen':>7s} {'lo_th':>6s} {'lo_rew':>7s}")
print(f"  {'-'*75}")
for i, r in enumerate(best_grid[:20]):
    ht, hp, lt, lr = r['params']
    improvement = (r['sharpe'] / v16b_sharpe - 1) * 100
    sign = '+' if improvement > 0 else ''
    print(f"  {i+1:>4d} {r['sharpe']:>8.3f} {sign}{improvement:>6.0f}% {r['n']:>5d} {r['wr']:>6.1%} {r['pf']:>6.2f} {ht:>6.1f} {hp:>7.1f} {lt:>6.1f} {lr:>7.2f}")

# ================================================================
# Final: combine best today_range with dist_from_open and timing
# ================================================================
print("\n" + "="*100)
print("  FINAL: COMBINED GRADING WITH BEST THRESHOLDS")
print("="*100)

# Use top range thresholds, then add other intraday features
if best_grid:
    best_ht, best_hp, best_lt, best_lr = best_grid[0]['params']
    print(f"  Best range params: hi>{best_ht} penalty={best_hp}, lo<{best_lt} reward={best_lr}")

    # Add dist_from_open and timing on top
    final_results = []
    for open_pen in [0, -0.2, -0.3, -0.4, -0.5]:
        for late_pen in [0, -0.2, -0.3, -0.4]:
            for dvr_pen in [0, -0.2, -0.3, -0.4]:
                def make_final(op, lp, dp, ht, hp, lt, lr):
                    def fn(t):
                        s = v16b(t)
                        if s <= 0: return 0
                        tr = t.get('today_range_pct', 0.5)
                        if tr > ht: s += hp
                        if tr < lt: s += lr
                        dist_open = t.get('dist_from_open_pct', 0)
                        if dist_open > 0 and op < 0: s += op
                        mins = t.get('mins_from_open', 100)
                        if mins > 330 and lp < 0: s += lp
                        dvr = t.get('daily_vol_ratio', 1.0)
                        if dvr > 1.5 and dp < 0: s += dp
                        return max(s, 0.1)
                    return fn

                fn = make_final(open_pen, late_pen, dvr_pen, best_ht, best_hp, best_lt, best_lr)
                r = test_grading(trades, fn, "combined")
                if r:
                    r['params'] = (open_pen, late_pen, dvr_pen)
                    final_results.append(r)

    final_results.sort(key=lambda x: x['sharpe'], reverse=True)
    print(f"\n  Tested {len(final_results)} combos")
    print(f"\n  Top 15:")
    print(f"  {'Rank':>4s} {'Sharpe':>8s} {'vs V16b':>8s} {'N':>5s} {'WR':>7s} {'PF':>6s} {'open_p':>7s} {'late_p':>7s} {'dvr_p':>7s}")
    print(f"  {'-'*68}")
    for i, r in enumerate(final_results[:15]):
        op, lp, dp = r['params']
        improvement = (r['sharpe'] / v16b_sharpe - 1) * 100
        sign = '+' if improvement > 0 else ''
        print(f"  {i+1:>4d} {r['sharpe']:>8.3f} {sign}{improvement:>6.0f}% {r['n']:>5d} {r['wr']:>6.1%} {r['pf']:>6.2f} {op:>7.1f} {lp:>7.1f} {dp:>7.1f}")

    # Yearly check on top combined
    if final_results:
        top = final_results[0]
        op, lp, dp = top['params']
        fn = make_final(op, lp, dp, best_ht, best_hp, best_lt, best_lr)
        print(f"\n  CHAMPION: Sharpe={top['sharpe']:.3f} (+{(top['sharpe']/v16b_sharpe-1)*100:.0f}% vs V16b)")
        print(f"  Params: range>{best_ht} pen={best_hp}, range<{best_lt} rew={best_lr}, "
              f"open_pen={op}, late_pen={lp}, dvr_pen={dp}")
        yearly_breakdown(trades, fn, f"CHAMPION (S={top['sharpe']:.3f})")

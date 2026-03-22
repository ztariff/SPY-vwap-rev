#!/usr/bin/env python3
"""
Build a WEIGHTED SCORING SYSTEM for trade grading.
Every signal contributes a continuous score. Total score = sizing multiplier.
No cherry-picking features. Every signal gets a voice, weighted by predictive power.

Approach:
1. Normalize each feature to a -1 to +1 score
2. Weight each by its demonstrated edge
3. Sum all weighted scores -> total grade
4. Map grade to sizing multiplier
5. Grid search the weight ratios to find optimal blend
"""

import json
import numpy as np
from collections import defaultdict

with open('kite_deep_features.json') as f:
    trades = json.load(f)

# Filter to post-10m (skip first 10 minutes is a given)
trades = [t for t in trades if t.get('mins_from_open', 0) >= 10]
print(f"Trades (post-10m): {len(trades)}")

baseline_pnls = [t['pnl'] for t in trades]
baseline_sharpe = np.mean(baseline_pnls) / np.std(baseline_pnls, ddof=1) * np.sqrt(len(baseline_pnls)/4.2)
print(f"Flat baseline Sharpe: {baseline_sharpe:.3f}")

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
    for yr in sorted(by_year.keys()):
        yp = by_year[yr]
        yt = sum(yp)
        n = len(yp)
        wr = sum(1 for p in yp if p > 0) / n if n else 0
        std = np.std(yp, ddof=1) if n > 1 else 1
        sh = np.mean(yp) / std * np.sqrt(n) if std > 0 else 0
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={wr:.1%}  Sharpe={sh:.3f}")

# ================================================================
# STEP 1: Define scoring functions for each feature
# Each returns a value roughly in [-1, +1] range
# Positive = favorable for mean reversion, Negative = unfavorable
# ================================================================

def score_prior_day_range(t):
    """Wide prior day range = good. Narrow = bad."""
    r = t.get('prior_day_range_pct', 1.0)
    if r > 1.8: return 1.0
    if r > 1.2: return 0.5
    if r > 0.8: return 0.0
    if r > 0.5: return -0.5
    return -1.0

def score_prior_day_body(t):
    """Large candle body = good. Tiny body = bad."""
    b = t.get('prior_day_body_pct', 0.4)
    if b > 0.8: return 1.0
    if b > 0.5: return 0.5
    if b > 0.35: return 0.0
    if b > 0.2: return -0.5
    return -1.0

def score_return_2d(t):
    """Negative 2d return = good (reversion setup). Positive = bad."""
    r = t.get('return_2d', 0)
    if r < -2.0: return 1.0
    if r < -1.0: return 0.5
    if r < 0.5: return 0.0
    if r < 1.2: return -0.5
    return -1.0

def score_trend(t):
    """SMA5 > SMA20 = uptrend = good for buy-dip MR."""
    return 1.0 if t.get('daily_sma5_above_sma20', 0) == 1 else -1.0

def score_sma_slope(t):
    """Positive SMA slope = good."""
    s = t.get('daily_sma5_slope', 0)
    if s > 1.0: return 1.0
    if s > 0.3: return 0.5
    if s > -0.3: return 0.0
    if s > -1.0: return -0.5
    return -1.0

def score_vol_ratio(t):
    """Normal volume = good. Spike = bad (regime shift)."""
    v = t.get('daily_vol_ratio', 1.0)
    if v < 0.7: return 0.5    # quiet = good
    if v < 1.2: return 0.0    # normal
    if v < 1.5: return -0.3
    return -1.0                # spike = bad

def score_today_range(t):
    """Low intraday range = great. High = terrible."""
    r = t.get('today_range_pct', 1.0)
    if r < 0.4: return 1.0
    if r < 0.6: return 0.7
    if r < 0.8: return 0.3
    if r < 1.0: return 0.0
    if r < 1.5: return -0.5
    if r < 2.0: return -0.8
    return -1.0

def score_dist_from_open(t):
    """Below open = real dip = good. Above open = not a dip = bad."""
    d = t.get('dist_from_open_pct', 0)
    if d < -0.5: return 0.5
    if d < 0: return 0.2
    if d < 0.3: return -0.3
    return -1.0

def score_atr_pct(t):
    """Higher ATR = more vol = better for MR."""
    a = t.get('daily_atr_pct', 1.0)
    if a > 1.5: return 0.8
    if a > 1.0: return 0.3
    if a > 0.7: return 0.0
    return -0.5

def score_return_5d(t):
    """5-day return: negative = more reversion setup."""
    r = t.get('return_5d', 0)
    if r < -2.0: return 0.7
    if r < -0.5: return 0.3
    if r < 1.0: return 0.0
    return -0.5

def score_dist_sma20(t):
    """Price far below SMA20 = oversold = good for MR buy."""
    d = t.get('dist_daily_sma20', 0)
    if d < -3.0: return 0.8
    if d < -1.0: return 0.3
    if d < 1.0: return 0.0
    if d < 3.0: return -0.3
    return -0.5

# ================================================================
# All scoring functions with their feature names
# ================================================================
SCORERS = [
    ('prior_day_range',  score_prior_day_range),
    ('prior_day_body',   score_prior_day_body),
    ('return_2d',        score_return_2d),
    ('trend',            score_trend),
    ('sma_slope',        score_sma_slope),
    ('vol_ratio',        score_vol_ratio),
    ('today_range',      score_today_range),
    ('dist_from_open',   score_dist_from_open),
    ('atr_pct',          score_atr_pct),
    ('return_5d',        score_return_5d),
    ('dist_sma20',       score_dist_sma20),
]

# ================================================================
# STEP 2: Measure each scorer's predictive power independently
# ================================================================
print("\n" + "="*100)
print("  INDIVIDUAL SCORER PREDICTIVE POWER")
print("="*100)

print(f"\n  {'Scorer':<20s} {'Sharpe_neg':>10s} {'Sharpe_zero':>11s} {'Sharpe_pos':>10s} {'Spread':>8s} {'Corr_w_PnL':>10s}")
print(f"  {'-'*75}")

scorer_powers = {}
for name, fn in SCORERS:
    scores = [(fn(t), t['pnl']) for t in trades]

    neg = [pnl for s, pnl in scores if s < -0.1]
    zero = [pnl for s, pnl in scores if -0.1 <= s <= 0.1]
    pos = [pnl for s, pnl in scores if s > 0.1]

    def sh(pnls):
        if len(pnls) < 5: return 0
        s = np.std(pnls, ddof=1)
        return np.mean(pnls) / s * np.sqrt(len(pnls)/4.2) if s > 0 else 0

    s_neg = sh(neg) if neg else 0
    s_pos = sh(pos) if pos else 0
    s_zero = sh(zero) if zero else 0
    spread = abs(s_pos - s_neg)

    # Correlation with PnL
    score_vals = [s for s, _ in scores]
    pnl_vals = [p for _, p in scores]
    corr = np.corrcoef(score_vals, pnl_vals)[0, 1] if len(score_vals) > 5 else 0

    scorer_powers[name] = {'spread': spread, 'corr': corr, 's_pos': s_pos, 's_neg': s_neg}
    print(f"  {name:<20s} {s_neg:>10.3f} {s_zero:>10.3f} {s_pos:>10.3f} {spread:>8.3f} {corr:>10.4f}")

# ================================================================
# STEP 3: Build weighted composite score
# Weight options: equal, by spread, by correlation, grid search
# ================================================================
print("\n" + "="*100)
print("  WEIGHTED COMPOSITE SCORING SYSTEMS")
print("="*100)

# Method A: Equal weight (each signal gets 1.0)
def grade_equal_weight(t):
    total = sum(fn(t) for _, fn in SCORERS)
    # Scale: 11 scorers, range roughly -11 to +11
    # Map to multiplier: center at 1.0, scale by 0.1 per point
    mult = 1.0 + total * 0.1
    return max(mult, 0.1)

# Method B: Weight by Sharpe spread (stronger signals count more)
spread_weights = {name: scorer_powers[name]['spread'] for name in scorer_powers}
total_spread = sum(spread_weights.values())
norm_spread_weights = {k: v/total_spread * len(SCORERS) for k, v in spread_weights.items()}

def grade_spread_weighted(t):
    total = 0
    for name, fn in SCORERS:
        total += fn(t) * norm_spread_weights[name]
    mult = 1.0 + total * 0.1
    return max(mult, 0.1)

# Method C: Weight by |correlation| with PnL
corr_weights = {name: abs(scorer_powers[name]['corr']) for name in scorer_powers}
total_corr = sum(corr_weights.values())
norm_corr_weights = {k: v/total_corr * len(SCORERS) for k, v in corr_weights.items()}

def grade_corr_weighted(t):
    total = 0
    for name, fn in SCORERS:
        total += fn(t) * norm_corr_weights[name]
    mult = 1.0 + total * 0.1
    return max(mult, 0.1)

# Method D: Asymmetric - negative scores count 3x (penalty heavier)
def grade_asymmetric(t):
    total = 0
    for name, fn in SCORERS:
        s = fn(t) * norm_spread_weights[name]
        if s < 0:
            s *= 3.0  # triple penalty
        total += s
    mult = 1.0 + total * 0.08
    return max(mult, 0.1)

# Method E: Asymmetric spread-weighted with 2x penalty
def grade_asym_2x(t):
    total = 0
    for name, fn in SCORERS:
        s = fn(t) * norm_spread_weights[name]
        if s < 0:
            s *= 2.0
        total += s
    mult = 1.0 + total * 0.1
    return max(mult, 0.1)

# Method F: V16b (current champion for comparison)
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

# Method G: Old champion (V16b + range + open + dvr)
def old_champion(t):
    s = v16b(t)
    tr = t.get('today_range_pct', 0.5)
    if tr > 1.0: s -= 1.0
    if tr < 0.6: s += 0.3
    dist_open = t.get('dist_from_open_pct', 0)
    if dist_open > 0: s -= 0.2
    dvr = t.get('daily_vol_ratio', 1.0)
    if dvr > 1.5: s -= 0.4
    return max(s, 0.1)

graders = [
    (v16b, "V16b (4 features, if/else)"),
    (old_champion, "OldChampion (7 feat, if/else)"),
    (grade_equal_weight, "A: Equal weight (11 feat)"),
    (grade_spread_weighted, "B: Spread-weighted (11 feat)"),
    (grade_corr_weighted, "C: Corr-weighted (11 feat)"),
    (grade_asymmetric, "D: Asym 3x penalty (11 feat)"),
    (grade_asym_2x, "E: Asym 2x penalty (11 feat)"),
]

results = []
for fn, name in graders:
    r = test_grading(trades, fn, name)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)

print(f"\n  {'Strategy':<35s} {'N':>5s} {'Skip':>5s} {'Sharpe':>8s} {'vs Flat':>8s} {'WR':>7s} {'PF':>6s} {'Total $':>13s} {'MaxDD $':>11s}")
print(f"  {'-'*105}")
for r in results:
    imp = (r['sharpe'] / baseline_sharpe - 1) * 100
    print(f"  {r['name']:<35s} {r['n']:>5d} {r['skipped']:>5d} {r['sharpe']:>8.3f} {imp:>+7.0f}% {r['wr']:>6.1%} {r['pf']:>6.2f} ${r['total']:>12,.0f} ${r['max_dd']:>10,.0f}")

# ================================================================
# STEP 4: Grid search over the scale factor and asymmetry ratio
# ================================================================
print("\n" + "="*100)
print("  GRID SEARCH: SCALE FACTOR x ASYMMETRY RATIO")
print("="*100)

best_grid = []
for scale in [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12, 0.15, 0.18, 0.20]:
    for asym in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        for weight_type in ['spread', 'corr', 'equal']:
            def make_fn(sc, asy, wt):
                def fn(t):
                    total = 0
                    for name, scorer_fn in SCORERS:
                        s = scorer_fn(t)
                        if wt == 'spread':
                            s *= norm_spread_weights[name]
                        elif wt == 'corr':
                            s *= norm_corr_weights[name]
                        # else equal
                        if s < 0:
                            s *= asy
                        total += s
                    mult = 1.0 + total * sc
                    return max(mult, 0.1)
                return fn
            fn = make_fn(scale, asym, weight_type)
            r = test_grading(trades, fn, f"s={scale}_a={asym}_{weight_type}")
            if r:
                r['params'] = (scale, asym, weight_type)
                best_grid.append(r)

best_grid.sort(key=lambda x: x['sharpe'], reverse=True)
print(f"\n  Tested {len(best_grid)} combos")
print(f"\n  Top 20:")
print(f"  {'Rank':>4s} {'Sharpe':>8s} {'vs Flat':>8s} {'N':>5s} {'PF':>6s} {'Scale':>6s} {'Asym':>5s} {'Weights':>8s} {'Total $':>12s} {'MaxDD $':>10s}")
print(f"  {'-'*80}")
for i, r in enumerate(best_grid[:20]):
    sc, asy, wt = r['params']
    imp = (r['sharpe'] / baseline_sharpe - 1) * 100
    print(f"  {i+1:>4d} {r['sharpe']:>8.3f} {imp:>+7.0f}% {r['n']:>5d} {r['pf']:>6.2f} {sc:>6.2f} {asy:>5.1f} {wt:>8s} ${r['total']:>11,.0f} ${r['max_dd']:>9,.0f}")

# ================================================================
# STEP 5: Yearly stability on top candidates
# ================================================================
print("\n" + "="*100)
print("  YEARLY STABILITY ON TOP CANDIDATES")
print("="*100)

yearly_breakdown(trades, v16b, "V16b (current best)")
yearly_breakdown(trades, old_champion, "OldChampion (if/else)")

if best_grid:
    for i in range(min(3, len(best_grid))):
        bc = best_grid[i]
        sc, asy, wt = bc['params']
        fn = make_fn(sc, asy, wt)
        yearly_breakdown(trades, fn, f"Grid#{i+1} (S={bc['sharpe']:.3f}, scale={sc}, asym={asy}, wt={wt})")

# ================================================================
# STEP 6: Show the weight distribution of the best system
# ================================================================
print("\n" + "="*100)
print("  BEST SYSTEM WEIGHT ANALYSIS")
print("="*100)

if best_grid:
    bc = best_grid[0]
    sc, asy, wt = bc['params']

    print(f"\n  Best system: scale={sc}, asymmetry={asy}x, weight_type={wt}")
    print(f"  Sharpe: {bc['sharpe']:.3f}")

    if wt == 'spread':
        weights = norm_spread_weights
    elif wt == 'corr':
        weights = norm_corr_weights
    else:
        weights = {name: 1.0 for name, _ in SCORERS}

    print(f"\n  {'Feature':<20s} {'Weight':>8s} {'EffWeight':>10s} {'Up Contrib':>11s} {'Down Contrib':>13s}")
    print(f"  {'-'*65}")
    for name, fn in SCORERS:
        w = weights[name]
        eff_up = w * sc
        eff_down = w * sc * asy
        print(f"  {name:<20s} {w:>8.3f} {w*sc:>10.4f} {'+':>1s}{eff_up:>9.4f} {'-':>1s}{eff_down:>11.4f}")

# ================================================================
# STEP 7: Score distribution analysis
# ================================================================
print("\n" + "="*100)
print("  SCORE DISTRIBUTION ANALYSIS")
print("="*100)

if best_grid:
    bc = best_grid[0]
    sc, asy, wt = bc['params']
    fn = make_fn(sc, asy, wt)

    mults = [fn(t) for t in trades]
    pnls_by_mult = [(fn(t), t['pnl']) for t in trades]
    pnls_by_mult.sort(key=lambda x: x[0])

    print(f"\n  Multiplier distribution:")
    print(f"    Min: {min(mults):.3f}  Max: {max(mults):.3f}")
    print(f"    Mean: {np.mean(mults):.3f}  Median: {np.median(mults):.3f}")
    print(f"    Std: {np.std(mults):.3f}")

    # Quintile analysis
    n = len(pnls_by_mult)
    q_size = n // 5
    print(f"\n  {'Quintile':<12s} {'MultRange':<20s} {'N':>4s} {'WR':>7s} {'AvgPnL':>10s} {'Sharpe':>8s}")
    print(f"  {'-'*65}")
    for q in range(5):
        start = q * q_size
        end = (q + 1) * q_size if q < 4 else n
        group = pnls_by_mult[start:end]
        gm = [m for m, _ in group]
        gp = [p for _, p in group]
        wr = sum(1 for p in gp if p > 0) / len(gp)
        std = np.std(gp, ddof=1) if len(gp) > 1 else 1
        sh = np.mean(gp) / std * np.sqrt(len(gp)/4.2) if std > 0 else 0
        print(f"  Q{q+1} ({min(gm):.2f}-{max(gm):.2f}) {'':>1s} {len(group):>4d} {wr:>6.1%} ${np.mean(gp):>9,.0f} {sh:>8.3f}")

# ================================================================
# STEP 8: Compare: all features vs subsets
# Does including more features help or hurt?
# ================================================================
print("\n" + "="*100)
print("  FEATURE ABLATION: ALL vs SUBSETS")
print("="*100)

if best_grid:
    bc = best_grid[0]
    sc, asy, wt = bc['params']

    if wt == 'spread':
        weights = norm_spread_weights
    elif wt == 'corr':
        weights = norm_corr_weights
    else:
        weights = {name: 1.0 for name, _ in SCORERS}

    # Test removing each feature one at a time
    ablation = []

    # Full model
    fn_full = make_fn(sc, asy, wt)
    r_full = test_grading(trades, fn_full, "ALL 11 features")
    ablation.append(r_full)

    for drop_name, _ in SCORERS:
        def make_drop_fn(drop, sc_val, asy_val, wt_val, wts):
            def fn(t):
                total = 0
                for name, scorer_fn in SCORERS:
                    if name == drop:
                        continue
                    s = scorer_fn(t)
                    if wt_val == 'spread':
                        s *= wts.get(name, 1.0)
                    elif wt_val == 'corr':
                        s *= wts.get(name, 1.0)
                    if s < 0:
                        s *= asy_val
                    total += s
                mult = 1.0 + total * sc_val
                return max(mult, 0.1)
            return fn

        if wt == 'spread':
            use_weights = norm_spread_weights
        elif wt == 'corr':
            use_weights = norm_corr_weights
        else:
            use_weights = {name: 1.0 for name, _ in SCORERS}

        fn_drop = make_drop_fn(drop_name, sc, asy, wt, use_weights)
        r_drop = test_grading(trades, fn_drop, f"drop {drop_name}")
        if r_drop:
            r_drop['dropped'] = drop_name
            ablation.append(r_drop)

    ablation.sort(key=lambda x: x['sharpe'], reverse=True)

    print(f"\n  {'Config':<30s} {'Sharpe':>8s} {'Delta':>8s} {'PF':>6s}")
    print(f"  {'-'*55}")
    full_sharpe = r_full['sharpe']
    for r in ablation:
        delta = r['sharpe'] - full_sharpe
        marker = " ***" if 'dropped' in r and delta > 0.05 else ""
        print(f"  {r['name']:<30s} {r['sharpe']:>8.3f} {delta:>+8.3f} {r['pf']:>6.2f}{marker}")

    print(f"\n  Features where removal IMPROVES Sharpe = probably noise/overfitting")
    print(f"  Features where removal HURTS Sharpe = genuine signal")

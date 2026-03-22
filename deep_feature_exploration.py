#!/usr/bin/env python3
"""
Deep exploration for additional sizing edge beyond G3.
Tests NEW features, interactions, threshold optimization, and non-linear effects.
All features are safe (known at or before entry time, zero hindsight).
"""

import json, numpy as np
from collections import defaultdict
from itertools import combinations

with open('kite_deep_features.json') as f:
    trades = json.load(f)

print(f"Loaded {len(trades)} enriched KITE trades")

FLAT_NOTIONAL = 15_000_000

# ---------------------------------------------------------------
# SIMULATION ENGINE
# ---------------------------------------------------------------
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
    avg_notional = np.mean(notionals) if notionals else 0
    return {
        'name': name, 'n': n, 'total': total, 'avg': avg, 'sharpe': sharpe,
        'wr': wr, 'pf': pf, 'max_dd': max_dd, 'neg_years': neg_years,
        'by_year': dict(by_year), 'skipped': skipped, 'avg_notional': avg_notional
    }


# ---------------------------------------------------------------
# PART 1: FEATURE CORRELATION ON SAFE FEATURES
# Identify ALL safe features and rank them
# ---------------------------------------------------------------
print("\n" + "=" * 100)
print("  PART 1: SAFE FEATURE RANKING (features known at or before entry)")
print("=" * 100)

# Classify features as safe vs hindsight
# SAFE prior-day features (known before 9:30):
prior_day_safe = [
    'gap_pct', 'prior_day_range_pct', 'prior_day_body_pct', 'prior_day_return',
    'prior_day_up', 'return_2d', 'return_3d', 'return_5d', 'return_10d',
    'prior_week_range_pct', 'prior_10d_range_pct',
    'daily_atr_pct', 'daily_sma5_above_sma20', 'dist_daily_sma5',
    'dist_daily_sma10', 'dist_daily_sma20', 'daily_sma5_slope',
    'vix', 'vix_change', 'dow',
]

# SAFE intraday features (known at entry time, not hindsight):
intraday_safe = [
    'mins_from_open', 'bars_into_session',
    'vwap_dev_pct', 'vwap_slope_5', 'vwap_slope_10',
    'max_vwap_dev_before_entry',
    'velocity', 'dev_speed', 'price_acceleration',
    'momentum_3b', 'momentum_5b', 'momentum_10b', 'momentum_15b', 'momentum_20b',
    'consec_down_bars', 'consec_below_vwap',
    'dist_ema5_pct', 'dist_ema10_pct', 'dist_ema20_pct',
    'ema5_above_ema20', 'ema5_slope',
    'intraday_atr_pct', 'entry_bar_range_pct', 'range_last_5_pct',
    'vol_compression',
    'vol_surge_5', 'vol_surge_session',
    'opening_range_pct', 'or30_range_pct',
    'dist_from_or_high', 'dist_from_or_low',
    'below_or_low', 'below_or30_low',
    'pct_of_session_range', 'dist_from_session_high', 'new_session_low',
    'dist_from_open_pct', 'dist_from_prev_close_pct',
    'pct_of_5d_range',
    'gap_filled', 'gap_extended',
    'bars_since_low', 'bounce_from_low_pct',
    'entry_candle_body', 'lower_lows_10',
    'mr_strength', 'oversold_score', 'trend_counter',
]

all_safe = prior_day_safe + intraday_safe
returns = np.array([t['ret_pct'] for t in trades])

feature_stats = []
for fname in all_safe:
    try:
        vals = np.array([t.get(fname, 0) for t in trades], dtype=float)
    except (ValueError, TypeError):
        continue
    mask = np.isfinite(vals) & np.isfinite(returns)
    if mask.sum() < 50:
        continue
    v, r = vals[mask], returns[mask]
    if np.std(v) < 1e-12:
        continue
    corr = np.corrcoef(v, r)[0, 1]
    # Quintile analysis
    pcts = np.percentile(v, [0, 20, 40, 60, 80, 100])
    q_sharpes = []
    for qi in range(5):
        lo, hi = pcts[qi], pcts[qi+1]
        if qi == 4:
            qmask = (v >= lo) & (v <= hi)
        else:
            qmask = (v >= lo) & (v < hi)
        qr = r[qmask]
        if len(qr) > 10:
            qavg = np.mean(qr)
            qstd = np.std(qr, ddof=1)
            qs = qavg / qstd * np.sqrt(len(qr) / 4.2) if qstd > 0 else 0
            q_sharpes.append(qs)
        else:
            q_sharpes.append(0)
    # Monotonicity: is there a clear trend across quintiles?
    mono_score = 0
    for qi in range(4):
        if q_sharpes[qi+1] > q_sharpes[qi]:
            mono_score += 1
        elif q_sharpes[qi+1] < q_sharpes[qi]:
            mono_score -= 1

    is_prior = fname in prior_day_safe
    feature_stats.append({
        'name': fname, 'corr': corr, 'abs_corr': abs(corr),
        'q_sharpes': q_sharpes, 'mono': mono_score,
        'q1_sharpe': q_sharpes[0], 'q5_sharpe': q_sharpes[4],
        'spread': q_sharpes[4] - q_sharpes[0],
        'type': 'prior-day' if is_prior else 'intraday',
    })

feature_stats.sort(key=lambda x: x['abs_corr'], reverse=True)

print(f"\n  {'Rank':<4} {'Feature':<30s} {'Type':<10s} {'Corr':>7s} {'Q1':>7s} {'Q2':>7s} {'Q3':>7s} {'Q4':>7s} {'Q5':>7s} {'Spread':>7s} {'Mono':>5s}")
print(f"  {'-'*100}")
for i, f in enumerate(feature_stats[:40]):
    qs = f['q_sharpes']
    tag = '*' if f['type'] == 'prior-day' else ' '
    print(f"  {i+1:<4d} {f['name']:<30s} {f['type']:<10s} {f['corr']:>+6.3f} {qs[0]:>7.3f} {qs[1]:>7.3f} {qs[2]:>7.3f} {qs[3]:>7.3f} {qs[4]:>7.3f} {f['spread']:>+6.3f} {f['mono']:>+4d}")

# ---------------------------------------------------------------
# PART 2: UNEXPLORED PRIOR-DAY FEATURES
# These can be pre-computed and loaded from CSV
# ---------------------------------------------------------------
print("\n\n" + "=" * 100)
print("  PART 2: UNEXPLORED PRIOR-DAY FEATURES - Bucket Analysis")
print("=" * 100)

unexplored_prior = [
    'return_3d', 'return_5d', 'return_10d', 'prior_day_return',
    'prior_10d_range_pct', 'daily_atr_pct', 'dist_daily_sma5',
    'dist_daily_sma10', 'dist_daily_sma20', 'daily_sma5_slope',
    'vix', 'vix_change', 'dow', 'prior_day_up', 'gap_pct',
]

for fname in unexplored_prior:
    vals = np.array([t.get(fname, 0) for t in trades], dtype=float)
    valid = np.isfinite(vals)
    if valid.sum() < 50:
        continue
    unique = len(np.unique(vals[valid]))
    if unique <= 7:
        # Categorical - use unique values
        boundaries = sorted(np.unique(vals[valid]))
        is_cat = True
    else:
        boundaries = list(np.percentile(vals[valid], [0, 20, 40, 60, 80, 100]))
        is_cat = False

    print(f"\n  {fname} (type: prior-day)")
    print(f"  {'-'*85}")
    print(f"  {'Bucket':<35s} {'N':>4s} {'WR':>6s} {'AvgRet%':>9s} {'TotalPnL':>12s} {'Sharpe':>7s}")

    if is_cat:
        for val in boundaries:
            subset = [t for t in trades if abs(t.get(fname, -999) - val) < 0.01]
            if len(subset) < 10:
                continue
            pnls = [t['pnl'] for t in subset]
            rets = [t['ret_pct'] for t in subset]
            n = len(subset)
            wr = sum(1 for p in pnls if p > 0) / n
            avg_ret = np.mean(rets)
            total = sum(pnls)
            std = np.std(pnls, ddof=1)
            sharpe = np.mean(pnls) / std * np.sqrt(n / 4.2) if std > 0 else 0
            print(f"  {f'= {val}':<35s} {n:>4d} {wr:>5.1%} {avg_ret:>+8.4f}% ${total:>11,.0f} {sharpe:>7.3f}")
    else:
        for bi in range(len(boundaries) - 1):
            lo, hi = boundaries[bi], boundaries[bi + 1]
            if bi == len(boundaries) - 2:
                subset = [t for t in trades if lo <= t.get(fname, -999) <= hi]
            else:
                subset = [t for t in trades if lo <= t.get(fname, -999) < hi]
            if len(subset) < 5:
                continue
            pnls = [t['pnl'] for t in subset]
            rets = [t['ret_pct'] for t in subset]
            n = len(subset)
            wr = sum(1 for p in pnls if p > 0) / n
            avg_ret = np.mean(rets)
            total = sum(pnls)
            std = np.std(pnls, ddof=1)
            sharpe = np.mean(pnls) / std * np.sqrt(n / 4.2) if std > 0 else 0
            print(f"  {f'{lo:>+8.3f} to {hi:>+8.3f}':<35s} {n:>4d} {wr:>5.1%} {avg_ret:>+8.4f}% ${total:>11,.0f} {sharpe:>7.3f}")


# ---------------------------------------------------------------
# PART 3: INTRADAY FEATURES KNOWN AT ENTRY
# These can be computed in strategy code at entry time
# ---------------------------------------------------------------
print("\n\n" + "=" * 100)
print("  PART 3: INTRADAY FEATURES (known at entry) - Top 15 Bucket Analysis")
print("=" * 100)

intraday_ranked = [f for f in feature_stats if f['type'] == 'intraday']
intraday_ranked.sort(key=lambda x: x['abs_corr'], reverse=True)

for fi in intraday_ranked[:15]:
    fname = fi['name']
    vals = np.array([t.get(fname, 0) for t in trades], dtype=float)
    valid = np.isfinite(vals)
    boundaries = list(np.percentile(vals[valid], [0, 20, 40, 60, 80, 100]))

    print(f"\n  {fname} (corr={fi['corr']:+.3f})")
    print(f"  {'-'*85}")
    print(f"  {'Bucket':<35s} {'N':>4s} {'WR':>6s} {'AvgRet%':>9s} {'TotalPnL':>12s} {'Sharpe':>7s}")

    for bi in range(len(boundaries) - 1):
        lo, hi = boundaries[bi], boundaries[bi + 1]
        try:
            if bi == len(boundaries) - 2:
                subset = [t for t in trades if float(lo) <= float(t.get(fname, -999)) <= float(hi)]
            else:
                subset = [t for t in trades if float(lo) <= float(t.get(fname, -999)) < float(hi)]
        except (ValueError, TypeError):
            continue
        if len(subset) < 5:
            continue
        pnls = [t['pnl'] for t in subset]
        rets = [t['ret_pct'] for t in subset]
        n = len(subset)
        wr = sum(1 for p in pnls if p > 0) / n
        avg_ret = np.mean(rets)
        total = sum(pnls)
        std = np.std(pnls, ddof=1)
        sharpe = np.mean(pnls) / std * np.sqrt(n / 4.2) if std > 0 else 0
        print(f"  {f'{lo:>+8.3f} to {hi:>+8.3f}':<35s} {n:>4d} {wr:>5.1%} {avg_ret:>+8.4f}% ${total:>11,.0f} {sharpe:>7.3f}")


# ---------------------------------------------------------------
# PART 4: 2-FEATURE INTERACTIONS
# Find pairs of features that predict better together
# ---------------------------------------------------------------
print("\n\n" + "=" * 100)
print("  PART 4: FEATURE INTERACTIONS (top prior-day pairs)")
print("=" * 100)

# Use the top prior-day features for interaction analysis
top_prior = [f['name'] for f in feature_stats if f['type'] == 'prior-day'][:10]

interaction_results = []
for f1, f2 in combinations(top_prior, 2):
    v1 = np.array([t.get(f1, 0) for t in trades], dtype=float)
    v2 = np.array([t.get(f2, 0) for t in trades], dtype=float)
    med1, med2 = np.median(v1), np.median(v2)

    # Split into 4 quadrants
    quadrants = {
        'HiHi': [t for t, a, b in zip(trades, v1, v2) if a >= med1 and b >= med2],
        'HiLo': [t for t, a, b in zip(trades, v1, v2) if a >= med1 and b < med2],
        'LoHi': [t for t, a, b in zip(trades, v1, v2) if a < med1 and b >= med2],
        'LoLo': [t for t, a, b in zip(trades, v1, v2) if a < med1 and b < med2],
    }

    q_stats = {}
    for qname, qtrades in quadrants.items():
        if len(qtrades) < 15:
            continue
        rets = [t['ret_pct'] for t in qtrades]
        pnls = [t['pnl'] for t in qtrades]
        n = len(qtrades)
        avg = np.mean(pnls)
        std = np.std(pnls, ddof=1)
        sharpe = avg / std * np.sqrt(n / 4.2) if std > 0 else 0
        q_stats[qname] = {'n': n, 'sharpe': sharpe, 'avg_ret': np.mean(rets)}

    if len(q_stats) == 4:
        sharpes = [q_stats[q]['sharpe'] for q in ['HiHi','HiLo','LoHi','LoLo']]
        spread = max(sharpes) - min(sharpes)
        best_q = max(q_stats, key=lambda q: q_stats[q]['sharpe'])
        worst_q = min(q_stats, key=lambda q: q_stats[q]['sharpe'])
        interaction_results.append({
            'f1': f1, 'f2': f2, 'spread': spread,
            'best': best_q, 'worst': worst_q,
            'stats': q_stats,
        })

interaction_results.sort(key=lambda x: x['spread'], reverse=True)

for ir in interaction_results[:15]:
    print(f"\n  {ir['f1']} x {ir['f2']} (Sharpe spread: {ir['spread']:.3f})")
    for qname in ['HiHi','HiLo','LoHi','LoLo']:
        qs = ir['stats'][qname]
        tag = ' <-- BEST' if qname == ir['best'] else (' <-- WORST' if qname == ir['worst'] else '')
        print(f"    {qname}: N={qs['n']:>3d}  Sharpe={qs['sharpe']:>6.3f}  AvgRet={qs['avg_ret']:>+.4f}%{tag}")


# ---------------------------------------------------------------
# PART 5: THRESHOLD OPTIMIZATION for G3 components
# Test finer thresholds for each feature in G3
# ---------------------------------------------------------------
print("\n\n" + "=" * 100)
print("  PART 5: THRESHOLD OPTIMIZATION")
print("=" * 100)

# For each G3 component, test different thresholds
threshold_tests = {
    'prior_day_range_pct': {
        'up_thresholds': [1.0, 1.2, 1.43, 1.6, 1.8, 2.0],
        'down_thresholds': [0.5, 0.6, 0.7, 0.80, 0.9, 1.0],
        'up_weight_range': [0.2, 0.3, 0.4, 0.5, 0.6],
        'down_weight_range': [0.2, 0.3, 0.4, 0.5],
    },
    'prior_day_body_pct': {
        'up_thresholds': [0.5, 0.6, 0.79, 0.9, 1.0],
        'down_thresholds': [0.15, 0.20, 0.23, 0.30, 0.35],
        'up_weight_range': [0.2, 0.3, 0.4, 0.5],
        'down_weight_range': [0.2, 0.3, 0.4, 0.5],
    },
    'return_2d': {
        'up_thresholds': [-2.0, -1.49, -1.0, -0.5],
        'down_thresholds': [0.5, 0.8, 1.0, 1.18, 1.5],
        'up_weight_range': [0.2, 0.3, 0.4, 0.5],
        'down_weight_range': [0.2, 0.3, 0.4, 0.5],
    },
}

for fname, config in threshold_tests.items():
    print(f"\n  Optimizing: {fname}")
    print(f"  {'UpThresh':>8s} {'UpWt':>5s} {'DnThresh':>8s} {'DnWt':>5s} | {'Sharpe':>7s} {'N':>4s} {'Total$':>12s}")
    print(f"  {'-'*65}")

    best_sharpe = -999
    best_config = None

    for ut in config['up_thresholds']:
        for uw in config['up_weight_range']:
            for dt in config['down_thresholds']:
                for dw in config['down_weight_range']:
                    def make_size_fn(f, ut, uw, dt, dw):
                        def size_fn(t):
                            score = 1.0
                            if t[f] > ut: score += uw
                            if t[f] < dt: score -= dw
                            return max(score, 0.2)
                        return size_fn

                    r = simulate(trades, f'{fname}', make_size_fn(fname, ut, uw, dt, dw),
                                lambda t: t['gap_pct'] < -1.0)
                    if r and r['sharpe'] > best_sharpe:
                        best_sharpe = r['sharpe']
                        best_config = (ut, uw, dt, dw, r)

    if best_config:
        ut, uw, dt, dw, r = best_config
        print(f"  {'BEST:':>8s} {ut:>8.2f} {uw:>5.2f} {dt:>8.2f} {dw:>5.2f} | {r['sharpe']:>7.3f} {r['n']:>4d} ${r['total']:>11,.0f}")


# ---------------------------------------------------------------
# PART 6: NEW COMPOSITE STRATEGIES
# Build on G3 by adding unexplored features
# ---------------------------------------------------------------
print("\n\n" + "=" * 100)
print("  PART 6: ENHANCED COMPOSITES (building on G3)")
print("=" * 100)

strategies = []

# G3 baseline for reference
def g3_base(t):
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

strategies.append(('G3-ref: Composite v2', g3_base, lambda t: t['gap_pct'] < -1.0))

# H1: G3 + VIX
def h1(t):
    score = g3_base(t)
    vix = t.get('vix', 20)
    if vix > 25: score += 0.3    # High VIX = bigger mean reversion
    if vix < 15: score -= 0.2    # Low VIX = less edge
    return max(score, 0.2)
strategies.append(('H1: G3 + VIX regime', h1, lambda t: t['gap_pct'] < -1.0))

# H2: G3 + VIX change
def h2(t):
    score = g3_base(t)
    vc = t.get('vix_change', 0)
    if vc > 2: score += 0.3      # VIX spiking = mean reversion opportunity
    if vc < -2: score -= 0.2     # VIX dropping = trending, less MR
    return max(score, 0.2)
strategies.append(('H2: G3 + VIX change', h2, lambda t: t['gap_pct'] < -1.0))

# H3: G3 + return_5d (longer lookback)
def h3(t):
    score = g3_base(t)
    r5 = t.get('return_5d', 0)
    if r5 < -2.5: score += 0.3   # 5-day selloff = stronger MR
    if r5 > 2.5: score -= 0.3    # 5-day rally = weaker MR
    return max(score, 0.2)
strategies.append(('H3: G3 + return_5d', h3, lambda t: t['gap_pct'] < -1.0))

# H4: G3 + return_3d
def h4(t):
    score = g3_base(t)
    r3 = t.get('return_3d', 0)
    if r3 < -1.5: score += 0.3
    if r3 > 1.5: score -= 0.3
    return max(score, 0.2)
strategies.append(('H4: G3 + return_3d', h4, lambda t: t['gap_pct'] < -1.0))

# H5: G3 + daily ATR pct
def h5(t):
    score = g3_base(t)
    atr = t.get('daily_atr_pct', 0)
    if atr > 1.5: score += 0.3   # High ATR = more room to revert
    if atr < 0.7: score -= 0.2   # Low ATR = tight market
    return max(score, 0.2)
strategies.append(('H5: G3 + daily ATR', h5, lambda t: t['gap_pct'] < -1.0))

# H6: G3 + prior_day_return
def h6(t):
    score = g3_base(t)
    pdr = t.get('prior_day_return', 0)
    if pdr < -1.0: score += 0.3   # Prior day big down = bounce potential
    if pdr > 1.0: score -= 0.2    # Prior day big up = less MR
    return max(score, 0.2)
strategies.append(('H6: G3 + prior day return', h6, lambda t: t['gap_pct'] < -1.0))

# H7: G3 + SMA distance
def h7(t):
    score = g3_base(t)
    d20 = t.get('dist_daily_sma20', 0)
    if d20 < -3: score += 0.3    # Far below SMA20 = oversold
    if d20 > 3: score -= 0.2     # Far above SMA20 = overbought
    return max(score, 0.2)
strategies.append(('H7: G3 + dist SMA20', h7, lambda t: t['gap_pct'] < -1.0))

# H8: G3 + SMA5 slope
def h8(t):
    score = g3_base(t)
    slope = t.get('daily_sma5_slope', 0)
    if slope > 0.5: score += 0.2   # Positive slope = momentum up
    if slope < -0.5: score -= 0.2  # Negative slope = momentum down
    return max(score, 0.2)
strategies.append(('H8: G3 + SMA5 slope', h8, lambda t: t['gap_pct'] < -1.0))

# H9: G3 + DOW (day of week)
def h9(t):
    score = g3_base(t)
    dow = t.get('dow', 2)
    if dow == 0: score += 0.15   # Monday
    if dow == 4: score -= 0.15   # Friday
    return max(score, 0.2)
strategies.append(('H9: G3 + DOW (Mon+/Fri-)', h9, lambda t: t['gap_pct'] < -1.0))

# H10: G3 + gap magnitude sizing
def h10(t):
    score = g3_base(t)
    gap = t.get('gap_pct', 0)
    if gap < -0.5: score += 0.3   # Gap down = MR opportunity
    if gap > 0.5: score -= 0.2    # Gap up = less MR
    return max(score, 0.2)
strategies.append(('H10: G3 + gap magnitude', h10, lambda t: t['gap_pct'] < -1.0))

# H11: G3 + prior_10d_range
def h11(t):
    score = g3_base(t)
    r10d = t.get('prior_10d_range_pct', 0)
    if r10d > 7: score += 0.3    # Wide 10d range = volatile
    if r10d < 3: score -= 0.2    # Narrow 10d range = calm
    return max(score, 0.2)
strategies.append(('H11: G3 + 10d range', h11, lambda t: t['gap_pct'] < -1.0))

# H12: G3 + prior_day_up
def h12(t):
    score = g3_base(t)
    if t.get('prior_day_up', 0) == 0: score += 0.2   # Prior day was down
    return max(score, 0.2)
strategies.append(('H12: G3 + prior day down', h12, lambda t: t['gap_pct'] < -1.0))

# H13: G3 + return_10d
def h13(t):
    score = g3_base(t)
    r10 = t.get('return_10d', 0)
    if r10 < -4: score += 0.3
    if r10 > 4: score -= 0.3
    return max(score, 0.2)
strategies.append(('H13: G3 + return_10d', h13, lambda t: t['gap_pct'] < -1.0))

# H14: Kitchen sink (all promising prior-day additions)
def h14(t):
    score = g3_base(t)
    # VIX
    vix = t.get('vix', 20)
    if vix > 25: score += 0.2
    if vix < 15: score -= 0.15
    # return_5d
    r5 = t.get('return_5d', 0)
    if r5 < -2.5: score += 0.2
    if r5 > 2.5: score -= 0.2
    # ATR
    atr = t.get('daily_atr_pct', 0)
    if atr > 1.5: score += 0.15
    # Gap
    gap = t.get('gap_pct', 0)
    if gap < -0.5: score += 0.15
    return max(score, 0.2)
strategies.append(('H14: G3 + VIX+5d+ATR+gap', h14, lambda t: t['gap_pct'] < -1.0))

# H15: Conservative kitchen sink (only add proven factors, smaller weights)
def h15(t):
    score = g3_base(t)
    vix = t.get('vix', 20)
    if vix > 25: score += 0.15
    r5 = t.get('return_5d', 0)
    if r5 < -2.5: score += 0.15
    if r5 > 2.5: score -= 0.15
    return max(score, 0.2)
strategies.append(('H15: G3 + VIX+5d (conserv)', h15, lambda t: t['gap_pct'] < -1.0))

# H16-H20: Intraday feature overlays on G3
# These would require code changes in the strategy

# H16: G3 + skip first 10 mins
strategies.append(('H16: G3 + skip first 10m',
    g3_base, lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 10))

# H17: G3 + skip entries after 2pm
strategies.append(('H17: G3 + skip after 2pm',
    g3_base, lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] > 270))

# H18: G3 + skip entries after 1pm
strategies.append(('H18: G3 + skip after 1pm',
    g3_base, lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] > 210))

# H19: G3 + only 10am-1pm
strategies.append(('H19: G3 + only 10am-1pm',
    g3_base, lambda t: t['gap_pct'] < -1.0 or t['mins_from_open'] < 30 or t['mins_from_open'] > 210))

# H20: G3 + finer TOD granularity
strategies.append(('H20: G3 + skip 30-60m',
    g3_base, lambda t: t['gap_pct'] < -1.0 or 30 <= t['mins_from_open'] < 60))

# H21: G3 + skip if momentum too negative (panic selling)
def h21(t):
    score = g3_base(t)
    m5 = t.get('momentum_5b', 0)
    if m5 < -0.3: score += 0.2   # Sharp drop = bounce potential
    if m5 > 0.1: score -= 0.2    # Already bouncing
    return max(score, 0.2)
strategies.append(('H21: G3 + intraday momentum', h21, lambda t: t['gap_pct'] < -1.0))

# H22: G3 + velocity sizing
def h22(t):
    score = g3_base(t)
    vel = t.get('velocity', 0)
    if vel > 15: score += 0.2    # Long time below VWAP
    if vel < 3: score -= 0.2     # Just crossed below
    return max(score, 0.2)
strategies.append(('H22: G3 + velocity', h22, lambda t: t['gap_pct'] < -1.0))

# H23: G3 + opening range
def h23(t):
    score = g3_base(t)
    orng = t.get('opening_range_pct', 0)
    if orng > 0.5: score += 0.2  # Wide OR = volatile day
    if orng < 0.2: score -= 0.15 # Tight OR = less edge
    return max(score, 0.2)
strategies.append(('H23: G3 + opening range', h23, lambda t: t['gap_pct'] < -1.0))

# H24: G3 + below opening range low
def h24(t):
    score = g3_base(t)
    if t.get('below_or_low', 0) == 1: score += 0.3  # Below OR low = oversold
    return max(score, 0.2)
strategies.append(('H24: G3 + below OR low', h24, lambda t: t['gap_pct'] < -1.0))

# H25: G3 + consec bars below VWAP
def h25(t):
    score = g3_base(t)
    cb = t.get('consec_below_vwap', 0)
    if cb > 10: score += 0.2
    if cb < 3: score -= 0.15
    return max(score, 0.2)
strategies.append(('H25: G3 + consec below VWAP', h25, lambda t: t['gap_pct'] < -1.0))

# Run all
results = []
for name, size_fn, skip_fn in strategies:
    r = simulate(trades, name, size_fn, skip_fn)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)

print(f"\n  {'Strategy':<42s} {'N':>4s} {'Skip':>4s} {'Sharpe':>7s} {'vs G3':>6s} {'WR':>6s} {'PF':>5s} {'Total$':>12s} {'AvgPnL':>9s} {'MaxDD':>10s} {'NY':>3s}")
print(f"  {'-'*115}")

g3_sharpe = None
for r in results:
    if 'G3-ref' in r['name']:
        g3_sharpe = r['sharpe']
        break

for r in results:
    diff = ((r['sharpe'] / g3_sharpe - 1) * 100) if g3_sharpe else 0
    sign = '+' if diff > 0 else ''
    print(f"  {r['name']:<42s} {r['n']:>4d} {r['skipped']:>4d} {r['sharpe']:>7.3f} {sign}{diff:>4.0f}% {r['wr']:>5.1%} {r['pf']:>5.2f} ${r['total']:>11,.0f} ${r['avg']:>8,.0f} ${r['max_dd']:>9,.0f} {r['neg_years']:>3d}")


# ---------------------------------------------------------------
# PART 7: YEARLY BREAKDOWN for top 5 + G3 ref
# ---------------------------------------------------------------
print("\n\n" + "=" * 80)
print("  YEARLY BREAKDOWN - Top 5 + G3 ref")
print("=" * 80)

g3_ref = next((r for r in results if 'G3-ref' in r['name']), None)
top5 = results[:5]
if g3_ref and g3_ref not in top5:
    top5.append(g3_ref)

for r in top5:
    print(f"\n  {r['name']} (Sharpe={r['sharpe']:.3f})")
    for yr in sorted(r['by_year'].keys()):
        yp = r['by_year'][yr]
        yt = sum(yp)
        n = len(yp)
        yw = sum(1 for p in yp if p > 0)
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={yw/n:.1%}")


# ---------------------------------------------------------------
# PART 8: GRID SEARCH FOR OPTIMAL G3 WEIGHTS
# ---------------------------------------------------------------
print("\n\n" + "=" * 100)
print("  PART 8: GRID SEARCH - Optimizing G3 weights")
print("=" * 100)

best_sharpe = 0
best_params = None
tested = 0

# Grid over the main lever weights
for w_range_up in [0.2, 0.3, 0.4, 0.5, 0.6]:
    for w_range_dn in [0.2, 0.3, 0.4, 0.5]:
        for w_body_up in [0.2, 0.3, 0.4, 0.5]:
            for w_body_dn in [0.2, 0.3, 0.4, 0.5]:
                for w_2d_up in [0.2, 0.3, 0.4]:
                    for w_2d_dn in [0.2, 0.3, 0.4, 0.5]:
                        for w_trend in [0.1, 0.2, 0.3]:
                            for w_week in [0.0, 0.1, 0.2, 0.3]:
                                def make_fn(wru, wrd, wbu, wbd, w2u, w2d, wt, ww):
                                    def fn(t):
                                        s = 1.0
                                        if t['prior_day_range_pct'] > 1.43: s += wru
                                        if t['prior_day_range_pct'] < 0.80: s -= wrd
                                        if t['prior_day_body_pct'] > 0.79: s += wbu
                                        if t['prior_day_body_pct'] < 0.23: s -= wbd
                                        if t['return_2d'] < -1.49: s += w2u
                                        if t['return_2d'] > 1.18: s -= w2d
                                        if t['daily_sma5_above_sma20'] == 1: s += wt
                                        if t['prior_week_range_pct'] > 5.32: s += ww
                                        return max(s, 0.2)
                                    return fn

                                r = simulate(trades, 'grid',
                                    make_fn(w_range_up, w_range_dn, w_body_up, w_body_dn,
                                            w_2d_up, w_2d_dn, w_trend, w_week),
                                    lambda t: t['gap_pct'] < -1.0)
                                tested += 1
                                if r and r['sharpe'] > best_sharpe and r['neg_years'] == 0:
                                    best_sharpe = r['sharpe']
                                    best_params = (w_range_up, w_range_dn, w_body_up, w_body_dn,
                                                   w_2d_up, w_2d_dn, w_trend, w_week)
                                    best_result = r

print(f"  Tested {tested} weight combinations")
if best_params:
    wru, wrd, wbu, wbd, w2u, w2d, wt, ww = best_params
    print(f"  Best Sharpe: {best_sharpe:.3f}")
    print(f"  Weights: range_up={wru}, range_dn={wrd}, body_up={wbu}, body_dn={wbd}")
    print(f"           2d_up={w2u}, 2d_dn={w2d}, trend={wt}, week={ww}")
    print(f"  N={best_result['n']}, Total=${best_result['total']:,.0f}, WR={best_result['wr']:.1%}")
    print(f"  Neg years: {best_result['neg_years']}")

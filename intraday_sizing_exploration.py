#!/usr/bin/env python3
"""
Explore INTRADAY features as trade-grading signals for sizing.
All features tested are known AT ENTRY TIME (not hindsight).

Goal: find which intraday features predict win/loss to build a
per-trade grade that drives position sizing.
"""

import json
import numpy as np
from collections import defaultdict

with open('kite_deep_features.json') as f:
    trades = json.load(f)

print(f"Total trades: {len(trades)}")
print(f"Wins: {sum(1 for t in trades if t['is_win'])}, "
      f"Losses: {sum(1 for t in trades if not t['is_win'])}")
print(f"Baseline WR: {sum(1 for t in trades if t['is_win'])/len(trades):.1%}")

pnls = [t['pnl'] for t in trades]
baseline_sharpe = np.mean(pnls) / np.std(pnls, ddof=1) * np.sqrt(len(pnls)/4.2)
print(f"Baseline Sharpe (flat $150K): {baseline_sharpe:.3f}")

# ================================================================
# PART 1: Rank ALL intraday features by predictive power
# ================================================================
print("\n" + "="*100)
print("  PART 1: INTRADAY FEATURE PREDICTIVE POWER RANKING")
print("="*100)

# Features known at entry time (intraday, not prior-day)
intraday_features = [
    'vwap_slope_5', 'vwap_slope_10',
    'velocity', 'consec_below_vwap',
    'dist_from_open_pct', 'dist_from_or_high', 'dist_from_or_low',
    'dist_from_prev_close_pct', 'dist_from_session_high',
    'dist_ema5_pct', 'dist_ema10_pct', 'dist_ema20_pct',
    'ema5_above_ema20', 'ema5_slope',
    'cum_vol_pct', 'entry_bar_volume', 'entry_bar_range_pct',
    'entry_candle_body',
    'opening_range_pct', 'or30_range_pct',
    'bars_into_session', 'mins_from_open',
    'bounce_from_low_pct', 'bars_since_low',
    'below_or_low', 'below_or30_low', 'new_session_low',
    'gap_filled',
    'momentum_3b', 'momentum_5b', 'momentum_10b', 'momentum_15b', 'momentum_20b',
    'price_acceleration',
    'mr_strength', 'oversold_score',
    'trend_counter', 'dev_speed',
    'max_vwap_dev_before_entry',
    'today_move_atr_mult', 'today_range_pct',
    'vol_surge_5', 'vol_surge_session', 'vol_compression',
    'pct_of_session', 'pct_of_session_range',
    'lower_lows_10', 'consec_down_bars',
    'range_last_5_pct', 'intraday_atr', 'intraday_atr_pct',
    'vwap_dev_pct',
]

# Prior-day features (for comparison)
prior_day_features = [
    'prior_day_range_pct', 'prior_day_body_pct', 'prior_day_return',
    'prior_day_up', 'return_2d', 'return_3d', 'return_5d', 'return_10d',
    'daily_sma5_above_sma20', 'daily_sma5_slope', 'daily_vol_ratio',
    'daily_atr_pct', 'prior_week_range_pct', 'prior_10d_range_pct',
    'gap_pct', 'gap_extended',
    'dist_daily_sma5', 'dist_daily_sma10', 'dist_daily_sma20',
    'pct_of_5d_range',
    'vix', 'vix_change',
    'dow',
]

def feature_predictive_power(trades, feature_name):
    """Compute Sharpe spread between top/bottom tercile by feature value."""
    valid = []
    for t in trades:
        if feature_name not in t or t[feature_name] is None:
            continue
        try:
            v = float(t[feature_name])
            valid.append((v, t['pnl'], t['ret_pct']))
        except (ValueError, TypeError):
            continue
    if len(valid) < 30:
        return None

    valid.sort(key=lambda x: x[0])
    n = len(valid)
    t1 = n // 3
    t2 = 2 * n // 3

    bot = [v[1] for v in valid[:t1]]
    mid = [v[1] for v in valid[t1:t2]]
    top = [v[1] for v in valid[t2:]]

    def sharpe(pnls):
        if len(pnls) < 5 or np.std(pnls, ddof=1) == 0:
            return 0
        return np.mean(pnls) / np.std(pnls, ddof=1) * np.sqrt(len(pnls)/4.2)

    s_bot = sharpe(bot)
    s_top = sharpe(top)
    s_mid = sharpe(mid)
    spread = abs(s_top - s_bot)

    wr_bot = sum(1 for p in bot if p > 0) / len(bot) if bot else 0
    wr_top = sum(1 for p in top if p > 0) / len(top) if top else 0

    return {
        'feature': feature_name,
        'spread': spread,
        's_bot': s_bot, 's_mid': s_mid, 's_top': s_top,
        'wr_bot': wr_bot, 'wr_top': wr_top,
        'n': n,
        'bot_avg': np.mean([v[0] for v in valid[:t1]]),
        'top_avg': np.mean([v[0] for v in valid[t2:]]),
        'best_tercile': 'TOP' if s_top > s_bot else 'BOT',
    }

# Rank all features
print(f"\n  {'Feature':<30s} {'Spread':>8s} {'S_bot':>8s} {'S_mid':>8s} {'S_top':>8s} {'WR_bot':>7s} {'WR_top':>7s} {'Best':>5s}")
print(f"  {'-'*90}")

all_results = []
for feat in intraday_features + prior_day_features:
    r = feature_predictive_power(trades, feat)
    if r:
        all_results.append(r)

all_results.sort(key=lambda x: x['spread'], reverse=True)
for r in all_results:
    tag = "[ID]" if r['feature'] in intraday_features else "[PD]"
    print(f"  {tag} {r['feature']:<26s} {r['spread']:>8.3f} {r['s_bot']:>8.3f} {r['s_mid']:>8.3f} {r['s_top']:>8.3f} {r['wr_bot']:>6.1%} {r['wr_top']:>6.1%} {r['best_tercile']:>5s}")

# ================================================================
# PART 2: Deep dive on VWAP slope features
# ================================================================
print("\n" + "="*100)
print("  PART 2: VWAP SLOPE DEEP DIVE")
print("="*100)

for slope_feat in ['vwap_slope_5', 'vwap_slope_10']:
    vals = [t[slope_feat] for t in trades if slope_feat in t]
    print(f"\n  {slope_feat}:")
    print(f"    Range: [{min(vals):.4f}, {max(vals):.4f}]")
    print(f"    Mean: {np.mean(vals):.4f}, Median: {np.median(vals):.4f}")
    print(f"    Std: {np.std(vals):.4f}")

    # Bucket analysis
    pcts = [0, 10, 25, 50, 75, 90, 100]
    boundaries = np.percentile(vals, pcts)
    print(f"    Percentiles: {', '.join(f'p{p}={b:.4f}' for p, b in zip(pcts, boundaries))}")

    # Quintile analysis
    quintiles = np.percentile(vals, [0, 20, 40, 60, 80, 100])
    print(f"\n    {'Quintile':<12s} {'Range':<25s} {'N':>4s} {'WR':>7s} {'AvgPnL':>10s} {'Sharpe':>8s} {'TotalPnL':>12s}")
    print(f"    {'-'*80}")
    for q in range(5):
        lo, hi = quintiles[q], quintiles[q+1]
        bucket = [t for t in trades if slope_feat in t and lo <= t[slope_feat] <= hi]
        if q < 4:
            bucket = [t for t in trades if slope_feat in t and lo <= t[slope_feat] < hi]
        if not bucket:
            continue
        bpnls = [t['pnl'] for t in bucket]
        wr = sum(1 for p in bpnls if p > 0) / len(bpnls)
        avg = np.mean(bpnls)
        std = np.std(bpnls, ddof=1) if len(bpnls) > 1 else 1
        sh = avg / std * np.sqrt(len(bpnls)/4.2) if std > 0 else 0
        total = sum(bpnls)
        print(f"    Q{q+1} ({lo:>7.4f},{hi:>7.4f}) {len(bucket):>4d} {wr:>6.1%} ${avg:>9,.0f} {sh:>8.3f} ${total:>11,.0f}")

# ================================================================
# PART 3: Interaction analysis - best intraday x prior-day combos
# ================================================================
print("\n" + "="*100)
print("  PART 3: TOP INTRADAY x PRIOR-DAY INTERACTIONS")
print("="*100)

# Take top 10 intraday and top 5 prior-day features
top_intraday = [r['feature'] for r in all_results if r['feature'] in intraday_features][:10]
top_priorday = [r['feature'] for r in all_results if r['feature'] in prior_day_features][:5]

print(f"\n  Testing {len(top_intraday)} intraday x {len(top_priorday)} prior-day features")

interactions = []
for id_feat in top_intraday:
    for pd_feat in top_priorday:
        try:
            id_vals = [float(t[id_feat]) for t in trades if id_feat in t and t[id_feat] is not None]
            pd_vals = [float(t[pd_feat]) for t in trades if pd_feat in t and t[pd_feat] is not None]
            id_med = np.median(id_vals)
            pd_med = np.median(pd_vals)
        except (ValueError, TypeError):
            continue

        # 4 quadrants
        quads = {
            'id_hi_pd_hi': [], 'id_hi_pd_lo': [],
            'id_lo_pd_hi': [], 'id_lo_pd_lo': [],
        }
        for t in trades:
            if id_feat not in t or pd_feat not in t:
                continue
            if t[id_feat] is None or t[pd_feat] is None:
                continue
            try:
                id_val = float(t[id_feat])
                pd_val = float(t[pd_feat])
            except (ValueError, TypeError):
                continue
            id_hi = id_val >= id_med
            pd_hi = pd_val >= pd_med
            if id_hi and pd_hi:
                quads['id_hi_pd_hi'].append(t['pnl'])
            elif id_hi and not pd_hi:
                quads['id_hi_pd_lo'].append(t['pnl'])
            elif not id_hi and pd_hi:
                quads['id_lo_pd_hi'].append(t['pnl'])
            else:
                quads['id_lo_pd_lo'].append(t['pnl'])

        sharpes = {}
        for qname, qpnls in quads.items():
            if len(qpnls) < 10:
                sharpes[qname] = 0
            else:
                std = np.std(qpnls, ddof=1)
                sharpes[qname] = np.mean(qpnls) / std * np.sqrt(len(qpnls)/4.2) if std > 0 else 0

        best_q = max(sharpes, key=sharpes.get)
        worst_q = min(sharpes, key=sharpes.get)
        spread = sharpes[best_q] - sharpes[worst_q]

        interactions.append({
            'id_feat': id_feat, 'pd_feat': pd_feat,
            'spread': spread,
            'best': best_q, 'best_sharpe': sharpes[best_q],
            'worst': worst_q, 'worst_sharpe': sharpes[worst_q],
            'sharpes': sharpes,
        })

interactions.sort(key=lambda x: x['spread'], reverse=True)
print(f"\n  {'Intraday':<26s} {'Prior-Day':<22s} {'Spread':>8s} {'Best':>15s} {'S_best':>8s} {'Worst':>15s} {'S_worst':>8s}")
print(f"  {'-'*105}")
for ix in interactions[:20]:
    print(f"  {ix['id_feat']:<26s} {ix['pd_feat']:<22s} {ix['spread']:>8.3f} {ix['best']:>15s} {ix['best_sharpe']:>8.3f} {ix['worst']:>15s} {ix['worst_sharpe']:>8.3f}")

# ================================================================
# PART 4: Build comprehensive trade grading system
# ================================================================
print("\n" + "="*100)
print("  PART 4: COMPREHENSIVE TRADE GRADING SYSTEM")
print("="*100)

# Use top features from Parts 1-3 to build a multi-signal grade
# Test systematic combinations of intraday + prior-day signals

# First, get optimal thresholds for top intraday features via bucket analysis
print("\n  Optimal threshold search for top intraday features:")

def find_optimal_thresholds(trades, feature, n_splits=10):
    """Find the threshold that maximizes Sharpe spread."""
    try:
        vals = sorted(set(float(t[feature]) for t in trades if feature in t and t[feature] is not None))
    except (ValueError, TypeError):
        return None
    if len(vals) < 20:
        return None

    best = None
    percentiles = np.linspace(10, 90, n_splits)
    all_vals = [float(t[feature]) for t in trades if feature in t and t[feature] is not None]

    for pct in percentiles:
        thresh = np.percentile(all_vals, pct)
        above = [t['pnl'] for t in trades if feature in t and t[feature] is not None and float(t[feature]) >= thresh]
        below = [t['pnl'] for t in trades if feature in t and t[feature] is not None and float(t[feature]) < thresh]

        if len(above) < 20 or len(below) < 20:
            continue

        def sh(p):
            s = np.std(p, ddof=1)
            return np.mean(p) / s * np.sqrt(len(p)/4.2) if s > 0 else 0

        s_above = sh(above)
        s_below = sh(below)
        spread = abs(s_above - s_below)

        if best is None or spread > best['spread']:
            best = {
                'thresh': thresh, 'pct': pct, 'spread': spread,
                's_above': s_above, 's_below': s_below,
                'n_above': len(above), 'n_below': len(below),
                'better': 'above' if s_above > s_below else 'below',
            }

    return best

for feat in top_intraday[:10]:
    r = find_optimal_thresholds(trades, feat)
    if r:
        print(f"    {feat:<28s} thresh={r['thresh']:>8.3f} (p{r['pct']:.0f}) "
              f"spread={r['spread']:.3f} above={r['s_above']:.3f}({r['n_above']}) "
              f"below={r['s_below']:.3f}({r['n_below']}) better={r['better']}")

# ================================================================
# PART 5: Test grading systems with intraday features
# ================================================================
print("\n" + "="*100)
print("  PART 5: GRADING SYSTEMS WITH INTRADAY FEATURES")
print("="*100)

def test_grading(trades, grade_fn, name, baseline_sharpe=0.881):
    """Test a grading function that returns a sizing multiplier per trade."""
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

# V16b (current champion) for comparison
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
    # skip first 10 mins
    if t.get('mins_from_open', 999) < 10:
        return 0
    return s

# G1: VWAP slope as sizing signal
def g_vwap_slope(t):
    s = v16b(t)  # start from V16b base
    if s <= 0:
        return 0
    slope5 = t.get('vwap_slope_5', 0)
    slope10 = t.get('vwap_slope_10', 0)
    # For mean reversion BUYS: falling VWAP = bigger dip = more reversion potential?
    # Or rising VWAP = market recovering = better setup?
    # Test both directions
    if slope10 < -0.02: s += 0.2    # VWAP falling = bigger opportunity
    if slope10 > 0.02: s -= 0.2     # VWAP rising = maybe already recovering
    return max(s, 0.1)

# G2: VWAP slope opposite direction
def g_vwap_slope_rev(t):
    s = v16b(t)
    if s <= 0:
        return 0
    slope10 = t.get('vwap_slope_10', 0)
    if slope10 > 0.02: s += 0.2     # VWAP rising = market healthy, dip is temporary
    if slope10 < -0.02: s -= 0.2    # VWAP falling = trend against us
    return max(s, 0.1)

# G3: Momentum signals
def g_momentum(t):
    s = v16b(t)
    if s <= 0:
        return 0
    mom5 = t.get('momentum_5b', 0)
    mom10 = t.get('momentum_10b', 0)
    # Oversold = more reversion potential
    if mom5 < 0 and mom10 < 0: s += 0.2  # strong downward momentum = bigger snap back
    if mom5 > 0 and mom10 > 0: s -= 0.2  # upward momentum = less dip
    return max(s, 0.1)

# G4: Entry timing (mins from open)
def g_entry_timing(t):
    s = v16b(t)
    if s <= 0:
        return 0
    mins = t.get('mins_from_open', 100)
    # Test if mid-day entries are better than early/late
    if 30 <= mins <= 180: s += 0.15  # prime trading hours
    if mins > 300: s -= 0.2          # late day
    return max(s, 0.1)

# G5: Volume signals
def g_volume(t):
    s = v16b(t)
    if s <= 0:
        return 0
    cum_vol = t.get('cum_vol_pct', 1.0)
    vol_surge = t.get('vol_surge_5', 0)
    if vol_surge == 1: s += 0.15     # volume spike = capitulation
    if cum_vol < 0.5: s -= 0.15     # low volume = less conviction
    return max(s, 0.1)

# G6: Mean reversion strength
def g_mr_strength(t):
    s = v16b(t)
    if s <= 0:
        return 0
    mr = t.get('mr_strength', 0)
    oversold = t.get('oversold_score', 0)
    if mr > 0.7: s += 0.2           # strong MR signal
    if mr < 0.3: s -= 0.2           # weak MR
    if oversold > 0.7: s += 0.15    # oversold
    return max(s, 0.1)

# G7: Distance from key levels
def g_distance(t):
    s = v16b(t)
    if s <= 0:
        return 0
    dist_open = t.get('dist_from_open_pct', 0)
    dist_or_low = t.get('dist_from_or_low', 0)
    # Further from open = bigger move = more reversion
    if dist_open < -0.5: s += 0.15
    if dist_open > 0: s -= 0.2       # above open = not really a dip
    return max(s, 0.1)

# G8: Consecutive bars below VWAP
def g_consec(t):
    s = v16b(t)
    if s <= 0:
        return 0
    consec = t.get('consec_below_vwap', 0)
    if consec >= 5: s += 0.15     # sustained below = better reversion
    if consec <= 1: s -= 0.15    # brief touch = weak signal
    return max(s, 0.1)

# G9: VWAP slope + momentum combo
def g_slope_mom(t):
    s = v16b(t)
    if s <= 0:
        return 0
    slope10 = t.get('vwap_slope_10', 0)
    mom5 = t.get('momentum_5b', 0)
    mr = t.get('mr_strength', 0)

    if slope10 < -0.01 and mom5 < 0: s += 0.2   # falling VWAP + down momentum
    if slope10 > 0.01 and mom5 > 0: s -= 0.2    # rising already
    if mr > 0.6: s += 0.1
    return max(s, 0.1)

# G10: Today's range as volatility signal
def g_today_range(t):
    s = v16b(t)
    if s <= 0:
        return 0
    today_range = t.get('today_range_pct', 0)
    atr_mult = t.get('today_move_atr_mult', 0)
    if today_range > 0.8: s += 0.15     # volatile day = more reversion
    if today_range < 0.3: s -= 0.15     # dead day
    return max(s, 0.1)

# G11: EMA signals (intraday trend)
def g_ema(t):
    s = v16b(t)
    if s <= 0:
        return 0
    ema_above = t.get('ema5_above_ema20', 0)
    ema_slope = t.get('ema5_slope', 0)
    if ema_above == 0: s += 0.15    # price below EMA = more oversold
    if ema_slope < 0: s += 0.1     # EMA declining = more dip
    return max(s, 0.1)

# G12: Kitchen sink intraday - everything together
def g_kitchen_intraday(t):
    s = v16b(t)
    if s <= 0:
        return 0

    # VWAP slope
    slope10 = t.get('vwap_slope_10', 0)
    if slope10 < -0.01: s += 0.1
    if slope10 > 0.02: s -= 0.15

    # MR strength
    mr = t.get('mr_strength', 0)
    if mr > 0.6: s += 0.1
    if mr < 0.3: s -= 0.1

    # Volume
    vol_surge = t.get('vol_surge_5', 0)
    if vol_surge == 1: s += 0.1

    # Consecutive below VWAP
    consec = t.get('consec_below_vwap', 0)
    if consec >= 5: s += 0.1

    return max(s, 0.1)

# G13: Asymmetric intraday penalties (like V16b approach)
def g_asym_intraday(t):
    s = v16b(t)
    if s <= 0:
        return 0

    # Heavy penalties for bad intraday conditions
    slope10 = t.get('vwap_slope_10', 0)
    if slope10 > 0.03: s -= 0.4     # VWAP rising fast = already recovering
    if slope10 < -0.03: s += 0.1    # VWAP still falling = opportunity

    mr = t.get('mr_strength', 0)
    if mr < 0.3: s -= 0.3           # weak MR signal
    if mr > 0.7: s += 0.1

    mins = t.get('mins_from_open', 100)
    if mins > 330: s -= 0.3          # last 30 mins

    return max(s, 0.1)

# G14: VIX regime
def g_vix(t):
    s = v16b(t)
    if s <= 0:
        return 0
    vix = t.get('vix', 20)
    vix_chg = t.get('vix_change', 0)
    if vix > 25: s += 0.15         # higher vol = better MR
    if vix < 14: s -= 0.2          # low vol = small moves
    if vix_chg > 2: s += 0.1      # rising VIX = panic dip
    return max(s, 0.1)

# G15: Day of week
def g_dow(t):
    s = v16b(t)
    if s <= 0:
        return 0
    dow = t.get('dow', 2)
    # Monday=0, Friday=4
    if dow == 0: s -= 0.15        # Monday gaps/continuation
    if dow == 4: s -= 0.1         # Friday position squaring
    if dow in (1, 2, 3): s += 0.05  # mid-week
    return max(s, 0.1)

# Run all grading systems
graders = [
    (v16b, "V16b (baseline)"),
    (g_vwap_slope, "G_VWAPslope (falling=good)"),
    (g_vwap_slope_rev, "G_VWAPslope_rev (rising=good)"),
    (g_momentum, "G_Momentum"),
    (g_entry_timing, "G_EntryTiming"),
    (g_volume, "G_Volume"),
    (g_mr_strength, "G_MR_Strength"),
    (g_distance, "G_Distance"),
    (g_consec, "G_ConsecBelow"),
    (g_slope_mom, "G_SlopeMom"),
    (g_today_range, "G_TodayRange"),
    (g_ema, "G_EMA"),
    (g_kitchen_intraday, "G_KitchenIntraday"),
    (g_asym_intraday, "G_AsymIntraday"),
    (g_vix, "G_VIX"),
    (g_dow, "G_DOW"),
]

results = []
for fn, name in graders:
    r = test_grading(trades, fn, name)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)

print(f"\n  {'Strategy':<30s} {'N':>5s} {'Skip':>5s} {'Sharpe':>8s} {'vs V16b':>8s} {'WR':>7s} {'PF':>6s} {'Total $':>13s} {'Avg PnL':>10s} {'MaxDD $':>11s}")
print(f"  {'-'*110}")

v16b_sharpe = next(r['sharpe'] for r in results if r['name'] == 'V16b (baseline)')
for r in results:
    improvement = (r['sharpe'] / v16b_sharpe - 1) * 100 if v16b_sharpe > 0 else 0
    sign = '+' if improvement > 0 else ''
    print(f"  {r['name']:<30s} {r['n']:>5d} {r['skipped']:>5d} {r['sharpe']:>8.3f} {sign}{improvement:>6.0f}% {r['wr']:>6.1%} {r['pf']:>6.2f} ${r['total']:>12,.0f} ${r['avg']:>9,.0f} ${r['max_dd']:>10,.0f}")

# ================================================================
# PART 6: Grid search over intraday feature weights
# ================================================================
print("\n" + "="*100)
print("  PART 6: GRID SEARCH OVER INTRADAY FEATURE WEIGHTS")
print("="*100)

# Based on results above, take the top 3-4 intraday features
# and grid search their weights added to V16b

# Use asymmetric approach: heavy penalties, light rewards
weight_options = [0, 0.1, 0.2, 0.3]
penalty_options = [0, -0.2, -0.4, -0.6]

best_combos = []
count = 0

# Features to test (will be filled based on Part 1 results, using reasonable defaults)
# VWAP slope, MR strength, volume surge, consecutive below
for w_slope in [0, 0.1, 0.15, 0.2]:
    for p_slope in [0, -0.15, -0.3, -0.5]:
        for w_mr in [0, 0.1, 0.15, 0.2]:
            for p_mr in [0, -0.15, -0.3]:
                for w_vol in [0, 0.1, 0.15]:
                    count += 1

                    def make_grader(ws, ps, wmr, pmr, wv):
                        def grader(t):
                            s = v16b(t)
                            if s <= 0:
                                return 0
                            # VWAP slope
                            slope10 = t.get('vwap_slope_10', 0)
                            if slope10 < -0.01 and ws > 0: s += ws
                            if slope10 > 0.02 and ps < 0: s += ps  # penalty
                            # MR strength
                            mr = t.get('mr_strength', 0)
                            if mr > 0.6 and wmr > 0: s += wmr
                            if mr < 0.3 and pmr < 0: s += pmr
                            # Volume surge
                            vol_surge = t.get('vol_surge_5', 0)
                            if vol_surge == 1 and wv > 0: s += wv
                            return max(s, 0.1)
                        return grader

                    fn = make_grader(w_slope, p_slope, w_mr, p_mr, w_vol)
                    r = test_grading(trades, fn, f"grid_{count}")
                    if r:
                        r['params'] = (w_slope, p_slope, w_mr, p_mr, w_vol)
                        best_combos.append(r)

best_combos.sort(key=lambda x: x['sharpe'], reverse=True)
print(f"\n  Tested {count} combinations")
print(f"\n  Top 15 grid results:")
print(f"  {'Rank':>4s} {'Sharpe':>8s} {'vs V16b':>8s} {'N':>5s} {'WR':>7s} {'PF':>6s} {'w_slope':>8s} {'p_slope':>8s} {'w_mr':>8s} {'p_mr':>8s} {'w_vol':>8s}")
print(f"  {'-'*85}")
for i, r in enumerate(best_combos[:15]):
    improvement = (r['sharpe'] / v16b_sharpe - 1) * 100
    sign = '+' if improvement > 0 else ''
    ws, ps, wmr, pmr, wv = r['params']
    print(f"  {i+1:>4d} {r['sharpe']:>8.3f} {sign}{improvement:>6.0f}% {r['n']:>5d} {r['wr']:>6.1%} {r['pf']:>6.2f} {ws:>8.2f} {ps:>8.2f} {wmr:>8.2f} {pmr:>8.2f} {wv:>8.2f}")

# ================================================================
# PART 7: Yearly stability check on top candidates
# ================================================================
print("\n" + "="*100)
print("  PART 7: YEARLY STABILITY CHECK")
print("="*100)

def yearly_breakdown(trades, grade_fn, name):
    by_year = defaultdict(list)
    for t in trades:
        mult = grade_fn(t)
        if mult <= 0:
            continue
        yr = t['date'][:4]
        by_year[yr].append(t['pnl'] * mult)

    print(f"\n  {name}:")
    neg_years = 0
    for yr in sorted(by_year.keys()):
        yp = by_year[yr]
        yt = sum(yp)
        n = len(yp)
        wr = sum(1 for p in yp if p > 0) / n if n else 0
        std = np.std(yp, ddof=1) if n > 1 else 1
        sh = np.mean(yp) / std * np.sqrt(n) if std > 0 else 0
        if yt < 0:
            neg_years += 1
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={wr:.1%}  Sharpe={sh:.3f}")
    return neg_years

# Check V16b and top grid results
yearly_breakdown(trades, v16b, "V16b (baseline)")

if best_combos:
    # Reconstruct top 3 grid graders
    for i in range(min(3, len(best_combos))):
        bc = best_combos[i]
        ws, ps, wmr, pmr, wv = bc['params']
        fn = make_grader(ws, ps, wmr, pmr, wv)
        yearly_breakdown(trades, fn, f"Grid #{i+1} (S={bc['sharpe']:.3f}, w={ws}/{ps}/{wmr}/{pmr}/{wv})")

print("\n" + "="*100)
print("  SUMMARY")
print("="*100)
print(f"\n  V16b baseline Sharpe: {v16b_sharpe:.3f}")
if best_combos:
    top = best_combos[0]
    improvement = (top['sharpe'] / v16b_sharpe - 1) * 100
    print(f"  Best grid Sharpe: {top['sharpe']:.3f} ({improvement:+.0f}% vs V16b)")
    ws, ps, wmr, pmr, wv = top['params']
    print(f"  Best params: slope_reward={ws}, slope_penalty={ps}, mr_reward={wmr}, mr_penalty={pmr}, vol_reward={wv}")
print(f"\n  Key insight: each trade should get a GRADE based on the confluence of signals.")
print(f"  Higher grade = larger position. Lower grade = smaller or skip.")

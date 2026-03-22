#!/usr/bin/env python3
"""
Final weighted grade system - drop noise features, optimize.
Keep only the 7 features that survived ablation:
  today_range, vol_ratio, prior_day_body, trend, return_2d,
  prior_day_range, sma_slope
"""

import json
import numpy as np
from collections import defaultdict

with open('kite_deep_features.json') as f:
    trades = json.load(f)

trades = [t for t in trades if t.get('mins_from_open', 0) >= 10]
print(f"Trades (post-10m): {len(trades)}")

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
# Scoring functions (same as before, just the 7 that matter)
# ================================================================

def s_today_range(t):
    r = t.get('today_range_pct', 1.0)
    if r < 0.4: return 1.0
    if r < 0.6: return 0.7
    if r < 0.8: return 0.3
    if r < 1.0: return 0.0
    if r < 1.5: return -0.5
    if r < 2.0: return -0.8
    return -1.0

def s_vol_ratio(t):
    v = t.get('daily_vol_ratio', 1.0)
    if v < 0.7: return 0.5
    if v < 1.2: return 0.0
    if v < 1.5: return -0.3
    return -1.0

def s_prior_day_body(t):
    b = t.get('prior_day_body_pct', 0.4)
    if b > 0.8: return 1.0
    if b > 0.5: return 0.5
    if b > 0.35: return 0.0
    if b > 0.2: return -0.5
    return -1.0

def s_trend(t):
    return 1.0 if t.get('daily_sma5_above_sma20', 0) == 1 else -1.0

def s_return_2d(t):
    r = t.get('return_2d', 0)
    if r < -2.0: return 1.0
    if r < -1.0: return 0.5
    if r < 0.5: return 0.0
    if r < 1.2: return -0.5
    return -1.0

def s_prior_day_range(t):
    r = t.get('prior_day_range_pct', 1.0)
    if r > 1.8: return 1.0
    if r > 1.2: return 0.5
    if r > 0.8: return 0.0
    if r > 0.5: return -0.5
    return -1.0

def s_sma_slope(t):
    s = t.get('daily_sma5_slope', 0)
    if s > 1.0: return 1.0
    if s > 0.3: return 0.5
    if s > -0.3: return 0.0
    if s > -1.0: return -0.5
    return -1.0

# 7 features with correlation-based weights (from ablation)
SCORERS_7 = [
    ('today_range',      s_today_range,      1.925),  # correlation weight
    ('vol_ratio',        s_vol_ratio,        1.705),
    ('prior_day_body',   s_prior_day_body,   1.682),
    ('prior_day_range',  s_prior_day_range,  1.504),
    ('return_2d',        s_return_2d,        1.108),
    ('trend',            s_trend,            1.046),
    ('sma_slope',        s_sma_slope,        0.870),
]

# ================================================================
# Grid search: scale, asymmetry, and weight variations
# ================================================================
print("="*100)
print("  GRID SEARCH: 7-FEATURE WEIGHTED GRADE")
print("="*100)

best = []
for scale in [0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]:
    for asym in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        # Correlation-weighted
        def make_fn(sc, asy):
            def fn(t):
                total = 0
                for name, scorer_fn, weight in SCORERS_7:
                    s = scorer_fn(t) * weight
                    if s < 0:
                        s *= asy
                    total += s
                mult = 1.0 + total * sc
                return max(mult, 0.1)
            return fn
        fn = make_fn(scale, asym)
        r = test_grading(trades, fn, f"s={scale}_a={asym}")
        if r:
            r['params'] = (scale, asym)
            best.append(r)

        # Also test equal weights
        def make_fn_eq(sc, asy):
            def fn(t):
                total = 0
                for name, scorer_fn, _ in SCORERS_7:
                    s = scorer_fn(t)
                    if s < 0:
                        s *= asy
                    total += s
                mult = 1.0 + total * sc
                return max(mult, 0.1)
            return fn
        fn2 = make_fn_eq(scale, asym)
        r2 = test_grading(trades, fn2, f"eq_s={scale}_a={asym}")
        if r2:
            r2['params'] = (scale, asym, 'equal')
            best.append(r2)

best.sort(key=lambda x: x['sharpe'], reverse=True)

baseline_sh = 0.822
print(f"\n  Tested {len(best)} combos")
print(f"\n  Top 20:")
print(f"  {'Rank':>4s} {'Sharpe':>8s} {'vs Flat':>8s} {'N':>5s} {'PF':>6s} {'Scale':>6s} {'Asym':>5s} {'Total $':>12s} {'MaxDD $':>10s}")
print(f"  {'-'*75}")
for i, r in enumerate(best[:20]):
    p = r['params']
    sc, asy = p[0], p[1]
    wt = p[2] if len(p) > 2 else 'corr'
    imp = (r['sharpe'] / baseline_sh - 1) * 100
    tag = 'eq' if wt == 'equal' else 'cr'
    print(f"  {i+1:>4d} {r['sharpe']:>8.3f} {imp:>+7.0f}% {r['n']:>5d} {r['pf']:>6.2f} {sc:>6.2f} {asy:>5.1f} ${r['total']:>11,.0f} ${r['max_dd']:>9,.0f} {tag}")

# ================================================================
# Yearly stability of top 3
# ================================================================
print("\n" + "="*100)
print("  YEARLY STABILITY")
print("="*100)

# V16b for reference
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

yearly_breakdown(trades, v16b, "V16b (if/else reference)")

for i in range(min(3, len(best))):
    bc = best[i]
    p = bc['params']
    sc, asy = p[0], p[1]
    wt = p[2] if len(p) > 2 else 'corr'
    if wt == 'equal':
        fn = make_fn_eq(sc, asy)
    else:
        fn = make_fn(sc, asy)
    yearly_breakdown(trades, fn, f"#{i+1} (S={bc['sharpe']:.3f}, scale={sc}, asym={asy}, {wt})")

# ================================================================
# Score distribution of best
# ================================================================
print("\n" + "="*100)
print("  BEST SYSTEM DETAILS")
print("="*100)

if best:
    bc = best[0]
    p = bc['params']
    sc, asy = p[0], p[1]
    wt = p[2] if len(p) > 2 else 'corr'
    if wt == 'equal':
        fn = make_fn_eq(sc, asy)
    else:
        fn = make_fn(sc, asy)

    mults = [fn(t) for t in trades]
    print(f"\n  Scale={sc}, Asymmetry={asy}x, Weights={'equal' if wt == 'equal' else 'correlation'}")
    print(f"  Sharpe: {bc['sharpe']:.3f}, PF: {bc['pf']:.2f}")
    print(f"\n  Multiplier stats: min={min(mults):.3f} max={max(mults):.3f} mean={np.mean(mults):.3f} median={np.median(mults):.3f}")

    # Show weight table
    print(f"\n  {'Feature':<20s} {'RawWeight':>10s} {'EffUp':>8s} {'EffDown':>10s} {'Contrib%':>9s}")
    print(f"  {'-'*60}")
    total_w = sum(w for _, _, w in SCORERS_7) if wt != 'equal' else len(SCORERS_7)
    for name, scorer_fn, weight in SCORERS_7:
        w = weight if wt != 'equal' else 1.0
        eff_up = w * sc
        eff_down = w * sc * asy
        pct = w / total_w * 100
        print(f"  {name:<20s} {w:>10.3f} {eff_up:>+8.4f} {eff_down:>-10.4f} {pct:>8.1f}%")

    # Quintile performance
    pnls_by_mult = sorted([(fn(t), t['pnl']) for t in trades], key=lambda x: x[0])
    n = len(pnls_by_mult)
    q_size = n // 5
    print(f"\n  {'Quintile':<18s} {'MultRange':<18s} {'N':>4s} {'WR':>7s} {'AvgPnL':>10s} {'Sharpe':>8s}")
    print(f"  {'-'*70}")
    for q in range(5):
        start = q * q_size
        end = (q + 1) * q_size if q < 4 else n
        group = pnls_by_mult[start:end]
        gm = [m for m, _ in group]
        gp = [p for _, p in group]
        wr = sum(1 for p in gp if p > 0) / len(gp)
        std = np.std(gp, ddof=1) if len(gp) > 1 else 1
        sh = np.mean(gp) / std * np.sqrt(len(gp)/4.2) if std > 0 else 0
        print(f"  Q{q+1} ({min(gm):>5.2f} - {max(gm):>5.2f}) {len(group):>4d} {wr:>6.1%} ${np.mean(gp):>9,.0f} {sh:>8.3f}")

    # ================================================================
    # Print the KITE-ready formula
    # ================================================================
    print("\n" + "="*100)
    print("  KITE-READY FORMULA")
    print("="*100)
    print(f"""
  def compute_trade_grade(self):
      \"\"\"7-feature weighted grade. Returns sizing multiplier.\"\"\"
      score = 0.0

      # --- Prior-day features (from CSV) ---
      # prior_day_range (weight {SCORERS_7[3][2]:.3f})
      r = self.today_prior_day_range
      if r > 1.8: s = 1.0
      elif r > 1.2: s = 0.5
      elif r > 0.8: s = 0.0
      elif r > 0.5: s = -0.5
      else: s = -1.0
      score += s * {SCORERS_7[3][2]:.3f} * ({asy} if s < 0 else 1.0)

      # prior_day_body (weight {SCORERS_7[2][2]:.3f})
      b = self.today_prior_day_body
      if b > 0.8: s = 1.0
      elif b > 0.5: s = 0.5
      elif b > 0.35: s = 0.0
      elif b > 0.2: s = -0.5
      else: s = -1.0
      score += s * {SCORERS_7[2][2]:.3f} * ({asy} if s < 0 else 1.0)

      # return_2d (weight {SCORERS_7[4][2]:.3f})
      r2 = self.today_return_2d
      if r2 < -2.0: s = 1.0
      elif r2 < -1.0: s = 0.5
      elif r2 < 0.5: s = 0.0
      elif r2 < 1.2: s = -0.5
      else: s = -1.0
      score += s * {SCORERS_7[4][2]:.3f} * ({asy} if s < 0 else 1.0)

      # trend (weight {SCORERS_7[5][2]:.3f})
      s = 1.0 if self.today_sma5_above_sma20 else -1.0
      score += s * {SCORERS_7[5][2]:.3f} * ({asy} if s < 0 else 1.0)

      # sma_slope (weight {SCORERS_7[6][2]:.3f})
      sl = self.today_sma_slope
      if sl > 1.0: s = 1.0
      elif sl > 0.3: s = 0.5
      elif sl > -0.3: s = 0.0
      elif sl > -1.0: s = -0.5
      else: s = -1.0
      score += s * {SCORERS_7[6][2]:.3f} * ({asy} if s < 0 else 1.0)

      # vol_ratio (weight {SCORERS_7[1][2]:.3f})
      v = self.today_vol_ratio
      if v < 0.7: s = 0.5
      elif v < 1.2: s = 0.0
      elif v < 1.5: s = -0.3
      else: s = -1.0
      score += s * {SCORERS_7[1][2]:.3f} * ({asy} if s < 0 else 1.0)

      # --- Intraday feature (computed at entry time) ---
      # today_range (weight {SCORERS_7[0][2]:.3f})
      tr = self.today_range_pct  # (session_high - session_low) / price * 100
      if tr < 0.4: s = 1.0
      elif tr < 0.6: s = 0.7
      elif tr < 0.8: s = 0.3
      elif tr < 1.0: s = 0.0
      elif tr < 1.5: s = -0.5
      elif tr < 2.0: s = -0.8
      else: s = -1.0
      score += s * {SCORERS_7[0][2]:.3f} * ({asy} if s < 0 else 1.0)

      # Convert total score to multiplier
      mult = 1.0 + score * {sc}
      return max(mult, 0.1)
""")

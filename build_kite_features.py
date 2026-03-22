#!/usr/bin/env python3
"""
Build per-date feature CSV for KITE strategy.
All features are PRIOR-DAY (no hindsight) - known before 9:30 open.
Also creates filtered date lists for each strategy variant.
"""

import sys, os, json
import numpy as np
import pandas as pd

sys.path.insert(0, 'spy_fade_strategy')
from data_fetcher import PolygonFetcher

fetcher = PolygonFetcher()
daily = fetcher.get_daily_bars('SPY', '2021-06-01', '2026-03-22')
daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
daily = daily.sort_values('date_obj').reset_index(drop=True)

dates = [d.strftime('%Y-%m-%d') for d in daily['date_obj']]
opens = daily['open'].values.astype(float)
highs = daily['high'].values.astype(float)
lows = daily['low'].values.astype(float)
closes = daily['close'].values.astype(float)
volumes = daily['volume'].values.astype(float)

# Build feature rows
rows = []
for i in range(21, len(dates)):
    d = dates[i]

    # Gap
    gap_pct = (opens[i] - closes[i-1]) / closes[i-1] * 100

    # Prior day features
    prior_day_range = (highs[i-1] - lows[i-1]) / closes[i-1] * 100
    prior_day_body = abs(closes[i-1] - opens[i-1]) / closes[i-1] * 100
    prior_day_return = (closes[i-1] - closes[i-2]) / closes[i-2] * 100

    # 2-day return (prior 2 days)
    return_2d = (closes[i-1] - closes[i-3]) / closes[i-3] * 100

    # Prior week range
    week_high = max(highs[i-5:i])
    week_low = min(lows[i-5:i])
    prior_week_range = (week_high - week_low) / closes[i-1] * 100

    # 3-day return
    return_3d = (closes[i-1] - closes[i-4]) / closes[i-4] * 100

    # SMA5 vs SMA20
    sma5 = np.mean(closes[i-5:i])
    sma20 = np.mean(closes[i-20:i])
    sma5_above_sma20 = 1 if sma5 > sma20 else 0

    # SMA5 slope (change in SMA5 over last 5 days)
    sma5_prev = np.mean(closes[i-10:i-5])
    sma5_slope = (sma5 - sma5_prev) / sma5 * 100

    # Daily volume ratio: yesterday's volume / 20-day avg volume
    avg_vol_20 = np.mean(volumes[i-20:i])
    daily_vol_ratio = volumes[i-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0

    # Composite v1 sizing multiplier
    score_v1 = 1.0
    if prior_day_range > 1.43: score_v1 += 0.3
    if prior_day_range < 0.80: score_v1 -= 0.3
    if prior_day_body > 0.79: score_v1 += 0.3
    if prior_day_body < 0.23: score_v1 -= 0.3
    if return_2d < -1.49: score_v1 += 0.2
    if return_2d > 1.18: score_v1 -= 0.3
    if sma5_above_sma20 == 1: score_v1 += 0.15
    score_v1 = max(score_v1, 0.3)

    # Composite v2 sizing multiplier
    score_v2 = 1.0
    if prior_day_range > 1.43: score_v2 += 0.4
    if prior_day_range < 0.80: score_v2 -= 0.4
    if prior_day_body > 0.79: score_v2 += 0.3
    if prior_day_body < 0.23: score_v2 -= 0.4
    if return_2d < -1.49: score_v2 += 0.3
    if return_2d > 1.18: score_v2 -= 0.4
    if sma5_above_sma20 == 1: score_v2 += 0.2
    if prior_week_range > 5.32: score_v2 += 0.2
    score_v2 = max(score_v2, 0.2)

    # F6 sizing: 1.67x if wide prior, 1.2x if uptrend else 0.8x
    f6_base = 1.67 if prior_day_range > 1.43 else 1.0
    f6_trend = 1.2 if sma5_above_sma20 == 1 else 0.8
    f6_mult = f6_base * f6_trend

    # V16 sizing: asymmetric heavy penalty, optimized thresholds
    score_v16 = 1.0
    if prior_day_range > 1.20: score_v16 += 0.2
    if prior_day_range < 0.80: score_v16 -= 0.6
    if prior_day_body > 0.50: score_v16 += 0.2
    if prior_day_body < 0.35: score_v16 -= 0.6
    if return_2d < -1.49: score_v16 += 0.2
    if return_2d > 1.18: score_v16 -= 0.6
    if sma5_above_sma20 == 1: score_v16 += 0.3
    else: score_v16 -= 0.3
    score_v16 = max(score_v16, 0.1)

    # V9 base sizing: v2_opt_thresh + slope (velocity added at runtime)
    score_v9_base = 1.0
    if prior_day_range > 1.20: score_v9_base += 0.4
    if prior_day_range < 0.80: score_v9_base -= 0.5
    if prior_day_body > 0.50: score_v9_base += 0.4
    if prior_day_body < 0.35: score_v9_base -= 0.5
    if return_2d < -1.49: score_v9_base += 0.2
    if return_2d > 1.18: score_v9_base -= 0.5
    if sma5_above_sma20 == 1: score_v9_base += 0.3
    # slope adjustment (prior-day feature)
    if sma5_slope > 0.5: score_v9_base += 0.15
    if sma5_slope < -0.5: score_v9_base -= 0.15
    score_v9_base = max(score_v9_base, 0.2)

    rows.append({
        'date': d,
        'gap_pct': round(gap_pct, 4),
        'prior_day_range': round(prior_day_range, 4),
        'prior_day_body': round(prior_day_body, 4),
        'return_2d': round(return_2d, 4),
        'sma5_above_sma20': sma5_above_sma20,
        'prior_week_range': round(prior_week_range, 4),
        'return_3d': round(return_3d, 4),
        'sma5_slope': round(sma5_slope, 4),
        'score_v1': round(score_v1, 4),
        'score_v2': round(score_v2, 4),
        'f6_mult': round(f6_mult, 4),
        'score_v16': round(score_v16, 4),
        'score_v9_base': round(score_v9_base, 4),
        'daily_vol_ratio': round(daily_vol_ratio, 4),
    })

# Write CSV
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kite_daily_features.csv')
with open(csv_path, 'w') as f:
    header = 'date,gap_pct,prior_day_range,prior_day_body,return_2d,sma5_above_sma20,prior_week_range,return_3d,sma5_slope,score_v1,score_v2,f6_mult,score_v16,score_v9_base,daily_vol_ratio'
    f.write(header + '\n')
    for r in rows:
        line = f"{r['date']},{r['gap_pct']},{r['prior_day_range']},{r['prior_day_body']},{r['return_2d']},{r['sma5_above_sma20']},{r['prior_week_range']},{r['return_3d']},{r['sma5_slope']},{r['score_v1']},{r['score_v2']},{r['f6_mult']},{r['score_v16']},{r['score_v9_base']},{r['daily_vol_ratio']}"
        f.write(line + '\n')

print(f"Wrote {len(rows)} rows to {csv_path}")

# Now create filtered date lists for each strategy
# All strategies use gap-filtered dates as base
all_dates_file = []
for i in range(21, len(dates)):
    gap_pct = (opens[i] - closes[i-1]) / closes[i-1] * 100
    if gap_pct >= -1.0 and dates[i] >= '2022-01-01':
        all_dates_file.append(dates[i])

print(f"\nGap-filtered dates (base): {len(all_dates_file)}")

# G1/G3: gap filter only (sizing handled in code)
# -> use standard gap-filtered batch files (strat_d_XX.txt already exist)
print(f"G1/G3: {len(all_dates_file)} dates (gap filter only, sizing in code)")

# G4: gap + TOD 30-45m skip (TOD handled in code, dates same as G1)
print(f"G4: {len(all_dates_file)} dates (gap filter, TOD skip in code)")

# F6: gap + skip return_2d > 1.18 + skip prior_day_body < 0.23 + TOD skip in code
f6_dates = []
for d in all_dates_file:
    r = next((x for x in rows if x['date'] == d), None)
    if r is None:
        continue
    if r['return_2d'] > 1.18:
        continue
    if r['prior_day_body'] < 0.23:
        continue
    f6_dates.append(d)

print(f"F6: {len(f6_dates)} dates (gap + 2d>1.18 + body<0.23 filtered)")

# Write F6 batch files
batch_size = 25
for i in range(0, len(f6_dates), batch_size):
    batch = f6_dates[i:i+batch_size]
    batch_num = i // batch_size
    with open(f'strat_f6_{batch_num:02d}.txt', 'w') as f:
        f.write(','.join(batch))

f6_batches = (len(f6_dates) + batch_size - 1) // batch_size
print(f"  Created {f6_batches} batch files (strat_f6_XX.txt)")

# Save metadata
meta = {
    'g1_g3_g4_batches': 40,  # same as strat_d_XX.txt
    'f6_batches': f6_batches,
    'g1_g3_dates': len(all_dates_file),
    'f6_dates': len(f6_dates),
}
with open('strategy_batch_meta.json', 'w') as f:
    json.dump(meta, f, indent=2)

print(f"\nDone. Upload kite_daily_features.csv to KITE, then submit backtests.")

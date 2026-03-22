#!/usr/bin/env python3
"""Debug why instant flush trades differ between local model and KITE."""

import json, csv, sys, os
import numpy as np
import pandas as pd
from datetime import datetime, time as dt_time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spy_fade_strategy'))
from data_fetcher import PolygonFetcher

# Load enriched KITE data
with open('kite_d2_enriched.json') as f:
    enriched = json.load(f)

# Fast trades on KITE
fast_trades = [t for t in enriched if t['velocity'] <= 4]
print(f'Fast velocity trades (0-4 bars) on KITE: {len(fast_trades)}')
print()
print(f'{"Date":<12s} {"Vel":>3s} {"MFO":>4s} {"Entry$":>9s} {"Exit$":>9s} {"Ret%":>8s} {"Shares":>7s} {"Notional":>12s} {"P&L":>10s} {"Hold":>6s}')
print('-' * 95)
for t in sorted(fast_trades, key=lambda x: x['date']):
    print(f'{t["date"]:<12s} {t["velocity"]:>3d} {t["mins_from_open"]:>4d} '
          f'${t["entry_price"]:>8.2f} ${t["exit_price"]:>8.2f} {t["ret_pct"]:>7.4f}% '
          f'{t["shares"]:>7,d} ${t["notional"]:>11,.0f} ${t["pnl"]:>9,.0f} {t["hold_mins"]:>5.1f}m')

print()
wins = [t for t in fast_trades if t['pnl'] > 0]
losses = [t for t in fast_trades if t['pnl'] <= 0]
print(f'Winners: {len(wins)}/{len(fast_trades)}')
if wins:
    print(f'Avg win:  ${sum(t["pnl"] for t in wins)/len(wins):,.0f}')
if losses:
    print(f'Avg loss: ${sum(t["pnl"] for t in losses)/len(losses):,.0f}')

# Implied risk from position size
print()
print('IMPLIED RISK BUDGETS:')
STOP_PCT = 1.0
for t in sorted(fast_trades, key=lambda x: x['date']):
    risk_implied = t['shares'] * t['entry_price'] * STOP_PCT / 100
    print(f'  {t["date"]} vel={t["velocity"]} notional=${t["notional"]:>11,.0f} '
          f'implied_risk=${risk_implied:>9,.0f}')

# Now let's look at WHAT the local model would have produced on these same dates
# using Polygon minute bars
print()
print('=' * 80)
print('  LOCAL vs KITE: Same dates, same velocity')
print('=' * 80)

fetcher = PolygonFetcher()
fast_dates = sorted(set(t['date'] for t in fast_trades))
results_dict = fetcher.get_intraday_bars_bulk('SPY', fast_dates)

RTH_START = dt_time(9, 30)
RTH_END = dt_time(16, 0)
ENTRY_PCT = 0.4
TARGET_PCT = 0.75
TIME_BARS = 15

print()
print(f'{"Date":<12s} {"Vel":>3s} | {"KITE Entry":>10s} {"KITE Exit":>10s} {"KITE Ret":>8s} | '
      f'{"Local Entry":>11s} {"Local Exit":>10s} {"Local Ret":>9s} | {"Diff":>7s}')
print('-' * 105)

for date_str in fast_dates:
    if date_str not in results_dict:
        continue

    day_df = results_dict[date_str].copy()
    day_df['ts'] = pd.to_datetime(day_df['timestamp'])
    day_df['tm'] = day_df['ts'].dt.time
    day_df = day_df[(day_df['tm'] >= RTH_START) & (day_df['tm'] < RTH_END)].copy()
    day_df.sort_values('ts', inplace=True)
    day_df.reset_index(drop=True, inplace=True)

    if len(day_df) < 10:
        continue

    highs = day_df['high'].values.astype(np.float64)
    lows = day_df['low'].values.astype(np.float64)
    closes = day_df['close'].values.astype(np.float64)
    volumes = day_df['volume'].values.astype(np.float64)

    tp = (highs + lows + closes) / 3.0
    cum_tpv = np.cumsum(tp * volumes)
    cum_v = np.cumsum(volumes)
    vwap = np.where(cum_v > 0, cum_tpv / cum_v, 0.0)

    # Find local model entry
    eod_idx = len(day_df)
    for i in range(len(day_df)):
        t_val = day_df['tm'].iloc[i]
        if t_val >= dt_time(15, 55):
            eod_idx = i
            break

    for i in range(5, eod_idx):
        v = vwap[i]
        if v <= 0:
            continue
        threshold = v * (1.0 - ENTRY_PCT / 100.0)
        if lows[i] <= threshold:
            entry_price_local = threshold

            # Compute velocity
            velocity = i
            for j in range(i, -1, -1):
                if closes[j] >= vwap[j]:
                    velocity = i - j
                    break

            if velocity > 4:
                continue  # only looking at fast trades

            # Simulate exit (local model)
            end = min(eod_idx + 5, len(day_df))
            target = entry_price_local * (1 + TARGET_PCT / 100)
            stop = entry_price_local * (1 - STOP_PCT / 100)

            exit_price_local = closes[min(i + TIME_BARS, len(day_df) - 1)]
            for bi in range(1, min(TIME_BARS + 1, end - i)):
                if lows[i + bi] <= stop:
                    exit_price_local = stop
                    break
                if highs[i + bi] >= target:
                    exit_price_local = target
                    break
            else:
                if i + TIME_BARS < len(day_df):
                    exit_price_local = closes[i + TIME_BARS]

            local_ret = (exit_price_local - entry_price_local) / entry_price_local * 100

            # Find matching KITE trade
            kite_match = [t for t in fast_trades if t['date'] == date_str]
            if kite_match:
                kt = kite_match[0]
                kite_ret = kt['ret_pct']
                diff = kite_ret - local_ret
                print(f'{date_str:<12s} {velocity:>3d} | '
                      f'${kt["entry_price"]:>9.2f} ${kt["exit_price"]:>9.2f} {kite_ret:>7.4f}% | '
                      f'${entry_price_local:>10.2f} ${exit_price_local:>9.2f} {local_ret:>8.4f}% | '
                      f'{diff:>+6.4f}%')
            break

# Also: count how many fast-velocity signals the LOCAL model finds vs KITE
print()
print('=' * 80)
print('  TOTAL FAST SIGNAL COUNT: Local vs KITE')
print('=' * 80)

# Reload ALL dates for local signal count
daily = fetcher.get_daily_bars('SPY', '2022-01-01', '2026-03-12')
daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
daily_sorted = daily.sort_values('date_obj')
gap_map = {}
for i in range(1, len(daily_sorted)):
    d = daily_sorted['date_obj'].iloc[i]
    prev_close = daily_sorted['close'].iloc[i-1]
    today_open = daily_sorted['open'].iloc[i]
    gap_map[d.strftime('%Y-%m-%d')] = (today_open - prev_close) / prev_close * 100

all_dates = [d.strftime('%Y-%m-%d') for d in sorted(daily_sorted['date_obj'].tolist())]
# filter gap
all_dates_filtered = [d for d in all_dates if gap_map.get(d, 0) >= -1.0]

all_dict = fetcher.get_intraday_bars_bulk('SPY', all_dates_filtered)

local_fast_count = 0
local_fast_dates = []
for date_str in sorted(all_dict.keys()):
    day_df = all_dict[date_str].copy()
    day_df['ts'] = pd.to_datetime(day_df['timestamp'])
    day_df['tm'] = day_df['ts'].dt.time
    day_df = day_df[(day_df['tm'] >= RTH_START) & (day_df['tm'] < RTH_END)].copy()
    day_df.sort_values('ts', inplace=True)
    day_df.reset_index(drop=True, inplace=True)

    if len(day_df) < 10:
        continue

    h = day_df['high'].values.astype(np.float64)
    l = day_df['low'].values.astype(np.float64)
    c = day_df['close'].values.astype(np.float64)
    vol = day_df['volume'].values.astype(np.float64)

    tp2 = (h + l + c) / 3.0
    cv2 = np.cumsum(tp2 * vol)
    cvol2 = np.cumsum(vol)
    vw2 = np.where(cvol2 > 0, cv2 / cvol2, 0.0)

    eod2 = len(day_df)
    for ii in range(len(day_df)):
        if day_df['tm'].iloc[ii] >= dt_time(15, 55):
            eod2 = ii
            break

    for ii in range(5, eod2):
        v2 = vw2[ii]
        if v2 <= 0:
            continue
        thr2 = v2 * (1.0 - ENTRY_PCT / 100.0)
        if l[ii] <= thr2:
            vel2 = ii
            for jj in range(ii, -1, -1):
                if c[jj] >= vw2[jj]:
                    vel2 = ii - jj
                    break
            if vel2 <= 4:
                local_fast_count += 1
                local_fast_dates.append(date_str)
            break

kite_fast_dates = sorted(set(t['date'] for t in fast_trades))
print(f'  Local model fast signals (vel 0-4): {local_fast_count}')
print(f'  KITE fast trades (vel 0-4):         {len(fast_trades)}')
print(f'  Overlap dates: {len(set(local_fast_dates) & set(kite_fast_dates))}')
print(f'  Local-only dates: {len(set(local_fast_dates) - set(kite_fast_dates))}')
print(f'  KITE-only dates: {len(set(kite_fast_dates) - set(local_fast_dates))}')

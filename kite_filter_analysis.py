#!/usr/bin/env python3
"""
Rebuild velocity/TOD/gap filter analysis using KITE execution data.
No local fill assumptions - everything comes from actual KITE trades.
"""

import csv, sys, os, json
import numpy as np
import pandas as pd
from datetime import datetime, time as dt_time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spy_fade_strategy'))
from data_fetcher import PolygonFetcher

# ---------------------------------------------------------------
# 1. Load KITE v2 trades
# ---------------------------------------------------------------
kite_trades = []
with open('kite_strategy_d2_trades.csv') as f:
    for row in csv.DictReader(f):
        kite_trades.append(row)

print(f'Loaded {len(kite_trades)} KITE v2 trades')

# ---------------------------------------------------------------
# 2. Load Polygon minute data to compute velocity for each trade
# ---------------------------------------------------------------
fetcher = PolygonFetcher()
daily = fetcher.get_daily_bars('SPY', '2022-01-01', '2026-03-12')
daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
daily_sorted = daily.sort_values('date_obj')

gap_map = {}
for i in range(1, len(daily_sorted)):
    d = daily_sorted['date_obj'].iloc[i]
    prev_close = daily_sorted['close'].iloc[i-1]
    today_open = daily_sorted['open'].iloc[i]
    gap_map[d.strftime('%Y-%m-%d')] = (today_open - prev_close) / prev_close * 100

trade_dates = sorted(set(t['entry_time'][:10] for t in kite_trades))
print(f'Fetching minute data for {len(trade_dates)} trade dates...')
results_dict = fetcher.get_intraday_bars_bulk('SPY', trade_dates)
print(f'Got minute data for {len(results_dict)} dates')

# ---------------------------------------------------------------
# 3. Enrich each KITE trade with velocity, TOD, gap
# ---------------------------------------------------------------
RTH_START = dt_time(9, 30)
RTH_END = dt_time(16, 0)

enriched = []
for t in kite_trades:
    date_str = t['entry_time'][:10]
    entry_dt = datetime.strptime(t['entry_time'], '%Y-%m-%d %H:%M:%S.%f')
    exit_dt = datetime.strptime(t['exit_time'], '%Y-%m-%d %H:%M:%S.%f')

    entry_price = float(t['entry_price'])
    exit_price = float(t['exit_price'])
    shares = abs(int(float(t['entry_shares'])))
    pnl = float(t['mtm_pl'])
    notional = shares * entry_price
    ret_pct = (exit_price - entry_price) / entry_price * 100
    hold_mins = (exit_dt - entry_dt).total_seconds() / 60
    mins_from_open = (entry_dt.hour - 9) * 60 + (entry_dt.minute - 30)
    gap = gap_map.get(date_str, 0)

    # Velocity from Polygon minute bars
    velocity = 999
    if date_str in results_dict:
        day_df = results_dict[date_str].copy()
        day_df['ts'] = pd.to_datetime(day_df['timestamp'])
        day_df['tm'] = day_df['ts'].dt.time
        day_df = day_df[(day_df['tm'] >= RTH_START) & (day_df['tm'] < RTH_END)].copy()
        day_df.sort_values('ts', inplace=True)
        day_df.reset_index(drop=True, inplace=True)

        if len(day_df) >= 5:
            highs = day_df['high'].values.astype(np.float64)
            lows = day_df['low'].values.astype(np.float64)
            closes = day_df['close'].values.astype(np.float64)
            volumes = day_df['volume'].values.astype(np.float64)

            tp = (highs + lows + closes) / 3.0
            cum_tpv = np.cumsum(tp * volumes)
            cum_v = np.cumsum(volumes)
            vwap = np.where(cum_v > 0, cum_tpv / cum_v, 0.0)

            # Find bar closest to KITE entry time
            entry_bar = len(day_df) - 1
            for idx in range(len(day_df)):
                bar_time = day_df['ts'].iloc[idx]
                if (bar_time.hour > entry_dt.hour or
                    (bar_time.hour == entry_dt.hour and bar_time.minute >= entry_dt.minute)):
                    entry_bar = idx
                    break

            # Velocity: bars since close was last at or above VWAP
            velocity = entry_bar  # default: been below entire session
            for j in range(entry_bar, -1, -1):
                if closes[j] >= vwap[j]:
                    velocity = entry_bar - j
                    break

    enriched.append({
        'date': date_str,
        'entry_time': t['entry_time'],
        'entry_price': entry_price,
        'exit_price': exit_price,
        'pnl': pnl,
        'ret_pct': ret_pct,
        'shares': shares,
        'notional': notional,
        'hold_mins': hold_mins,
        'mins_from_open': mins_from_open,
        'velocity': velocity,
        'gap_pct': gap,
        'dow': entry_dt.weekday(),
        'year': entry_dt.year,
        'fees': abs(float(t.get('entry_fees', 0) or 0)) + abs(float(t.get('exit_fees', 0) or 0)),
    })

print(f'Enriched {len(enriched)} trades')


# ---------------------------------------------------------------
# 4. Analysis helper
# ---------------------------------------------------------------
def analyze(trades_list, label=''):
    if len(trades_list) < 3:
        return None
    pnls = [t['pnl'] for t in trades_list]
    n = len(pnls)
    avg = np.mean(pnls)
    std = np.std(pnls, ddof=1)
    wr = sum(1 for p in pnls if p > 0) / n
    sharpe = avg / std * np.sqrt(n / 4.2) if std > 1e-10 else 0
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 99.9
    avg_ret = np.mean([t['ret_pct'] for t in trades_list])
    return {
        'label': label, 'n': n, 'sharpe': round(sharpe, 3),
        'wr': round(wr * 100, 1), 'pf': round(pf, 2),
        'avg_pnl': round(avg, 0), 'avg_ret': round(avg_ret, 4),
        'total': round(sum(pnls), 0)
    }


def print_table(rows, header_label='Category'):
    hdr = f'  {header_label:<30s} {"N":>5s} {"Sharpe":>8s} {"WR":>7s} {"PF":>7s} {"Avg P&L":>10s} {"Avg Ret%":>9s} {"Total $":>12s}'
    print(hdr)
    print('  ' + '-' * len(hdr.strip()))
    for r in rows:
        if r:
            print(f'  {r["label"]:<30s} {r["n"]:>5d} {r["sharpe"]:>8.3f} {r["wr"]:>6.1f}% {r["pf"]:>7.2f} ${r["avg_pnl"]:>9,.0f} {r["avg_ret"]:>8.4f}% ${r["total"]:>11,.0f}')


# ---------------------------------------------------------------
# 5. RUN ALL ANALYSES
# ---------------------------------------------------------------
print()
print('=' * 80)
print('  KITE-BASED FILTER ANALYSIS (real execution data, no local assumptions)')
print('=' * 80)

# VELOCITY
print()
print('1. VELOCITY (bars since price was at VWAP)')
vel_defs = [
    ('0-1 bars (instant flush)', lambda t: t['velocity'] <= 1),
    ('2-4 bars (fast)', lambda t: 2 <= t['velocity'] <= 4),
    ('5-9 bars', lambda t: 5 <= t['velocity'] <= 9),
    ('10-19 bars', lambda t: 10 <= t['velocity'] <= 19),
    ('20-49 bars', lambda t: 20 <= t['velocity'] <= 49),
    ('50+ bars (slow grind)', lambda t: t['velocity'] >= 50),
]
rows = [analyze([t for t in enriched if f(t)], lbl) for lbl, f in vel_defs]
print_table(rows, 'Velocity')

# TOD
print()
print('2. TIME OF DAY (minutes from 9:30 open)')
tod_defs = [
    ('0-10 min (9:30-9:40)', lambda t: t['mins_from_open'] < 10),
    ('10-15 min (9:40-9:45)', lambda t: 10 <= t['mins_from_open'] < 15),
    ('15-30 min (9:45-10:00)', lambda t: 15 <= t['mins_from_open'] < 30),
    ('30-45 min (10:00-10:15)', lambda t: 30 <= t['mins_from_open'] < 45),
    ('45-60 min (10:15-10:30)', lambda t: 45 <= t['mins_from_open'] < 60),
    ('60-90 min (10:30-11:00)', lambda t: 60 <= t['mins_from_open'] < 90),
    ('90-120 min (11:00-11:30)', lambda t: 90 <= t['mins_from_open'] < 120),
    ('120-195 min (11:30-12:45)', lambda t: 120 <= t['mins_from_open'] < 195),
    ('195-270 min (12:45-2:00)', lambda t: 195 <= t['mins_from_open'] < 270),
    ('270+ min (2:00+)', lambda t: t['mins_from_open'] >= 270),
]
rows = [analyze([t for t in enriched if f(t)], lbl) for lbl, f in tod_defs]
print_table(rows, 'Time Window')

# GAP
print()
print('3. GAP % (already filtered < -1%)')
gap_defs = [
    ('Gap < -0.5%', lambda t: t['gap_pct'] < -0.5),
    ('Gap -0.5% to 0%', lambda t: -0.5 <= t['gap_pct'] < 0),
    ('Gap 0% to +0.5%', lambda t: 0 <= t['gap_pct'] < 0.5),
    ('Gap +0.5% to +1%', lambda t: 0.5 <= t['gap_pct'] < 1.0),
    ('Gap > +1%', lambda t: t['gap_pct'] >= 1.0),
]
rows = [analyze([t for t in enriched if f(t)], lbl) for lbl, f in gap_defs]
print_table(rows, 'Gap Range')

# DOW
print()
print('4. DAY OF WEEK')
dow_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
rows = [analyze([t for t in enriched if t['dow'] == d], dow_names[d]) for d in range(5)]
print_table(rows, 'Day')

# VELOCITY x TOD cross-tab
print()
print('5. VELOCITY x TOD CROSS-TAB')
vt_defs = [
    ('Fast(0-4) + Early(0-30m)', lambda t: t['velocity'] <= 4 and t['mins_from_open'] < 30),
    ('Fast(0-4) + Dead(30-60m)', lambda t: t['velocity'] <= 4 and 30 <= t['mins_from_open'] < 60),
    ('Fast(0-4) + Mid(60-195m)', lambda t: t['velocity'] <= 4 and 60 <= t['mins_from_open'] < 195),
    ('Fast(0-4) + Late(195m+)', lambda t: t['velocity'] <= 4 and t['mins_from_open'] >= 195),
    ('Mid(5-49) + Early(0-30m)', lambda t: 5 <= t['velocity'] <= 49 and t['mins_from_open'] < 30),
    ('Mid(5-49) + Dead(30-60m)', lambda t: 5 <= t['velocity'] <= 49 and 30 <= t['mins_from_open'] < 60),
    ('Mid(5-49) + Mid(60-195m)', lambda t: 5 <= t['velocity'] <= 49 and 60 <= t['mins_from_open'] < 195),
    ('Mid(5-49) + Late(195m+)', lambda t: 5 <= t['velocity'] <= 49 and t['mins_from_open'] >= 195),
    ('Slow(50+) + Any', lambda t: t['velocity'] >= 50),
]
rows = [analyze([t for t in enriched if f(t)], lbl) for lbl, f in vt_defs]
print_table(rows, 'Velocity x TOD')

# NOTIONAL SIZE (infer velocity tier behavior)
print()
print('6. POSITION SIZE (current dynamic sizing result)')
sz_defs = [
    ('< $3.5M notional', lambda t: t['notional'] < 3_500_000),
    ('$3.5M - $7M', lambda t: 3_500_000 <= t['notional'] < 7_000_000),
    ('$7M - $12M', lambda t: 7_000_000 <= t['notional'] < 12_000_000),
    ('$12M - $18M', lambda t: 12_000_000 <= t['notional'] < 18_000_000),
    ('> $18M', lambda t: t['notional'] >= 18_000_000),
]
rows = [analyze([t for t in enriched if f(t)], lbl) for lbl, f in sz_defs]
print_table(rows, 'Notional Size')

# OVERALL
print()
print('=' * 80)
print('  OVERALL STRATEGY D v2 (gap-filtered)')
print('=' * 80)
r = analyze(enriched, 'All trades')
if r:
    cum = np.cumsum([t['pnl'] for t in enriched])
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum)
    print(f'  Trades: {r["n"]}  Total: ${r["total"]:,.0f}  Sharpe: {r["sharpe"]}')
    print(f'  WR: {r["wr"]}%  PF: {r["pf"]}  Avg P&L: ${r["avg_pnl"]:,.0f}  MaxDD: ${max_dd:,.0f}')
    print()
    for yr in sorted(set(t['year'] for t in enriched)):
        yr_r = analyze([t for t in enriched if t['year'] == yr], str(yr))
        if yr_r:
            print(f'    {yr}: N={yr_r["n"]:3d}  Total=${yr_r["total"]:>10,.0f}  Sh={yr_r["sharpe"]:>6.3f}  WR={yr_r["wr"]:.1f}%  PF={yr_r["pf"]:.2f}')

# Save enriched data
with open('kite_d2_enriched.json', 'w') as f:
    json.dump(enriched, f, indent=2, default=str)
print(f'\nSaved enriched trade data to kite_d2_enriched.json')

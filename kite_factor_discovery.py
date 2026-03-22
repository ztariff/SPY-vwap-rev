#!/usr/bin/env python3
"""
Factor discovery using KITE execution data as source of truth.

Takes the 519 flat KITE trades (real fills, real P&L) and finds
which factors actually predict trade quality under realistic execution.
Then simulates sizing strategies by replaying those trades at different
notional sizes — no new KITE runs needed since fills are size-independent.
"""

import csv, sys, os, json
import numpy as np
import pandas as pd
from datetime import datetime, time as dt_time
from collections import defaultdict
import statistics

sys.path.insert(0, 'spy_fade_strategy')
from data_fetcher import PolygonFetcher

# ---------------------------------------------------------------
# 1. Load KITE flat trades (source of truth)
# ---------------------------------------------------------------
print("=" * 75)
print("  KITE FACTOR DISCOVERY")
print("  Using 519 real KITE trades as ground truth")
print("=" * 75)

kite_trades = []
with open('kite_spy_alt_trades.csv') as f:
    for row in csv.DictReader(f):
        kite_trades.append(row)

print(f"\n[1] Loaded {len(kite_trades)} KITE trades")

# ---------------------------------------------------------------
# 2. Enrich each trade with every available factor
# ---------------------------------------------------------------
print("[2] Enriching trades with factors from Polygon...")

fetcher = PolygonFetcher()

# Daily bars for gap, prior-day return, ATR
daily = fetcher.get_daily_bars('SPY', '2021-12-01', '2026-03-12')
daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
daily_sorted = daily.sort_values('date_obj').reset_index(drop=True)

# Build daily lookup
daily_lookup = {}
for i in range(len(daily_sorted)):
    d = daily_sorted['date_obj'].iloc[i]
    daily_lookup[d.strftime('%Y-%m-%d')] = {
        'open': float(daily_sorted['open'].iloc[i]),
        'high': float(daily_sorted['high'].iloc[i]),
        'low': float(daily_sorted['low'].iloc[i]),
        'close': float(daily_sorted['close'].iloc[i]),
        'volume': float(daily_sorted['volume'].iloc[i]),
    }

# Compute gap, prior-day return, 5-day return for each date
dates_sorted = sorted(daily_lookup.keys())
gap_map = {}
prior_ret_map = {}
five_day_ret_map = {}
daily_range_map = {}
volume_ratio_map = {}
vol_20d = {}

for i in range(1, len(dates_sorted)):
    d = dates_sorted[i]
    prev_d = dates_sorted[i-1]
    prev_close = daily_lookup[prev_d]['close']
    today_open = daily_lookup[d]['open']
    gap_map[d] = (today_open - prev_close) / prev_close * 100
    prior_ret_map[d] = (daily_lookup[prev_d]['close'] - daily_lookup[dates_sorted[max(0,i-2)]]['close']) / daily_lookup[dates_sorted[max(0,i-2)]]['close'] * 100 if i >= 2 else 0

    if i >= 5:
        five_d_ago = dates_sorted[i-5]
        five_day_ret_map[d] = (daily_lookup[prev_d]['close'] - daily_lookup[five_d_ago]['close']) / daily_lookup[five_d_ago]['close'] * 100
    else:
        five_day_ret_map[d] = 0

    # Daily range as % of price
    daily_range_map[d] = (daily_lookup[d]['high'] - daily_lookup[d]['low']) / daily_lookup[d]['close'] * 100

    # Volume ratio vs 20-day avg
    if i >= 20:
        avg_vol = np.mean([daily_lookup[dates_sorted[j]]['volume'] for j in range(i-20, i)])
        volume_ratio_map[d] = daily_lookup[d]['volume'] / avg_vol if avg_vol > 0 else 1.0
    else:
        volume_ratio_map[d] = 1.0

# VIX data
try:
    vix = fetcher.get_vix_daily('2021-12-01', '2026-03-12')
    vix['date_obj'] = pd.to_datetime(vix['date']).dt.date
    # Try different column names
    vix_col = 'close' if 'close' in vix.columns else 'c' if 'c' in vix.columns else vix.columns[-1]
    vix_map = {row['date_obj'].strftime('%Y-%m-%d'): float(row[vix_col]) for _, row in vix.iterrows()}
    print(f"  Got VIX data: {len(vix_map)} days")
except Exception as e:
    print(f"  VIX fetch failed: {e}, using fallback")
    vix_map = {}

# Minute data for velocity calculation
trade_dates = sorted(set(t['entry_time'][:10] for t in kite_trades))
print(f"  Fetching minute data for {len(trade_dates)} trade dates...")
results_dict = fetcher.get_intraday_bars_bulk('SPY', trade_dates)
print(f"  Got minute data for {len(results_dict)} dates")

# ---------------------------------------------------------------
# 3. Compute all factors per trade
# ---------------------------------------------------------------
print("[3] Computing factors per trade...")

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
    ret_pct = (exit_price - entry_price) / entry_price * 100
    hold_mins = (exit_dt - entry_dt).total_seconds() / 60
    fees = abs(float(t.get('entry_fees', 0) or 0)) + abs(float(t.get('exit_fees', 0) or 0))

    # TOD
    mins_from_open = (entry_dt.hour - 9) * 60 + (entry_dt.minute - 30)

    # DOW
    dow = entry_dt.weekday()

    # Gap
    gap = gap_map.get(date_str, 0)

    # Prior day return
    prior_ret = prior_ret_map.get(date_str, 0)

    # 5-day trend
    five_day = five_day_ret_map.get(date_str, 0)

    # VIX
    vix_level = vix_map.get(date_str, 20)

    # Volume ratio
    vol_ratio = volume_ratio_map.get(date_str, 1.0)

    # Daily range
    day_range = daily_range_map.get(date_str, 1.0)

    # Velocity from Polygon minute bars
    velocity = 999
    vwap_dev_at_entry = 0
    bars_into_session = 0
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

            # Find entry bar
            entry_bar = len(day_df) - 1
            for idx in range(len(day_df)):
                bar_time = day_df['ts'].iloc[idx]
                if bar_time.replace(tzinfo=None) >= entry_dt.replace(tzinfo=None):
                    entry_bar = idx
                    break

            bars_into_session = entry_bar

            # VWAP deviation at entry
            if entry_bar < len(vwap) and vwap[entry_bar] > 0:
                vwap_dev_at_entry = (entry_price - vwap[entry_bar]) / vwap[entry_bar] * 100

            # Velocity: bars since close was last at or above VWAP
            velocity = 0
            for j in range(entry_bar, -1, -1):
                if closes[j] >= vwap[j]:
                    velocity = entry_bar - j
                    break
            if velocity == 0 and entry_bar > 0 and closes[0] < vwap[0]:
                velocity = entry_bar

    enriched.append({
        'date': date_str,
        'entry_time': t['entry_time'],
        'entry_price': entry_price,
        'exit_price': exit_price,
        'pnl': pnl,
        'ret_pct': ret_pct,
        'shares': shares,
        'notional': shares * entry_price,
        'hold_mins': hold_mins,
        'fees': fees,
        'mins_from_open': mins_from_open,
        'velocity': velocity,
        'vwap_dev': vwap_dev_at_entry,
        'bars_into_session': bars_into_session,
        'gap_pct': gap,
        'prior_ret': prior_ret,
        'five_day_ret': five_day,
        'vix': vix_level,
        'vol_ratio': vol_ratio,
        'day_range': day_range,
        'dow': dow,
        'year': entry_dt.year,
        'is_win': 1 if pnl > 0 else 0,
    })

print(f"  Enriched {len(enriched)} trades")

# ---------------------------------------------------------------
# 4. Factor analysis: what predicts KITE return quality?
# ---------------------------------------------------------------
print()
print("=" * 75)
print("  FACTOR ANALYSIS: What predicts returns on KITE?")
print("=" * 75)


def bucket_analysis(trades, factor_name, buckets):
    """Analyze trade quality by buckets of a factor."""
    print(f"\n  {factor_name}")
    print(f"  {'-'*65}")
    header = f"  {'Bucket':<30s} {'N':>4s} {'WR':>6s} {'Avg Ret%':>9s} {'Avg $PnL':>10s} {'Total $':>12s} {'Sharpe':>7s}"
    print(header)

    for label, filt_fn in buckets:
        subset = [t for t in trades if filt_fn(t)]
        if len(subset) < 5:
            continue
        n = len(subset)
        rets = [t['ret_pct'] for t in subset]
        pnls = [t['pnl'] for t in subset]
        wr = sum(1 for r in rets if r > 0) / n
        avg_ret = np.mean(rets)
        avg_pnl = np.mean(pnls)
        total = sum(pnls)
        std = np.std(pnls, ddof=1)
        sharpe = avg_pnl / std * np.sqrt(n / 4.2) if std > 0 else 0
        print(f"  {label:<30s} {n:>4d} {wr:>5.1%} {avg_ret:>8.4f}% ${avg_pnl:>9,.0f} ${total:>11,.0f} {sharpe:>7.3f}")


# VELOCITY
bucket_analysis(enriched, "VELOCITY (bars since at VWAP)", [
    ("0-1 bars (instant)", lambda t: t['velocity'] <= 1),
    ("2-4 bars", lambda t: 2 <= t['velocity'] <= 4),
    ("5-9 bars", lambda t: 5 <= t['velocity'] <= 9),
    ("10-19 bars", lambda t: 10 <= t['velocity'] <= 19),
    ("20-49 bars", lambda t: 20 <= t['velocity'] <= 49),
    ("50-99 bars", lambda t: 50 <= t['velocity'] <= 99),
    ("100+ bars", lambda t: t['velocity'] >= 100),
])

# TOD (minutes from open)
bucket_analysis(enriched, "TIME OF DAY (minutes from 9:30)", [
    ("0-5m (9:30-9:35)", lambda t: t['mins_from_open'] < 5),
    ("5-10m (9:35-9:40)", lambda t: 5 <= t['mins_from_open'] < 10),
    ("10-15m (9:40-9:45)", lambda t: 10 <= t['mins_from_open'] < 15),
    ("15-30m (9:45-10:00)", lambda t: 15 <= t['mins_from_open'] < 30),
    ("30-45m (10:00-10:15)", lambda t: 30 <= t['mins_from_open'] < 45),
    ("45-60m (10:15-10:30)", lambda t: 45 <= t['mins_from_open'] < 60),
    ("60-90m (10:30-11:00)", lambda t: 60 <= t['mins_from_open'] < 90),
    ("90-120m (11:00-11:30)", lambda t: 90 <= t['mins_from_open'] < 120),
    ("120-195m (11:30-12:45)", lambda t: 120 <= t['mins_from_open'] < 195),
    ("195-270m (12:45-2:00)", lambda t: 195 <= t['mins_from_open'] < 270),
    ("270+ (2:00+)", lambda t: t['mins_from_open'] >= 270),
])

# GAP %
bucket_analysis(enriched, "GAP % (today open vs prior close)", [
    ("Gap < -1.0%", lambda t: t['gap_pct'] < -1.0),
    ("Gap -1.0 to -0.5%", lambda t: -1.0 <= t['gap_pct'] < -0.5),
    ("Gap -0.5 to 0%", lambda t: -0.5 <= t['gap_pct'] < 0),
    ("Gap 0 to +0.5%", lambda t: 0 <= t['gap_pct'] < 0.5),
    ("Gap +0.5 to +1.0%", lambda t: 0.5 <= t['gap_pct'] < 1.0),
    ("Gap > +1.0%", lambda t: t['gap_pct'] >= 1.0),
])

# VIX LEVEL
bucket_analysis(enriched, "VIX LEVEL", [
    ("VIX < 15", lambda t: t['vix'] < 15),
    ("VIX 15-20", lambda t: 15 <= t['vix'] < 20),
    ("VIX 20-25", lambda t: 20 <= t['vix'] < 25),
    ("VIX 25-30", lambda t: 25 <= t['vix'] < 30),
    ("VIX 30+", lambda t: t['vix'] >= 30),
])

# DAY OF WEEK
bucket_analysis(enriched, "DAY OF WEEK", [
    ("Monday", lambda t: t['dow'] == 0),
    ("Tuesday", lambda t: t['dow'] == 1),
    ("Wednesday", lambda t: t['dow'] == 2),
    ("Thursday", lambda t: t['dow'] == 3),
    ("Friday", lambda t: t['dow'] == 4),
])

# PRIOR DAY RETURN
bucket_analysis(enriched, "PRIOR DAY RETURN", [
    ("Prior < -1%", lambda t: t['prior_ret'] < -1.0),
    ("Prior -1 to -0.5%", lambda t: -1.0 <= t['prior_ret'] < -0.5),
    ("Prior -0.5 to 0%", lambda t: -0.5 <= t['prior_ret'] < 0),
    ("Prior 0 to +0.5%", lambda t: 0 <= t['prior_ret'] < 0.5),
    ("Prior +0.5 to +1%", lambda t: 0.5 <= t['prior_ret'] < 1.0),
    ("Prior > +1%", lambda t: t['prior_ret'] >= 1.0),
])

# 5-DAY TREND
bucket_analysis(enriched, "5-DAY TREND", [
    ("5d < -3%", lambda t: t['five_day_ret'] < -3.0),
    ("5d -3 to -1%", lambda t: -3.0 <= t['five_day_ret'] < -1.0),
    ("5d -1 to 0%", lambda t: -1.0 <= t['five_day_ret'] < 0),
    ("5d 0 to +1%", lambda t: 0 <= t['five_day_ret'] < 1.0),
    ("5d +1 to +3%", lambda t: 1.0 <= t['five_day_ret'] < 3.0),
    ("5d > +3%", lambda t: t['five_day_ret'] >= 3.0),
])

# VWAP DEVIATION AT ENTRY
bucket_analysis(enriched, "VWAP DEVIATION AT ENTRY (%)", [
    ("Dev < -0.6%", lambda t: t['vwap_dev'] < -0.6),
    ("Dev -0.6 to -0.4%", lambda t: -0.6 <= t['vwap_dev'] < -0.4),
    ("Dev -0.4 to -0.3%", lambda t: -0.4 <= t['vwap_dev'] < -0.3),
    ("Dev -0.3 to -0.2%", lambda t: -0.3 <= t['vwap_dev'] < -0.2),
    ("Dev > -0.2%", lambda t: t['vwap_dev'] >= -0.2),
])

# VOLUME RATIO
bucket_analysis(enriched, "VOLUME RATIO (vs 20d avg)", [
    ("Vol < 0.7x", lambda t: t['vol_ratio'] < 0.7),
    ("Vol 0.7-1.0x", lambda t: 0.7 <= t['vol_ratio'] < 1.0),
    ("Vol 1.0-1.3x", lambda t: 1.0 <= t['vol_ratio'] < 1.3),
    ("Vol 1.3-1.7x", lambda t: 1.3 <= t['vol_ratio'] < 1.7),
    ("Vol > 1.7x", lambda t: t['vol_ratio'] >= 1.7),
])

# BARS INTO SESSION (how far into the day)
bucket_analysis(enriched, "BARS INTO SESSION (entry bar #)", [
    ("Bar 0-10", lambda t: t['bars_into_session'] <= 10),
    ("Bar 11-30", lambda t: 11 <= t['bars_into_session'] <= 30),
    ("Bar 31-60", lambda t: 31 <= t['bars_into_session'] <= 60),
    ("Bar 61-120", lambda t: 61 <= t['bars_into_session'] <= 120),
    ("Bar 121-200", lambda t: 121 <= t['bars_into_session'] <= 200),
    ("Bar 200+", lambda t: t['bars_into_session'] > 200),
])

# HOLD DURATION
bucket_analysis(enriched, "HOLD DURATION (minutes)", [
    ("< 10 min", lambda t: t['hold_mins'] < 10),
    ("10-15 min", lambda t: 10 <= t['hold_mins'] < 15.5),
    ("15-16 min (time exit)", lambda t: 15.5 <= t['hold_mins'] < 16),
    ("> 16 min", lambda t: t['hold_mins'] >= 16),
])

# DAILY RANGE
bucket_analysis(enriched, "DAILY RANGE (% of price)", [
    ("Range < 0.8%", lambda t: t['day_range'] < 0.8),
    ("Range 0.8-1.2%", lambda t: 0.8 <= t['day_range'] < 1.2),
    ("Range 1.2-1.8%", lambda t: 1.2 <= t['day_range'] < 1.8),
    ("Range 1.8-2.5%", lambda t: 1.8 <= t['day_range'] < 2.5),
    ("Range > 2.5%", lambda t: t['day_range'] >= 2.5),
])

# ---------------------------------------------------------------
# 5. COMPOSITE SCORING: rank factors by predictive power
# ---------------------------------------------------------------
print()
print("=" * 75)
print("  FACTOR RANKING: Correlation with trade return %")
print("=" * 75)

factors = [
    ('velocity', [t['velocity'] for t in enriched]),
    ('mins_from_open', [t['mins_from_open'] for t in enriched]),
    ('gap_pct', [t['gap_pct'] for t in enriched]),
    ('vix', [t['vix'] for t in enriched]),
    ('prior_ret', [t['prior_ret'] for t in enriched]),
    ('five_day_ret', [t['five_day_ret'] for t in enriched]),
    ('vwap_dev', [t['vwap_dev'] for t in enriched]),
    ('vol_ratio', [t['vol_ratio'] for t in enriched]),
    ('day_range', [t['day_range'] for t in enriched]),
    ('bars_into_session', [t['bars_into_session'] for t in enriched]),
    ('dow', [t['dow'] for t in enriched]),
]

returns = np.array([t['ret_pct'] for t in enriched])
wins = np.array([t['is_win'] for t in enriched])

print(f"\n  {'Factor':<22s} {'Corr w/ Ret%':>12s} {'Corr w/ Win':>12s} {'|Corr Ret|':>12s}")
print(f"  {'-'*58}")

ranked = []
for name, values in factors:
    vals = np.array(values, dtype=float)
    # Remove any inf/nan
    mask = np.isfinite(vals)
    if mask.sum() < 10:
        continue
    corr_ret = np.corrcoef(vals[mask], returns[mask])[0, 1]
    corr_win = np.corrcoef(vals[mask], wins[mask])[0, 1]
    ranked.append((name, corr_ret, corr_win, abs(corr_ret)))

ranked.sort(key=lambda x: x[3], reverse=True)
for name, cr, cw, acr in ranked:
    marker = " ***" if acr > 0.05 else " *" if acr > 0.03 else ""
    print(f"  {name:<22s} {cr:>+11.4f} {cw:>+11.4f} {acr:>11.4f}{marker}")

# ---------------------------------------------------------------
# 6. SIZING SIMULATION: test strategies on KITE returns
# ---------------------------------------------------------------
print()
print("=" * 75)
print("  SIZING SIMULATION: Replay KITE trades with different sizes")
print("=" * 75)

FLAT_NOTIONAL = 15_000_000  # baseline notional
FLAT_RISK = 150_000
STOP_PCT = 1.0


def simulate_sizing(trades, name, size_fn, skip_fn=None):
    """Replay trades with custom sizing. Returns stats dict."""
    pnls = []
    by_year = defaultdict(list)

    for t in trades:
        if skip_fn and skip_fn(t):
            continue

        # Get the multiplier from size_fn
        mult = size_fn(t)
        if mult <= 0:
            continue

        # Scale the P&L: original was at FLAT_NOTIONAL
        # New P&L = original_ret% * new_notional
        new_notional = min(FLAT_NOTIONAL * mult, 25_000_000)
        new_pnl = t['ret_pct'] / 100.0 * new_notional
        # Subtract proportional fees
        fee_ratio = new_notional / t['notional'] if t['notional'] > 0 else 1
        new_pnl -= t['fees'] * fee_ratio

        pnls.append(new_pnl)
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

    return {
        'name': name, 'n': n, 'total': total, 'avg': avg,
        'sharpe': sharpe, 'wr': wr, 'pf': pf, 'max_dd': max_dd,
        'neg_years': neg_years, 'by_year': dict(by_year),
    }


# Define sizing strategies to test
strategies = []

# Baseline: flat
strategies.append(("BASELINE (flat $15M)", lambda t: 1.0, None))

# Gap filter only
strategies.append(("Gap filter only (skip <-1%)",
                   lambda t: 1.0,
                   lambda t: t['gap_pct'] < -1.0))

# Gap + skip worst TOD bucket (test each)
for tod_start, tod_end, tod_label in [
    (30, 45, "30-45m"), (45, 60, "45-60m"), (30, 60, "30-60m"),
    (195, 270, "195-270m"), (270, 390, "270+m")
]:
    strategies.append((f"Gap + skip TOD {tod_label}",
                       lambda t: 1.0,
                       lambda t, s=tod_start, e=tod_end: t['gap_pct'] < -1.0 or s <= t['mins_from_open'] < e))

# Gap + skip worst velocity bucket
for v_min, v_max, v_label in [
    (0, 2, "vel 0-1"), (100, 9999, "vel 100+"), (50, 9999, "vel 50+"),
]:
    strategies.append((f"Gap + skip {v_label}",
                       lambda t: 1.0,
                       lambda t, mn=v_min, mx=v_max: t['gap_pct'] < -1.0 or mn <= t['velocity'] < mx))

# Gap + VIX filter
strategies.append(("Gap + skip VIX > 30",
                   lambda t: 1.0,
                   lambda t: t['gap_pct'] < -1.0 or t['vix'] >= 30))

# Gap + prior day filter
strategies.append(("Gap + skip prior_ret < -1%",
                   lambda t: 1.0,
                   lambda t: t['gap_pct'] < -1.0 or t['prior_ret'] < -1.0))

# Size by strongest factor (from correlation analysis)
# Test various factor-based sizing
strategies.append(("Gap + 2x if VIX 15-25, 0.5x else",
                   lambda t: 2.0 if 15 <= t['vix'] < 25 else 0.5,
                   lambda t: t['gap_pct'] < -1.0))

strategies.append(("Gap + 2x if gap +0.1 to +0.5, 0.5x else",
                   lambda t: 2.0 if 0.1 <= t['gap_pct'] < 0.5 else 0.5,
                   lambda t: t['gap_pct'] < -1.0))

strategies.append(("Gap + 1.5x if 60-195m, 0.7x else",
                   lambda t: 1.5 if 60 <= t['mins_from_open'] < 195 else 0.7,
                   lambda t: t['gap_pct'] < -1.0))

strategies.append(("Gap + 1.5x if vel 5-49, 0.7x else",
                   lambda t: 1.5 if 5 <= t['velocity'] < 50 else 0.7,
                   lambda t: t['gap_pct'] < -1.0))

strategies.append(("Gap + 1.5x high vol days, 0.7x low",
                   lambda t: 1.5 if t['vol_ratio'] >= 1.3 else 0.7,
                   lambda t: t['gap_pct'] < -1.0))

strategies.append(("Gap + 1.5x if range > 1.5%, 0.7x else",
                   lambda t: 1.5 if t['day_range'] >= 1.5 else 0.7,
                   lambda t: t['gap_pct'] < -1.0))

strategies.append(("Gap + 1.5x if 5d trend < -1%",
                   lambda t: 1.5 if t['five_day_ret'] < -1.0 else 0.7,
                   lambda t: t['gap_pct'] < -1.0))

# Multi-factor combos
strategies.append(("Gap + skip TOD30-45 + skip vel0-1",
                   lambda t: 1.0,
                   lambda t: t['gap_pct'] < -1.0 or (30 <= t['mins_from_open'] < 45) or t['velocity'] <= 1))

strategies.append(("Gap + skip worst (gap/TOD30-60/vel0-1/VIX30+)",
                   lambda t: 1.0,
                   lambda t: (t['gap_pct'] < -1.0 or
                              30 <= t['mins_from_open'] < 60 or
                              t['velocity'] <= 1 or
                              t['vix'] >= 30)))

# Score-based sizing: combine multiple weak signals
def score_size(t):
    score = 0
    # Each factor adds/subtracts from score
    if 0.1 <= t['gap_pct'] < 0.5: score += 1
    if t['gap_pct'] < -0.5: score -= 1
    if 60 <= t['mins_from_open'] < 195: score += 1
    if 30 <= t['mins_from_open'] < 60: score -= 1
    if 5 <= t['velocity'] < 50: score += 1
    if t['velocity'] <= 1: score -= 1
    if 15 <= t['vix'] < 25: score += 1
    if t['vix'] >= 30: score -= 1
    if t['vol_ratio'] >= 1.3: score += 1
    # Map score to size multiplier
    mult_map = {-4: 0.25, -3: 0.25, -2: 0.4, -1: 0.6, 0: 1.0, 1: 1.3, 2: 1.6, 3: 1.67, 4: 1.67, 5: 1.67}
    return mult_map.get(score, 1.0)

strategies.append(("Gap + COMPOSITE SCORE sizing",
                   score_size,
                   lambda t: t['gap_pct'] < -1.0))

# Run all strategies
print(f"\n  {'Strategy':<48s} {'N':>4s} {'Sharpe':>7s} {'WR':>6s} {'PF':>5s} {'Total $':>12s} {'MaxDD $':>10s} {'NY':>3s}")
print(f"  {'-'*100}")

results = []
for name, size_fn, skip_fn in strategies:
    r = simulate_sizing(enriched, name, size_fn, skip_fn)
    if r:
        results.append(r)

results.sort(key=lambda x: x['sharpe'], reverse=True)
for r in results:
    marker = " <-- BEST" if r == results[0] else ""
    print(f"  {r['name']:<48s} {r['n']:>4d} {r['sharpe']:>7.3f} {r['wr']:>5.1%} {r['pf']:>5.2f} ${r['total']:>11,.0f} ${r['max_dd']:>9,.0f} {r['neg_years']:>3d}{marker}")

# Show yearly for top 3
print()
print("  YEARLY BREAKDOWN - Top 3")
print("  " + "-" * 70)
for r in results[:3]:
    print(f"\n  {r['name']}")
    for yr in sorted(r['by_year'].keys()):
        yp = r['by_year'][yr]
        yt = sum(yp)
        print(f"    {yr}: N={len(yp):3d}  Total=${yt:>10,.0f}")

# Save enriched data
with open('kite_factor_enriched.json', 'w') as f:
    json.dump(enriched, f, indent=2, default=str)
print(f"\n\nSaved enriched data to kite_factor_enriched.json")

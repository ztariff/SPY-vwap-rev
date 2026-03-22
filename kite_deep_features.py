#!/usr/bin/env python3
"""
Deep feature engineering on 519 KITE trades.

Computes 80+ features per trade from Polygon minute bars, daily bars,
and KITE execution data. Then ranks every feature by predictive power
on actual KITE returns.
"""

import csv, sys, os, json
import numpy as np
import pandas as pd
from datetime import datetime, time as dt_time, timedelta
from collections import defaultdict

sys.path.insert(0, 'spy_fade_strategy')
from data_fetcher import PolygonFetcher

# ---------------------------------------------------------------
# 1. Load KITE trades
# ---------------------------------------------------------------
print("=" * 80)
print("  DEEP FEATURE ENGINEERING ON 519 KITE TRADES")
print("=" * 80)

kite_trades = []
with open('kite_spy_alt_trades.csv') as f:
    for row in csv.DictReader(f):
        kite_trades.append(row)
print(f"\n[1] Loaded {len(kite_trades)} KITE trades")

# ---------------------------------------------------------------
# 2. Load all market data
# ---------------------------------------------------------------
print("[2] Loading market data...")
fetcher = PolygonFetcher()

# Daily bars (extra history for lookback windows)
daily = fetcher.get_daily_bars('SPY', '2021-06-01', '2026-03-12')
daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
daily = daily.sort_values('date_obj').reset_index(drop=True)
print(f"  Daily bars: {len(daily)}")

# Build daily arrays for fast lookback
daily_dates = [d.strftime('%Y-%m-%d') for d in daily['date_obj']]
daily_open = daily['open'].values.astype(float)
daily_high = daily['high'].values.astype(float)
daily_low = daily['low'].values.astype(float)
daily_close = daily['close'].values.astype(float)
daily_volume = daily['volume'].values.astype(float)
daily_date_idx = {d: i for i, d in enumerate(daily_dates)}

# Minute bars for all trade dates
trade_dates = sorted(set(t['entry_time'][:10] for t in kite_trades))
print(f"  Fetching minute bars for {len(trade_dates)} dates...")
minute_data = fetcher.get_intraday_bars_bulk('SPY', trade_dates)
print(f"  Got minute data for {len(minute_data)} dates")

# VIX daily
try:
    vix_df = fetcher.get_vix_daily('2021-06-01', '2026-03-12')
    vix_df['date_obj'] = pd.to_datetime(vix_df['date']).dt.date
    # Find the close column
    for col in ['close', 'c']:
        if col in vix_df.columns:
            vix_map = {}
            for _, row in vix_df.iterrows():
                try:
                    vix_map[row['date_obj'].strftime('%Y-%m-%d')] = float(row[col])
                except:
                    pass
            break
    print(f"  VIX data: {len(vix_map)} days")
except Exception as e:
    print(f"  VIX failed: {e}")
    vix_map = {}

RTH_START = dt_time(9, 30)
RTH_END = dt_time(16, 0)


# ---------------------------------------------------------------
# 3. Helper functions for feature computation
# ---------------------------------------------------------------
def get_rth_bars(date_str):
    """Get RTH minute bars as numpy arrays for a date."""
    if date_str not in minute_data:
        return None
    df = minute_data[date_str].copy()
    df['ts'] = pd.to_datetime(df['timestamp'])
    df['tm'] = df['ts'].dt.time
    df = df[(df['tm'] >= RTH_START) & (df['tm'] < RTH_END)].copy()
    df.sort_values('ts', inplace=True)
    df.reset_index(drop=True, inplace=True)
    if len(df) < 10:
        return None
    return {
        'ts': df['ts'].values,
        'open': df['open'].values.astype(float),
        'high': df['high'].values.astype(float),
        'low': df['low'].values.astype(float),
        'close': df['close'].values.astype(float),
        'volume': df['volume'].values.astype(float),
        'n': len(df),
    }


def compute_vwap(bars):
    """Compute running VWAP from bar data."""
    tp = (bars['high'] + bars['low'] + bars['close']) / 3.0
    cum_tpv = np.cumsum(tp * bars['volume'])
    cum_v = np.cumsum(bars['volume'])
    return np.where(cum_v > 0, cum_tpv / cum_v, bars['close'])


def compute_ema(prices, span):
    """Simple EMA."""
    alpha = 2.0 / (span + 1)
    ema = np.zeros_like(prices)
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = alpha * prices[i] + (1 - alpha) * ema[i - 1]
    return ema


def find_entry_bar(bars, entry_dt):
    """Find the minute bar index closest to entry time."""
    entry_naive = np.datetime64(entry_dt.replace(tzinfo=None))
    for idx in range(bars['n']):
        bar_ts = bars['ts'][idx]
        # Convert to comparable
        if hasattr(bar_ts, 'tz_localize'):
            bar_ts = bar_ts.tz_localize(None)
        if bar_ts >= entry_naive:
            return idx
    return bars['n'] - 1


def safe_div(a, b, default=0):
    return a / b if b != 0 else default


# ---------------------------------------------------------------
# 4. Compute features for each trade
# ---------------------------------------------------------------
print("[3] Computing features for each trade...")

enriched = []
skipped = 0

for ti, t in enumerate(kite_trades):
    if (ti + 1) % 100 == 0:
        print(f"  Trade {ti+1}/{len(kite_trades)}...")

    date_str = t['entry_time'][:10]
    entry_dt = datetime.strptime(t['entry_time'], '%Y-%m-%d %H:%M:%S.%f')
    exit_dt = datetime.strptime(t['exit_time'], '%Y-%m-%d %H:%M:%S.%f')

    entry_price = float(t['entry_price'])
    exit_price = float(t['exit_price'])
    shares = abs(int(float(t['entry_shares'])))
    pnl = float(t['mtm_pl'])
    ret_pct = (exit_price - entry_price) / entry_price * 100
    hold_secs = (exit_dt - entry_dt).total_seconds()
    hold_mins = hold_secs / 60
    fees = abs(float(t.get('entry_fees', 0) or 0)) + abs(float(t.get('exit_fees', 0) or 0))

    bars = get_rth_bars(date_str)
    di = daily_date_idx.get(date_str)

    if bars is None or di is None or di < 20:
        skipped += 1
        continue

    entry_bar = find_entry_bar(bars, entry_dt)
    vwap = compute_vwap(bars)
    closes = bars['close']
    highs = bars['high']
    lows = bars['low']
    opens = bars['open']
    volumes = bars['volume']
    n_bars = bars['n']

    feat = {}

    # === BASIC ===
    feat['ret_pct'] = ret_pct
    feat['pnl'] = pnl
    feat['is_win'] = 1 if pnl > 0 else 0
    feat['date'] = date_str
    feat['entry_time'] = t['entry_time']
    feat['hold_mins'] = hold_mins

    # === TIME FEATURES ===
    feat['mins_from_open'] = (entry_dt.hour - 9) * 60 + (entry_dt.minute - 30)
    feat['dow'] = entry_dt.weekday()
    feat['bars_into_session'] = entry_bar
    feat['pct_of_session'] = entry_bar / max(n_bars - 1, 1)  # 0=open, 1=close

    # === VWAP FEATURES ===
    feat['vwap_dev_pct'] = (entry_price - vwap[entry_bar]) / vwap[entry_bar] * 100
    if entry_bar > 0:
        feat['vwap_slope_5'] = (vwap[entry_bar] - vwap[max(0, entry_bar - 5)]) / vwap[max(0, entry_bar - 5)] * 100
        feat['vwap_slope_10'] = (vwap[entry_bar] - vwap[max(0, entry_bar - 10)]) / vwap[max(0, entry_bar - 10)] * 100
    else:
        feat['vwap_slope_5'] = 0
        feat['vwap_slope_10'] = 0

    # Max VWAP deviation before entry (how far below VWAP did price get)
    if entry_bar > 0:
        min_dev = min((closes[j] - vwap[j]) / vwap[j] * 100 for j in range(entry_bar + 1))
        feat['max_vwap_dev_before_entry'] = min_dev
    else:
        feat['max_vwap_dev_before_entry'] = feat['vwap_dev_pct']

    # === VELOCITY FEATURES ===
    # Bars since close was at/above VWAP
    velocity = 0
    for j in range(entry_bar, -1, -1):
        if closes[j] >= vwap[j]:
            velocity = entry_bar - j
            break
    if velocity == 0 and entry_bar > 0 and closes[0] < vwap[0]:
        velocity = entry_bar
    feat['velocity'] = velocity

    # Speed of deviation: how fast price moved from VWAP to entry level
    # (VWAP dev / velocity) = rate of deviation per bar
    feat['dev_speed'] = abs(feat['vwap_dev_pct']) / max(velocity, 1)

    # Acceleration: compare speed in last 3 bars vs prior 3 bars
    if entry_bar >= 6:
        recent_move = abs(closes[entry_bar] - closes[entry_bar - 3]) / closes[entry_bar - 3] * 100
        prior_move = abs(closes[entry_bar - 3] - closes[entry_bar - 6]) / closes[entry_bar - 6] * 100
        feat['price_acceleration'] = recent_move - prior_move
    else:
        feat['price_acceleration'] = 0

    # === MOMENTUM FEATURES ===
    # Price change over last N bars before entry
    for lookback in [3, 5, 10, 15, 20]:
        if entry_bar >= lookback:
            feat[f'momentum_{lookback}b'] = (closes[entry_bar] - closes[entry_bar - lookback]) / closes[entry_bar - lookback] * 100
        else:
            feat[f'momentum_{lookback}b'] = 0

    # Consecutive down bars before entry
    consec_down = 0
    for j in range(entry_bar, 0, -1):
        if closes[j] < closes[j - 1]:
            consec_down += 1
        else:
            break
    feat['consec_down_bars'] = consec_down

    # Consecutive bars below VWAP
    consec_below_vwap = 0
    for j in range(entry_bar, -1, -1):
        if closes[j] < vwap[j]:
            consec_below_vwap += 1
        else:
            break
    feat['consec_below_vwap'] = consec_below_vwap

    # === MOVING AVERAGE FEATURES ===
    ema5 = compute_ema(closes[:entry_bar + 1], 5)
    ema10 = compute_ema(closes[:entry_bar + 1], 10)
    ema20 = compute_ema(closes[:entry_bar + 1], 20)

    feat['dist_ema5_pct'] = (entry_price - ema5[-1]) / ema5[-1] * 100
    feat['dist_ema10_pct'] = (entry_price - ema10[-1]) / ema10[-1] * 100
    feat['dist_ema20_pct'] = (entry_price - ema20[-1]) / ema20[-1] * 100
    feat['ema5_above_ema20'] = 1 if ema5[-1] > ema20[-1] else 0
    feat['ema5_slope'] = (ema5[-1] - ema5[max(0, len(ema5) - 6)]) / ema5[max(0, len(ema5) - 6)] * 100 if len(ema5) > 5 else 0

    # === INTRADAY VOLATILITY FEATURES ===
    # ATR of bars up to entry
    if entry_bar >= 5:
        true_ranges = []
        for j in range(1, entry_bar + 1):
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j - 1]),
                     abs(lows[j] - closes[j - 1]))
            true_ranges.append(tr)
        feat['intraday_atr'] = np.mean(true_ranges[-14:]) if len(true_ranges) >= 14 else np.mean(true_ranges)
        feat['intraday_atr_pct'] = feat['intraday_atr'] / entry_price * 100
    else:
        feat['intraday_atr'] = 0
        feat['intraday_atr_pct'] = 0

    # Bar range at entry
    feat['entry_bar_range_pct'] = (highs[entry_bar] - lows[entry_bar]) / entry_price * 100

    # Range of last 5 bars
    if entry_bar >= 5:
        feat['range_last_5_pct'] = (max(highs[entry_bar-4:entry_bar+1]) - min(lows[entry_bar-4:entry_bar+1])) / entry_price * 100
    else:
        feat['range_last_5_pct'] = 0

    # Volatility compression: current bar range vs avg bar range
    if entry_bar >= 10:
        avg_range = np.mean(highs[:entry_bar] - lows[:entry_bar])
        curr_range = highs[entry_bar] - lows[entry_bar]
        feat['vol_compression'] = curr_range / avg_range if avg_range > 0 else 1
    else:
        feat['vol_compression'] = 1

    # === VOLUME FEATURES (INTRADAY) ===
    feat['entry_bar_volume'] = volumes[entry_bar]
    if entry_bar >= 5:
        avg_vol_5 = np.mean(volumes[entry_bar - 5:entry_bar])
        feat['vol_surge_5'] = volumes[entry_bar] / avg_vol_5 if avg_vol_5 > 0 else 1
    else:
        feat['vol_surge_5'] = 1

    if entry_bar >= 10:
        avg_vol_10 = np.mean(volumes[:entry_bar])
        feat['vol_surge_session'] = volumes[entry_bar] / avg_vol_10 if avg_vol_10 > 0 else 1
    else:
        feat['vol_surge_session'] = 1

    # Cumulative volume at entry vs total day
    cum_vol_at_entry = np.sum(volumes[:entry_bar + 1])
    total_vol = np.sum(volumes)
    feat['cum_vol_pct'] = cum_vol_at_entry / total_vol * 100 if total_vol > 0 else 0

    # === OPENING RANGE FEATURES ===
    # First 15 minutes (bars 0-14) high/low
    or_end = min(15, n_bars)
    or_high = max(highs[:or_end])
    or_low = min(lows[:or_end])
    feat['opening_range_pct'] = (or_high - or_low) / opens[0] * 100
    feat['dist_from_or_high'] = (entry_price - or_high) / or_high * 100
    feat['dist_from_or_low'] = (entry_price - or_low) / or_low * 100
    feat['below_or_low'] = 1 if entry_price < or_low else 0

    # First 30 minutes range
    or30_end = min(30, n_bars)
    or30_high = max(highs[:or30_end])
    or30_low = min(lows[:or30_end])
    feat['or30_range_pct'] = (or30_high - or30_low) / opens[0] * 100
    feat['below_or30_low'] = 1 if entry_price < or30_low else 0

    # === PRICE POSITION FEATURES ===
    session_high = max(highs[:entry_bar + 1])
    session_low = min(lows[:entry_bar + 1])
    session_range = session_high - session_low
    feat['pct_of_session_range'] = (entry_price - session_low) / session_range * 100 if session_range > 0 else 50
    feat['dist_from_session_high'] = (entry_price - session_high) / session_high * 100
    feat['new_session_low'] = 1 if entry_price <= session_low else 0

    # Distance from open
    feat['dist_from_open_pct'] = (entry_price - opens[0]) / opens[0] * 100

    # === GAP FEATURES ===
    prev_close = daily_close[di - 1]
    today_open = daily_open[di]
    feat['gap_pct'] = (today_open - prev_close) / prev_close * 100
    feat['gap_filled'] = 1 if (feat['gap_pct'] < 0 and max(highs[:entry_bar + 1]) >= prev_close) else 0
    feat['gap_extended'] = 1 if (feat['gap_pct'] < 0 and min(lows[:entry_bar + 1]) < today_open) else 0

    # Distance from prior close
    feat['dist_from_prev_close_pct'] = (entry_price - prev_close) / prev_close * 100

    # === DAILY CONTEXT FEATURES ===
    # Prior day stats
    feat['prior_day_return'] = (daily_close[di - 1] - daily_close[di - 2]) / daily_close[di - 2] * 100 if di >= 2 else 0
    feat['prior_day_range_pct'] = (daily_high[di - 1] - daily_low[di - 1]) / daily_close[di - 1] * 100
    feat['prior_day_body_pct'] = abs(daily_close[di - 1] - daily_open[di - 1]) / daily_close[di - 1] * 100

    # Prior day was up or down
    feat['prior_day_up'] = 1 if daily_close[di - 1] > daily_open[di - 1] else 0

    # 2-day return
    feat['return_2d'] = (daily_close[di - 1] - daily_close[di - 3]) / daily_close[di - 3] * 100 if di >= 3 else 0

    # 3-day return
    feat['return_3d'] = (daily_close[di - 1] - daily_close[di - 4]) / daily_close[di - 4] * 100 if di >= 4 else 0

    # 5-day return
    feat['return_5d'] = (daily_close[di - 1] - daily_close[di - 6]) / daily_close[di - 6] * 100 if di >= 6 else 0

    # 10-day return
    feat['return_10d'] = (daily_close[di - 1] - daily_close[di - 11]) / daily_close[di - 11] * 100 if di >= 11 else 0

    # Prior weekly range (last 5 trading days high to low)
    if di >= 5:
        week_high = max(daily_high[di - 5:di])
        week_low = min(daily_low[di - 5:di])
        feat['prior_week_range_pct'] = (week_high - week_low) / daily_close[di - 1] * 100
    else:
        feat['prior_week_range_pct'] = 0

    # Prior 10-day range
    if di >= 10:
        ten_high = max(daily_high[di - 10:di])
        ten_low = min(daily_low[di - 10:di])
        feat['prior_10d_range_pct'] = (ten_high - ten_low) / daily_close[di - 1] * 100
    else:
        feat['prior_10d_range_pct'] = 0

    # Where is price relative to 5-day range?
    if di >= 5:
        feat['pct_of_5d_range'] = (entry_price - week_low) / (week_high - week_low) * 100 if (week_high - week_low) > 0 else 50
    else:
        feat['pct_of_5d_range'] = 50

    # Today's range so far
    feat['today_range_pct'] = (daily_high[di] - daily_low[di]) / daily_close[di] * 100

    # Daily volume ratio (vs 20-day average)
    if di >= 20:
        avg_vol_20d = np.mean(daily_volume[di - 20:di])
        feat['daily_vol_ratio'] = daily_volume[di] / avg_vol_20d if avg_vol_20d > 0 else 1
    else:
        feat['daily_vol_ratio'] = 1

    # === DAILY ATR ===
    if di >= 15:
        true_ranges_daily = []
        for j in range(di - 14, di):
            tr = max(daily_high[j] - daily_low[j],
                     abs(daily_high[j] - daily_close[j - 1]),
                     abs(daily_low[j] - daily_close[j - 1]))
            true_ranges_daily.append(tr)
        feat['daily_atr'] = np.mean(true_ranges_daily)
        feat['daily_atr_pct'] = feat['daily_atr'] / entry_price * 100
    else:
        feat['daily_atr'] = 0
        feat['daily_atr_pct'] = 0

    # Today's move as multiple of ATR
    if feat['daily_atr'] > 0:
        feat['today_move_atr_mult'] = abs(entry_price - today_open) / feat['daily_atr']
    else:
        feat['today_move_atr_mult'] = 0

    # === DAILY MOVING AVERAGES ===
    if di >= 20:
        sma5 = np.mean(daily_close[di - 5:di])
        sma10 = np.mean(daily_close[di - 10:di])
        sma20 = np.mean(daily_close[di - 20:di])
        feat['dist_daily_sma5'] = (entry_price - sma5) / sma5 * 100
        feat['dist_daily_sma10'] = (entry_price - sma10) / sma10 * 100
        feat['dist_daily_sma20'] = (entry_price - sma20) / sma20 * 100
        feat['daily_sma5_above_sma20'] = 1 if sma5 > sma20 else 0
        feat['daily_sma5_slope'] = (sma5 - np.mean(daily_close[di - 10:di - 5])) / sma5 * 100
    else:
        feat['dist_daily_sma5'] = 0
        feat['dist_daily_sma10'] = 0
        feat['dist_daily_sma20'] = 0
        feat['daily_sma5_above_sma20'] = 0
        feat['daily_sma5_slope'] = 0

    # === VIX ===
    feat['vix'] = vix_map.get(date_str, 20)

    # VIX change from prior day
    prev_date = daily_dates[di - 1] if di >= 1 else date_str
    feat['vix_change'] = feat['vix'] - vix_map.get(prev_date, feat['vix'])

    # === PATTERN FEATURES ===
    # Is this a "V-bottom" setup? (price made new low then bounced)
    if entry_bar >= 3:
        low_bar_idx = np.argmin(lows[max(0, entry_bar - 10):entry_bar + 1]) + max(0, entry_bar - 10)
        feat['bars_since_low'] = entry_bar - low_bar_idx
        feat['bounce_from_low_pct'] = (entry_price - lows[low_bar_idx]) / lows[low_bar_idx] * 100
    else:
        feat['bars_since_low'] = 0
        feat['bounce_from_low_pct'] = 0

    # Candle body at entry (bullish or bearish)
    feat['entry_candle_body'] = (closes[entry_bar] - opens[entry_bar]) / opens[entry_bar] * 100

    # Number of bars with lower lows in last 10
    if entry_bar >= 2:
        lower_lows = sum(1 for j in range(max(1, entry_bar - 9), entry_bar + 1) if lows[j] < lows[j - 1])
        feat['lower_lows_10'] = lower_lows
    else:
        feat['lower_lows_10'] = 0

    # === COMPOSITE / DERIVED ===
    # Mean reversion strength: deviation * speed
    feat['mr_strength'] = abs(feat['vwap_dev_pct']) * feat['dev_speed']

    # Oversold score: combination of distance from VWAP, EMAs, and session low
    feat['oversold_score'] = (abs(feat['dist_ema5_pct']) +
                               abs(feat['dist_ema10_pct']) +
                               abs(feat['vwap_dev_pct'])) / 3

    # Trend-counter score: buying dips in uptrend vs downtrend
    feat['trend_counter'] = feat['return_5d'] + feat['daily_sma5_slope']

    # Year (for regime analysis)
    feat['year'] = entry_dt.year

    enriched.append(feat)

print(f"  Enriched {len(enriched)} trades ({skipped} skipped)")

# ---------------------------------------------------------------
# 5. Rank ALL features by correlation with KITE return %
# ---------------------------------------------------------------
print()
print("=" * 80)
print("  FEATURE RANKING BY PREDICTIVE POWER (correlation with KITE return %)")
print("=" * 80)

# Exclude non-numeric / target features
exclude = {'ret_pct', 'pnl', 'is_win', 'date', 'entry_time', 'year'}
feature_names = [k for k in enriched[0].keys() if k not in exclude]

returns = np.array([t['ret_pct'] for t in enriched])
wins = np.array([t['is_win'] for t in enriched])

results = []
for fname in feature_names:
    vals = np.array([t[fname] for t in enriched], dtype=float)
    mask = np.isfinite(vals) & np.isfinite(returns)
    if mask.sum() < 20:
        continue
    v = vals[mask]
    r = returns[mask]
    w = wins[mask]

    # Skip if zero variance
    if np.std(v) < 1e-12:
        continue

    corr_ret = np.corrcoef(v, r)[0, 1]
    corr_win = np.corrcoef(v, w)[0, 1]

    # Also compute: if we split at median, is there a P&L difference?
    med = np.median(v)
    above = r[v >= med]
    below = r[v < med]
    if len(above) > 5 and len(below) > 5:
        split_diff = np.mean(above) - np.mean(below)
        above_wr = np.mean(w[v >= med])
        below_wr = np.mean(w[v < med])
    else:
        split_diff = 0
        above_wr = 0
        below_wr = 0

    results.append({
        'name': fname,
        'corr_ret': corr_ret,
        'corr_win': corr_win,
        'abs_corr': abs(corr_ret),
        'split_diff': split_diff,
        'above_med_wr': above_wr,
        'below_med_wr': below_wr,
    })

# Sort by absolute correlation
results.sort(key=lambda x: x['abs_corr'], reverse=True)

print(f"\n  {'Rank':<5s} {'Feature':<30s} {'Corr Ret%':>10s} {'Corr Win':>10s} {'|Corr|':>8s} {'SplitDiff':>10s} {'HiWR':>6s} {'LoWR':>6s}")
print(f"  {'-' * 90}")

for i, r in enumerate(results):
    stars = " ***" if r['abs_corr'] >= 0.08 else " **" if r['abs_corr'] >= 0.06 else " *" if r['abs_corr'] >= 0.04 else ""
    print(f"  {i+1:<5d} {r['name']:<30s} {r['corr_ret']:>+9.4f} {r['corr_win']:>+9.4f} {r['abs_corr']:>8.4f} {r['split_diff']:>+9.4f}% {r['above_med_wr']:>5.1%} {r['below_med_wr']:>5.1%}{stars}")

# ---------------------------------------------------------------
# 6. Deep dive on top 15 features: bucket analysis
# ---------------------------------------------------------------
print()
print("=" * 80)
print("  DEEP DIVE: Top 15 features bucketed analysis")
print("=" * 80)


def auto_bucket(trades, feat_name, n_buckets=5):
    """Auto-bucket a feature into quantiles and show performance."""
    vals = np.array([t[feat_name] for t in trades], dtype=float)
    valid_mask = np.isfinite(vals)
    valid_vals = vals[valid_mask]

    if len(valid_vals) < 20:
        return

    # Use quantile boundaries
    boundaries = np.percentile(valid_vals, np.linspace(0, 100, n_buckets + 1))
    boundaries = np.unique(boundaries)  # remove duplicates

    print(f"\n  {feat_name}")
    print(f"  {'-' * 75}")
    print(f"  {'Bucket':<35s} {'N':>4s} {'WR':>6s} {'AvgRet%':>9s} {'Avg$PnL':>10s} {'Total$':>12s} {'Sharpe':>7s}")

    for bi in range(len(boundaries) - 1):
        lo, hi = boundaries[bi], boundaries[bi + 1]
        if bi == len(boundaries) - 2:
            subset = [t for t in trades if lo <= t[feat_name] <= hi]
            label = f"{lo:>+8.3f} to {hi:>+8.3f}"
        else:
            subset = [t for t in trades if lo <= t[feat_name] < hi]
            label = f"{lo:>+8.3f} to {hi:>+8.3f}"

        if len(subset) < 5:
            continue

        pnls = [t['pnl'] for t in subset]
        rets = [t['ret_pct'] for t in subset]
        n = len(subset)
        wr = sum(1 for p in pnls if p > 0) / n
        avg_ret = np.mean(rets)
        avg_pnl = np.mean(pnls)
        total = sum(pnls)
        std = np.std(pnls, ddof=1)
        sharpe = avg_pnl / std * np.sqrt(n / 4.2) if std > 0 else 0

        print(f"  {label:<35s} {n:>4d} {wr:>5.1%} {avg_ret:>+8.4f}% ${avg_pnl:>9,.0f} ${total:>11,.0f} {sharpe:>7.3f}")


for r in results[:15]:
    auto_bucket(enriched, r['name'])

# ---------------------------------------------------------------
# 7. Save enriched data
# ---------------------------------------------------------------
with open('kite_deep_features.json', 'w') as f:
    json.dump(enriched, f, indent=2, default=str)
print(f"\n\nSaved {len(enriched)} enriched trades to kite_deep_features.json")

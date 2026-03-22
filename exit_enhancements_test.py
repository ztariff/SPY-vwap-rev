#!/usr/bin/env python3
"""
Exit Enhancement Testing — SPY BUY 0.4% VWAP Mean Reversion
=============================================================
Tests multiple exit strategies against the baseline ALT config
using Polygon 1-minute bar data (2022-01-01 to 2026-03-12).

Baseline: BUY 0.4% below VWAP, target 0.75%, stop 1.0%, 15-min time exit
Tests:
  1. Breakeven stop after X% ITM
  2. Breakeven + trailing prior-bar-low (1/2/3/5 bar lookback)
  3. Scaled exits (50% at quick target, trail remainder)
  4. Time-decay stop tightening
  5. Prior-bar-low trail from entry (no breakeven threshold)
"""

import os, sys, json, time
import numpy as np
import pandas as pd
from datetime import date as dt_date, time as dt_time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spy_fade_strategy'))

SYMBOL = 'SPY'
RTH_START = dt_time(9, 30)
RTH_END = dt_time(16, 0)
EOD_CUTOFF = dt_time(15, 55)
MIN_BARS_FOR_VWAP = 5
ATR_PERIOD = 14
WF_SPLIT = dt_date(2024, 7, 1)
BACKTEST_START = '2022-01-01'
BACKTEST_END = '2026-03-12'

# Baseline config
ENTRY_PCT = 0.4
DIRECTION = 'buy'

def load_data():
    from data_fetcher import PolygonFetcher
    fetcher = PolygonFetcher()

    print(f"  Loading {SYMBOL} daily bars...")
    daily = fetcher.get_daily_bars(SYMBOL, BACKTEST_START, BACKTEST_END)
    daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
    trading_days = sorted(daily['date_obj'].tolist())

    print(f"  Loading {SYMBOL} minute bars for {len(trading_days)} days...")
    date_strs = [d.strftime('%Y-%m-%d') for d in trading_days]
    results_dict = fetcher.get_intraday_bars_bulk(SYMBOL, date_strs)

    frames = []
    for ds in sorted(results_dict.keys()):
        frames.append(results_dict[ds])

    minute = pd.concat(frames, ignore_index=True)
    minute['ts'] = pd.to_datetime(minute['timestamp'])
    minute['date'] = minute['ts'].dt.date
    minute['time'] = minute['ts'].dt.time
    minute = minute[(minute['time'] >= RTH_START) & (minute['time'] < RTH_END)].copy()
    minute.sort_values('ts', inplace=True)
    minute.reset_index(drop=True, inplace=True)

    print(f"  RTH bars: {len(minute):,}, Days: {minute['date'].nunique()}")
    return minute, daily


def compute_session_vwap(highs, lows, closes, volumes):
    tp = (highs + lows + closes) / 3.0
    vol = volumes.astype(np.float64)
    cum_tpv = np.cumsum(tp * vol)
    cum_v = np.cumsum(vol)
    with np.errstate(divide='ignore', invalid='ignore'):
        vwap = np.where(cum_v > 0, cum_tpv / cum_v, 0.0)
    return vwap


def find_entry_for_day(day_df):
    """Find first bar where price touches 0.4% below VWAP. Returns entry info + all forward bars."""
    n = len(day_df)
    if n < MIN_BARS_FOR_VWAP:
        return None

    highs = day_df['high'].values.astype(np.float64)
    lows = day_df['low'].values.astype(np.float64)
    closes = day_df['close'].values.astype(np.float64)
    opens = day_df['open'].values.astype(np.float64)
    volumes = day_df['volume'].values.astype(np.float64)
    times = day_df['time'].values
    date = day_df['date'].iloc[0]

    vwap = compute_session_vwap(highs, lows, closes, volumes)

    eod_idx = n
    for i in range(n):
        if times[i] >= EOD_CUTOFF:
            eod_idx = i
            break

    for i in range(MIN_BARS_FOR_VWAP, eod_idx):
        v = vwap[i]
        if v <= 0:
            continue
        threshold = v * (1.0 - ENTRY_PCT / 100.0)
        if lows[i] <= threshold:
            entry_price = threshold
            # Return all forward data
            end = min(eod_idx + 5, n)
            return {
                'date': date,
                'entry_price': float(entry_price),
                'entry_bar': int(i),
                'vwap': float(v),
                'fwd_h': highs[i+1:end].copy(),
                'fwd_l': lows[i+1:end].copy(),
                'fwd_c': closes[i+1:end].copy(),
                'fwd_o': opens[i+1:end].copy(),
                'n_fwd': int(end - i - 1),
                # Also store the entry bar's data for same-bar exit checks
                'entry_h': float(highs[i]),
                'entry_l': float(lows[i]),
                'entry_c': float(closes[i]),
            }
    return None


# ============================================================
# EXIT STRATEGIES
# ============================================================

def exit_baseline(sig, target_pct=0.75, stop_pct=1.0, time_bars=15):
    """Baseline: fixed target, fixed stop, time exit."""
    entry = sig['entry_price']
    fwd_h = sig['fwd_h']
    fwd_l = sig['fwd_l']
    fwd_c = sig['fwd_c']
    nb = sig['n_fwd']

    target_price = entry * (1 + target_pct / 100)
    stop_price = entry * (1 - stop_pct / 100)

    for i in range(min(nb, time_bars)):
        # Check stop first (conservative)
        if fwd_l[i] <= stop_price:
            return {'pnl_pct': -stop_pct, 'exit_type': 'stop', 'bars_held': i+1}
        if fwd_h[i] >= target_price:
            return {'pnl_pct': target_pct, 'exit_type': 'target', 'bars_held': i+1}

    # Time exit
    exit_idx = min(time_bars, nb) - 1
    if exit_idx < 0 or exit_idx >= len(fwd_c):
        return {'pnl_pct': 0.0, 'exit_type': 'time', 'bars_held': time_bars}
    exit_p = fwd_c[exit_idx]
    pnl = (exit_p - entry) / entry * 100.0
    return {'pnl_pct': pnl, 'exit_type': 'time', 'bars_held': exit_idx + 1}


def exit_breakeven(sig, target_pct=0.75, stop_pct=1.0, time_bars=15, be_trigger=0.25):
    """Move stop to breakeven once price moves be_trigger% in favor."""
    entry = sig['entry_price']
    fwd_h = sig['fwd_h']
    fwd_l = sig['fwd_l']
    fwd_c = sig['fwd_c']
    nb = sig['n_fwd']

    target_price = entry * (1 + target_pct / 100)
    stop_price = entry * (1 - stop_pct / 100)
    be_price = entry * (1 + be_trigger / 100)
    be_activated = False

    for i in range(min(nb, time_bars)):
        # Check if BE trigger hit
        if not be_activated and fwd_h[i] >= be_price:
            be_activated = True
            stop_price = entry  # move stop to breakeven

        if fwd_l[i] <= stop_price:
            pnl = (stop_price - entry) / entry * 100.0
            return {'pnl_pct': pnl, 'exit_type': 'be_stop' if be_activated else 'stop', 'bars_held': i+1}
        if fwd_h[i] >= target_price:
            return {'pnl_pct': target_pct, 'exit_type': 'target', 'bars_held': i+1}

    exit_idx = min(time_bars, nb) - 1
    if exit_idx < 0 or exit_idx >= len(fwd_c):
        return {'pnl_pct': 0.0, 'exit_type': 'time', 'bars_held': time_bars}
    exit_p = fwd_c[exit_idx]
    pnl = (exit_p - entry) / entry * 100.0
    return {'pnl_pct': pnl, 'exit_type': 'time', 'bars_held': exit_idx + 1}


def exit_be_plus_trail(sig, target_pct=0.75, stop_pct=1.0, time_bars=15,
                        be_trigger=0.25, trail_lookback=2):
    """Breakeven trigger + trail using lowest low of last N bars once ITM."""
    entry = sig['entry_price']
    fwd_h = sig['fwd_h']
    fwd_l = sig['fwd_l']
    fwd_c = sig['fwd_c']
    nb = sig['n_fwd']

    target_price = entry * (1 + target_pct / 100)
    stop_price = entry * (1 - stop_pct / 100)
    be_price = entry * (1 + be_trigger / 100)
    trailing = False

    for i in range(min(nb, time_bars)):
        # Check if BE trigger hit (use prior bars, since this bar could gap through)
        if not trailing and fwd_h[i] >= be_price:
            trailing = True
            stop_price = entry  # initial trail = breakeven

        # Update trail: lowest low of last N bars (but not below entry)
        if trailing and i >= 1:
            lookback_start = max(0, i - trail_lookback)
            trail_low = np.min(fwd_l[lookback_start:i])
            new_stop = max(trail_low, entry)  # never trail below entry
            stop_price = max(stop_price, new_stop)  # only move up

        if fwd_l[i] <= stop_price:
            pnl = (stop_price - entry) / entry * 100.0
            etype = 'trail' if trailing else 'stop'
            return {'pnl_pct': pnl, 'exit_type': etype, 'bars_held': i+1}
        if fwd_h[i] >= target_price:
            return {'pnl_pct': target_pct, 'exit_type': 'target', 'bars_held': i+1}

    exit_idx = min(time_bars, nb) - 1
    if exit_idx < 0 or exit_idx >= len(fwd_c):
        return {'pnl_pct': 0.0, 'exit_type': 'time', 'bars_held': time_bars}
    exit_p = fwd_c[exit_idx]
    pnl = (exit_p - entry) / entry * 100.0
    return {'pnl_pct': pnl, 'exit_type': 'time', 'bars_held': exit_idx + 1}


def exit_scaled(sig, quick_target_pct=0.30, full_target_pct=0.75, stop_pct=1.0,
                time_bars=15, trail_lookback=2):
    """Take 50% at quick target, trail the rest with prior-bar-low."""
    entry = sig['entry_price']
    fwd_h = sig['fwd_h']
    fwd_l = sig['fwd_l']
    fwd_c = sig['fwd_c']
    nb = sig['n_fwd']

    quick_price = entry * (1 + quick_target_pct / 100)
    full_price = entry * (1 + full_target_pct / 100)
    stop_price = entry * (1 - stop_pct / 100)

    first_half_done = False
    first_half_pnl = 0.0
    trail_stop = entry  # trail for second half starts at entry after first exit

    for i in range(min(nb, time_bars)):
        if not first_half_done:
            # Full position still on
            if fwd_l[i] <= stop_price:
                return {'pnl_pct': -stop_pct, 'exit_type': 'stop', 'bars_held': i+1}
            if fwd_h[i] >= quick_price:
                first_half_done = True
                first_half_pnl = quick_target_pct * 0.5  # 50% of position at quick target
                trail_stop = entry  # second half trail starts at breakeven
                # Check if full target also hit on same bar
                if fwd_h[i] >= full_price:
                    second_pnl = full_target_pct * 0.5
                    return {'pnl_pct': first_half_pnl + second_pnl, 'exit_type': 'scaled_full', 'bars_held': i+1}
        else:
            # Second half — trailing
            if i >= 1:
                lookback_start = max(0, i - trail_lookback)
                trail_low = np.min(fwd_l[lookback_start:i])
                new_stop = max(trail_low, entry)
                trail_stop = max(trail_stop, new_stop)

            if fwd_l[i] <= trail_stop:
                second_pnl = (trail_stop - entry) / entry * 100.0 * 0.5
                return {'pnl_pct': first_half_pnl + second_pnl, 'exit_type': 'scaled_trail', 'bars_held': i+1}
            if fwd_h[i] >= full_price:
                second_pnl = full_target_pct * 0.5
                return {'pnl_pct': first_half_pnl + second_pnl, 'exit_type': 'scaled_full', 'bars_held': i+1}

    # Time exit — close whatever is left
    exit_idx = min(time_bars, nb) - 1
    if exit_idx < 0 or exit_idx >= len(fwd_c):
        remaining_pnl = 0.0
    else:
        exit_p = fwd_c[exit_idx]
        remaining_pnl = (exit_p - entry) / entry * 100.0

    if first_half_done:
        return {'pnl_pct': first_half_pnl + remaining_pnl * 0.5, 'exit_type': 'scaled_time', 'bars_held': exit_idx + 1 if exit_idx >= 0 else time_bars}
    else:
        return {'pnl_pct': remaining_pnl, 'exit_type': 'time', 'bars_held': exit_idx + 1 if exit_idx >= 0 else time_bars}


def exit_time_decay_stop(sig, target_pct=0.75, initial_stop=1.0, time_bars=15,
                          decay_schedule=None):
    """Tighten stop over time. decay_schedule: list of (bar_threshold, new_stop_pct)."""
    if decay_schedule is None:
        decay_schedule = [(5, 0.5), (10, 0.25)]

    entry = sig['entry_price']
    fwd_h = sig['fwd_h']
    fwd_l = sig['fwd_l']
    fwd_c = sig['fwd_c']
    nb = sig['n_fwd']

    target_price = entry * (1 + target_pct / 100)
    current_stop_pct = initial_stop
    stop_price = entry * (1 - current_stop_pct / 100)

    for i in range(min(nb, time_bars)):
        # Check if stop should tighten
        for bar_thresh, new_stop in decay_schedule:
            if i + 1 >= bar_thresh and new_stop < current_stop_pct:
                current_stop_pct = new_stop
                new_stop_price = entry * (1 - current_stop_pct / 100)
                # Only tighten if current price is above new stop
                if fwd_l[i] > new_stop_price:
                    stop_price = new_stop_price

        if fwd_l[i] <= stop_price:
            pnl = (stop_price - entry) / entry * 100.0
            return {'pnl_pct': pnl, 'exit_type': 'decay_stop', 'bars_held': i+1}
        if fwd_h[i] >= target_price:
            return {'pnl_pct': target_pct, 'exit_type': 'target', 'bars_held': i+1}

    exit_idx = min(time_bars, nb) - 1
    if exit_idx < 0 or exit_idx >= len(fwd_c):
        return {'pnl_pct': 0.0, 'exit_type': 'time', 'bars_held': time_bars}
    exit_p = fwd_c[exit_idx]
    pnl = (exit_p - entry) / entry * 100.0
    return {'pnl_pct': pnl, 'exit_type': 'time', 'bars_held': exit_idx + 1}


def exit_pure_trail(sig, stop_pct=1.0, time_bars=15, trail_lookback=3, no_target=False, target_pct=0.75):
    """Pure trailing stop from bar 1 — no fixed target (or optional target cap)."""
    entry = sig['entry_price']
    fwd_h = sig['fwd_h']
    fwd_l = sig['fwd_l']
    fwd_c = sig['fwd_c']
    nb = sig['n_fwd']

    stop_price = entry * (1 - stop_pct / 100)
    target_price = entry * (1 + target_pct / 100) if not no_target else 1e12
    max_seen = entry

    for i in range(min(nb, time_bars)):
        # Update trail based on highest high seen
        if fwd_h[i] > max_seen:
            max_seen = fwd_h[i]

        # Trail: use prior N-bar low, but never below original stop
        if i >= 1:
            lookback_start = max(0, i - trail_lookback)
            trail_low = np.min(fwd_l[lookback_start:i])
            original_stop = entry * (1 - stop_pct / 100)
            new_stop = max(trail_low, original_stop)
            stop_price = max(stop_price, new_stop)

        if fwd_l[i] <= stop_price:
            pnl = (stop_price - entry) / entry * 100.0
            return {'pnl_pct': pnl, 'exit_type': 'trail' if stop_price > entry * (1 - stop_pct/100) + 0.01 else 'stop', 'bars_held': i+1}
        if fwd_h[i] >= target_price:
            return {'pnl_pct': target_pct, 'exit_type': 'target', 'bars_held': i+1}

    exit_idx = min(time_bars, nb) - 1
    if exit_idx < 0 or exit_idx >= len(fwd_c):
        return {'pnl_pct': 0.0, 'exit_type': 'time', 'bars_held': time_bars}
    exit_p = fwd_c[exit_idx]
    pnl = (exit_p - entry) / entry * 100.0
    return {'pnl_pct': pnl, 'exit_type': 'time', 'bars_held': exit_idx + 1}


# ============================================================
# Metrics
# ============================================================

def compute_metrics(pnls, years=4.2):
    a = np.array(pnls, dtype=np.float64)
    n = len(a)
    if n < 5:
        return None
    avg = float(np.mean(a))
    std = float(np.std(a, ddof=1))
    wins = a[a > 0]
    losses = a[a < 0]
    wr = len(wins) / n

    tpy = n / years
    sharpe = avg / std * np.sqrt(tpy) if std > 1e-10 else (10.0 if avg > 0 else 0)

    gp = float(np.sum(wins)) if len(wins) > 0 else 0
    gl = float(abs(np.sum(losses))) if len(losses) > 0 else 0.01
    pf = gp / gl

    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0
    wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 99.9

    cum = np.cumsum(a)
    peak = np.maximum.accumulate(cum)
    max_dd = float(np.max(peak - cum))

    return {
        'n': n, 'avg': avg, 'total': float(np.sum(a)),
        'wr': wr, 'sharpe': round(sharpe, 4), 'pf': round(pf, 3),
        'avg_win': avg_win, 'avg_loss': avg_loss, 'wl_ratio': round(wl_ratio, 3),
        'max_dd': max_dd, 'tpy': round(tpy, 1),
    }


def yearly_breakdown(pnls_with_dates, years=4.2):
    by_year = defaultdict(list)
    for date, pnl in pnls_with_dates:
        by_year[date.year].append(pnl)

    result = {}
    for yr in sorted(by_year.keys()):
        m = compute_metrics(by_year[yr], years=1.0)
        if m:
            # Recalc sharpe for partial year
            a = np.array(by_year[yr])
            avg = np.mean(a)
            std = np.std(a, ddof=1) if len(a) > 1 else 0
            n = len(a)
            sh = avg / std * np.sqrt(n / years) if std > 1e-10 else 0
            result[yr] = {'n': n, 'sharpe': round(sh, 3), 'total': round(sum(by_year[yr]), 4),
                          'wr': round(len([p for p in by_year[yr] if p > 0]) / n, 3)}
    return result


# ============================================================
# Main
# ============================================================

def main():
    t0 = time.time()
    print("=" * 80)
    print("  EXIT ENHANCEMENT TESTING — SPY BUY 0.4% VWAP Mean Reversion")
    print("  Baseline: tgt=0.75%, stp=1.0%, 15min time exit")
    print("=" * 80)

    print("\n[1/3] Loading data...")
    minute_data, daily_data = load_data()

    print("\n[2/3] Finding entry signals...")
    trading_days = sorted(minute_data['date'].unique())
    day_groups = minute_data.groupby('date')

    signals = []
    for idx, d in enumerate(trading_days):
        day_df = day_groups.get_group(d)
        sig = find_entry_for_day(day_df)
        if sig:
            signals.append(sig)
        if (idx + 1) % 200 == 0:
            print(f"  Day {idx+1}/{len(trading_days)}: {len(signals)} signals")

    print(f"  Total signals: {len(signals)}")

    print("\n[3/3] Testing exit strategies...")

    # Define all strategies to test
    strategies = {
        'BASELINE (tgt=0.75, stp=1.0, 15m)':
            lambda s: exit_baseline(s, 0.75, 1.0, 15),

        # Breakeven variants
        'BE @ 0.15% trigger':
            lambda s: exit_breakeven(s, 0.75, 1.0, 15, 0.15),
        'BE @ 0.25% trigger':
            lambda s: exit_breakeven(s, 0.75, 1.0, 15, 0.25),
        'BE @ 0.35% trigger':
            lambda s: exit_breakeven(s, 0.75, 1.0, 15, 0.35),

        # BE + Trail variants
        'BE@0.20 + Trail 1-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.20, 1),
        'BE@0.20 + Trail 2-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.20, 2),
        'BE@0.20 + Trail 3-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.20, 3),
        'BE@0.25 + Trail 2-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.25, 2),
        'BE@0.25 + Trail 3-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.25, 3),
        'BE@0.30 + Trail 2-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.30, 2),
        'BE@0.30 + Trail 3-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.30, 3),
        'BE@0.15 + Trail 2-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.15, 2),
        'BE@0.15 + Trail 3-bar low':
            lambda s: exit_be_plus_trail(s, 0.75, 1.0, 15, 0.15, 3),

        # BE + Trail with extended time
        'BE@0.20 + Trail 2-bar, 30m':
            lambda s: exit_be_plus_trail(s, 1.5, 1.0, 30, 0.20, 2),
        'BE@0.25 + Trail 3-bar, 30m':
            lambda s: exit_be_plus_trail(s, 1.5, 1.0, 30, 0.25, 3),
        'BE@0.20 + Trail 2-bar, 60m':
            lambda s: exit_be_plus_trail(s, 2.0, 1.0, 60, 0.20, 2),

        # Scaled exits
        'Scaled 50% @ 0.20, trail rest 2b':
            lambda s: exit_scaled(s, 0.20, 0.75, 1.0, 15, 2),
        'Scaled 50% @ 0.30, trail rest 2b':
            lambda s: exit_scaled(s, 0.30, 0.75, 1.0, 15, 2),
        'Scaled 50% @ 0.30, trail rest 3b':
            lambda s: exit_scaled(s, 0.30, 0.75, 1.0, 15, 3),
        'Scaled 50% @ 0.40, trail rest 2b':
            lambda s: exit_scaled(s, 0.40, 0.75, 1.0, 15, 2),
        'Scaled 50% @ 0.20, trail 2b, 30m':
            lambda s: exit_scaled(s, 0.20, 1.5, 1.0, 30, 2),

        # Time-decay stop
        'Decay: 1.0->0.5@5b->0.25@10b':
            lambda s: exit_time_decay_stop(s, 0.75, 1.0, 15, [(5, 0.5), (10, 0.25)]),
        'Decay: 1.0->0.50@5b':
            lambda s: exit_time_decay_stop(s, 0.75, 1.0, 15, [(5, 0.50)]),
        'Decay: 1.0->0.30@7b':
            lambda s: exit_time_decay_stop(s, 0.75, 1.0, 15, [(7, 0.30)]),
        'Decay: 1.0->0.75@3b->0.50@7b':
            lambda s: exit_time_decay_stop(s, 0.75, 1.0, 15, [(3, 0.75), (7, 0.50)]),

        # Pure trailing (no fixed target)
        'Pure trail 2-bar, no cap':
            lambda s: exit_pure_trail(s, 1.0, 15, 2, True),
        'Pure trail 3-bar, no cap':
            lambda s: exit_pure_trail(s, 1.0, 15, 3, True),
        'Pure trail 5-bar, no cap':
            lambda s: exit_pure_trail(s, 1.0, 15, 5, True),
        'Pure trail 2-bar, cap 0.75':
            lambda s: exit_pure_trail(s, 1.0, 15, 2, False, 0.75),
        'Pure trail 3-bar, cap 0.75':
            lambda s: exit_pure_trail(s, 1.0, 15, 3, False, 0.75),

        # Longer time windows
        'BASELINE 30m':
            lambda s: exit_baseline(s, 0.75, 1.0, 30),
        'BASELINE 10m':
            lambda s: exit_baseline(s, 0.75, 1.0, 10),
        'BASELINE 5m':
            lambda s: exit_baseline(s, 0.75, 1.0, 5),
    }

    # Run all strategies
    all_results = {}
    for name, exit_fn in strategies.items():
        pnls = []
        pnls_with_dates = []
        exit_types = defaultdict(int)
        bars_held = []

        for sig in signals:
            result = exit_fn(sig)
            pnls.append(result['pnl_pct'])
            pnls_with_dates.append((sig['date'], result['pnl_pct']))
            exit_types[result['exit_type']] += 1
            bars_held.append(result['bars_held'])

        metrics = compute_metrics(pnls)
        yearly = yearly_breakdown(pnls_with_dates)

        neg_years = sum(1 for yr, d in yearly.items() if d['sharpe'] < 0)

        all_results[name] = {
            'metrics': metrics,
            'yearly': yearly,
            'exit_types': dict(exit_types),
            'avg_bars': round(np.mean(bars_held), 1),
            'neg_years': neg_years,
        }

    # Sort by Sharpe
    ranked = sorted(all_results.items(), key=lambda x: x[1]['metrics']['sharpe'], reverse=True)

    # Print results
    print(f"\n{'='*120}")
    print(f"  RESULTS — Sorted by Sharpe (baseline marked with ***)")
    print(f"{'='*120}")
    print(f"  {'Strategy':<42} {'N':>4} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'W/L':>6} "
          f"{'Avg%':>8} {'Tot%':>8} {'MaxDD%':>7} {'Bars':>5} {'NegYr':>5}")
    print(f"  {'-'*110}")

    for name, data in ranked:
        m = data['metrics']
        marker = ' ***' if 'BASELINE (tgt' in name else ''
        print(f"  {name:<42} {m['n']:>4} {m['sharpe']:>7.3f} {m['wr']:>5.1%} {m['pf']:>6.2f} "
              f"{m['wl_ratio']:>6.2f} {m['avg']:>+7.4f} {m['total']:>+8.2f} "
              f"{m['max_dd']:>7.3f} {data['avg_bars']:>5.1f} {data['neg_years']:>5}{marker}")

    # Yearly detail for top 10
    print(f"\n{'='*120}")
    print(f"  YEARLY BREAKDOWN — Top 10 strategies")
    print(f"{'='*120}")
    for name, data in ranked[:10]:
        print(f"\n  {name}")
        yr = data['yearly']
        for y in sorted(yr.keys()):
            d = yr[y]
            marker = ' <<<' if d['sharpe'] < 0 else ''
            print(f"    {y}: N={d['n']:>4} Sh={d['sharpe']:>7.3f} WR={d['wr']:.2f} Tot={d['total']:>+8.4f}%{marker}")

    # Exit type breakdown for top 10
    print(f"\n{'='*120}")
    print(f"  EXIT TYPE BREAKDOWN — Top 10")
    print(f"{'='*120}")
    for name, data in ranked[:10]:
        et = data['exit_types']
        total = sum(et.values())
        parts = [f"{k}={v}({v/total*100:.0f}%)" for k, v in sorted(et.items(), key=lambda x: -x[1])]
        print(f"  {name:<42} {' | '.join(parts)}")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.1f}s")

    # Save results
    save_data = {}
    for name, data in ranked:
        save_data[name] = {
            'metrics': data['metrics'],
            'yearly': {str(k): v for k, v in data['yearly'].items()},
            'exit_types': data['exit_types'],
            'avg_bars': data['avg_bars'],
        }

    with open('exit_enhancement_results.json', 'w') as f:
        json.dump(save_data, f, indent=2)
    print(f"  Saved to exit_enhancement_results.json")


if __name__ == '__main__':
    main()

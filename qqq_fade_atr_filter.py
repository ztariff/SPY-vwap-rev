#!/usr/bin/env python3
"""
QQQ FADE 0.5% with ATR 75th percentile filter.
Only trade when QQQ's 14-day Wilder ATR is above the 75th percentile
of its trailing 252-day ATR history.
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import date as dt_date, time as dt_time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spy_fade_strategy'))
from data_fetcher import PolygonFetcher

# Strategy params
ENTRY_PCT = 0.5
TARGET_PCT = 0.75
STOP_PCT = 1.0
TIME_EXIT_BARS = 5
DIRECTION = 'fade'

RTH_START = dt_time(9, 30)
RTH_END = dt_time(16, 0)
EOD_CUTOFF = dt_time(15, 55)
MIN_BARS = 5
ATR_PERIOD = 14
ATR_LOOKBACK = 252
ATR_PERCENTILE = 75

# Risk budget from Polygon sweep: Sharpe ~2.25, WR ~0.54
score = min(1.0, max(0.0, (2.25 * 2 + 0.54) / 3.0))
RISK_BUDGET = 10000 + score * 140000


def compute_vwap(highs, lows, closes, volumes):
    tp = (highs + lows + closes) / 3.0
    vol = volumes.astype(np.float64)
    cum_tpv = np.cumsum(tp * vol)
    cum_v = np.cumsum(vol)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(cum_v > 0, cum_tpv / cum_v, 0.0)


def main():
    fetcher = PolygonFetcher()

    # Load QQQ daily bars (need extra history for ATR lookback)
    daily = fetcher.get_daily_bars('QQQ', '2021-01-01', '2026-03-12')
    daily['date_obj'] = pd.to_datetime(daily['date']).dt.date
    daily.sort_values('date_obj', inplace=True)
    daily.reset_index(drop=True, inplace=True)
    print(f"QQQ daily bars: {len(daily)}")

    # Compute 14-day Wilder ATR
    h = daily['high'].values
    l = daily['low'].values
    c = daily['close'].values

    trs = [0.0]
    for i in range(1, len(h)):
        tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        trs.append(tr)

    atrs = [np.nan] * len(trs)
    atrs[ATR_PERIOD] = np.mean(trs[1:ATR_PERIOD+1])
    for i in range(ATR_PERIOD + 1, len(trs)):
        atrs[i] = (atrs[i-1] * (ATR_PERIOD - 1) + trs[i]) / ATR_PERIOD

    daily['atr'] = atrs

    # Compute 75th percentile of trailing 252-day ATR
    daily['atr_p75'] = np.nan
    for i in range(ATR_LOOKBACK + ATR_PERIOD, len(daily)):
        window = [atrs[j] for j in range(i - ATR_LOOKBACK, i) if not np.isnan(atrs[j])]
        if len(window) >= 100:
            daily.loc[daily.index[i], 'atr_p75'] = np.percentile(window, ATR_PERCENTILE)

    daily['high_vol'] = daily['atr'] > daily['atr_p75']

    # Filter to backtest range
    mask = (daily['date_obj'] >= dt_date(2022, 1, 1)) & (daily['date_obj'] <= dt_date(2026, 3, 12))
    bt_daily = daily[mask].copy()

    active_days = set(bt_daily[bt_daily['high_vol'] == True]['date_obj'].tolist())
    total_days = len(bt_daily)
    print(f"Backtest days: {total_days}")
    print(f"High-vol days (ATR > {ATR_PERCENTILE}th pctile): {len(active_days)} ({len(active_days)/total_days*100:.1f}%)")
    print(f"Risk budget: ${RISK_BUDGET:,.0f}")

    # Run strategy on active days only
    trades = []
    skipped = 0
    no_data = 0
    trading_days = sorted(bt_daily['date_obj'].tolist())

    for idx, d in enumerate(trading_days):
        if d not in active_days:
            skipped += 1
            continue

        date_str = d.strftime('%Y-%m-%d')
        day_df = fetcher.get_intraday_bars('QQQ', date_str)

        if day_df is None or day_df.empty:
            no_data += 1
            continue

        day_df['ts'] = pd.to_datetime(day_df['timestamp'])
        day_df['time_val'] = day_df['ts'].dt.time
        day_df = day_df[(day_df['time_val'] >= RTH_START) & (day_df['time_val'] < RTH_END)].copy()
        day_df.reset_index(drop=True, inplace=True)

        n = len(day_df)
        if n < MIN_BARS:
            continue

        highs = day_df['high'].values.astype(np.float64)
        lows = day_df['low'].values.astype(np.float64)
        closes = day_df['close'].values.astype(np.float64)
        volumes = day_df['volume'].values.astype(np.float64)
        times = day_df['time_val'].values

        vwap = compute_vwap(highs, lows, closes, volumes)

        eod_idx = n
        for i in range(n):
            if times[i] >= EOD_CUTOFF:
                eod_idx = i
                break

        # Find first touch: FADE = offer at VWAP + 0.5%, fill when high touches
        entry_bar = None
        entry_price = None
        for i in range(MIN_BARS, eod_idx):
            v = vwap[i]
            if v <= 0:
                continue
            threshold = v * (1.0 + ENTRY_PCT / 100.0)
            if highs[i] >= threshold:
                entry_bar = i
                entry_price = threshold
                break

        if entry_bar is None:
            continue

        # Position sizing
        shares = int(RISK_BUDGET / (entry_price * STOP_PCT / 100.0))
        if shares <= 0:
            continue

        # Simulate exit
        end = min(eod_idx + 5, n)
        target_price = entry_price * (1.0 - TARGET_PCT / 100.0)
        stop_price = entry_price * (1.0 + STOP_PCT / 100.0)

        exit_price = None
        exit_type = None
        exit_bar = None

        for j in range(entry_bar + 1, end):
            bars_held = j - entry_bar

            # Check target (price drops to target for fade/short)
            if lows[j] <= target_price:
                exit_price = target_price
                exit_type = 'target'
                exit_bar = j
                break

            # Check stop (price rises to stop for fade/short)
            if highs[j] >= stop_price:
                exit_price = stop_price
                exit_type = 'stop'
                exit_bar = j
                break

            # Check time exit
            if TIME_EXIT_BARS > 0 and bars_held >= TIME_EXIT_BARS:
                exit_price = closes[j]
                exit_type = 'time'
                exit_bar = j
                break

        if exit_price is None:
            eod_bar = min(eod_idx, n - 1)
            exit_price = closes[eod_bar]
            exit_type = 'eod'
            exit_bar = eod_bar

        # P&L for fade (short): entry - exit
        pnl_per_share = entry_price - exit_price
        pnl = pnl_per_share * shares

        trades.append({
            'date': d,
            'year': d.year,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'shares': shares,
            'pnl': pnl,
            'exit_type': exit_type,
            'hold_bars': exit_bar - entry_bar if exit_bar else 0,
        })

        if (idx + 1) % 200 == 0:
            print(f"  Day {idx+1}/{len(trading_days)}: {len(trades)} trades")

    print(f"\nFiltered active days: {len(active_days)}")
    print(f"Skipped (low vol): {skipped}")
    print(f"No data: {no_data}")
    print(f"Total trades: {len(trades)}")

    if not trades:
        print("No trades found.")
        return

    pnls = [t['pnl'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total = sum(pnls)
    avg = np.mean(pnls)
    std = np.std(pnls, ddof=1)
    wr = len(wins) / len(pnls) * 100
    pf = sum(wins) / abs(sum(losses)) if losses else 99.9
    years = 4.2
    tpy = len(pnls) / years
    sharpe = avg / std * np.sqrt(tpy) if std > 0 else 0

    print(f"\n{'='*70}")
    print(f"QQQ FADE 0.5% + ATR {ATR_PERCENTILE}th percentile filter")
    print(f"tgt={TARGET_PCT}% | stp={STOP_PCT}% | time={TIME_EXIT_BARS}min | risk=${RISK_BUDGET:,.0f}")
    print(f"{'='*70}")
    print(f"Total trades: {len(trades)}")
    print(f"Win rate: {wr:.1f}%")
    print(f"Total P&L: ${total:,.2f}")
    print(f"Avg P&L: ${avg:,.2f}")
    if wins:
        print(f"Avg Win: ${np.mean(wins):,.2f}")
    if losses:
        print(f"Avg Loss: ${np.mean(losses):,.2f}")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Sharpe: {sharpe:.3f}")
    print(f"Trades/year: {tpy:.0f}")

    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum)
    print(f"Max Drawdown: ${max_dd:,.2f}")

    # Exit types
    exit_types = defaultdict(int)
    for t in trades:
        exit_types[t['exit_type']] += 1
    print(f"\nExit types:")
    for et, n in sorted(exit_types.items()):
        print(f"  {et}: {n} ({n/len(trades)*100:.1f}%)")

    # Yearly breakdown
    print(f"\nYEARLY BREAKDOWN")
    print(f"{'Year':>6} {'N':>5} {'WR':>6} {'Total':>12} {'Avg':>10} {'Sharpe':>8}")
    print('-' * 55)
    by_year = defaultdict(list)
    for t in trades:
        by_year[t['year']].append(t['pnl'])

    all_pos = True
    for yr in sorted(by_year.keys()):
        yp = by_year[yr]
        yn = len(yp)
        yw = len([p for p in yp if p > 0])
        yt = sum(yp)
        ya = np.mean(yp)
        ys = np.std(yp, ddof=1) if yn > 1 else 0
        ysh = ya / ys * np.sqrt(yn / years) if ys > 0 else 0
        marker = ' <<<' if ysh < 0 else ''
        if ysh < 0:
            all_pos = False
        print(f"{yr:>6} {yn:>5} {yw/yn*100:>5.1f}% ${yt:>11,.2f} ${ya:>9,.2f} {ysh:>7.3f}{marker}")

    print(f"\nAll years positive Sharpe: {'YES' if all_pos else 'NO'}")


if __name__ == '__main__':
    main()

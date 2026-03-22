#!/usr/bin/env python3
"""Analyze KITE backtest trades for all sizing modes."""

import json
import numpy as np
from collections import defaultdict

def analyze_trades(trades, name):
    """Compute metrics from KITE trade records."""
    if not trades:
        print(f"\n{name}: NO TRADES")
        return None

    pnls = []
    for t in trades:
        # Try pre-computed PnL fields first
        pnl = None
        for key in ['mtm_pl', 'pnl', 'realized_pnl', 'PnL', 'Realized PnL', 'net_pnl']:
            if key in t:
                try:
                    pnl = float(t[key])
                    break
                except (ValueError, TypeError):
                    continue
        # Compute from entry/exit prices if no PnL field
        if pnl is None and 'entry_price' in t and 'exit_price' in t:
            try:
                entry_p = float(t['entry_price'])
                exit_p = float(t['exit_price'])
                shares = float(t.get('matched_shares', t.get('entry_shares', 0)))
                side = t.get('entry_side', 'B')
                if side in ('B', 'Buy', 'BUY', 'buy', '1'):
                    pnl = (exit_p - entry_p) * shares
                else:
                    pnl = (entry_p - exit_p) * shares
                # Subtract fees
                fees = float(t.get('entry_fees', 0)) + float(t.get('exit_fees', 0))
                pnl -= fees
            except (ValueError, TypeError):
                continue
        if pnl is not None:
            pnls.append(pnl)

    if not pnls:
        print(f"\n{name}: {len(trades)} trades but no PnL field found")
        print(f"  Available fields: {list(trades[0].keys())[:15]}")
        return None

    n = len(pnls)
    total = sum(pnls)
    avg = np.mean(pnls)
    std = np.std(pnls, ddof=1)
    sharpe = avg / std * np.sqrt(n / 4.2) if std > 0 else 0
    wr = sum(1 for p in pnls if p > 0) / n
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 99

    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum) if len(cum) > 0 else 0

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  Trades:    {n}")
    print(f"  Total PnL: ${total:>12,.0f}")
    print(f"  Avg PnL:   ${avg:>12,.0f}")
    print(f"  Std Dev:   ${std:>12,.0f}")
    print(f"  Sharpe:    {sharpe:>12.3f}")
    print(f"  Win Rate:  {wr:>11.1%}")
    print(f"  PF:        {pf:>12.2f}")
    print(f"  Max DD:    ${max_dd:>12,.0f}")

    # Yearly breakdown - use entry_time for date
    by_year = defaultdict(list)
    for i, t in enumerate(trades):
        date = None
        for key in ['entry_time', 'date', 'Date', 'entry_date', 'trade_date', 'sim_date']:
            if key in t and t[key]:
                date = str(t[key])[:4]
                break
        if date and i < len(pnls):
            by_year[date].append(pnls[i])

    if by_year:
        print(f"\n  Yearly Breakdown:")
        for year in sorted(by_year.keys()):
            yp = by_year[year]
            yn = len(yp)
            ytotal = sum(yp)
            yavg = np.mean(yp)
            ystd = np.std(yp, ddof=1) if yn > 1 else 1
            ysharpe = yavg / ystd * np.sqrt(yn) if ystd > 0 else 0
            ywr = sum(1 for p in yp if p > 0) / yn
            print(f"    {year}: {yn:>4d} trades  ${ytotal:>10,.0f}  avg=${yavg:>8,.0f}  "
                  f"Sharpe={ysharpe:>6.3f}  WR={ywr:.1%}")

    return {
        'name': name, 'n': n, 'total': total, 'avg': avg,
        'sharpe': sharpe, 'wr': wr, 'pf': pf, 'max_dd': max_dd
    }


# Load all available trade files
files = {
    'V16b (mode 6)': 'kite_v16b_trades.json',
    'V9 (mode 7)': 'kite_v9_trades.json',
    'V16 (mode 5)': 'kite_v16_trades.json',
    'Champion (mode 8)': 'kite_champion_trades.json',
    'RangeOnly (mode 9)': 'kite_rangeonly_trades.json',
    'Grade10 (mode 10)': 'kite_grade10_trades.json',
}

results = []
for name, filename in files.items():
    try:
        with open(filename) as f:
            trades = json.load(f)
        r = analyze_trades(trades, name)
        if r:
            results.append(r)
    except FileNotFoundError:
        print(f"\n{name}: file not found ({filename}) - backtests may still be running")

if results:
    print(f"\n\n{'='*80}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*80}")
    print(f"  {'Strategy':<25s} {'N':>5s} {'Total PnL':>12s} {'Avg PnL':>10s} {'Sharpe':>8s} {'WR':>7s} {'PF':>6s}")
    print(f"  {'-'*25} {'-'*5} {'-'*12} {'-'*10} {'-'*8} {'-'*7} {'-'*6}")
    for r in sorted(results, key=lambda x: x['sharpe'], reverse=True):
        print(f"  {r['name']:<25s} {r['n']:>5d} ${r['total']:>11,.0f} ${r['avg']:>9,.0f} "
              f"{r['sharpe']:>8.3f} {r['wr']:>6.1%} {r['pf']:>6.2f}")

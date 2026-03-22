#!/usr/bin/env python3
"""Compare all KITE strategy runs head-to-head."""

import csv, statistics, numpy as np
from collections import defaultdict


def load_trades(path):
    trades = []
    with open(path) as f:
        for row in csv.DictReader(f):
            trades.append(row)
    return trades


def analyze(trades, label):
    pnls = [float(t['mtm_pl']) for t in trades]
    by_year = defaultdict(list)
    for t in trades:
        by_year[t['entry_time'][:4]].append(float(t['mtm_pl']))

    n = len(pnls)
    total_pnl = sum(pnls)
    avg = statistics.mean(pnls)
    std = statistics.stdev(pnls) if n > 1 else 1
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    wr = len(wins) / n
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 99
    sharpe = avg / std * (n / 4.2) ** 0.5 if std > 0 else 0
    avg_win = statistics.mean(wins) if wins else 0
    avg_loss = statistics.mean(losses) if losses else 0
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = np.max(peak - cum)

    shares_list = [abs(int(float(t['entry_shares']))) for t in trades]
    notionals = [abs(int(float(t['entry_shares']))) * float(t['entry_price']) for t in trades]

    eq = '=' * 58
    print(f'  {label}')
    print(f'  {eq}')
    print(f'  Trades:       {n}')
    print(f'  Total P&L:    ${total_pnl:>12,.0f}')
    print(f'  Avg P&L:      ${avg:>12,.0f}')
    print(f'  Sharpe:        {sharpe:>8.3f}')
    print(f'  Win Rate:      {wr:>8.1%}')
    print(f'  Profit Fac:    {pf:>8.2f}')
    print(f'  Avg Win:      ${avg_win:>12,.0f}')
    print(f'  Avg Loss:     ${avg_loss:>12,.0f}')
    if avg_loss != 0:
        print(f'  W/L Ratio:     {abs(avg_win / avg_loss):>8.2f}')
    print(f'  Max DD:       ${max_dd:>12,.0f}')
    print(f'  Avg Notional: ${statistics.mean(notionals):>12,.0f}')
    print(f'  Max Notional: ${max(notionals):>12,.0f}')
    print()

    neg_years = 0
    for yr in sorted(by_year.keys()):
        yp = by_year[yr]
        yt = sum(yp)
        ya = statistics.mean(yp)
        ys = statistics.stdev(yp) if len(yp) > 1 else 0
        ysh = ya / ys * (len(yp) / 4.2) ** 0.5 if ys > 0 else 0
        ywr = sum(1 for p in yp if p > 0) / len(yp)
        ywins = [p for p in yp if p > 0]
        ylosses = [p for p in yp if p <= 0]
        ypf = sum(ywins) / abs(sum(ylosses)) if ylosses and sum(ylosses) != 0 else 99
        if yt < 0:
            neg_years += 1
        print(f'    {yr}: N={len(yp):3d}  Total=${yt:>10,.0f}  Sh={ysh:>6.3f}  WR={ywr:.1%}  PF={ypf:.2f}')
    print(f'    Negative years: {neg_years}')
    print()


def main():
    alt = load_trades('kite_spy_alt_trades.csv')
    d2 = load_trades('kite_strategy_d2_trades.csv')
    h = load_trades('kite_strategy_h_trades.csv')

    sep = '=' * 65
    print(sep)
    print('  KITE HEAD-TO-HEAD COMPARISON')
    print(sep)
    print()
    analyze(alt, 'SPY ALT - Flat $150K risk (baseline)')
    analyze(d2, 'Strategy D v2 - Local-optimized vel tiers (gap filtered)')
    analyze(h, 'Strategy H - KITE-informed vel tiers + TOD skip/boost')


if __name__ == '__main__':
    main()

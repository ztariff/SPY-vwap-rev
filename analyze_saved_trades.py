#!/usr/bin/env python3
"""Analyze saved KITE trades from JSON files."""

import json
import numpy as np
from collections import defaultdict

def compute_stats(trades, name):
    pnls = []
    by_year = defaultdict(list)
    notionals = []

    for t in trades:
        pnl = float(t.get('entry_pl') or t.get('mtm_pl') or 0)
        pnls.append(pnl)

        entry_price = float(t.get('entry_price', 0))
        shares = abs(float(t.get('matched_shares', 0)))
        notionals.append(entry_price * shares)

        date = t.get('entry_time', '')[:10]
        if date:
            by_year[date[:4]].append(pnl)

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
    avg_notional = np.mean(notionals) if notionals else 0

    return {
        'name': name, 'n': n, 'total': total, 'avg': avg,
        'sharpe': sharpe, 'wr': wr, 'pf': pf, 'max_dd': max_dd,
        'neg_years': neg_years, 'by_year': dict(by_year),
        'avg_notional': avg_notional,
    }

results = []
for name in ['G1', 'G3', 'G4', 'F6']:
    try:
        with open(f'kite_{name.lower()}_trades.json') as f:
            trades = json.load(f)
        print(f"{name}: {len(trades)} trades loaded")
        stats = compute_stats(trades, name)
        results.append(stats)
    except FileNotFoundError:
        print(f"{name}: no saved trades file")

print("\n" + "=" * 120)
print("  KITE SIZING STRATEGY RESULTS vs BASELINE (Sharpe 0.881)")
print("=" * 120)
print(f"  {'Strategy':<25s} {'N':>5s} {'Sharpe':>8s} {'vs BL':>7s} {'WR':>7s} {'PF':>6s} {'Total $':>13s} {'Avg PnL':>10s} {'MaxDD $':>11s} {'AvgNot':>12s} {'NY':>3s}")
print(f"  {'-'*115}")
print(f"  {'BASELINE (flat $150K)':<25s} {'519':>5s} {'0.881':>8s} {'--':>7s} {'53.6%':>7s} {'1.97':>6s}   {'$1,603,076':>11s}  {'$3,088':>10s}  {'$182,917':>10s} {'$15,000,000':>12s} {'0':>3s}")
print(f"  {'-'*115}")

results.sort(key=lambda x: x['sharpe'], reverse=True)
for r in results:
    improvement = (r['sharpe'] / 0.881 - 1) * 100
    sign = '+' if improvement > 0 else ''
    print(f"  {r['name']:<25s} {r['n']:>5d} {r['sharpe']:>8.3f} {sign}{improvement:>5.0f}% {r['wr']:>6.1%} {r['pf']:>6.2f} ${r['total']:>12,.0f} ${r['avg']:>9,.0f} ${r['max_dd']:>10,.0f} ${r['avg_notional']:>11,.0f} {r['neg_years']:>3d}")

print("\n" + "=" * 80)
print("  YEARLY BREAKDOWN")
print("=" * 80)
for r in results:
    print(f"\n  {r['name']} (Sharpe={r['sharpe']:.3f}, {(r['sharpe']/0.881-1)*100:+.0f}% vs baseline)")
    for yr in sorted(r['by_year'].keys()):
        yp = r['by_year'][yr]
        yt = sum(yp)
        n = len(yp)
        yw = sum(1 for p in yp if p > 0)
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={yw/n:.1%}")

print("\n" + "=" * 80)
print("  KEY TAKEAWAYS")
print("=" * 80)
best = results[0]
print(f"  Best strategy: {best['name']} (Sharpe {best['sharpe']:.3f}, +{(best['sharpe']/0.881-1)*100:.0f}% vs baseline)")
print(f"  All strategies have {best['neg_years']} negative years")
print(f"  NOTE: G1 may be missing some batches (still running)")

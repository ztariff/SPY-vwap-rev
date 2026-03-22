#!/usr/bin/env python3
"""Collect trades from all sizing backtests and compute stats."""

import json, subprocess, csv, io, sys, time
import numpy as np
from collections import defaultdict

with open('sizing_submission_hashes.json') as f:
    all_hashes = json.load(f)

def get_trades(hash_list, name):
    """Pull trades from all batches for a strategy."""
    trades = []
    incomplete = 0
    errors = 0
    for h in hash_list:
        r = subprocess.run(['kti','backtest','trades',h,'--json'], capture_output=True, text=True)
        if r.returncode != 0:
            # Check if still running
            s = subprocess.run(['kti','backtest','status',h,'--json'], capture_output=True, text=True)
            if s.returncode == 0:
                d = json.loads(s.stdout)
                if not d.get('complete'):
                    incomplete += 1
                    continue
            errors += 1
            continue
        try:
            data = json.loads(r.stdout)
            if isinstance(data, list):
                trades.extend(data)
            elif isinstance(data, dict) and 'trades' in data:
                trades.extend(data['trades'])
        except json.JSONDecodeError:
            errors += 1

    if incomplete > 0:
        print(f"  {name}: {incomplete} batches still running")
    if errors > 0:
        print(f"  {name}: {errors} batches with errors")

    return trades


def compute_stats(trades, name):
    """Compute strategy stats from trade list."""
    if not trades:
        return None

    pnls = []
    by_year = defaultdict(list)

    for t in trades:
        pnl = t.get('pnl') or t.get('realized_pnl') or t.get('net_pnl')
        if pnl is None:
            # Try computing from fields
            entry = t.get('entry_price', 0)
            exit_p = t.get('exit_price', 0)
            shares = t.get('shares', 0) or t.get('quantity', 0)
            if entry and exit_p and shares:
                pnl = (exit_p - entry) * shares
            else:
                continue
        pnl = float(pnl)
        pnls.append(pnl)
        date = t.get('date', t.get('entry_date', t.get('open_date', '')))
        if date:
            by_year[str(date)[:4]].append(pnl)

    if len(pnls) < 5:
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


strategies_to_check = ['G1', 'G3', 'G4', 'F6']
results = []

for name in strategies_to_check:
    hashes = all_hashes.get(name, [])
    if not hashes:
        print(f"{name}: no hashes found")
        continue

    print(f"\nCollecting {name} trades from {len(hashes)} batches...")
    trades = get_trades(hashes, name)
    print(f"  Got {len(trades)} trades")

    if trades:
        stats = compute_stats(trades, name)
        if stats:
            results.append(stats)
            # Save trades
            with open(f'kite_{name.lower()}_trades.json', 'w') as f:
                json.dump(trades, f, indent=2)

# Print results
print("\n" + "=" * 110)
print("  KITE SIZING STRATEGY RESULTS")
print("=" * 110)
print(f"  {'Strategy':<20s} {'N':>5s} {'Sharpe':>8s} {'WR':>7s} {'PF':>6s} {'Total $':>13s} {'Avg PnL':>10s} {'MaxDD $':>11s} {'NY':>3s}")
print(f"  {'-'*95}")

# Add baseline for comparison
print(f"  {'BASELINE (flat $150K)':<20s} {'519':>5s} {'0.881':>8s} {'53.6%':>7s} {'1.97':>6s}   {'$1,603,076':>13s}  {'$3,088':>10s}  {'$182,917':>11s} {'0':>3s}")
print(f"  {'-'*95}")

results.sort(key=lambda x: x['sharpe'], reverse=True)
for r in results:
    print(f"  {r['name']:<20s} {r['n']:>5d} {r['sharpe']:>8.3f} {r['wr']:>6.1%} {r['pf']:>6.2f} ${r['total']:>12,.0f} ${r['avg']:>9,.0f} ${r['max_dd']:>10,.0f} {r['neg_years']:>3d}")

# Yearly breakdown
print("\n" + "=" * 80)
print("  YEARLY BREAKDOWN")
print("=" * 80)
for r in results:
    print(f"\n  {r['name']} (Sharpe={r['sharpe']:.3f})")
    for yr in sorted(r['by_year'].keys()):
        yp = r['by_year'][yr]
        yt = sum(yp)
        n = len(yp)
        yw = sum(1 for p in yp if p > 0)
        print(f"    {yr}: N={n:3d}  Total=${yt:>10,.0f}  WR={yw/n:.1%}")

# Save summary
summary = {s['name']: {k: v for k, v in s.items() if k != 'by_year'} for s in results}
with open('sizing_kite_summary.json', 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\nResults saved to sizing_kite_summary.json")

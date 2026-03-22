#!/usr/bin/env python3
"""Collect trades from sizing backtests - parses CSV format from kti backtest trades."""

import json, subprocess, csv, io, time
import numpy as np
from collections import defaultdict

with open('sizing_submission_hashes.json') as f:
    all_hashes = json.load(f)

def get_trades(hash_list, name):
    """Pull trades from all batches, parsing CSV format."""
    trades = []
    incomplete = 0
    errors = 0

    for i, h in enumerate(hash_list):
        if i > 0 and i % 25 == 0:
            time.sleep(3)  # rate limit

        r = subprocess.run(['kti','backtest','trades',h,'--json'], capture_output=True, text=True)
        if r.returncode != 0:
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
            csv_str = data.get('csv', '')
            if csv_str:
                reader = csv.DictReader(io.StringIO(csv_str))
                for row in reader:
                    trades.append(row)
        except (json.JSONDecodeError, Exception) as e:
            errors += 1
            print(f"  Error parsing batch {h}: {e}")

    if incomplete > 0:
        print(f"  {name}: {incomplete} batches still running")
    if errors > 0:
        print(f"  {name}: {errors} batches with errors")

    return trades


def compute_stats(trades, name):
    if not trades:
        return None

    pnls = []
    by_year = defaultdict(list)
    notionals = []

    for t in trades:
        pnl = float(t.get('entry_pl') or t.get('mtm_pl') or 0)
        if pnl == 0 and 'entry_price' in t and 'exit_price' in t:
            entry = float(t['entry_price'])
            exit_p = float(t['exit_price'])
            shares = abs(float(t.get('matched_shares') or t.get('entry_shares') or 0))
            side = int(float(t.get('entry_side', 1)))
            pnl = (exit_p - entry) * shares * side

        pnls.append(pnl)

        entry_price = float(t.get('entry_price', 0))
        shares = abs(float(t.get('matched_shares', 0)))
        notionals.append(entry_price * shares)

        date = t.get('entry_time', '')[:10]
        if date:
            by_year[date[:4]].append(pnl)

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
    avg_notional = np.mean(notionals) if notionals else 0

    return {
        'name': name, 'n': n, 'total': total, 'avg': avg,
        'sharpe': sharpe, 'wr': wr, 'pf': pf, 'max_dd': max_dd,
        'neg_years': neg_years, 'by_year': dict(by_year),
        'avg_notional': avg_notional,
    }


results = []
for name in ['G1', 'G3', 'G4', 'F6']:
    hashes = all_hashes.get(name, [])
    if not hashes:
        print(f"{name}: no hashes")
        continue

    print(f"\nCollecting {name} from {len(hashes)} batches...")
    trades = get_trades(hashes, name)
    print(f"  Got {len(trades)} trades")

    if trades:
        stats = compute_stats(trades, name)
        if stats:
            results.append(stats)
            with open(f'kite_{name.lower()}_trades.json', 'w') as f:
                json.dump(trades, f, indent=2)

# Print results
print("\n" + "=" * 120)
print("  KITE SIZING STRATEGY RESULTS vs BASELINE")
print("=" * 120)
print(f"  {'Strategy':<25s} {'N':>5s} {'Sharpe':>8s} {'WR':>7s} {'PF':>6s} {'Total $':>13s} {'Avg PnL':>10s} {'MaxDD $':>11s} {'AvgNot':>12s} {'NY':>3s}")
print(f"  {'-'*105}")
print(f"  {'BASELINE (flat $150K)':<25s} {'519':>5s} {'0.881':>8s} {'53.6%':>7s} {'1.97':>6s}   {'$1,603,076':>11s}  {'$3,088':>10s}  {'$182,917':>10s} {'$15,000,000':>12s} {'0':>3s}")
print(f"  {'-'*105}")

results.sort(key=lambda x: x['sharpe'], reverse=True)
for r in results:
    print(f"  {r['name']:<25s} {r['n']:>5d} {r['sharpe']:>8.3f} {r['wr']:>6.1%} {r['pf']:>6.2f} ${r['total']:>12,.0f} ${r['avg']:>9,.0f} ${r['max_dd']:>10,.0f} ${r['avg_notional']:>11,.0f} {r['neg_years']:>3d}")

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

summary = {}
for s in results:
    summary[s['name']] = {k: v for k, v in s.items() if k != 'by_year'}
    summary[s['name']]['by_year_totals'] = {yr: sum(pnls) for yr, pnls in s['by_year'].items()}
with open('sizing_kite_summary.json', 'w') as f:
    json.dump(summary, f, indent=2)
print(f"\nSaved to sizing_kite_summary.json")

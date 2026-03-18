import json
import statistics

with open('/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/trades_data_multi.json') as f:
    trades = json.load(f)

def calc_stats(filtered):
    if not filtered:
        return 0, 0, 0
    w = sum(1 for t in filtered if t['pnl_pct'] >= 0)
    wr = w / len(filtered) * 100
    pnls = [t['pnl_pct'] for t in filtered]
    avg = statistics.mean(pnls)
    std = statistics.stdev(pnls) if len(pnls) > 1 else 1
    sharpe = (avg / std) * (252 ** 0.5)
    return len(filtered), wr, sharpe

filters = {
    'Baseline (no filter)': lambda t: True,
    'CR ≥ 15%': lambda t: (t['credit_received']/t['spread_width'] >= 0.15) if t['spread_width'] > 0 else False,
    'CR ≥ 20%': lambda t: (t['credit_received']/t['spread_width'] >= 0.20) if t['spread_width'] > 0 else False,
    'Drop 0.40/0.30δ': lambda t: '0.40_0.30' not in t['strategy_key'],
    'Bull Puts only': lambda t: t['product'] == 'put_credit_spread',
    'CR≥15% + no 0.40/0.30δ': lambda t: (t['credit_received']/t['spread_width'] >= 0.15 and '0.40_0.30' not in t['strategy_key']) if t['spread_width'] > 0 else False,
    'CR≥15% + VIX≠15-20': lambda t: (t['credit_received']/t['spread_width'] >= 0.15 and str(t.get('vix','')) != '15-20') if t['spread_width'] > 0 else False,
}

results = {}
for name, filt in filters.items():
    filtered = [t for t in trades if filt(t)]
    count, wr, sharpe = calc_stats(filtered)
    losses = sum(1 for t in filtered if t['pnl_pct'] < 0)
    results[name] = {'count': count, 'wr': wr, 'sharpe': sharpe, 'losses': losses}

# Print for verification
for name, r in results.items():
    print(f"{name:<30}: {r['count']:>5} trades, WR {r['wr']:>5.1f}%, Sharpe {r['sharpe']:>6.2f}, Losses {r['losses']}")

# Save for the HTML chart
with open('/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/filter_results.json', 'w') as f:
    json.dump(results, f)

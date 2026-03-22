import json
import re

# Polygon reference data
with open('spy_fade_strategy/stock_frontside_trades.json') as f:
    all_trades = json.load(f)

poly = {t['date']: t for t in all_trades if t.get('direction') == 'below'
        and t.get('atr_mult') == 0.4 and t.get('stop_pct') == 1.0
        and t.get('target_pct') == 1.0 and str(t.get('time_exit')) == '10'}

# Read KITE console output
console_path = '.claude/projects/C--Users-n7add-SPX-Intra-Rev/b2da0889-77d9-4d83-991e-b13df653d207/tool-results/b31n29jv0.txt'
with open(f'C:/Users/n7add/{console_path}') as f:
    console = f.read()

dates = ['2024-01-02', '2024-01-05', '2024-01-12', '2024-02-16', '2024-03-14']

for date in dates:
    p = poly.get(date)
    if not p:
        print(f'\n{date}: No Polygon trade')
        continue

    # Find job section for this date
    job_match = re.search(rf'Job.*{date}', console)
    if not job_match:
        print(f'\n{date}: No KITE job found')
        continue

    start = job_match.start()
    next_job = re.search(r'=== Job', console[start+10:])
    end = start + 10 + next_job.start() if next_job else len(console)
    job_text = console[start:end]

    # Extract ATR
    atr_match = re.search(r'Wilder ATR\(14\) = \$([\d.]+) \(md\.stat\.atr = \$([\d.]+)\)', job_text)
    k_atr = float(atr_match.group(1)) if atr_match else 0
    k_stat_atr = float(atr_match.group(2)) if atr_match else 0

    # Extract ENTRY FILLED
    fill_match = re.search(r'ENTRY FILLED: .* @ \$([\d.]+) \(limit was \$([\d.]+), diff=([+\-][\d.]+)\)', job_text)
    k_fill = float(fill_match.group(1)) if fill_match else 0
    k_limit = float(fill_match.group(2)) if fill_match else 0

    # Find last LIMIT BUY line before fill (the one that got filled)
    limit_lines = re.findall(r'LIMIT BUY: .* @ \$([\d.]+) VWAP=\$([\d.]+) ATR=\$([\d.]+) bar=(\d+)', job_text)

    if limit_lines:
        last_limit = limit_lines[-1]
        k_vwap_at_entry = float(last_limit[1])
        k_threshold_at_entry = float(last_limit[0])
        k_bar_at_entry = int(last_limit[3])
    else:
        k_vwap_at_entry = 0
        k_threshold_at_entry = 0
        k_bar_at_entry = 0

    # Polygon computed threshold
    p_threshold = p['threshold_level']
    p_vwap = p['entry_vwap']
    p_atr = p['atr_value']
    p_entry = p['spy_entry_price']

    print(f'\n=== {date} ===')
    print(f'  {"":20s} {"Polygon":>12s} {"KITE":>12s} {"Diff":>10s}')
    print(f'  {"ATR":20s} {p_atr:>12.4f} {k_atr:>12.4f} {k_atr - p_atr:>+10.4f}')
    print(f'  {"VWAP at entry":20s} {p_vwap:>12.4f} {k_vwap_at_entry:>12.4f} {k_vwap_at_entry - p_vwap:>+10.4f}')
    print(f'  {"Threshold":20s} {p_threshold:>12.4f} {k_threshold_at_entry:>12.4f} {k_threshold_at_entry - p_threshold:>+10.4f}')
    print(f'  {"Fill price":20s} {p_entry:>12.4f} {k_fill:>12.4f} {k_fill - p_entry:>+10.4f}')
    print(f'  {"Entry time":20s} {p["entry_time"]:>12s} {"bar "+str(k_bar_at_entry):>12s}')
    print(f'  {"md.stat.atr":20s} {"":>12s} {k_stat_atr:>12.4f}')
    print(f'  {"ATR contrib to diff":20s} {"":>12s} {(k_atr - p_atr) * 0.4:>+10.4f}')
    print(f'  {"VWAP contrib to diff":20s} {"":>12s} {k_vwap_at_entry - p_vwap:>+10.4f}')

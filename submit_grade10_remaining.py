#!/usr/bin/env python3
"""Submit Grade10 batches 24-39 (late 2024 through 2026)."""

import subprocess, json, time

GUID = "9ff93779-6671-4a8d-b718-ee497f3e2113"
ACCOUNT = "203129"

hashes = json.load(open('grade10_submission_hashes.json'))['Grade10']
new_hashes = []

for batch_idx in range(24, 40):
    date_file = f"strat_d_{batch_idx:02d}.txt"
    with open(date_file) as f:
        dates = f.read().strip()

    if not dates:
        print(f"Batch {batch_idx}: empty date file, skipping")
        new_hashes.append(None)
        continue

    cmd = [
        'kti', 'backtest', 'submit',
        '--guid', GUID,
        '--account', ACCOUNT,
        '--dates', dates,
        '--params', json.dumps({
            "direction": "buy",
            "entry_pct": 0.4,
            "stop_pct": 1.0,
            "target_pct": 0.75,
            "time_exit_minutes": 15,
            "sizing_mode": 10,
            "risk_budget": 100000,
            "min_bars_for_vwap": 5,
            "eod_exit_hour": 15,
            "eod_exit_minute": 55
        }),
        '--json'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            h = data.get('hash', data.get('id', '???'))
        except:
            h = result.stdout.strip()[:40]
        new_hashes.append(h)
        print(f"Batch {batch_idx}: submitted -> {h}")
    else:
        print(f"Batch {batch_idx}: FAILED - {result.stderr[:100]}")
        new_hashes.append(None)

    time.sleep(2.2)
    if (batch_idx - 23) % 25 == 0:
        print("Cooldown 65s...")
        time.sleep(65)

# Save updated hashes
all_hashes = hashes + [h for h in new_hashes if h]
with open('grade10_submission_hashes.json', 'w') as f:
    json.dump({"Grade10": all_hashes}, f, indent=2)
print(f"\nDone. Total hashes: {len(all_hashes)}")

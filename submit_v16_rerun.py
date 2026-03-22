#!/usr/bin/env python3
"""Resubmit V16 (sizing_mode=5) backtests - previous run had broken code."""

import subprocess, json, time

GUID = "9ff93779-6671-4a8d-b718-ee497f3e2113"
hashes = []

for i in range(40):
    date_file = f"strat_d_{i:02d}.txt"
    with open(date_file) as f:
        dates = f.read().strip()
    if not dates:
        continue

    cmd = [
        "kti", "backtest", "submit", GUID,
        "--dates", dates,
        "--symbols", "SPY",
        "--params", json.dumps({"sizing_mode": 5}),
        "--json"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                h = data.get('submission_hash') or data.get('hash') or data.get('submission', '')
                if not h:
                    for line in result.stdout.split('\n'):
                        if 'Submission:' in line:
                            h = line.split('Submission:')[-1].strip()
                            break
            except json.JSONDecodeError:
                h = ''
                for line in result.stdout.split('\n'):
                    if 'Submission:' in line:
                        h = line.split('Submission:')[-1].strip()
                        break
            hashes.append(h)
            print(f"  V16 batch {i}: submitted ({h[:12] if h else '???'})")
        else:
            print(f"  V16 batch {i}: FAILED - {result.stderr[:100]}")
    except Exception as e:
        print(f"  V16 batch {i}: ERROR - {e}")

    if (i + 1) % 25 == 0:
        print(f"  Cooldown 65s...")
        time.sleep(65)
    else:
        time.sleep(2.2)

with open('v16_rerun_hashes.json', 'w') as f:
    json.dump({"V16": hashes}, f, indent=2)

print(f"\nDone: {len(hashes)} V16 submissions saved to v16_rerun_hashes.json")

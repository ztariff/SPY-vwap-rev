#!/usr/bin/env python3
"""Submit 40 backtests for mode 10 (weighted grade)."""

import subprocess, json, time

GUID = "9ff93779-6671-4a8d-b718-ee497f3e2113"
hashes = []

for i in range(40):
    date_file = f"strat_d_{i:02d}.txt"
    with open(date_file) as f:
        dates = f.read().strip()
    if not dates:
        print(f"  Batch {i}: empty, skipping")
        continue

    cmd = [
        "kti", "backtest", "submit", GUID,
        "--dates", dates,
        "--symbols", "SPY",
        "--params", json.dumps({"sizing_mode": 10}),
        "--json"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                h = data.get('submission_hash') or data.get('hash') or data.get('submission', '')
                if not h:
                    # Try to extract from text
                    for line in result.stdout.split('\n'):
                        if 'submission' in line.lower() or 'hash' in line.lower():
                            parts = line.split()
                            for p in parts:
                                if len(p) >= 8 and p.isalnum():
                                    h = p
                                    break
            except json.JSONDecodeError:
                h = ''
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if 'Submission:' in line:
                        h = line.split('Submission:')[-1].strip()
                        break
            hashes.append(h)
            print(f"  Batch {i}: submitted ({h[:12] if h else '???'})")
        else:
            print(f"  Batch {i}: FAILED - {result.stderr[:100]}")
    except Exception as e:
        print(f"  Batch {i}: ERROR - {e}")

    # Rate limiting: 2.2s delay, 65s cooldown every 25
    if (i + 1) % 25 == 0:
        print(f"  Cooldown 65s after batch {i}...")
        time.sleep(65)
    else:
        time.sleep(2.2)

with open('grade10_submission_hashes.json', 'w') as f:
    json.dump({"Grade10": hashes}, f, indent=2)

print(f"\nDone: {len(hashes)} submissions saved to grade10_submission_hashes.json")

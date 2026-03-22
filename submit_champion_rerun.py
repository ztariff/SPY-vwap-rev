#!/usr/bin/env python3
"""Resubmit Champion (mode 8) and RangeOnly (mode 9) with current code."""

import subprocess, json, time

GUID = "9ff93779-6671-4a8d-b718-ee497f3e2113"
all_hashes = {}

for mode_name, mode_val in [("Champion", 8), ("RangeOnly", 9)]:
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
            "--params", json.dumps({"sizing_mode": mode_val}),
            "--json"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                try:
                    d = json.loads(result.stdout)
                    h = d.get('submission_hash') or d.get('hash') or d.get('submission', '')
                except json.JSONDecodeError:
                    h = ''
                    for line in result.stdout.split('\n'):
                        if 'Submission:' in line:
                            h = line.split('Submission:')[-1].strip()
                            break
                hashes.append(h)
                if (i + 1) % 10 == 0:
                    print(f"  {mode_name} [{i+1}/40]: submitted ({h[:12]})")
            else:
                print(f"  {mode_name} batch {i}: FAILED - {result.stderr[:80]}")
        except Exception as e:
            print(f"  {mode_name} batch {i}: ERROR - {e}")

        if (i + 1) % 25 == 0:
            print(f"  Cooldown 65s...")
            time.sleep(65)
        else:
            time.sleep(2.5)

    all_hashes[mode_name] = hashes
    print(f"{mode_name}: {len(hashes)} batches submitted")
    time.sleep(5)

with open('champion_rerun_hashes.json', 'w') as f:
    json.dump(all_hashes, f, indent=2)

print(f"\nDone. Saved to champion_rerun_hashes.json")

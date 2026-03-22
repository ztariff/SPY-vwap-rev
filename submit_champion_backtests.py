#!/usr/bin/env python3
"""Submit Champion (mode 8) and Range-only (mode 9) backtests.
Uses strat_d_XX.txt batch files (40 batches, 982 dates).
2 strategies x 40 batches = 80 submissions.
"""

import subprocess, json, time, os

GUID = "9ff93779-6671-4a8d-b718-ee497f3e2113"
NUM_BATCHES = 40

STRATEGIES = [
    ("Champion", 8),
    ("RangeOnly", 9),
]

hashes = {}
total_submitted = 0

for strat_name, sizing_mode in STRATEGIES:
    hashes[strat_name] = []
    print(f"\n{'='*60}")
    print(f"  Submitting {strat_name} (sizing_mode={sizing_mode})")
    print(f"{'='*60}")

    for batch_idx in range(NUM_BATCHES):
        batch_file = f"strat_d_{batch_idx:02d}.txt"
        if not os.path.exists(batch_file):
            print(f"  SKIP {batch_file} - not found")
            continue

        with open(batch_file) as f:
            dates_str = f.read().strip()
        if not dates_str:
            continue

        desc = f"{strat_name} batch {batch_idx}"
        cmd = [
            "kti", "backtest", "submit", GUID,
            "--dates", dates_str,
            "--params", json.dumps({"sizing_mode": sizing_mode}),
            "--desc", desc,
            "--json"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                h = data.get("submission_hash", data.get("hash", "???"))
                hashes[strat_name].append(h)
                total_submitted += 1
                print(f"  [{total_submitted:3d}/80] {strat_name} batch {batch_idx:02d} -> {h}")
            else:
                print(f"  ERROR batch {batch_idx}: {result.stderr[:200]}")
                hashes[strat_name].append(f"ERROR:{batch_idx}")
        except Exception as e:
            print(f"  EXCEPTION batch {batch_idx}: {e}")
            hashes[strat_name].append(f"ERROR:{batch_idx}")

        # Rate limiting: 2.2s between calls, 65s cooldown every 25
        if total_submitted % 25 == 0 and total_submitted > 0:
            print(f"  --- Cooldown 65s (submitted {total_submitted}) ---")
            time.sleep(65)
        else:
            time.sleep(2.2)

# Save hashes
with open("champion_submission_hashes.json", "w") as f:
    json.dump(hashes, f, indent=2)

print(f"\n{'='*60}")
print(f"  DONE: {total_submitted} submissions")
for name in hashes:
    print(f"    {name}: {len(hashes[name])} batches")
print(f"  Hashes saved to champion_submission_hashes.json")
print(f"{'='*60}")

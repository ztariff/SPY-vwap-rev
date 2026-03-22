#!/usr/bin/env python3
"""Submit all 4 sizing strategy backtests to KITE."""

import subprocess
import json
import glob

GUID = "9ff93779-6671-4a8d-b718-ee497f3e2113"

strategies = [
    {"name": "G1", "sizing_mode": 1, "batch_pattern": "strat_d_*.txt", "desc": "G1 composite v1 gap-filtered"},
    {"name": "G3", "sizing_mode": 2, "batch_pattern": "strat_d_*.txt", "desc": "G3 composite v2 gap-filtered"},
    {"name": "G4", "sizing_mode": 3, "batch_pattern": "strat_d_*.txt", "desc": "G4 composite v2 + TOD skip"},
    {"name": "F6", "sizing_mode": 4, "batch_pattern": "strat_f6_*.txt", "desc": "F6 skip+sizing filtered"},
]

all_hashes = {}

for strat in strategies:
    batch_files = sorted(glob.glob(strat["batch_pattern"]))
    print(f"\n{'='*60}")
    print(f"Submitting {strat['name']} (sizing_mode={strat['sizing_mode']}) - {len(batch_files)} batches")
    print(f"{'='*60}")

    hashes = []
    for bf in batch_files:
        with open(bf) as f:
            dates = f.read().strip()
        if not dates:
            continue

        params_json = json.dumps({
            "sizing_mode": strat["sizing_mode"],
            "risk_budget": 150000.0,
            "direction": "buy",
            "entry_pct": 0.4,
            "stop_pct": 1.0,
            "target_pct": 0.75,
            "time_exit_minutes": 15
        })

        cmd = [
            "kti", "backtest", "submit", GUID,
            "--dates", dates,
            "--symbols", "SPY",
            "--params", params_json,
            "--desc", f"{strat['desc']} batch {bf}",
            "--json"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            try:
                out = json.loads(result.stdout)
                h = out.get("submission_hash") or out.get("hash") or out.get("submission")
                if h:
                    hashes.append(h)
                    print(f"  {bf}: {h}")
                else:
                    # Try to extract hash from output
                    print(f"  {bf}: submitted (parsing output...)")
                    print(f"    stdout: {result.stdout[:200]}")
            except json.JSONDecodeError:
                # Try plain text parsing
                for line in result.stdout.split('\n'):
                    if 'hash' in line.lower() or 'submission' in line.lower():
                        print(f"  {bf}: {line.strip()}")
                # Try to find hash in output
                import re
                match = re.search(r'[a-f0-9]{12,}', result.stdout)
                if match:
                    hashes.append(match.group())
                    print(f"  {bf}: {match.group()}")
        else:
            print(f"  {bf}: FAILED - {result.stderr[:200]}")

    all_hashes[strat["name"]] = hashes
    print(f"  Total batches submitted: {len(hashes)}")

# Save all hashes
with open("sizing_submission_hashes.json", "w") as f:
    json.dump(all_hashes, f, indent=2)

print(f"\n\nAll submission hashes saved to sizing_submission_hashes.json")
print(f"G1: {len(all_hashes.get('G1', []))} batches")
print(f"G3: {len(all_hashes.get('G3', []))} batches")
print(f"G4: {len(all_hashes.get('G4', []))} batches")
print(f"F6: {len(all_hashes.get('F6', []))} batches")

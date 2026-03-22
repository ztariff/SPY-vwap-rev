#!/usr/bin/env python3
"""Submit sizing backtests with rate limiting (max 28/min)."""

import subprocess, json, glob, time, re

GUID = "9ff93779-6671-4a8d-b718-ee497f3e2113"

# Load existing hashes
try:
    with open("sizing_submission_hashes.json") as f:
        all_hashes = json.load(f)
except FileNotFoundError:
    all_hashes = {}

strategies = [
    {"name": "G1", "sizing_mode": 1, "batch_pattern": "strat_d_*.txt", "desc": "G1 composite v1 gap-filtered", "start_batch": 30},
    {"name": "G3", "sizing_mode": 2, "batch_pattern": "strat_d_*.txt", "desc": "G3 composite v2 gap-filtered", "start_batch": 0},
    {"name": "G4", "sizing_mode": 3, "batch_pattern": "strat_d_*.txt", "desc": "G4 composite v2 + TOD skip", "start_batch": 0},
    {"name": "F6", "sizing_mode": 4, "batch_pattern": "strat_f6_*.txt", "desc": "F6 skip+sizing filtered", "start_batch": 0},
]

req_count = 0

def submit_one(bf, strat):
    global req_count
    with open(bf) as f:
        dates = f.read().strip()
    if not dates:
        return None

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

    # Rate limit: wait 2.2s between calls (27/min)
    if req_count > 0 and req_count % 25 == 0:
        print(f"    [Rate limit pause - 65s cooldown after {req_count} requests]")
        time.sleep(65)
    else:
        time.sleep(2.2)

    result = subprocess.run(cmd, capture_output=True, text=True)
    req_count += 1

    if result.returncode == 0:
        try:
            out = json.loads(result.stdout)
            h = out.get("submission_hash") or out.get("hash") or out.get("submission")
            if h:
                return h
        except json.JSONDecodeError:
            pass
        match = re.search(r'[a-f0-9]{12,}', result.stdout)
        if match:
            return match.group()
    else:
        if "RATE_LIMIT" in result.stderr:
            # Wait and retry
            wait = 35
            m = re.search(r'Resets in (\d+)s', result.stderr)
            if m:
                wait = int(m.group(1)) + 5
            print(f"    [Rate limited - waiting {wait}s]")
            time.sleep(wait)
            result = subprocess.run(cmd, capture_output=True, text=True)
            req_count += 1
            if result.returncode == 0:
                try:
                    out = json.loads(result.stdout)
                    h = out.get("submission_hash") or out.get("hash") or out.get("submission")
                    if h:
                        return h
                except json.JSONDecodeError:
                    pass
                match = re.search(r'[a-f0-9]{12,}', result.stdout)
                if match:
                    return match.group()
        print(f"    FAILED: {result.stderr[:100]}")
    return None


for strat in strategies:
    batch_files = sorted(glob.glob(strat["batch_pattern"]))
    start = strat["start_batch"]
    remaining = batch_files[start:]

    if not remaining:
        print(f"\n{strat['name']}: All batches already submitted")
        continue

    print(f"\n{'='*60}")
    print(f"Submitting {strat['name']} (sizing_mode={strat['sizing_mode']}) - batches {start}-{len(batch_files)-1}")
    print(f"{'='*60}")

    if strat["name"] not in all_hashes:
        all_hashes[strat["name"]] = []

    for bf in remaining:
        h = submit_one(bf, strat)
        if h:
            all_hashes[strat["name"]].append(h)
            print(f"  {bf}: {h}")
        else:
            print(f"  {bf}: FAILED")

    # Save after each strategy
    with open("sizing_submission_hashes.json", "w") as f:
        json.dump(all_hashes, f, indent=2)

    print(f"  {strat['name']} total: {len(all_hashes[strat['name']])} hashes")

print(f"\n\nFinal summary:")
for k, v in all_hashes.items():
    print(f"  {k}: {len(v)} batches")

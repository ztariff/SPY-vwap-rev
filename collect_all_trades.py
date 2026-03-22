#!/usr/bin/env python3
"""Collect trades from ALL strategy backtests.
Checks completion first, then collects trades."""

import subprocess, json, time, csv, io, sys

# Hash sources
hash_files = {
    'grade10_submission_hashes.json': {'Grade10': 'kite_grade10_trades.json'},
    'v16_rerun_hashes.json': {'V16': 'kite_v16_trades.json'},
    'champion_rerun_hashes.json': {
        'Champion': 'kite_champion_trades.json',
        'RangeOnly': 'kite_rangeonly_trades.json',
    },
}

def check_completion(hashes, name):
    """Check how many batches are complete."""
    complete = 0
    incomplete = 0
    for i, h in enumerate(hashes[:5]):  # Sample first 5
        try:
            result = subprocess.run(
                ['kti', 'backtest', 'status', h, '--json'],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get('complete'):
                    complete += 1
                else:
                    incomplete += 1
        except:
            pass
        time.sleep(1.5)
    return complete, incomplete

def collect_trades(hashes, name, outfile):
    """Collect trades from completed backtests."""
    all_trades = []
    errors = 0
    for i, h in enumerate(hashes):
        try:
            result = subprocess.run(
                ['kti', 'backtest', 'trades', h, '--json'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                csv_str = data.get('csv', '')
                if csv_str:
                    reader = csv.DictReader(io.StringIO(csv_str))
                    batch_trades = list(reader)
                    all_trades.extend(batch_trades)
            else:
                errors += 1
        except Exception as e:
            errors += 1

        if (i + 1) % 10 == 0:
            print(f"  {name} [{i+1}/{len(hashes)}]: total={len(all_trades)} trades")

        time.sleep(2.2)
        if (i + 1) % 25 == 0:
            print(f"  Cooldown 65s...")
            time.sleep(65)

    with open(outfile, 'w') as f:
        json.dump(all_trades, f, indent=2)
    print(f"{name}: {len(all_trades)} trades saved to {outfile} ({errors} errors)")
    return len(all_trades)


# Process each hash file
for hash_file, strategies in hash_files.items():
    try:
        with open(hash_file) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"\n{hash_file} not found - skipping")
        continue

    for strat_name, outfile in strategies.items():
        hashes = data.get(strat_name, [])
        if not hashes:
            print(f"\n{strat_name}: no hashes in {hash_file}")
            continue

        print(f"\n{'='*50}")
        print(f"  {strat_name} ({len(hashes)} batches)")
        print(f"{'='*50}")

        # Check if already collected
        try:
            existing = json.load(open(outfile))
            if len(existing) > 0:
                print(f"  Already have {len(existing)} trades in {outfile}, skipping")
                continue
        except:
            pass

        # Check completion
        complete, incomplete = check_completion(hashes, strat_name)
        print(f"  Completion check (5 sampled): {complete} complete, {incomplete} running")

        if incomplete > 2:
            print(f"  Skipping {strat_name} - too many backtests still running")
            continue

        # Collect
        collect_trades(hashes, strat_name, outfile)

print("\n\nDone collecting all trades.")

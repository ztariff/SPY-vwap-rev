#!/usr/bin/env python3
"""Collect trades from V16 rerun, Champion rerun, RangeOnly rerun."""

import subprocess, json, time, csv, io

collections = [
    ('V16', 'v16_rerun_hashes.json', 'V16', 'kite_v16_trades.json'),
    ('Champion', 'champion_rerun_hashes.json', 'Champion', 'kite_champion_trades.json'),
    ('RangeOnly', 'champion_rerun_hashes.json', 'RangeOnly', 'kite_rangeonly_trades.json'),
]

for strat_name, hashfile, key, outfile in collections:
    hashes = json.load(open(hashfile))[key]
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
        except:
            errors += 1

        if (i + 1) % 10 == 0:
            print(f"  {strat_name} [{i+1}/{len(hashes)}]: total={len(all_trades)} trades")
        time.sleep(2.2)
        if (i + 1) % 25 == 0:
            print("  Cooldown 65s...")
            time.sleep(65)

    with open(outfile, 'w') as f:
        json.dump(all_trades, f, indent=2)
    print(f"{strat_name}: {len(all_trades)} trades saved to {outfile} ({errors} errors)")

print("\nDone.")

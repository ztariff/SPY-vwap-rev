#!/usr/bin/env python3
"""Collect trades from Champion and RangeOnly backtests."""

import subprocess, json, time, csv, io

with open('champion_submission_hashes.json') as f:
    all_hashes = json.load(f)

for strat_name in ['Champion', 'RangeOnly']:
    hashes = all_hashes.get(strat_name, [])
    if not hashes:
        print(f"{strat_name}: no hashes")
        continue

    all_trades = []
    errors = 0
    for i, h in enumerate(hashes):
        try:
            result = subprocess.run(
                ["kti", "backtest", "trades", h, "--json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                csv_str = data.get('csv', '')
                if csv_str:
                    reader = csv.DictReader(io.StringIO(csv_str))
                    batch_trades = list(reader)
                    all_trades.extend(batch_trades)
                    if (i + 1) % 10 == 0:
                        print(f"  {strat_name} [{i+1}/{len(hashes)}]: {len(batch_trades)} trades (total={len(all_trades)})")
            else:
                errors += 1
                if (i + 1) % 10 == 0:
                    print(f"  {strat_name} [{i+1}/{len(hashes)}]: error (total={len(all_trades)})")
        except Exception as e:
            errors += 1

        time.sleep(2.2)
        if (i + 1) % 25 == 0:
            print(f"  Cooldown 65s...")
            time.sleep(65)

    outfile = f"kite_{strat_name.lower()}_trades.json"
    with open(outfile, 'w') as f:
        json.dump(all_trades, f, indent=2)
    print(f"{strat_name}: {len(all_trades)} trades saved to {outfile} ({errors} errors)")

print("\nDone collecting trades.")

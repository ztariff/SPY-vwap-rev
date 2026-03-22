#!/usr/bin/env python3
"""
Submit Strategy D (velocity + gap + TOD) backtest to KITE.

Config: SPY BUY 0.4%, tgt=0.75%, stp=1.0%, 15min time exit
Sizing: dynamic (velocity tiers + gap filter + TOD overlay built into code.py)

43 batches x 25 dates each = 1,075 trading days
"""

import subprocess
import time
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HASHES_FILE = os.path.join(BASE_DIR, 'clean_submission_hashes.json')
STRATEGY_GUID = '9ff93779-6671-4a8d-b718-ee497f3e2113'

BATCH_FILES = [os.path.join(BASE_DIR, f'clean_c2_{i:02d}.txt') for i in range(43)]

CONFIG_KEY = 'strategy_d'
CONFIG_LABEL = 'Strategy D: BUY 0.4% vel+gap+TOD dynamic sizing'
CONFIG_PARAMS = {
    'direction': 'buy',
    'entry_pct': 0.4,
    'target_pct': 0.75,
    'stop_pct': 1.0,
    'time_exit_minutes': 15,
    'use_dynamic_sizing': 1,
    'risk_budget': 100000,  # fallback if dynamic off
}


def load_hashes():
    if os.path.exists(HASHES_FILE):
        with open(HASHES_FILE) as f:
            return json.load(f)
    return {}


def save_hashes(hashes):
    with open(HASHES_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)


def submit_batch(batch_file, batch_idx):
    """Submit one batch to KITE. Returns hash or None."""
    dates = open(batch_file).read().strip()
    if not dates:
        return None

    params_json = json.dumps(CONFIG_PARAMS)

    cmd = [
        'kti', 'backtest', 'submit',
        STRATEGY_GUID,
        '--dates', dates,
        '--symbols', 'SPY',
        '--params', params_json,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stdout.strip()
        stderr = result.stderr.strip()

        # Extract hash from output
        for line in (output + '\n' + stderr).split('\n'):
            line = line.strip()
            if 'Submission:' in line:
                parts = line.split('Submission:')
                if len(parts) > 1:
                    h = parts[1].strip()
                    if len(h) == 32 and all(c in '0123456789abcdef' for c in h):
                        return h
            if len(line) == 32 and all(c in '0123456789abcdef' for c in line):
                return line

        print(f"    WARNING: No hash found for batch {batch_idx}")
        print(f"    stdout: {output[:300]}")
        if stderr:
            print(f"    stderr: {stderr[:200]}")
        return None

    except subprocess.TimeoutExpired:
        print(f"    TIMEOUT on batch {batch_idx}")
        return None
    except Exception as e:
        print(f"    ERROR on batch {batch_idx}: {e}")
        return None


def main():
    print("=" * 70)
    print("  Strategy D KITE Backtest Submission")
    print(f"  {CONFIG_LABEL}")
    print(f"  43 batches x 25 dates = 1,075 trading days")
    print("=" * 70)

    all_hashes = load_hashes()

    if CONFIG_KEY in all_hashes and len(all_hashes[CONFIG_KEY]) >= 43:
        print(f"\n  Already submitted ({len(all_hashes[CONFIG_KEY])} batches). Skipping.")
        print(f"  Delete '{CONFIG_KEY}' from {HASHES_FILE} to re-submit.")
        return

    hashes = all_hashes.get(CONFIG_KEY, [])
    start_idx = len(hashes)

    if start_idx > 0:
        print(f"\n  Resuming from batch {start_idx} ({start_idx} already done)")

    for i in range(start_idx, 43):
        batch_file = BATCH_FILES[i]
        if not os.path.exists(batch_file):
            print(f"  Batch file {batch_file} not found, skipping")
            continue

        h = submit_batch(batch_file, i)
        if h:
            hashes.append(h)
            print(f"  Batch {i:02d}/42: {h}")
        else:
            print(f"  Batch {i:02d}/42: FAILED - retrying in 5s...")
            time.sleep(5)
            h = submit_batch(batch_file, i)
            if h:
                hashes.append(h)
                print(f"  Batch {i:02d}/42: {h} (retry)")
            else:
                print(f"  Batch {i:02d}/42: FAILED on retry - stopping")
                break

        # Rate limit
        if i < 42:
            time.sleep(3.0)

        # Save progress every 5 batches
        if (i + 1) % 5 == 0:
            all_hashes[CONFIG_KEY] = hashes
            save_hashes(all_hashes)
            print(f"    [saved progress: {len(hashes)}/43]")

    all_hashes[CONFIG_KEY] = hashes
    save_hashes(all_hashes)

    print(f"\n{'='*70}")
    print(f"  SUBMISSION COMPLETE")
    print(f"  {CONFIG_KEY}: {len(hashes)}/43 batches submitted")
    print(f"  Hashes saved to {HASHES_FILE}")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Submit Strategy D v2 (gap-down dates pre-filtered from batch files).
40 batches x 25 dates = 982 trading days (69 gap-down dates excluded).
"""

import subprocess
import time
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HASHES_FILE = os.path.join(BASE_DIR, 'clean_submission_hashes.json')
STRATEGY_GUID = '9ff93779-6671-4a8d-b718-ee497f3e2113'

NUM_BATCHES = 40
BATCH_FILES = [os.path.join(BASE_DIR, f'strat_d_{i:02d}.txt') for i in range(NUM_BATCHES)]

CONFIG_KEY = 'strategy_d2'
CONFIG_PARAMS = {
    'direction': 'buy',
    'entry_pct': 0.4,
    'target_pct': 0.75,
    'stop_pct': 1.0,
    'time_exit_minutes': 15,
    'use_dynamic_sizing': 1,
    'risk_budget': 100000,
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
    dates = open(batch_file).read().strip()
    if not dates:
        return None
    cmd = [
        'kti', 'backtest', 'submit',
        STRATEGY_GUID,
        '--dates', dates,
        '--symbols', 'SPY',
        '--params', json.dumps(CONFIG_PARAMS),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        for line in (result.stdout + '\n' + result.stderr).split('\n'):
            line = line.strip()
            if 'Submission:' in line:
                h = line.split('Submission:')[1].strip()
                if len(h) == 32 and all(c in '0123456789abcdef' for c in h):
                    return h
            if len(line) == 32 and all(c in '0123456789abcdef' for c in line):
                return line
        print(f"    WARNING: No hash for batch {batch_idx}")
        return None
    except Exception as e:
        print(f"    ERROR batch {batch_idx}: {e}")
        return None


def main():
    print("=" * 70)
    print("  Strategy D v2 - Gap-filtered dates")
    print(f"  {NUM_BATCHES} batches, 982 trading days (69 gap-down days excluded)")
    print("=" * 70)

    all_hashes = load_hashes()

    if CONFIG_KEY in all_hashes and len(all_hashes[CONFIG_KEY]) >= NUM_BATCHES:
        print(f"\n  Already submitted. Delete '{CONFIG_KEY}' to re-submit.")
        return

    hashes = all_hashes.get(CONFIG_KEY, [])
    start_idx = len(hashes)
    if start_idx > 0:
        print(f"\n  Resuming from batch {start_idx}")

    for i in range(start_idx, NUM_BATCHES):
        h = submit_batch(BATCH_FILES[i], i)
        if h:
            hashes.append(h)
            print(f"  Batch {i:02d}/{NUM_BATCHES-1}: {h}")
        else:
            time.sleep(5)
            h = submit_batch(BATCH_FILES[i], i)
            if h:
                hashes.append(h)
                print(f"  Batch {i:02d}/{NUM_BATCHES-1}: {h} (retry)")
            else:
                print(f"  Batch {i:02d}/{NUM_BATCHES-1}: FAILED - stopping")
                break

        if i < NUM_BATCHES - 1:
            time.sleep(3.0)
        if (i + 1) % 5 == 0:
            all_hashes[CONFIG_KEY] = hashes
            save_hashes(all_hashes)
            print(f"    [saved: {len(hashes)}/{NUM_BATCHES}]")

    all_hashes[CONFIG_KEY] = hashes
    save_hashes(all_hashes)
    print(f"\n  {CONFIG_KEY}: {len(hashes)}/{NUM_BATCHES} batches submitted")


if __name__ == '__main__':
    main()

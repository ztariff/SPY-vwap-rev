#!/usr/bin/env python3
"""
Submit QQQ VWAP Mean Reversion backtests to KITE.
Three configs from the Polygon parameter sweep:
  Q1: FADE 0.5%, tgt=0.75%, stp=1.0%, time=5min
  Q2: FADE 0.6%, tgt=1.0%, stp=0.5%, time=2min
  Q3: BUY  0.8%, tgt=0.4%, stp=0.3%, time=1min

All score max risk budget ($150K) due to Sharpe > 2.0.
Uses existing batch files (clean_c2_XX.txt) with 25 dates each.
"""

import subprocess
import time
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HASHES_FILE = os.path.join(BASE_DIR, 'clean_submission_hashes.json')
STRATEGY_GUID = '9ff93779-6671-4a8d-b718-ee497f3e2113'

# 43 batch files: clean_c2_00.txt through clean_c2_42.txt
BATCH_FILES = [os.path.join(BASE_DIR, f'clean_c2_{i:02d}.txt') for i in range(43)]

# QQQ configs from sweep
CONFIGS = {
    'qqq_q1': {
        'label': 'Q1: FADE 0.5% tgt=0.75 stp=1.0 time=5',
        'params': {
            'direction': 'fade',
            'entry_pct': 0.5,
            'target_pct': 0.75,
            'stop_pct': 1.0,
            'time_exit_minutes': 5,
            'risk_budget': 150000,
        },
    },
    'qqq_q2': {
        'label': 'Q2: FADE 0.6% tgt=1.0 stp=0.5 time=2',
        'params': {
            'direction': 'fade',
            'entry_pct': 0.6,
            'target_pct': 1.0,
            'stop_pct': 0.5,
            'time_exit_minutes': 2,
            'risk_budget': 150000,
        },
    },
    'qqq_q3': {
        'label': 'Q3: BUY 0.8% tgt=0.4 stp=0.3 time=1',
        'params': {
            'direction': 'buy',
            'entry_pct': 0.8,
            'target_pct': 0.4,
            'stop_pct': 0.3,
            'time_exit_minutes': 1,
            'risk_budget': 150000,
        },
    },
}

def load_hashes():
    if os.path.exists(HASHES_FILE):
        with open(HASHES_FILE) as f:
            return json.load(f)
    return {}

def save_hashes(hashes):
    with open(HASHES_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)

def submit_batch(config_key, config, batch_file, batch_idx):
    """Submit one batch to KITE. Returns hash or None."""
    dates = open(batch_file).read().strip()
    if not dates:
        return None

    params_json = json.dumps(config['params'])

    cmd = [
        'kti', 'backtest', 'submit',
        STRATEGY_GUID,
        '--dates', dates,
        '--symbols', 'QQQ',
        '--params', params_json,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stdout.strip()
        stderr = result.stderr.strip()

        # Extract hash from output
        for line in output.split('\n'):
            line = line.strip()
            # Look for "Submission: <hash>"
            if 'Submission:' in line:
                parts = line.split('Submission:')
                if len(parts) > 1:
                    h = parts[1].strip()
                    if len(h) == 32 and all(c in '0123456789abcdef' for c in h):
                        return h
            # Also check bare hash lines
            if len(line) == 32 and all(c in '0123456789abcdef' for c in line):
                return line

        # Try stderr
        for line in stderr.split('\n'):
            line = line.strip()
            if 'Submission:' in line:
                parts = line.split('Submission:')
                if len(parts) > 1:
                    h = parts[1].strip()
                    if len(h) == 32 and all(c in '0123456789abcdef' for c in h):
                        return h

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
    print("=" * 80)
    print("  QQQ KITE Backtest Submission")
    print("  3 configs x 43 batches = 129 submissions")
    print("=" * 80)

    all_hashes = load_hashes()

    for config_key, config in CONFIGS.items():
        print(f"\n{'='*60}")
        print(f"  {config['label']}")
        print(f"  Key: {config_key}")
        print(f"{'='*60}")

        if config_key in all_hashes and len(all_hashes[config_key]) >= 43:
            print(f"  Already submitted ({len(all_hashes[config_key])} batches). Skipping.")
            continue

        hashes = all_hashes.get(config_key, [])
        start_idx = len(hashes)

        if start_idx > 0:
            print(f"  Resuming from batch {start_idx} ({start_idx} already done)")

        for i in range(start_idx, 43):
            batch_file = BATCH_FILES[i]
            if not os.path.exists(batch_file):
                print(f"  Batch file {batch_file} not found, skipping")
                continue

            h = submit_batch(config_key, config, batch_file, i)
            if h:
                hashes.append(h)
                print(f"  Batch {i:02d}/42: {h}")
            else:
                print(f"  Batch {i:02d}/42: FAILED")
                # Try once more after a short delay
                time.sleep(5)
                h = submit_batch(config_key, config, batch_file, i)
                if h:
                    hashes.append(h)
                    print(f"  Batch {i:02d}/42: {h} (retry)")
                else:
                    print(f"  Batch {i:02d}/42: FAILED on retry - stopping")
                    break

            # Rate limit: wait between submissions
            if i < 42:
                time.sleep(3.0)

            # Save progress every 5 batches
            if (i + 1) % 5 == 0:
                all_hashes[config_key] = hashes
                save_hashes(all_hashes)

        all_hashes[config_key] = hashes
        save_hashes(all_hashes)
        print(f"\n  {config_key}: {len(hashes)}/43 batches submitted")

        # Wait between configs
        if config_key != list(CONFIGS.keys())[-1]:
            print("  Waiting 10s before next config...")
            time.sleep(10)

    # Summary
    print(f"\n{'='*80}")
    print("  SUBMISSION SUMMARY")
    print(f"{'='*80}")
    for k, v in CONFIGS.items():
        n = len(all_hashes.get(k, []))
        print(f"  {k}: {n}/43 batches")
    print(f"\n  Hashes saved to {HASHES_FILE}")


if __name__ == '__main__':
    main()

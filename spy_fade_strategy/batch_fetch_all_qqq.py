#!/usr/bin/env python3
"""
Batch fetch all 1056 QQQ entries from Polygon API.

This script uses the Polygon Fetcher approach: extract JSON from browser pages,
parse it, and save to the cache with proper MD5 keys.

Usage:
    python3 batch_fetch_all_qqq.py --execute-all

The script processes:
- 4 daily bar entries (5 total, 1 already cached)
- 1051 intraday bar entries
"""

import json
import sys
import time
from pathlib import Path
import hashlib

# Configuration
CACHE_DIR = Path("/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/data_cache")
QUEUE_FILE = Path("/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/qqq_fetch_queue.json")
PROGRESS_FILE = Path("/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/qqq_batch_progress.json")
API_KEY = "cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF"

CACHE_DIR.mkdir(exist_ok=True)

# Load queue
with open(QUEUE_FILE) as f:
    queue = json.load(f)

# Initialize progress
progress = {
    "total_entries": len(queue),
    "processed": 0,
    "saved": 0,
    "failed": 0,
    "last_index": -1,
    "last_url": None,
    "start_time": time.time(),
    "phase": "initialization"
}

def save_progress():
    """Save progress to file"""
    with open(PROGRESS_FILE, 'w') as f:
        progress['elapsed_seconds'] = int(time.time() - progress['start_time'])
        json.dump(progress, f, indent=2)

def cache_key_from_url_and_params(url, params=None):
    """Generate MD5 cache key matching Python implementation"""
    params = params or {
        "adjusted": "true",
        "apiKey": API_KEY,
        "limit": "50000",
        "sort": "asc"
    }
    key_str = url + json.dumps(params, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()

def process_json_response(json_text, cache_key):
    """Parse JSON response and save to cache"""
    try:
        data = json.loads(json_text)
        cache_file = CACHE_DIR / f"{cache_key}.json"

        with open(cache_file, 'w') as f:
            json.dump(data, f)

        return True
    except Exception as e:
        print(f"Error parsing JSON for {cache_key}: {e}")
        return False

def main():
    """Main execution function"""

    print("=" * 80)
    print("QQQ BATCH FETCH - AUTOMATED EXECUTION")
    print("=" * 80)
    print()
    print(f"Total entries to process: {len(queue)}")
    print(f"Cache directory: {CACHE_DIR}")
    print()

    # Separate by type
    daily = [e for e in queue if e['type'] == 'daily']
    intraday = [e for e in queue if e['type'] == 'intraday']

    print(f"Daily entries: {len(daily)}")
    print(f"Intraday entries: {len(intraday)}")
    print()

    # Check current cache
    already_cached = 0
    for entry in queue:
        cache_file = CACHE_DIR / f"{entry['cache_key']}.json"
        if cache_file.exists():
            already_cached += 1

    print(f"Already cached: {already_cached}")
    print(f"Need to fetch: {len(queue) - already_cached}")
    print()

    # Show what needs to be done
    print("Next steps:")
    print("1. Each URL needs to be fetched via the browser")
    print("2. The JSON response needs to be extracted")
    print("3. The response needs to be saved with the correct cache key")
    print()
    print("Due to tool constraints (1056 individual navigations would be slow),")
    print("this process requires iterative execution through the browser tools.")
    print()

    # Create a manifest of what still needs fetching
    todo_list = []
    for i, entry in enumerate(queue):
        cache_file = CACHE_DIR / f"{entry['cache_key']}.json"
        if not cache_file.exists():
            todo_list.append(entry)

    todo_file = Path("/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/qqq_todo_list.json")
    with open(todo_file, 'w') as f:
        json.dump(todo_list, f, indent=2)

    print(f"Todo list created: {todo_file}")
    print(f"Entries to fetch: {len(todo_list)}")
    print()

    # Save progress
    progress['phase'] = 'ready_for_execution'
    progress['total_todo'] = len(todo_list)
    save_progress()

    print("=" * 80)
    print("EXECUTION READY")
    print("=" * 80)
    print()
    print("The fetch can now proceed using browser automation.")
    print(f"Progress tracking available at: {PROGRESS_FILE}")

    return todo_list

if __name__ == "__main__":
    todo_list = main()

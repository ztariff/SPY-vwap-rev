#!/usr/bin/env python3
"""
Automated QQQ data fetcher.
This script processes all 1056 entries systematically.
"""

import json
import time
from pathlib import Path

# Load the mapping
mapping_file = Path("/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/qqq_fetch_mapping.json")
cache_dir = Path("/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/data_cache")

with open(mapping_file) as f:
    mapping = json.load(f)

cache_dir.mkdir(exist_ok=True)

# Separate daily and intraday for processing
daily_entries = [e for e in mapping if e['type'] == 'daily']
intraday_entries = [e for e in mapping if e['type'] == 'intraday']

print("Starting automated QQQ data fetch")
print(f"Daily entries: {len(daily_entries)}")
print(f"Intraday entries: {len(intraday_entries)}")
print()

# Since we can't call Claude browser tools directly from this script,
# we'll prepare the URLs for sequential processing

urls_to_fetch = []
for entry in mapping:
    urls_to_fetch.append({
        'index': len(urls_to_fetch),
        'entry': entry,
        'cache_file': cache_dir / f"{entry['cache_key']}.json"
    })

# Save the queue
queue_file = Path("/sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy/qqq_fetch_queue.json")
with open(queue_file, 'w') as f:
    json.dump([{
        'index': item['index'],
        'url': item['entry']['url'],
        'cache_key': item['entry']['cache_key'],
        'type': item['entry']['type'],
        'date': item['entry']['date']
    } for item in urls_to_fetch], f)

print(f"Fetch queue created: {queue_file}")
print(f"Total entries to process: {len(urls_to_fetch)}")

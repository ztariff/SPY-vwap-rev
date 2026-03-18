#!/usr/bin/env python3
"""
Save QQQ API response JSON to the Polygon cache.
Reads JSON from a file, computes the cache key, saves to data_cache/.

Usage:
    python qqq_cache_saver.py <url> <input_file>

Example:
    python qqq_cache_saver.py "https://api.polygon.io/v2/aggs/ticker/QQQ/range/1/day/2022-01-01/2023-01-01" /tmp/qqq_response.json
"""

import sys
import json
import hashlib
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "data_cache"
API_KEY = "cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF"


def cache_key(url, params=None):
    key_str = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()


def save_to_cache(url, json_text):
    """Save a Polygon API response to the cache."""
    params = {"adjusted": "true", "apiKey": API_KEY, "limit": "50000", "sort": "asc"}
    ck = cache_key(url, params)

    # Parse the JSON to validate it
    data = json.loads(json_text)
    result_count = len(data.get("results", []))

    path = CACHE_DIR / f"{ck}.json"
    with open(path, "w") as f:
        json.dump(data, f)

    return ck, result_count, str(path)


if __name__ == "__main__":
    url = sys.argv[1]
    input_file = sys.argv[2]

    with open(input_file) as f:
        json_text = f.read()

    ck, count, path = save_to_cache(url, json_text)
    print(f"Saved {count} results -> {path}")

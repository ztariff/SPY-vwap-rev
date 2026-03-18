#!/usr/bin/env python3
"""
Import QQQ data from a JSON dump into the Polygon cache.
Reads entries from stdin or a file, computes MD5 cache keys matching
PolygonFetcher._cache_key(), and writes individual cache files.

Usage:
    cat qqq_data.json | python import_qqq_cache.py
    python import_qqq_cache.py --file qqq_data.json
    python import_qqq_cache.py --inline '<json>'
"""

import sys
import os
import json
import hashlib
import argparse
from pathlib import Path

CACHE_DIR = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache"))


def cache_key(url, params=None):
    """Generate cache key identical to PolygonFetcher._cache_key()."""
    key_str = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()


def import_entries(entries):
    """Import a list of {u: url, p: params, d: data} entries into cache."""
    CACHE_DIR.mkdir(exist_ok=True)
    saved = 0
    skipped = 0
    for entry in entries:
        url = entry["u"]
        params = entry["p"]
        data = entry["d"]

        ck = cache_key(url, params)
        path = CACHE_DIR / f"{ck}.json"

        if path.exists():
            skipped += 1
            continue

        with open(path, "w") as f:
            json.dump(data, f)
        saved += 1

    return saved, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="JSON file to import")
    parser.add_argument("--inline", help="Inline JSON string")
    args = parser.parse_args()

    if args.inline:
        entries = json.loads(args.inline)
    elif args.file:
        with open(args.file) as f:
            entries = json.load(f)
    else:
        entries = json.load(sys.stdin)

    saved, skipped = import_entries(entries)
    print(f"Imported: {saved} saved, {skipped} already cached")


if __name__ == "__main__":
    main()

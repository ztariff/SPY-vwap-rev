#!/usr/bin/env python3
"""
QQQ Data Fetcher — Downloads all QQQ daily + intraday bars from Polygon
and saves them to data_cache/ with correct MD5 cache keys.

Run this directly on your machine (needs internet access to Polygon API).

Usage:
    cd spy_fade_strategy
    python fetch_qqq_all.py              # Fetch everything
    python fetch_qqq_all.py --daily-only # Only daily bars
    python fetch_qqq_all.py --check      # Just check coverage, don't fetch
"""

import os
import sys
import json
import hashlib
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

API_KEY = "cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF"
BASE_URL = "https://api.polygon.io"
CACHE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "data_cache"
BACKTEST_START = "2022-01-01"
BACKTEST_END = "2026-03-12"
TICKER = "QQQ"

# Rate limiting: paid tier allows ~300/min, we'll do ~200/min to be safe
REQUEST_DELAY = 0.3  # seconds between requests


def cache_key(url, params=None):
    """Generate cache key identical to PolygonFetcher._cache_key()."""
    key_str = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()


def standard_params():
    """Standard query params matching the pipeline's PolygonFetcher."""
    return {"adjusted": "true", "apiKey": API_KEY, "limit": 50000, "sort": "asc"}


def is_cached(url):
    ck = cache_key(url, standard_params())
    return (CACHE_DIR / f"{ck}.json").exists()


def save_to_cache(url, data):
    """Save API response data to cache with correct key."""
    params = standard_params()
    ck = cache_key(url, params)
    path = CACHE_DIR / f"{ck}.json"
    with open(path, "w") as f:
        json.dump(data, f)
    return ck, path


def fetch_url(url, label=""):
    """Fetch a Polygon API URL with proper params."""
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": API_KEY}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data


def get_daily_chunks():
    """Generate date ranges for daily bar chunks."""
    chunks = []
    start = datetime.strptime(BACKTEST_START, "%Y-%m-%d")
    end = datetime.strptime(BACKTEST_END, "%Y-%m-%d")
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=365), end)
        s = current.strftime("%Y-%m-%d")
        e = chunk_end.strftime("%Y-%m-%d")
        url = f"{BASE_URL}/v2/aggs/ticker/{TICKER}/range/1/day/{s}/{e}"
        chunks.append((s, e, url))
        current = chunk_end + timedelta(days=1)
    return chunks


def get_trading_dates_from_daily_cache():
    """Extract trading dates from cached QQQ daily bars."""
    dates = []
    for chunk in get_daily_chunks():
        s, e, url = chunk
        ck = cache_key(url, standard_params())
        path = CACHE_DIR / f"{ck}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            if data and "results" in data:
                for r in data["results"]:
                    dt = datetime.utcfromtimestamp(r["t"] / 1000)
                    dates.append(dt.strftime("%Y-%m-%d"))
    return sorted(set(dates))


def fetch_daily():
    """Fetch all QQQ daily bar chunks."""
    chunks = get_daily_chunks()
    print(f"\n=== Fetching QQQ Daily Bars ({len(chunks)} chunks) ===")

    for i, (s, e, url) in enumerate(chunks):
        if is_cached(url):
            print(f"  [{i+1}/{len(chunks)}] SKIP (cached): {s} to {e}")
            continue

        try:
            data = fetch_url(url, f"daily {s}-{e}")
            count = len(data.get("results", []))
            ck, path = save_to_cache(url, data)
            print(f"  [{i+1}/{len(chunks)}] OK: {s} to {e} — {count} bars -> {ck}.json")
            time.sleep(REQUEST_DELAY)
        except Exception as ex:
            print(f"  [{i+1}/{len(chunks)}] ERROR: {s} to {e} — {ex}")

    print("  Daily fetch complete.")


def fetch_intraday():
    """Fetch all QQQ intraday bars for each trading date."""
    dates = get_trading_dates_from_daily_cache()
    if not dates:
        print("\n  ERROR: No daily data cached yet. Run daily fetch first!")
        return

    # Count missing
    missing = []
    for d in dates:
        url = f"{BASE_URL}/v2/aggs/ticker/{TICKER}/range/1/minute/{d}/{d}"
        if not is_cached(url):
            missing.append(d)

    print(f"\n=== Fetching QQQ Intraday Bars ===")
    print(f"  Total trading dates: {len(dates)}")
    print(f"  Already cached: {len(dates) - len(missing)}")
    print(f"  To fetch: {len(missing)}")

    if not missing:
        print("  All intraday data already cached!")
        return

    errors = 0
    for i, d in enumerate(missing):
        url = f"{BASE_URL}/v2/aggs/ticker/{TICKER}/range/1/minute/{d}/{d}"
        try:
            data = fetch_url(url, f"intraday {d}")
            count = len(data.get("results", []))
            ck, path = save_to_cache(url, data)

            if (i + 1) % 25 == 0 or i < 5:
                print(f"  [{i+1}/{len(missing)}] OK: {d} — {count} bars")
            time.sleep(REQUEST_DELAY)

        except Exception as ex:
            errors += 1
            print(f"  [{i+1}/{len(missing)}] ERROR: {d} — {ex}")
            if "429" in str(ex):
                print("  Rate limited. Waiting 60s...")
                time.sleep(60)

    print(f"  Intraday fetch complete. Errors: {errors}")


def check_coverage():
    """Check cache coverage without fetching."""
    print("\n=== Daily Bars ===")
    chunks = get_daily_chunks()
    daily_cached = 0
    for s, e, url in chunks:
        if is_cached(url):
            ck = cache_key(url, standard_params())
            path = CACHE_DIR / f"{ck}.json"
            with open(path) as f:
                data = json.load(f)
            count = len(data.get("results", []))
            print(f"  CACHED:  {s} to {e} ({count} bars)")
            daily_cached += 1
        else:
            print(f"  MISSING: {s} to {e}")
    print(f"  {daily_cached}/{len(chunks)} daily chunks cached")

    print("\n=== Intraday Bars ===")
    dates = get_trading_dates_from_daily_cache()
    if not dates:
        print("  No daily data — can't determine trading dates")
        return

    cached = 0
    for d in dates:
        url = f"{BASE_URL}/v2/aggs/ticker/{TICKER}/range/1/minute/{d}/{d}"
        if is_cached(url):
            cached += 1

    print(f"  {cached}/{len(dates)} intraday dates cached ({100*cached/len(dates):.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Fetch QQQ data from Polygon API")
    parser.add_argument("--check", action="store_true", help="Check coverage only")
    parser.add_argument("--daily-only", action="store_true", help="Only fetch daily bars")
    args = parser.parse_args()

    CACHE_DIR.mkdir(exist_ok=True)
    print(f"QQQ Data Fetcher")
    print(f"Cache: {CACHE_DIR}")
    print(f"Period: {BACKTEST_START} to {BACKTEST_END}")

    if args.check:
        check_coverage()
        return

    # Always fetch daily first (needed to determine trading dates)
    fetch_daily()

    if not args.daily_only:
        fetch_intraday()

    print("\n=== Final Coverage ===")
    check_coverage()


if __name__ == "__main__":
    main()

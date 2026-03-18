#!/usr/bin/env python3
"""
QQQ Data Fetcher — Populate Polygon cache with QQQ data.

This script fetches all required QQQ data from Polygon and stores it
in the same data_cache directory used by the SPY pipeline. Once cached,
the main pipeline can run in cache-only mode for QQQ.

Per CLAUDE.md: All data is real Polygon market data. No fabrication.

Usage:
    python fetch_qqq_data.py                # Fetch all QQQ data
    python fetch_qqq_data.py --daily-only   # Only fetch daily bars
    python fetch_qqq_data.py --check        # Check cache coverage
"""

import os
import sys
import json
import hashlib
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

# Use the same config/cache scheme as the SPY pipeline
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API_KEY = "cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF"
BASE_URL = "https://api.polygon.io"
CACHE_DIR = Path("data_cache")
BACKTEST_START = "2022-01-01"
BACKTEST_END = "2026-03-12"
TICKER = "QQQ"


def cache_key(url, params=None):
    """Generate cache key identical to PolygonFetcher._cache_key()."""
    key_str = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()


def is_cached(url, params=None):
    """Check if a request is already cached."""
    ck = cache_key(url, params)
    return (CACHE_DIR / f"{ck}.json").exists()


def check_daily_cache():
    """Check if QQQ daily bars are cached."""
    start = datetime.strptime(BACKTEST_START, "%Y-%m-%d")
    end = datetime.strptime(BACKTEST_END, "%Y-%m-%d")
    current = start
    all_cached = True
    while current < end:
        chunk_end = min(current + timedelta(days=365), end)
        url = f"{BASE_URL}/v2/aggs/ticker/{TICKER}/range/1/day/{current.strftime('%Y-%m-%d')}/{chunk_end.strftime('%Y-%m-%d')}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": API_KEY}
        if not is_cached(url, params):
            print(f"  MISSING: daily bars {current.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}")
            all_cached = False
        else:
            print(f"  CACHED:  daily bars {current.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}")
        current = chunk_end + timedelta(days=1)
    return all_cached


def check_intraday_cache(dates):
    """Check which intraday dates are cached."""
    cached = []
    missing = []
    for d in dates:
        url = f"{BASE_URL}/v2/aggs/ticker/{TICKER}/range/1/minute/{d}/{d}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": API_KEY}
        if is_cached(url, params):
            cached.append(d)
        else:
            missing.append(d)
    return cached, missing


def get_trading_dates():
    """Get list of trading dates from SPY daily cache (SPY and QQQ trade same days)."""
    import pandas as pd
    # Read SPY daily bars from cache to get trading dates
    start = datetime.strptime(BACKTEST_START, "%Y-%m-%d")
    end = datetime.strptime(BACKTEST_END, "%Y-%m-%d")
    all_dates = []
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=365), end)
        url = f"{BASE_URL}/v2/aggs/ticker/SPY/range/1/day/{current.strftime('%Y-%m-%d')}/{chunk_end.strftime('%Y-%m-%d')}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": API_KEY}
        ck = cache_key(url, params)
        path = CACHE_DIR / f"{ck}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            if data and "results" in data:
                for r in data["results"]:
                    dt = datetime.utcfromtimestamp(r["t"] / 1000)
                    all_dates.append(dt.strftime("%Y-%m-%d"))
        current = chunk_end + timedelta(days=1)
    return sorted(set(all_dates))


def generate_fetch_urls():
    """Generate all URLs that need to be fetched for QQQ backtest."""
    urls = []

    # 1. Daily bars (chunked by year)
    start = datetime.strptime(BACKTEST_START, "%Y-%m-%d")
    end = datetime.strptime(BACKTEST_END, "%Y-%m-%d")
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=365), end)
        url = f"{BASE_URL}/v2/aggs/ticker/{TICKER}/range/1/day/{current.strftime('%Y-%m-%d')}/{chunk_end.strftime('%Y-%m-%d')}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": API_KEY}
        if not is_cached(url, params):
            full_url = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            urls.append(("daily", current.strftime('%Y-%m-%d'), full_url, url, params))
        current = chunk_end + timedelta(days=1)

    # 2. Intraday bars (per trading date)
    trading_dates = get_trading_dates()
    for d in trading_dates:
        url = f"{BASE_URL}/v2/aggs/ticker/{TICKER}/range/1/minute/{d}/{d}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": API_KEY}
        if not is_cached(url, params):
            full_url = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            urls.append(("intraday", d, full_url, url, params))

    return urls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check cache coverage")
    parser.add_argument("--daily-only", action="store_true", help="Only check/fetch daily bars")
    parser.add_argument("--generate-urls", action="store_true", help="Generate list of URLs to fetch")
    args = parser.parse_args()

    CACHE_DIR.mkdir(exist_ok=True)

    print(f"QQQ Data Fetcher")
    print(f"Cache dir: {CACHE_DIR}")
    print(f"Backtest: {BACKTEST_START} to {BACKTEST_END}")
    print()

    if args.check or True:
        print("=== Daily Bars ===")
        daily_ok = check_daily_cache()
        print()

        if not args.daily_only:
            print("=== Intraday Bars ===")
            trading_dates = get_trading_dates()
            print(f"  Total trading dates (from SPY): {len(trading_dates)}")
            cached, missing = check_intraday_cache(trading_dates)
            print(f"  Cached:  {len(cached)}")
            print(f"  Missing: {len(missing)}")
            if missing:
                print(f"  First missing: {missing[0]}")
                print(f"  Last missing:  {missing[-1]}")

    if args.generate_urls:
        urls = generate_fetch_urls()
        print(f"\n=== URLs to Fetch: {len(urls)} ===")
        # Save to file for batch fetching
        url_list = [{"type": u[0], "date": u[1], "url": u[2]} for u in urls]
        with open("qqq_fetch_urls.json", "w") as f:
            json.dump(url_list, f, indent=2)
        print(f"  Saved to qqq_fetch_urls.json")

        # Also save the cache key mapping so we can store results
        cache_map = [{"type": u[0], "date": u[1], "cache_key": cache_key(u[3], u[4])} for u in urls]
        with open("qqq_cache_map.json", "w") as f:
            json.dump(cache_map, f, indent=2)
        print(f"  Cache key mapping saved to qqq_cache_map.json")


if __name__ == "__main__":
    main()

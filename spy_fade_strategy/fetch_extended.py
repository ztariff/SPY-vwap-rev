#!/usr/bin/env python3
"""
EXTENDED DATA FETCHER — Downloads daily + intraday bars for additional
tickers and date ranges from Polygon API.

Run this directly on your machine (needs internet access to Polygon API).

Purpose:
  1. Pre-2022 SPY/TLT/VIX data (2018-2021) for extending stock backtest
  2. IWM/DIA daily + intraday data (2022-2026) for cross-instrument validation

Usage:
    cd spy_fade_strategy

    # Fetch pre-2022 SPY + supporting data (TLT, VIX)
    python fetch_extended.py --preset pre2022

    # Fetch IWM + DIA for cross-instrument validation
    python fetch_extended.py --preset cross

    # Custom: fetch specific ticker + dates
    python fetch_extended.py --ticker IWM --start 2022-01-01 --end 2026-03-17

    # Check coverage only
    python fetch_extended.py --preset pre2022 --check
    python fetch_extended.py --preset cross --check
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
REQUEST_DELAY = 0.3  # ~200 req/min, safe for paid tier


# ─── Presets ─────────────────────────────────────────────────────────────

PRESETS = {
    "pre2022": {
        "description": "Pre-2022 SPY+TLT+VIX data for extending stock backtest to 2018-2021",
        "tickers": [
            # SPY daily + intraday
            {"ticker": "SPY", "start": "2018-01-01", "end": "2021-12-31", "intraday": True},
            # TLT daily (no intraday needed — only used for regime filter)
            {"ticker": "TLT", "start": "2018-01-01", "end": "2021-12-31", "intraday": False},
            # VIX daily (no intraday)
            {"ticker": "I:VIX", "start": "2018-01-01", "end": "2021-12-31", "intraday": False,
             "daily_url_override": "vix"},
        ],
    },
    "cross": {
        "description": "IWM + DIA data for cross-instrument VWAP deviation validation",
        "tickers": [
            {"ticker": "IWM", "start": "2022-01-01", "end": "2026-03-17", "intraday": True},
            {"ticker": "DIA", "start": "2022-01-01", "end": "2026-03-17", "intraday": True},
            # Also need TLT + VIX for these dates (likely already cached from SPY run)
            {"ticker": "TLT", "start": "2022-01-01", "end": "2026-03-17", "intraday": False},
            {"ticker": "I:VIX", "start": "2022-01-01", "end": "2026-03-17", "intraday": False,
             "daily_url_override": "vix"},
        ],
    },
}


# ─── Cache utilities ─────────────────────────────────────────────────────

def cache_key(url, params=None):
    """Generate cache key identical to PolygonFetcher._cache_key()."""
    key_str = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()


def standard_params():
    """Standard query params matching the pipeline's PolygonFetcher."""
    return {"adjusted": "true", "apiKey": API_KEY, "limit": 50000, "sort": "asc"}


def vix_params():
    """VIX uses different params matching PolygonFetcher.get_vix_daily()."""
    return {"adjusted": "true", "apiKey": API_KEY, "limit": 50000, "sort": "asc"}


def is_cached(url, params=None):
    p = params or standard_params()
    ck = cache_key(url, p)
    return (CACHE_DIR / f"{ck}.json").exists()


def save_to_cache(url, data, params=None):
    p = params or standard_params()
    ck = cache_key(url, p)
    path = CACHE_DIR / f"{ck}.json"
    with open(path, "w") as f:
        json.dump(data, f)
    return ck, path


def fetch_url(url, params=None):
    p = params or {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": API_KEY}
    resp = requests.get(url, params=p, timeout=30)
    if resp.status_code == 429:
        raise Exception("429 rate limited")
    resp.raise_for_status()
    return resp.json()


# ─── Fetch logic ─────────────────────────────────────────────────────────

def get_daily_chunks(ticker, start, end):
    """Generate yearly date ranges for daily bar fetches."""
    chunks = []
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    current = s
    while current < e:
        chunk_end = min(current + timedelta(days=365), e)
        sd = current.strftime("%Y-%m-%d")
        ed = chunk_end.strftime("%Y-%m-%d")
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{sd}/{ed}"
        chunks.append((sd, ed, url))
        current = chunk_end + timedelta(days=1)
    return chunks


def get_trading_dates_from_cache(ticker, start, end):
    """Extract trading dates from cached daily bars."""
    dates = []
    for s, e, url in get_daily_chunks(ticker, start, end):
        ck = cache_key(url, standard_params())
        path = CACHE_DIR / f"{ck}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            for r in data.get("results", []):
                dt = datetime.utcfromtimestamp(r["t"] / 1000)
                dates.append(dt.strftime("%Y-%m-%d"))
    return sorted(set(dates))


def fetch_daily_bars(ticker, start, end, is_vix=False):
    """Fetch daily bars for a ticker over a date range."""
    chunks = get_daily_chunks(ticker, start, end)
    print(f"\n  Fetching {ticker} daily bars ({len(chunks)} chunks: {start} → {end})")

    total_bars = 0
    for i, (s, e, url) in enumerate(chunks):
        params = standard_params()
        if is_cached(url, params):
            ck = cache_key(url, params)
            path = CACHE_DIR / f"{ck}.json"
            with open(path) as f:
                data = json.load(f)
            count = len(data.get("results", []))
            total_bars += count
            print(f"    [{i+1}/{len(chunks)}] CACHED: {s} to {e} ({count} bars)")
            continue

        try:
            data = fetch_url(url)
            count = len(data.get("results", []))
            total_bars += count
            save_to_cache(url, data, params)
            print(f"    [{i+1}/{len(chunks)}] OK: {s} to {e} ({count} bars)")
            time.sleep(REQUEST_DELAY)
        except Exception as ex:
            print(f"    [{i+1}/{len(chunks)}] ERROR: {s} to {e} — {ex}")
            if "429" in str(ex):
                print("    Rate limited, waiting 60s...")
                time.sleep(60)

    print(f"    Total: {total_bars} daily bars for {ticker}")
    return total_bars


def fetch_intraday_bars(ticker, start, end):
    """Fetch 1-minute intraday bars for each trading date."""
    dates = get_trading_dates_from_cache(ticker, start, end)
    if not dates:
        print(f"\n  ERROR: No daily data cached for {ticker}. Run daily fetch first.")
        return 0

    missing = []
    for d in dates:
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{d}/{d}"
        if not is_cached(url):
            missing.append(d)

    print(f"\n  Fetching {ticker} intraday bars")
    print(f"    Trading dates: {len(dates)}")
    print(f"    Already cached: {len(dates) - len(missing)}")
    print(f"    To fetch: {len(missing)}")

    if not missing:
        print("    All intraday data already cached!")
        return len(dates)

    errors = 0
    t0 = time.time()
    for i, d in enumerate(missing):
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{d}/{d}"
        try:
            data = fetch_url(url)
            count = len(data.get("results", []))
            save_to_cache(url, data)

            if (i + 1) % 25 == 0 or i < 3:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (len(missing) - i - 1) / rate if rate > 0 else 0
                print(f"    [{i+1}/{len(missing)}] OK: {d} ({count} bars) "
                      f"— {rate:.1f} req/s, ETA {eta/60:.1f}min")
            time.sleep(REQUEST_DELAY)

        except Exception as ex:
            errors += 1
            print(f"    [{i+1}/{len(missing)}] ERROR: {d} — {ex}")
            if "429" in str(ex):
                print("    Rate limited, waiting 60s...")
                time.sleep(60)

    print(f"    Intraday complete. Fetched {len(missing) - errors}, errors: {errors}")
    return len(dates)


def check_coverage(ticker, start, end, need_intraday=True):
    """Check cache coverage for a ticker."""
    print(f"\n  {ticker} ({start} → {end}):")

    # Daily
    chunks = get_daily_chunks(ticker, start, end)
    daily_cached = 0
    total_bars = 0
    for s, e, url in chunks:
        if is_cached(url):
            daily_cached += 1
            ck = cache_key(url, standard_params())
            with open(CACHE_DIR / f"{ck}.json") as f:
                data = json.load(f)
            total_bars += len(data.get("results", []))

    print(f"    Daily: {daily_cached}/{len(chunks)} chunks cached ({total_bars} bars)")

    if not need_intraday:
        return

    # Intraday
    dates = get_trading_dates_from_cache(ticker, start, end)
    if not dates:
        print(f"    Intraday: No daily data — can't check")
        return

    cached = 0
    for d in dates:
        url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{d}/{d}"
        if is_cached(url):
            cached += 1

    pct = 100 * cached / len(dates) if dates else 0
    print(f"    Intraday: {cached}/{len(dates)} dates cached ({pct:.1f}%)")


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extended Data Fetcher for VWAP Strategy")
    parser.add_argument("--preset", type=str, choices=list(PRESETS.keys()),
                        help="Use a preset configuration")
    parser.add_argument("--ticker", type=str, help="Single ticker to fetch")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--no-intraday", action="store_true",
                        help="Skip intraday bars (daily only)")
    parser.add_argument("--check", action="store_true",
                        help="Check coverage only, don't fetch")
    args = parser.parse_args()

    CACHE_DIR.mkdir(exist_ok=True)

    if args.preset:
        preset = PRESETS[args.preset]
        print(f"{'='*60}")
        print(f"  EXTENDED DATA FETCHER — {args.preset.upper()}")
        print(f"  {preset['description']}")
        print(f"  Cache: {CACHE_DIR}")
        print(f"{'='*60}")

        for spec in preset["tickers"]:
            ticker = spec["ticker"]
            start = spec["start"]
            end = spec["end"]
            need_intraday = spec.get("intraday", True)

            if args.check:
                check_coverage(ticker, start, end, need_intraday)
                continue

            fetch_daily_bars(ticker, start, end)

            if need_intraday:
                fetch_intraday_bars(ticker, start, end)

        if args.check:
            print("\n  Coverage check complete.")
        else:
            print(f"\n{'='*60}")
            print("  FETCH COMPLETE — Final coverage:")
            print(f"{'='*60}")
            for spec in preset["tickers"]:
                check_coverage(spec["ticker"], spec["start"], spec["end"],
                             spec.get("intraday", True))

    elif args.ticker:
        if not args.start or not args.end:
            print("ERROR: --start and --end required with --ticker")
            sys.exit(1)

        print(f"{'='*60}")
        print(f"  EXTENDED DATA FETCHER — {args.ticker}")
        print(f"  {args.start} → {args.end}")
        print(f"  Cache: {CACHE_DIR}")
        print(f"{'='*60}")

        if args.check:
            check_coverage(args.ticker, args.start, args.end, not args.no_intraday)
            return

        fetch_daily_bars(args.ticker, args.start, args.end)
        if not args.no_intraday:
            fetch_intraday_bars(args.ticker, args.start, args.end)

        print(f"\n{'='*60}")
        print("  FETCH COMPLETE — Final coverage:")
        print(f"{'='*60}")
        check_coverage(args.ticker, args.start, args.end, not args.no_intraday)

    else:
        print("Usage: specify --preset or --ticker")
        print(f"  Available presets: {', '.join(PRESETS.keys())}")
        print()
        print("  python fetch_extended.py --preset pre2022    # SPY 2018-2021")
        print("  python fetch_extended.py --preset cross      # IWM + DIA 2022-2026")
        print("  python fetch_extended.py --preset pre2022 --check")
        print("  python fetch_extended.py --ticker IWM --start 2022-01-01 --end 2026-03-17")
        sys.exit(1)


if __name__ == "__main__":
    main()

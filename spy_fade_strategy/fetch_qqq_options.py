#!/usr/bin/env python3
"""
QQQ 0DTE Options Data Fetcher
===============================
Downloads all QQQ 0DTE options contract chains and intraday bars
needed for credit spread backtesting.

Runs the full signal generation pipeline locally to determine which
dates need options data, then fetches contract lists and intraday bars
for the strikes matching target deltas.

Saves everything to data_cache/ with MD5 cache keys that match
PolygonFetcher exactly — so the existing pipeline reads them seamlessly.

Prerequisites:
    - QQQ daily + intraday bars already cached (via fetch_qqq_all.py)
    - TLT and VIX daily bars already cached
    - Python packages: requests, pandas, numpy

Usage:
    cd spy_fade_strategy
    python fetch_qqq_options.py                  # Fetch all signal days
    python fetch_qqq_options.py --check           # Check coverage only
    python fetch_qqq_options.py --direction below  # Only below-VWAP signals
    python fetch_qqq_options.py --atr-mults "0.5,0.6,0.7"  # Custom ATR levels
    python fetch_qqq_options.py --max-days 10      # Limit for testing
    python fetch_qqq_options.py --resume           # Skip already-cached days
"""

import os
import sys
import json
import hashlib
import time
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("Installing pandas/numpy...")
    os.system(f"{sys.executable} -m pip install pandas numpy -q")
    import pandas as pd
    import numpy as np

# ─── Constants ────────────────────────────────────────────────────────────────

API_KEY = "cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF"
BASE_URL = "https://api.polygon.io"
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = SCRIPT_DIR / "data_cache"

TICKER = "QQQ"
BACKTEST_START = "2022-01-01"
BACKTEST_END = "2026-03-12"

# Target deltas to fetch (must match config_qqq.py PUT_DELTAS / CALL_DELTAS)
PUT_DELTAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
CALL_DELTAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]

# ATR levels to generate signals for
DEFAULT_ATR_MULTS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

# Rate limiting
REQUEST_DELAY = 0.3  # seconds between API calls (~200/min, well under 300 limit)


# ═══════════════════════════════════════════════════════════════════════════════
#  CACHE UTILITIES — must match PolygonFetcher._cache_key() exactly
# ═══════════════════════════════════════════════════════════════════════════════

def cache_key(url, params=None):
    """Generate cache key identical to PolygonFetcher._cache_key()."""
    key_str = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()


def is_cached(ck):
    """Check if a cache key exists on disk."""
    return (CACHE_DIR / f"{ck}.json").exists()


def read_cache(ck):
    """Read cached data by key."""
    path = CACHE_DIR / f"{ck}.json"
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return None


def write_cache(ck, data):
    """Write data to cache."""
    path = CACHE_DIR / f"{ck}.json"
    with open(path, "w") as f:
        json.dump(data, f)


# ═══════════════════════════════════════════════════════════════════════════════
#  API FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Simple rate limiter."""
    def __init__(self, delay=REQUEST_DELAY):
        self.delay = delay
        self.last_call = 0
        self.total_calls = 0
        self.cache_hits = 0

    def wait(self):
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self.last_call = time.time()
        self.total_calls += 1


rate_limiter = RateLimiter()


def fetch_contracts(date_str, contract_type):
    """
    Fetch options contract list for a given date and type.
    Handles pagination. Returns list of contract dicts.

    Cache keys match PolygonFetcher.get_options_contracts() exactly:
      First page: url=BASE_URL+endpoint, params={all params + apiKey}
      Next pages: url=next_url, params={apiKey only}
    """
    endpoint = "/v3/reference/options/contracts"
    url = f"{BASE_URL}{endpoint}"
    params = {
        "underlying_ticker": TICKER,
        "expiration_date": date_str,
        "expired": "true",
        "limit": 1000,
        "sort": "strike_price",
        "order": "asc",
        "contract_type": contract_type,
        "apiKey": API_KEY,
    }

    all_contracts = []
    page = 0

    while url:
        ck = cache_key(url, params)

        # Check cache first
        cached = read_cache(ck)
        if cached is not None:
            rate_limiter.cache_hits += 1
            data = cached
        else:
            # Fetch from API
            rate_limiter.wait()
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                write_cache(ck, data)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    print(f"    Rate limited. Waiting 60s...")
                    time.sleep(60)
                    continue  # Retry same request
                print(f"    HTTP error on {contract_type} contracts for {date_str}: {e}")
                return all_contracts
            except requests.exceptions.RequestException as e:
                print(f"    Request error on {contract_type} contracts for {date_str}: {e}")
                return all_contracts

        if not data or "results" not in data:
            break

        all_contracts.extend(data["results"])
        page += 1

        # Handle pagination
        next_url = data.get("next_url")
        if next_url:
            # PolygonFetcher strips base_url from next_url to get endpoint,
            # then reconstructs: url = BASE_URL + endpoint
            # So the full url used for caching = next_url
            url = next_url
            params = {"apiKey": API_KEY}  # Only apiKey for paginated requests
        else:
            url = None

    return all_contracts


def fetch_options_intraday(options_ticker, date_str):
    """
    Fetch intraday minute bars for a specific options contract.
    Returns the raw API response data (or None).

    Cache key matches PolygonFetcher.get_options_intraday() exactly.
    """
    url = f"{BASE_URL}/v2/aggs/ticker/{options_ticker}/range/1/minute/{date_str}/{date_str}"
    params = {
        "adjusted": "true",
        "apiKey": API_KEY,
        "limit": 50000,
        "sort": "asc",
    }

    ck = cache_key(url, params)

    # Check cache
    cached = read_cache(ck)
    if cached is not None:
        rate_limiter.cache_hits += 1
        return cached

    # Fetch from API
    rate_limiter.wait()
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        write_cache(ck, data)
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print(f"    Rate limited. Waiting 60s...")
            time.sleep(60)
            return fetch_options_intraday(options_ticker, date_str)  # Retry
        # Don't spam errors for individual contracts with no data
        return None
    except requests.exceptions.RequestException:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  DELTA ESTIMATION & STRIKE SELECTION
#  (Mirrors options_data.py exactly — for strike SELECTION only, not pricing)
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_delta_from_strike(spot, strike, contract_type):
    """
    Rough delta estimate for strike selection.
    Uses strike distance from spot as a proxy.
    This is ONLY used to SELECT which strikes to pull data for.
    All actual P&L uses real market prices.
    """
    distance_pct = abs(spot - strike) / spot * 100

    if contract_type == "put":
        if strike >= spot:  # ITM put
            return min(0.95, 0.50 + distance_pct * 0.10)
        else:  # OTM put
            return max(0.02, 0.50 - distance_pct * 0.15)
    else:  # call
        if strike <= spot:  # ITM call
            return min(0.95, 0.50 + distance_pct * 0.10)
        else:  # OTM call
            return max(0.02, 0.50 - distance_pct * 0.15)


def select_strikes_for_deltas(spot, target_deltas, contract_type, available_strikes):
    """
    Select the closest available strike for each target delta.
    Returns dict of {target_delta: (strike, estimated_delta)}
    """
    result = {}
    for target in target_deltas:
        best_strike = None
        best_diff = float("inf")
        best_est_delta = None

        for strike in available_strikes:
            est_delta = estimate_delta_from_strike(spot, strike, contract_type)
            diff = abs(est_delta - target)
            if diff < best_diff:
                best_diff = diff
                best_strike = strike
                best_est_delta = est_delta

        if best_strike is not None:
            result[target] = (best_strike, best_est_delta)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  SIGNAL GENERATION (runs locally from cached QQQ data)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_signal_days(atr_mults, directions):
    """
    Run the signal generation pipeline using cached QQQ data.
    Returns dict of unique signal days: {date_str: {"spot": float, "entry_time": timestamp}}
    """
    # Patch config to use QQQ settings
    sys.path.insert(0, str(SCRIPT_DIR))
    import config_qqq
    sys.modules["config"] = config_qqq

    # Force reimport of modules that depend on config
    for mod_name in ["data_fetcher", "indicators", "signal_generator"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    from data_fetcher import PolygonFetcher
    from indicators import enrich_daily_data
    from signal_generator import generate_all_signals

    print("\n" + "=" * 70)
    print("  STEP 1: GENERATING QQQ SIGNAL DAYS")
    print("=" * 70)

    fetcher = PolygonFetcher(cache_only=True)
    qqq_daily = fetcher.get_daily_bars(TICKER, BACKTEST_START, BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", BACKTEST_START, BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(BACKTEST_START, BACKTEST_END)

    if qqq_daily.empty:
        print("FATAL: No QQQ daily data in cache. Run fetch_qqq_all.py first!")
        sys.exit(1)

    print(f"  QQQ daily bars: {len(qqq_daily)}")
    print(f"  TLT daily bars: {len(tlt_daily)}")
    print(f"  VIX daily bars: {len(vix_daily)}")

    enriched = enrich_daily_data(qqq_daily, vix_daily, tlt_daily, 14)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk(TICKER, valid_dates)

    print(f"  Intraday dates loaded: {len(intraday_data)}")

    signals = generate_all_signals(enriched, intraday_data, atr_mults, directions)

    # Collect unique signal days with spot/entry_time
    unique_days = {}
    for key, sig_df in signals.items():
        if sig_df.empty:
            continue
        for _, s in sig_df.iterrows():
            date_str = str(s["date"])
            if date_str not in unique_days:
                unique_days[date_str] = {
                    "spot": s["entry_price"],
                    "entry_time": s["entry_time"],
                }

    print(f"\n  Unique signal days: {len(unique_days)}")
    if unique_days:
        print(f"  Date range: {min(unique_days)} to {max(unique_days)}")

    return unique_days, signals


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN OPTIONS FETCH PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_options_for_day(date_str, spot, verbose=False):
    """
    Fetch all options data for a single signal day:
    1. Get put + call contract lists
    2. Select strikes matching target deltas
    3. Fetch intraday bars for each selected strike

    Returns (n_puts_fetched, n_calls_fetched, n_api_calls)
    """
    n_api = 0
    n_puts = 0
    n_calls = 0

    # Fetch contract lists
    put_contracts = fetch_contracts(date_str, "put")
    call_contracts = fetch_contracts(date_str, "call")

    if not put_contracts and not call_contracts:
        if verbose:
            print(f"    {date_str}: No 0DTE contracts found")
        return 0, 0, 0

    # Extract available strikes
    put_strikes = sorted(set(c["strike_price"] for c in put_contracts))
    call_strikes = sorted(set(c["strike_price"] for c in call_contracts))

    if verbose:
        print(f"    {date_str}: {len(put_strikes)} put strikes, "
              f"{len(call_strikes)} call strikes (spot={spot:.2f})")

    # Select strikes for target deltas
    put_selections = select_strikes_for_deltas(spot, PUT_DELTAS, "put", put_strikes)
    call_selections = select_strikes_for_deltas(spot, CALL_DELTAS, "call", call_strikes)

    # Build ticker lookup
    put_ticker_map = {}
    for c in put_contracts:
        put_ticker_map[c["strike_price"]] = c["ticker"]
    call_ticker_map = {}
    for c in call_contracts:
        call_ticker_map[c["strike_price"]] = c["ticker"]

    # Deduplicate strikes (different delta targets may map to same strike)
    put_strikes_to_fetch = set()
    for target_delta, (strike, est_delta) in put_selections.items():
        ticker = put_ticker_map.get(strike)
        if ticker:
            put_strikes_to_fetch.add((strike, ticker))

    call_strikes_to_fetch = set()
    for target_delta, (strike, est_delta) in call_selections.items():
        ticker = call_ticker_map.get(strike)
        if ticker:
            call_strikes_to_fetch.add((strike, ticker))

    # Fetch intraday bars for each unique put strike
    for strike, ticker in sorted(put_strikes_to_fetch):
        data = fetch_options_intraday(ticker, date_str)
        if data and "results" in data and len(data["results"]) > 0:
            n_puts += 1

    # Fetch intraday bars for each unique call strike
    for strike, ticker in sorted(call_strikes_to_fetch):
        data = fetch_options_intraday(ticker, date_str)
        if data and "results" in data and len(data["results"]) > 0:
            n_calls += 1

    return n_puts, n_calls, len(put_strikes_to_fetch) + len(call_strikes_to_fetch)


def check_coverage(signal_days):
    """Check how many signal days already have options data cached."""
    cached = 0
    partial = 0
    missing = 0

    for date_str, info in sorted(signal_days.items()):
        spot = info["spot"]

        # Check if contract lists are cached
        put_ck = cache_key(
            f"{BASE_URL}/v3/reference/options/contracts",
            {
                "apiKey": API_KEY,
                "contract_type": "put",
                "expiration_date": date_str,
                "expired": "true",
                "limit": 1000,
                "order": "asc",
                "sort": "strike_price",
                "underlying_ticker": TICKER,
            }
        )
        call_ck = cache_key(
            f"{BASE_URL}/v3/reference/options/contracts",
            {
                "apiKey": API_KEY,
                "contract_type": "call",
                "expiration_date": date_str,
                "expired": "true",
                "limit": 1000,
                "order": "asc",
                "sort": "strike_price",
                "underlying_ticker": TICKER,
            }
        )

        has_puts = is_cached(put_ck)
        has_calls = is_cached(call_ck)

        if has_puts and has_calls:
            cached += 1
        elif has_puts or has_calls:
            partial += 1
        else:
            missing += 1

    return cached, partial, missing


def run_fetch(signal_days, max_days=None, verbose=False, resume=False):
    """
    Main fetch loop: iterate over signal days and fetch options data.
    """
    sorted_days = sorted(signal_days.keys())
    if max_days:
        sorted_days = sorted_days[:max_days]

    total = len(sorted_days)

    # If resume, skip days that already have contract lists cached
    if resume:
        days_to_fetch = []
        for date_str in sorted_days:
            put_ck = cache_key(
                f"{BASE_URL}/v3/reference/options/contracts",
                {
                    "apiKey": API_KEY,
                    "contract_type": "put",
                    "expiration_date": date_str,
                    "expired": "true",
                    "limit": 1000,
                    "order": "asc",
                    "sort": "strike_price",
                    "underlying_ticker": TICKER,
                }
            )
            call_ck = cache_key(
                f"{BASE_URL}/v3/reference/options/contracts",
                {
                    "apiKey": API_KEY,
                    "contract_type": "call",
                    "expiration_date": date_str,
                    "expired": "true",
                    "limit": 1000,
                    "order": "asc",
                    "sort": "strike_price",
                    "underlying_ticker": TICKER,
                }
            )
            if not (is_cached(put_ck) and is_cached(call_ck)):
                days_to_fetch.append(date_str)
            else:
                # Contract lists cached, but still need to check intraday bars
                # Read contract lists and check if intraday bars are all cached
                put_data = read_cache(put_ck)
                call_data = read_cache(call_ck)

                need_intraday = False
                spot = signal_days[date_str]["spot"]

                # Check put intraday
                if put_data and "results" in put_data:
                    put_strikes_avail = sorted(set(c["strike_price"] for c in put_data["results"]))
                    selections = select_strikes_for_deltas(spot, PUT_DELTAS, "put", put_strikes_avail)
                    ticker_map = {c["strike_price"]: c["ticker"] for c in put_data["results"]}
                    for _, (strike, _) in selections.items():
                        ticker = ticker_map.get(strike)
                        if ticker:
                            intra_url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
                            intra_ck = cache_key(intra_url, {
                                "adjusted": "true", "apiKey": API_KEY,
                                "limit": 50000, "sort": "asc"
                            })
                            if not is_cached(intra_ck):
                                need_intraday = True
                                break

                # Check call intraday (only if puts looked complete)
                if not need_intraday and call_data and "results" in call_data:
                    call_strikes_avail = sorted(set(c["strike_price"] for c in call_data["results"]))
                    selections = select_strikes_for_deltas(spot, CALL_DELTAS, "call", call_strikes_avail)
                    ticker_map = {c["strike_price"]: c["ticker"] for c in call_data["results"]}
                    for _, (strike, _) in selections.items():
                        ticker = ticker_map.get(strike)
                        if ticker:
                            intra_url = f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}"
                            intra_ck = cache_key(intra_url, {
                                "adjusted": "true", "apiKey": API_KEY,
                                "limit": 50000, "sort": "asc"
                            })
                            if not is_cached(intra_ck):
                                need_intraday = True
                                break

                if need_intraday:
                    days_to_fetch.append(date_str)

        skipped = total - len(days_to_fetch)
        print(f"  Resume mode: skipping {skipped} fully-cached days, "
              f"fetching {len(days_to_fetch)} remaining")
        sorted_days = days_to_fetch

    if not sorted_days:
        print("  All days already cached!")
        return

    print(f"\n  Fetching options data for {len(sorted_days)} signal days...")
    print(f"  Estimated API calls: ~{len(sorted_days) * 18}")
    print(f"  Estimated time: ~{len(sorted_days) * 18 * REQUEST_DELAY / 60:.0f} minutes")
    print()

    start_time = time.time()
    total_puts = 0
    total_calls = 0
    total_api_calls = 0
    errors = 0
    no_contracts_days = 0

    for i, date_str in enumerate(sorted_days):
        info = signal_days[date_str]
        spot = info["spot"]

        try:
            n_puts, n_calls, n_api = fetch_options_for_day(date_str, spot, verbose=verbose)
            total_puts += n_puts
            total_calls += n_calls
            total_api_calls += n_api

            if n_puts == 0 and n_calls == 0:
                no_contracts_days += 1

            # Progress reporting
            if (i + 1) % 10 == 0 or i < 3 or verbose:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
                remaining = (len(sorted_days) - i - 1) / rate if rate > 0 else 0
                print(f"  [{i+1}/{len(sorted_days)}] {date_str}: "
                      f"{n_puts}P/{n_calls}C "
                      f"({rate:.0f} days/min, ~{remaining:.0f}min left) "
                      f"[API: {rate_limiter.total_calls}, cache: {rate_limiter.cache_hits}]")

        except KeyboardInterrupt:
            print(f"\n  Interrupted at day {i+1}/{len(sorted_days)}.")
            print(f"  Run with --resume to continue from where you left off.")
            break
        except Exception as e:
            errors += 1
            print(f"  [{i+1}/{len(sorted_days)}] ERROR on {date_str}: {e}")
            if errors > 20:
                print("  Too many errors. Stopping.")
                break

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  FETCH COMPLETE — {elapsed/60:.1f} minutes")
    print(f"  Days processed: {len(sorted_days)}")
    print(f"  Days with put data: {total_puts} contracts fetched")
    print(f"  Days with call data: {total_calls} contracts fetched")
    print(f"  Days with no 0DTE contracts: {no_contracts_days}")
    print(f"  Total API calls: {rate_limiter.total_calls}")
    print(f"  Cache hits: {rate_limiter.cache_hits}")
    print(f"  Errors: {errors}")
    print(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch QQQ 0DTE options data from Polygon for credit spread backtesting"
    )
    parser.add_argument("--check", action="store_true",
                        help="Check coverage only, don't fetch")
    parser.add_argument("--direction", type=str, default="both",
                        choices=["above", "below", "both"],
                        help="Which signal directions to fetch for")
    parser.add_argument("--atr-mults", type=str, default=None,
                        help="Comma-separated ATR multipliers (default: 0.5-1.0)")
    parser.add_argument("--max-days", type=int, default=None,
                        help="Max signal days to fetch (for testing)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-cached days")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output per day")
    return parser.parse_args()


def main():
    args = parse_args()

    CACHE_DIR.mkdir(exist_ok=True)

    print("=" * 70)
    print("  QQQ 0DTE OPTIONS DATA FETCHER")
    print("  For credit spread backtesting (bull put + bear call)")
    print("  All data from REAL Polygon prices — no Black-Scholes")
    print("=" * 70)
    print(f"\n  Ticker: {TICKER}")
    print(f"  Period: {BACKTEST_START} to {BACKTEST_END}")
    print(f"  Cache:  {CACHE_DIR}")
    print(f"  Put deltas:  {PUT_DELTAS}")
    print(f"  Call deltas: {CALL_DELTAS}")

    # Parse ATR multipliers
    if args.atr_mults:
        atr_mults = [float(x.strip()) for x in args.atr_mults.split(",")]
    else:
        atr_mults = DEFAULT_ATR_MULTS

    directions = ["above", "below"] if args.direction == "both" else [args.direction]

    print(f"  ATR levels: {atr_mults}")
    print(f"  Directions: {directions}")

    # Generate signal days
    signal_days, signals = generate_signal_days(atr_mults, directions)

    if not signal_days:
        print("\nNo signal days found. Check that QQQ daily + intraday data is cached.")
        sys.exit(1)

    if args.check:
        print(f"\n{'='*70}")
        print("  COVERAGE CHECK")
        print(f"{'='*70}")
        cached, partial, missing = check_coverage(signal_days)
        print(f"  Total signal days: {len(signal_days)}")
        print(f"  Fully cached (contract lists): {cached}")
        print(f"  Partially cached: {partial}")
        print(f"  Missing: {missing}")
        return

    # Run the fetch
    print(f"\n{'='*70}")
    print("  STEP 2: FETCHING 0DTE OPTIONS DATA")
    print(f"{'='*70}")

    run_fetch(
        signal_days,
        max_days=args.max_days,
        verbose=args.verbose,
        resume=args.resume,
    )

    # Final coverage check
    print(f"\n{'='*70}")
    print("  FINAL COVERAGE")
    print(f"{'='*70}")
    cached, partial, missing = check_coverage(signal_days)
    print(f"  Total signal days: {len(signal_days)}")
    print(f"  Fully cached (contract lists): {cached}")
    print(f"  Partially cached: {partial}")
    print(f"  Missing: {missing}")

    if missing == 0 and partial == 0:
        print("\n  All options data cached. Ready to run spread backtests!")
        print("  Next step: python run_spreads.py (with QQQ config)")
    print()


if __name__ == "__main__":
    main()

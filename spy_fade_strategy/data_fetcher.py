"""
Polygon.io Data Fetcher with Rate Limiting and Disk Caching
============================================================
Pulls daily bars, intraday bars, and options chain data.
All options pricing uses REAL Polygon trade/quote data — no Black-Scholes.
"""

import os
import json
import time
import hashlib
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import config


class PolygonFetcher:
    """Rate-limited, cached Polygon API client."""

    def __init__(self, cache_only=False):
        self.api_key = config.POLYGON_API_KEY
        self.base_url = config.POLYGON_BASE_URL
        self.cache_only = cache_only  # If True, never hit API — return None for uncached
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

        # Rate limiting
        self.calls_per_min = config.RATE_LIMIT_CALLS_PER_MIN
        self.call_timestamps = []

        # Disk cache
        self.cache_dir = Path(config.CACHE_DIR)
        self.cache_dir.mkdir(exist_ok=True)

    def _rate_limit(self):
        """Enforce rate limit."""
        now = time.time()
        self.call_timestamps = [t for t in self.call_timestamps if now - t < 60]
        if len(self.call_timestamps) >= self.calls_per_min:
            sleep_time = 60 - (now - self.call_timestamps[0]) + 0.1
            print(f"  Rate limit: sleeping {sleep_time:.1f}s...")
            time.sleep(sleep_time)
        self.call_timestamps.append(time.time())

    def _cache_key(self, url, params=None):
        """Generate cache key from URL + params."""
        key_str = url + json.dumps(params or {}, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cached(self, cache_key):
        """Check disk cache."""
        path = self.cache_dir / f"{cache_key}.json"
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
        return None

    def _set_cache(self, cache_key, data):
        """Write to disk cache."""
        path = self.cache_dir / f"{cache_key}.json"
        with open(path, "w") as f:
            json.dump(data, f)

    def _api_get(self, endpoint, params=None):
        """Make a rate-limited, cached API call."""
        url = f"{self.base_url}{endpoint}"
        if params is None:
            params = {}
        params["apiKey"] = self.api_key

        cache_key = self._cache_key(url, params)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # In cache-only mode, don't hit the API — return None for uncached data
        if self.cache_only:
            return None

        self._rate_limit()
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            self._set_cache(cache_key, data)
            return data
        except requests.exceptions.RequestException as e:
            print(f"  API error: {e}")
            return None

    # ─── Daily Bars ─────────────────────────────────────────────────────────

    def get_daily_bars(self, ticker, start_date, end_date):
        """
        Fetch daily OHLCV bars. Returns DataFrame with columns:
        date, open, high, low, close, volume, vwap
        """
        print(f"Fetching daily bars for {ticker} ({start_date} to {end_date})...")
        all_results = []

        # Polygon limits to 50000 results per call; chunk by year for safety
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        current = start
        while current < end:
            chunk_end = min(current + timedelta(days=365), end)
            data = self._api_get(
                f"/v2/aggs/ticker/{ticker}/range/1/day/"
                f"{current.strftime('%Y-%m-%d')}/{chunk_end.strftime('%Y-%m-%d')}",
                {"adjusted": "true", "sort": "asc", "limit": 50000}
            )
            if data and "results" in data:
                all_results.extend(data["results"])
            current = chunk_end + timedelta(days=1)

        if not all_results:
            print(f"  WARNING: No daily bars returned for {ticker}")
            return pd.DataFrame()

        df = pd.DataFrame(all_results)
        df["date"] = pd.to_datetime(df["t"], unit="ms").dt.date
        df = df.rename(columns={
            "o": "open", "h": "high", "l": "low", "c": "close",
            "v": "volume", "vw": "vwap"
        })
        df = df[["date", "open", "high", "low", "close", "volume", "vwap"]].copy()
        df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
        print(f"  Got {len(df)} daily bars for {ticker}")
        return df

    # ─── Intraday Bars ──────────────────────────────────────────────────────

    def get_intraday_bars(self, ticker, date_str, bar_size_min=1):
        """
        Fetch intraday minute bars for a single trading day.
        Returns DataFrame with: timestamp, open, high, low, close, volume, vwap
        """
        data = self._api_get(
            f"/v2/aggs/ticker/{ticker}/range/{bar_size_min}/minute/{date_str}/{date_str}",
            {"adjusted": "true", "sort": "asc", "limit": 50000}
        )
        if not data or "results" not in data:
            return pd.DataFrame()

        df = pd.DataFrame(data["results"])
        df["timestamp"] = pd.to_datetime(df["t"], unit="ms")
        # Convert to Eastern time for session filtering
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("US/Eastern")
        df = df.rename(columns={
            "o": "open", "h": "high", "l": "low", "c": "close",
            "v": "volume", "vw": "vwap_bar"  # per-bar vwap from Polygon
        })

        # Filter to regular trading hours
        mask = (
            (df["timestamp"].dt.time >= pd.Timestamp("09:30").time()) &
            (df["timestamp"].dt.time < pd.Timestamp("16:00").time())
        )
        df = df[mask].copy()
        df = df[["timestamp", "open", "high", "low", "close", "volume", "vwap_bar"]].reset_index(drop=True)
        return df

    def get_intraday_bars_bulk(self, ticker, dates):
        """
        Fetch intraday bars for multiple dates. Returns dict of {date_str: DataFrame}.
        Uses batching to be efficient.
        """
        print(f"Fetching intraday bars for {ticker} across {len(dates)} dates...")
        results = {}
        for i, date_str in enumerate(dates):
            if (i + 1) % 50 == 0:
                print(f"  Progress: {i+1}/{len(dates)} dates...")
            df = self.get_intraday_bars(ticker, date_str)
            if not df.empty:
                results[date_str] = df
        print(f"  Got intraday data for {len(results)}/{len(dates)} dates")
        return results

    # ─── Options Data ───────────────────────────────────────────────────────

    def get_options_contracts(self, underlying, expiration_date, contract_type=None):
        """
        Get list of options contracts for a given underlying and expiration.
        contract_type: 'call' or 'put' or None for both.
        Returns list of contract tickers.
        """
        params = {
            "underlying_ticker": underlying,
            "expiration_date": expiration_date,
            "expired": "true",  # CRITICAL: include expired contracts for historical lookups
            "limit": 1000,
            "sort": "strike_price",
            "order": "asc",
        }
        if contract_type:
            params["contract_type"] = contract_type

        all_contracts = []
        endpoint = "/v3/reference/options/contracts"

        while endpoint:
            data = self._api_get(endpoint, params)
            if not data or "results" not in data:
                break
            all_contracts.extend(data["results"])
            # Handle pagination
            next_url = data.get("next_url")
            if next_url:
                # Extract endpoint from full URL
                endpoint = next_url.replace(self.base_url, "")
                params = {}  # next_url includes params
            else:
                endpoint = None

        return all_contracts

    def get_options_intraday(self, options_ticker, date_str, bar_size_min=1):
        """
        Fetch intraday bars for a specific options contract on a given day.
        Uses REAL market data — no Black-Scholes.
        Returns DataFrame with: timestamp, open, high, low, close, volume
        """
        data = self._api_get(
            f"/v2/aggs/ticker/{options_ticker}/range/{bar_size_min}/minute/{date_str}/{date_str}",
            {"adjusted": "true", "sort": "asc", "limit": 50000}
        )
        if not data or "results" not in data:
            return pd.DataFrame()

        df = pd.DataFrame(data["results"])
        df["timestamp"] = pd.to_datetime(df["t"], unit="ms")
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("US/Eastern")
        df = df.rename(columns={
            "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"
        })

        mask = (
            (df["timestamp"].dt.time >= pd.Timestamp("09:30").time()) &
            (df["timestamp"].dt.time < pd.Timestamp("16:00").time())
        )
        df = df[mask].copy()
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        return df

    def get_options_snapshot(self, underlying, date_str=None):
        """
        Get snapshot of all options for an underlying ticker.
        Returns current greeks, IV, prices etc.
        NOTE: Snapshot is real-time only; for historical, use intraday bars.
        """
        all_results = []
        endpoint = f"/v3/snapshot/options/{underlying}"
        params = {"limit": 250}

        while endpoint:
            data = self._api_get(endpoint, params)
            if not data or "results" not in data:
                break
            all_results.extend(data["results"])
            next_url = data.get("next_url")
            if next_url:
                endpoint = next_url.replace(self.base_url, "")
                params = {}
            else:
                endpoint = None

        return all_results

    def get_options_daily_bar(self, options_ticker, date_str):
        """
        Get the daily bar for a specific options contract.
        This gives us open/high/low/close/volume for the day.
        """
        data = self._api_get(
            f"/v2/aggs/ticker/{options_ticker}/range/1/day/{date_str}/{date_str}",
            {"adjusted": "true"}
        )
        if data and "results" in data and len(data["results"]) > 0:
            return data["results"][0]
        return None

    # ─── VIX Index Data ─────────────────────────────────────────────────────

    def get_vix_daily(self, start_date, end_date):
        """
        Fetch VIX daily close values.
        Polygon uses I:VIX for the index.
        Fallback: use ^VIX or VIX ETF.
        """
        print(f"Fetching VIX data ({start_date} to {end_date})...")

        # Try the index ticker first
        for ticker in [config.VIX_INDEX, "VIX", "VIXY"]:
            data = self._api_get(
                f"/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}",
                {"adjusted": "true", "sort": "asc", "limit": 50000}
            )
            if data and "results" in data and len(data["results"]) > 20:
                df = pd.DataFrame(data["results"])
                df["date"] = pd.to_datetime(df["t"], unit="ms").dt.date
                df = df.rename(columns={"c": "vix_close", "o": "vix_open", "h": "vix_high", "l": "vix_low"})
                df = df[["date", "vix_open", "vix_high", "vix_low", "vix_close"]].drop_duplicates("date")
                print(f"  Got {len(df)} VIX daily bars via {ticker}")
                return df.sort_values("date").reset_index(drop=True)

        print("  WARNING: Could not fetch VIX data from any source")
        return pd.DataFrame()

    # ─── Helper: Build Options Ticker ───────────────────────────────────────

    @staticmethod
    def build_options_ticker(underlying, exp_date, call_put, strike):
        """
        Build Polygon options ticker.
        Format: O:SPY251231C00450000
        underlying: 'SPY'
        exp_date: '2025-12-31'
        call_put: 'C' or 'P'
        strike: 450.00 (will be formatted as 00450000)
        """
        exp = exp_date.replace("-", "")[2:]  # YYMMDD
        strike_str = f"{int(strike * 1000):08d}"
        return f"O:{underlying}{exp}{call_put}{strike_str}"


# ─── Convenience Functions ──────────────────────────────────────────────────

def fetch_all_base_data():
    """
    Fetch all base data needed for the backtest:
    - SPY daily bars (for ATR)
    - TLT daily bars (bond proxy)
    - VIX daily
    Returns dict of DataFrames.
    """
    fetcher = PolygonFetcher()

    spy_daily = fetcher.get_daily_bars(config.TICKER, config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars(config.TLT_TICKER, config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    return {
        "spy_daily": spy_daily,
        "tlt_daily": tlt_daily,
        "vix_daily": vix_daily,
        "fetcher": fetcher,
    }

"""
0DTE Options Data Puller
=========================
For each signal day, pulls REAL options data from Polygon.
No Black-Scholes — only actual traded prices.

Identifies contracts by approximate delta using strike distance from spot
and then validates with actual market prices.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data_fetcher import PolygonFetcher
import config


class OptionsDayData:
    """Container for a single day's 0DTE options data."""

    def __init__(self, date_str, spot_at_entry, entry_time):
        self.date_str = date_str
        self.spot = spot_at_entry
        self.entry_time = entry_time
        self.puts = {}   # {strike: DataFrame of intraday bars}
        self.calls = {}  # {strike: DataFrame of intraday bars}
        self.put_contracts = []  # Contract metadata
        self.call_contracts = []


def estimate_delta_from_strike(spot, strike, contract_type, dte_fraction=0.01):
    """
    Rough delta estimate for strike selection when we don't have greeks.
    Uses strike distance from spot as a proxy.

    For 0DTE, ATM delta ~ 0.50, and delta drops rapidly with distance.
    This is ONLY used to SELECT which strikes to pull data for.
    All actual P&L uses real market prices.

    Parameters
    ----------
    spot : float, current SPY price
    strike : float
    contract_type : 'put' or 'call'
    dte_fraction : float, fraction of year remaining (~0.003 for 0DTE)

    Returns
    -------
    float, estimated absolute delta (0-1)
    """
    # Simple moneyness-based approximation
    # For 0DTE, use distance as % of spot
    distance_pct = abs(spot - strike) / spot * 100

    if contract_type == "put":
        if strike >= spot:  # ITM put
            return min(0.95, 0.50 + distance_pct * 0.10)
        else:  # OTM put
            # Rough: every 0.5% OTM reduces delta by ~0.10 for 0DTE
            est_delta = max(0.02, 0.50 - distance_pct * 0.15)
            return est_delta
    else:  # call
        if strike <= spot:  # ITM call
            return min(0.95, 0.50 + distance_pct * 0.10)
        else:  # OTM call
            est_delta = max(0.02, 0.50 - distance_pct * 0.15)
            return est_delta


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


def pull_options_for_signal_day(fetcher, date_str, spot_at_entry, entry_time):
    """
    Pull all relevant 0DTE options data for a signal day.

    1. Get list of contracts expiring today
    2. Select strikes corresponding to target deltas
    3. Pull intraday bars for selected contracts

    Returns OptionsDayData with real market prices.
    """
    day_data = OptionsDayData(date_str, spot_at_entry, entry_time)

    # Get contracts expiring today
    put_contracts = fetcher.get_options_contracts(config.TICKER, date_str, "put")
    call_contracts = fetcher.get_options_contracts(config.TICKER, date_str, "call")

    if not put_contracts and not call_contracts:
        print(f"  {date_str}: No 0DTE contracts found")
        return day_data

    # Extract available strikes
    put_strikes = sorted(set(c["strike_price"] for c in put_contracts))
    call_strikes = sorted(set(c["strike_price"] for c in call_contracts))

    # Select strikes for target deltas
    put_selections = select_strikes_for_deltas(
        spot_at_entry, config.PUT_DELTAS, "put", put_strikes
    )
    call_selections = select_strikes_for_deltas(
        spot_at_entry, config.CALL_DELTAS, "call", call_strikes
    )

    # Build ticker lookup for puts
    put_ticker_map = {}
    for c in put_contracts:
        put_ticker_map[c["strike_price"]] = c["ticker"]
    call_ticker_map = {}
    for c in call_contracts:
        call_ticker_map[c["strike_price"]] = c["ticker"]

    # Pull intraday data for selected put strikes
    for target_delta, (strike, est_delta) in put_selections.items():
        ticker = put_ticker_map.get(strike)
        if not ticker:
            continue
        bars = fetcher.get_options_intraday(ticker, date_str)
        if not bars.empty:
            # Filter to bars at/after entry time
            bars_after = bars[bars["timestamp"] >= entry_time].copy()
            if not bars_after.empty:
                day_data.puts[target_delta] = {
                    "strike": strike,
                    "ticker": ticker,
                    "est_delta": est_delta,
                    "bars": bars_after.reset_index(drop=True),
                    "entry_price": bars_after.iloc[0]["open"],  # First available price after signal
                    "all_bars": bars,  # Keep full day for reference
                }

    # Pull intraday data for selected call strikes
    for target_delta, (strike, est_delta) in call_selections.items():
        ticker = call_ticker_map.get(strike)
        if not ticker:
            continue
        bars = fetcher.get_options_intraday(ticker, date_str)
        if not bars.empty:
            bars_after = bars[bars["timestamp"] >= entry_time].copy()
            if not bars_after.empty:
                day_data.calls[target_delta] = {
                    "strike": strike,
                    "ticker": ticker,
                    "est_delta": est_delta,
                    "bars": bars_after.reset_index(drop=True),
                    "entry_price": bars_after.iloc[0]["open"],
                    "all_bars": bars,
                }

    n_puts = len(day_data.puts)
    n_calls = len(day_data.calls)
    if n_puts > 0 or n_calls > 0:
        print(f"  {date_str}: Got {n_puts} put deltas, {n_calls} call deltas "
              f"(spot={spot_at_entry:.2f})")

    return day_data


def pull_all_options_data(fetcher, signals_df):
    """
    Pull 0DTE options data for all signal days.

    Parameters
    ----------
    fetcher : PolygonFetcher
    signals_df : DataFrame of signals

    Returns
    -------
    dict of {date_str: OptionsDayData}
    """
    print(f"\nPulling 0DTE options data for {len(signals_df)} signal days...")
    print("  This may take a while due to API rate limits...\n")

    all_options = {}
    for i, (_, signal) in enumerate(signals_df.iterrows()):
        date_str = str(signal["date"])
        spot = signal["entry_price"]
        entry_time = signal["entry_time"]

        if (i + 1) % 10 == 0:
            print(f"  Options pull progress: {i+1}/{len(signals_df)} days...")

        day_data = pull_options_for_signal_day(fetcher, date_str, spot, entry_time)
        all_options[date_str] = day_data

    print(f"\n  Options data pull complete.")
    days_with_data = sum(1 for d in all_options.values()
                         if len(d.puts) > 0 or len(d.calls) > 0)
    print(f"  Days with options data: {days_with_data}/{len(all_options)}")

    return all_options

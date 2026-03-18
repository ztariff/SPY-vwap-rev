"""
SPX 0DTE Options Data Puller
=============================
Same logic as options_data.py but pulls SPX/SPXW contracts instead of SPY.
Falls back from SPX -> SPXW if no contracts found (Polygon files some under each).

SPX 0DTE options have ~10x the premium of SPY at the same delta,
which means far more trades pass fill-realism filters.
"""

import pandas as pd
import numpy as np
from options_data import (
    OptionsDayData,
    estimate_delta_from_strike,
    select_strikes_for_deltas,
)
import config_spx as config


def pull_spx_options_for_signal_day(fetcher, date_str, spy_spot, entry_time):
    """
    Pull SPX 0DTE options data for a signal day.

    We use SPY for signals (VWAP deviation), but trade SPX options.
    SPX spot ~ 10x SPY spot, so we derive SPX spot from SPY.

    Parameters
    ----------
    fetcher : PolygonFetcher
    date_str : str, YYYY-MM-DD
    spy_spot : float, SPY price at signal time
    entry_time : Timestamp, signal entry time
    """
    # SPX spot = SPY spot * 10 (approximate; close enough for strike selection)
    spx_spot = spy_spot * 10

    day_data = OptionsDayData(date_str, spx_spot, entry_time)

    # Try SPX first, fall back to SPXW
    put_contracts = []
    call_contracts = []

    for underlying in [config.OPTIONS_UNDERLYING, config.OPTIONS_UNDERLYING_FALLBACK]:
        if not put_contracts:
            put_contracts = fetcher.get_options_contracts(underlying, date_str, "put")
        if not call_contracts:
            call_contracts = fetcher.get_options_contracts(underlying, date_str, "call")
        if put_contracts or call_contracts:
            break

    if not put_contracts and not call_contracts:
        print(f"  {date_str}: No SPX 0DTE contracts found")
        return day_data

    # Extract available strikes
    put_strikes = sorted(set(c["strike_price"] for c in put_contracts))
    call_strikes = sorted(set(c["strike_price"] for c in call_contracts))

    # Select strikes for target deltas (using SPX spot, not SPY)
    put_selections = select_strikes_for_deltas(
        spx_spot, config.PUT_DELTAS, "put", put_strikes
    )
    call_selections = select_strikes_for_deltas(
        spx_spot, config.CALL_DELTAS, "call", call_strikes
    )

    # Build ticker lookups
    put_ticker_map = {c["strike_price"]: c["ticker"] for c in put_contracts}
    call_ticker_map = {c["strike_price"]: c["ticker"] for c in call_contracts}

    # Pull intraday data for selected put strikes
    for target_delta, (strike, est_delta) in put_selections.items():
        ticker = put_ticker_map.get(strike)
        if not ticker:
            continue
        bars = fetcher.get_options_intraday(ticker, date_str)
        if not bars.empty:
            bars_after = bars[bars["timestamp"] >= entry_time].copy()
            if not bars_after.empty:
                day_data.puts[target_delta] = {
                    "strike": strike,
                    "ticker": ticker,
                    "est_delta": est_delta,
                    "bars": bars_after.reset_index(drop=True),
                    "entry_price": bars_after.iloc[0]["open"],
                    "all_bars": bars,
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
        print(f"  {date_str}: Got {n_puts} SPX put deltas, {n_calls} SPX call deltas "
              f"(SPX≈{spx_spot:.0f}, SPY={spy_spot:.2f})")

    return day_data

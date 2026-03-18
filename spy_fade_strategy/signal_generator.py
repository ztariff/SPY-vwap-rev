"""
Signal Generator: Identify VWAP Deviation Signals (Both Directions)
====================================================================
ABOVE VWAP: Fade signal (short) when price >= X ATR above session VWAP
BELOW VWAP: Buy signal (long) when price <= X ATR below session VWAP

Also handles scale-in logic: first entry at level A, add at level B.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import config
from indicators import calculate_session_vwap


def _classify_time_bucket(timestamp):
    """Classify a timestamp into a time-of-day bucket."""
    hour = timestamp.hour
    minute = timestamp.minute
    time_minutes = hour * 60 + minute
    if time_minutes < 630:    # before 10:30
        return "open_hour"
    elif time_minutes < 720:  # before 12:00
        return "late_morning"
    elif time_minutes < 840:  # before 14:00
        return "midday"
    elif time_minutes < 900:  # before 15:00
        return "afternoon"
    else:
        return "power_hour"


def _enrich_signal(signal_bar, daily_row, direction, atr_multiplier, all_signal_bars,
                    signal_date=None):
    """Add daily context to a signal bar."""
    signal_bar = signal_bar.copy()
    # Use the actual signal day, NOT the daily_row date (which is the prior day for ATR)
    signal_bar["date"] = signal_date if signal_date is not None else daily_row["date"]
    signal_bar["direction"] = direction
    signal_bar["atr"] = daily_row["atr"]
    signal_bar["atr_multiplier"] = atr_multiplier
    signal_bar["vix_close"] = daily_row.get("vix_close", np.nan)
    signal_bar["vix_regime"] = daily_row.get("vix_regime", "unknown")
    signal_bar["consecutive_up"] = daily_row.get("consecutive_up", 0)
    signal_bar["consecutive_down"] = daily_row.get("consecutive_down", 0)
    signal_bar["gap_pct"] = daily_row.get("gap_pct", 0)
    signal_bar["tlt_daily_return"] = daily_row.get("tlt_daily_return", np.nan)
    signal_bar["bonds_up"] = daily_row.get("bonds_up", np.nan)
    signal_bar["spy_5d_return"] = daily_row.get("spy_5d_return", np.nan)
    signal_bar["range_position_prev"] = daily_row.get("range_position", np.nan)
    signal_bar["spy_close_prev"] = daily_row.get("close", np.nan)
    signal_bar["time_bucket"] = _classify_time_bucket(signal_bar["timestamp"].iloc[0])
    signal_bar["total_signal_bars"] = len(all_signal_bars)
    signal_bar["entry_price"] = signal_bar["close"].iloc[0]
    signal_bar["entry_time"] = signal_bar["timestamp"].iloc[0]
    signal_bar["entry_vwap"] = signal_bar["vwap"].iloc[0]
    return signal_bar


def identify_signals_for_day(intraday_df, daily_row, atr_multiplier, direction="above",
                              signal_date=None):
    """
    For a single trading day, identify the FIRST bar where price deviates
    from VWAP by at least atr_multiplier * ATR in the given direction.

    Parameters
    ----------
    intraday_df : DataFrame of 1-min bars (with VWAP already calculated)
    daily_row : Series with prior day's enriched data
    atr_multiplier : float
    direction : "above" (fade/short signal) or "below" (buy/long signal)
    signal_date : the actual date of the signal (not the prior day)

    Returns
    -------
    DataFrame with one signal row, or empty DataFrame.
    """
    if intraday_df.empty or pd.isna(daily_row.get("atr")):
        return pd.DataFrame()

    df = intraday_df.copy()
    atr = daily_row["atr"]
    threshold = atr * atr_multiplier

    if "vwap" not in df.columns:
        df = calculate_session_vwap(df)

    df["dist_from_vwap"] = df["close"] - df["vwap"]
    df["dist_from_vwap_atr"] = df["dist_from_vwap"] / atr  # In ATR units (signed)

    if direction == "above":
        df["signal"] = df["dist_from_vwap"] >= threshold
        df["dist_above_vwap_atr"] = df["dist_from_vwap_atr"]  # positive
    else:  # below
        df["signal"] = df["dist_from_vwap"] <= -threshold
        df["dist_above_vwap_atr"] = -df["dist_from_vwap_atr"]  # make positive for consistency

    signals = df[df["signal"]]
    if signals.empty:
        return pd.DataFrame()

    first_signal = signals.iloc[0:1].copy()
    first_signal["max_atr_from_vwap"] = signals["dist_above_vwap_atr"].max()

    return _enrich_signal(first_signal, daily_row, direction, atr_multiplier, signals,
                          signal_date=signal_date)


def identify_scalein_signals_for_day(intraday_df, daily_row, entry_mult, add_mult, direction="above",
                                      signal_date=None):
    """
    Identify scale-in signal: first entry at entry_mult, second add at add_mult.

    Returns tuple: (entry1_signal, entry2_signal) — either can be empty DataFrame.
    """
    if intraday_df.empty or pd.isna(daily_row.get("atr")):
        return pd.DataFrame(), pd.DataFrame()

    df = intraday_df.copy()
    atr = daily_row["atr"]

    if "vwap" not in df.columns:
        df = calculate_session_vwap(df)

    df["dist_from_vwap"] = df["close"] - df["vwap"]
    df["dist_from_vwap_atr"] = df["dist_from_vwap"] / atr

    if direction == "above":
        df["dist_above_vwap_atr"] = df["dist_from_vwap_atr"]
        entry1_mask = df["dist_from_vwap"] >= atr * entry_mult
        entry2_mask = df["dist_from_vwap"] >= atr * add_mult
    else:
        df["dist_above_vwap_atr"] = -df["dist_from_vwap_atr"]
        entry1_mask = df["dist_from_vwap"] <= -atr * entry_mult
        entry2_mask = df["dist_from_vwap"] <= -atr * add_mult

    # First entry
    entry1_bars = df[entry1_mask]
    if entry1_bars.empty:
        return pd.DataFrame(), pd.DataFrame()

    entry1 = entry1_bars.iloc[0:1].copy()
    entry1["max_atr_from_vwap"] = entry1_bars["dist_above_vwap_atr"].max()
    entry1 = _enrich_signal(entry1, daily_row, direction, entry_mult, entry1_bars,
                            signal_date=signal_date)

    # Second entry (must come AFTER first)
    entry1_time = entry1["timestamp"].iloc[0]
    remaining = df[df["timestamp"] > entry1_time]
    entry2_bars = remaining[entry2_mask[remaining.index]]

    if entry2_bars.empty:
        return entry1, pd.DataFrame()

    entry2 = entry2_bars.iloc[0:1].copy()
    entry2["max_atr_from_vwap"] = entry2_bars["dist_above_vwap_atr"].max()
    entry2 = _enrich_signal(entry2, daily_row, direction, add_mult, entry2_bars,
                            signal_date=signal_date)

    return entry1, entry2


def generate_all_signals(enriched_daily, intraday_data_dict, atr_multipliers=None,
                          directions=None):
    """
    Generate all signals across the entire backtest period for both directions.

    Parameters
    ----------
    enriched_daily : DataFrame with all daily enrichment
    intraday_data_dict : dict of {date_str: DataFrame}
    atr_multipliers : list of multipliers to test
    directions : list of "above" and/or "below"

    Returns
    -------
    Dict of {(direction, multiplier): DataFrame of signals}
    """
    if atr_multipliers is None:
        atr_multipliers = config.ATR_MULTIPLIER_RANGE
    if directions is None:
        directions = config.DIRECTIONS

    all_signals = {(d, m): [] for d in directions for m in atr_multipliers}

    daily_dates = list(enriched_daily["date"])
    daily_lookup = {row["date"]: row for _, row in enriched_daily.iterrows()}

    sorted_dates = sorted(intraday_data_dict.keys())
    print(f"Scanning {len(sorted_dates)} days for signals ({len(directions)} directions, "
          f"{len(atr_multipliers)} ATR levels)...")

    for i, date_str in enumerate(sorted_dates):
        if (i + 1) % 100 == 0:
            print(f"  Progress: {i+1}/{len(sorted_dates)} days...")

        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

        prior_dates = [d for d in daily_dates if d < date_obj]
        if not prior_dates:
            continue
        prior_date = prior_dates[-1]
        if prior_date not in daily_lookup:
            continue
        daily_row = daily_lookup[prior_date]
        if pd.isna(daily_row.get("atr")):
            continue

        intraday_df = intraday_data_dict[date_str]
        intraday_with_vwap = calculate_session_vwap(intraday_df)

        for direction in directions:
            for mult in atr_multipliers:
                signal = identify_signals_for_day(intraday_with_vwap, daily_row, mult, direction,
                                                   signal_date=date_obj)
                if not signal.empty:
                    all_signals[(direction, mult)].append(signal)

    # Combine signals
    result = {}
    for key, sig_list in all_signals.items():
        if sig_list:
            result[key] = pd.concat(sig_list, ignore_index=True)
        else:
            result[key] = pd.DataFrame()

    # Print summary
    print(f"\n  Signal Summary:")
    for direction in directions:
        dir_label = "ABOVE VWAP (fade/short)" if direction == "above" else "BELOW VWAP (buy/long)"
        print(f"\n  {dir_label}:")
        for mult in atr_multipliers:
            key = (direction, mult)
            count = len(result[key]) if key in result else 0
            if count > 0:
                print(f"    {mult:.1f}x ATR: {count} signals")

    return result


def generate_scalein_signals(enriched_daily, intraday_data_dict, scale_pairs=None,
                              directions=None):
    """
    Generate scale-in signal pairs for all configured (entry, add) combinations.

    Returns dict of {(direction, entry_mult, add_mult): list of (entry1_df, entry2_df)}
    """
    if scale_pairs is None:
        scale_pairs = config.SCALE_IN_PAIRS
    if directions is None:
        directions = config.DIRECTIONS

    print(f"\nGenerating scale-in signals: {len(scale_pairs)} pairs x {len(directions)} directions...")

    results = {}
    daily_dates = list(enriched_daily["date"])
    daily_lookup = {row["date"]: row for _, row in enriched_daily.iterrows()}
    sorted_dates = sorted(intraday_data_dict.keys())

    for direction in directions:
        for entry_mult, add_mult in scale_pairs:
            key = (direction, entry_mult, add_mult)
            pair_signals = []

            for date_str in sorted_dates:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                prior_dates = [d for d in daily_dates if d < date_obj]
                if not prior_dates:
                    continue
                prior_date = prior_dates[-1]
                if prior_date not in daily_lookup:
                    continue
                daily_row = daily_lookup[prior_date]
                if pd.isna(daily_row.get("atr")):
                    continue

                intraday_df = intraday_data_dict[date_str]
                intraday_with_vwap = calculate_session_vwap(intraday_df)

                entry1, entry2 = identify_scalein_signals_for_day(
                    intraday_with_vwap, daily_row, entry_mult, add_mult, direction,
                    signal_date=date_obj
                )
                if not entry1.empty:
                    pair_signals.append((entry1, entry2))

            results[key] = pair_signals

            n_both = sum(1 for e1, e2 in pair_signals if not e2.empty)
            n_first_only = len(pair_signals) - n_both
            if pair_signals:
                dir_label = "ABOVE" if direction == "above" else "BELOW"
                print(f"  {dir_label} {entry_mult}x→{add_mult}x: "
                      f"{len(pair_signals)} days with entry1, {n_both} also hit entry2")

    return results


def get_remaining_bars(intraday_df, entry_time):
    """Get all intraday bars after the entry time."""
    if intraday_df.empty:
        return pd.DataFrame()
    mask = intraday_df["timestamp"] > entry_time
    return intraday_df[mask].copy().reset_index(drop=True)

"""
Multi-Signal Generator v2: RSI(2), Opening Range, Bollinger Band, Volume Spike
================================================================================
Each signal generator follows the SAME interface as the VWAP signal generator:
  - Takes enriched_daily + intraday_data_dict
  - Returns {(direction, label): DataFrame of signals}
  - Each signal has: date, entry_price, entry_time, vix_regime, etc.

All signals use the EXISTING cached SPY 1-min bars — no new API calls needed.

Per CLAUDE.md: Never fabricate data. All prices come from real Polygon bars.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import config
from indicators import calculate_session_vwap


# ═══════════════════════════════════════════════════════════════════════════
#  SHARED ENRICHMENT (same format as signal_generator.py)
# ═══════════════════════════════════════════════════════════════════════════

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


def _enrich_signal_row(signal_bar_row, daily_row, direction, signal_type, signal_date=None):
    """
    Enrich a single signal bar with daily context.
    Returns a dict (not a DataFrame) for efficiency.
    """
    entry = {
        "date": signal_date if signal_date else daily_row["date"],
        "direction": direction,
        "signal_type": signal_type,
        "atr": daily_row["atr"],
        "atr_multiplier": 0,  # Not ATR-based, but kept for pipeline compat
        "vix_close": daily_row.get("vix_close", np.nan),
        "vix_regime": daily_row.get("vix_regime", "unknown"),
        "consecutive_up": daily_row.get("consecutive_up", 0),
        "consecutive_down": daily_row.get("consecutive_down", 0),
        "gap_pct": daily_row.get("gap_pct", 0),
        "tlt_daily_return": daily_row.get("tlt_daily_return", np.nan),
        "bonds_up": daily_row.get("bonds_up", np.nan),
        "spy_5d_return": daily_row.get("spy_5d_return", np.nan),
        "range_position_prev": daily_row.get("range_position", np.nan),
        "spy_close_prev": daily_row.get("close", np.nan),
        "entry_price": float(signal_bar_row["close"]),
        "entry_time": signal_bar_row["timestamp"],
        "entry_vwap": float(signal_bar_row.get("vwap", np.nan)),
        "time_bucket": _classify_time_bucket(signal_bar_row["timestamp"]),
    }
    return entry


def _build_signal_df(signal_list):
    """Convert list of signal dicts to DataFrame."""
    if not signal_list:
        return pd.DataFrame()
    return pd.DataFrame(signal_list)


# ═══════════════════════════════════════════════════════════════════════════
#  SIGNAL 1: RSI(2) OVERSOLD / OVERBOUGHT
# ═══════════════════════════════════════════════════════════════════════════

def _calculate_rsi(series, period=2):
    """
    Calculate RSI on a price series.
    Uses Wilder's smoothing (exponential moving average).
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # Wilder's smoothed average
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def identify_rsi2_signals_for_day(intraday_df, daily_row, direction="below",
                                    rsi_threshold=10, signal_date=None):
    """
    Identify RSI(2) oversold/overbought signals on 1-min bars.

    - direction="below": RSI(2) < threshold → mean-reversion long (buy dip)
    - direction="above": RSI(2) > (100-threshold) → mean-reversion short (fade)

    Uses 1-min close prices for RSI calculation.
    Signal fires on the FIRST bar that crosses the threshold.
    """
    if intraday_df.empty or pd.isna(daily_row.get("atr")):
        return pd.DataFrame()

    df = intraday_df.copy()

    # Need VWAP for enrichment
    if "vwap" not in df.columns:
        df = calculate_session_vwap(df)

    # Calculate RSI(2) on 1-min closes
    df["rsi2"] = _calculate_rsi(df["close"], period=2)

    # Need at least 3 bars for RSI(2) to be meaningful
    df = df.iloc[2:].copy()

    if direction == "below":
        # Oversold: RSI(2) drops below threshold
        mask = df["rsi2"] <= rsi_threshold
    else:
        # Overbought: RSI(2) rises above (100 - threshold)
        mask = df["rsi2"] >= (100 - rsi_threshold)

    signals = df[mask]
    if signals.empty:
        return pd.DataFrame()

    # Take the FIRST signal of the day
    first = signals.iloc[0]
    entry = _enrich_signal_row(first, daily_row, direction, "rsi2_oversold" if direction == "below" else "rsi2_overbought",
                                signal_date=signal_date)
    entry["rsi2_value"] = float(first["rsi2"])
    return _build_signal_df([entry])


def generate_rsi2_signals(enriched_daily, intraday_data_dict, rsi_thresholds=None,
                           directions=None):
    """
    Generate RSI(2) signals across the full backtest period.

    Returns dict of {(direction, f"rsi2_{threshold}"): DataFrame of signals}
    """
    if rsi_thresholds is None:
        rsi_thresholds = [5, 10, 15]
    if directions is None:
        directions = ["below"]  # Primary use case is oversold → long

    daily_dates = list(enriched_daily["date"])
    daily_lookup = {row["date"]: row for _, row in enriched_daily.iterrows()}
    sorted_dates = sorted(intraday_data_dict.keys())

    all_signals = {}
    for direction in directions:
        for threshold in rsi_thresholds:
            key = (direction, f"rsi2_{threshold}")
            signals = []

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
                sig = identify_rsi2_signals_for_day(
                    intraday_df, daily_row, direction, threshold, signal_date=date_obj
                )
                if not sig.empty:
                    signals.append(sig)

            if signals:
                all_signals[key] = pd.concat(signals, ignore_index=True)
            else:
                all_signals[key] = pd.DataFrame()

            count = len(all_signals[key])
            if count > 0:
                dir_label = "OVERSOLD (long)" if direction == "below" else "OVERBOUGHT (short)"
                print(f"  RSI(2) ≤{threshold} {dir_label}: {count} signals")

    return all_signals


# ═══════════════════════════════════════════════════════════════════════════
#  SIGNAL 2: OPENING RANGE BREAKOUT FAILURE
# ═══════════════════════════════════════════════════════════════════════════

def identify_orb_failure_signals_for_day(intraday_df, daily_row, direction="below",
                                          range_minutes=30, signal_date=None):
    """
    Opening Range Breakout Failure: price breaks the opening range, then
    fails back inside — classic mean-reversion setup.

    - direction="below": Price breaks BELOW the opening range low, then
      reverses back above it. Enter long when it reclaims the range low.
    - direction="above": Price breaks ABOVE the opening range high, then
      fails back below it. Enter short when it breaks back below the range high.

    range_minutes: size of the opening range (15 or 30 min).
    """
    if intraday_df.empty or pd.isna(daily_row.get("atr")):
        return pd.DataFrame()

    df = intraday_df.copy()
    if "vwap" not in df.columns:
        df = calculate_session_vwap(df)

    # Define the opening range
    open_time = df["timestamp"].iloc[0]
    range_end = open_time + pd.Timedelta(minutes=range_minutes)

    range_bars = df[df["timestamp"] < range_end]
    if len(range_bars) < 5:  # Need at least 5 bars to define a range
        return pd.DataFrame()

    or_high = range_bars["high"].max()
    or_low = range_bars["low"].min()
    or_range = or_high - or_low

    # Skip if range is too tight (less than 0.05% of price)
    if or_range < df["close"].iloc[0] * 0.0005:
        return pd.DataFrame()

    # Look at bars AFTER the opening range
    post_range = df[df["timestamp"] >= range_end].copy()
    if post_range.empty:
        return pd.DataFrame()

    if direction == "below":
        # Step 1: Find a bar that breaks BELOW the opening range low
        break_mask = post_range["low"] < or_low
        breaks = post_range[break_mask]
        if breaks.empty:
            return pd.DataFrame()

        break_time = breaks.iloc[0]["timestamp"]

        # Step 2: Find a bar AFTER the break that closes back above the OR low
        # (the "failure" — price couldn't sustain below)
        after_break = post_range[post_range["timestamp"] > break_time]
        reclaim_mask = after_break["close"] > or_low
        reclaims = after_break[reclaim_mask]
        if reclaims.empty:
            return pd.DataFrame()

        signal_bar = reclaims.iloc[0]

    else:  # above
        # Step 1: Find a bar that breaks ABOVE the opening range high
        break_mask = post_range["high"] > or_high
        breaks = post_range[break_mask]
        if breaks.empty:
            return pd.DataFrame()

        break_time = breaks.iloc[0]["timestamp"]

        # Step 2: Find a bar AFTER the break that closes back below the OR high
        after_break = post_range[post_range["timestamp"] > break_time]
        reclaim_mask = after_break["close"] < or_high
        reclaims = after_break[reclaim_mask]
        if reclaims.empty:
            return pd.DataFrame()

        signal_bar = reclaims.iloc[0]

    entry = _enrich_signal_row(signal_bar, daily_row, direction,
                                f"orb_failure_{range_minutes}m", signal_date=signal_date)
    entry["or_high"] = float(or_high)
    entry["or_low"] = float(or_low)
    entry["or_range"] = float(or_range)
    return _build_signal_df([entry])


def generate_orb_failure_signals(enriched_daily, intraday_data_dict,
                                  range_minutes_list=None, directions=None):
    """
    Generate Opening Range Breakout Failure signals.

    Returns dict of {(direction, f"orb_failure_{range_min}m"): DataFrame}
    """
    if range_minutes_list is None:
        range_minutes_list = [15, 30]
    if directions is None:
        directions = ["below", "above"]

    daily_dates = list(enriched_daily["date"])
    daily_lookup = {row["date"]: row for _, row in enriched_daily.iterrows()}
    sorted_dates = sorted(intraday_data_dict.keys())

    all_signals = {}
    for direction in directions:
        for rm in range_minutes_list:
            key = (direction, f"orb_failure_{rm}m")
            signals = []

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
                sig = identify_orb_failure_signals_for_day(
                    intraday_df, daily_row, direction, rm, signal_date=date_obj
                )
                if not sig.empty:
                    signals.append(sig)

            if signals:
                all_signals[key] = pd.concat(signals, ignore_index=True)
            else:
                all_signals[key] = pd.DataFrame()

            count = len(all_signals[key])
            if count > 0:
                dir_label = "BELOW (long)" if direction == "below" else "ABOVE (short)"
                print(f"  ORB Failure {rm}m {dir_label}: {count} signals")

    return all_signals


# ═══════════════════════════════════════════════════════════════════════════
#  SIGNAL 3: BOLLINGER BAND TOUCH
# ═══════════════════════════════════════════════════════════════════════════

def identify_bollinger_signals_for_day(intraday_df, daily_row, direction="below",
                                        bb_period=20, bb_std=2.0, signal_date=None):
    """
    Bollinger Band touch: price hits the outer band → mean-reversion signal.

    - direction="below": Price touches or crosses BELOW the lower Bollinger Band.
      Enter long for mean-reversion back to the middle band.
    - direction="above": Price touches or crosses ABOVE the upper Bollinger Band.
      Enter short for mean-reversion back to the middle band.

    Uses 1-min bars with rolling window.
    """
    if intraday_df.empty or pd.isna(daily_row.get("atr")):
        return pd.DataFrame()

    df = intraday_df.copy()
    if "vwap" not in df.columns:
        df = calculate_session_vwap(df)

    # Calculate Bollinger Bands on 1-min closes
    df["bb_mid"] = df["close"].rolling(window=bb_period, min_periods=bb_period).mean()
    df["bb_std"] = df["close"].rolling(window=bb_period, min_periods=bb_period).std()
    df["bb_upper"] = df["bb_mid"] + bb_std * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - bb_std * df["bb_std"]

    # Drop rows before BB is calculated
    df = df.dropna(subset=["bb_mid"]).copy()
    if df.empty:
        return pd.DataFrame()

    if direction == "below":
        # Price closes at or below the lower band
        mask = df["close"] <= df["bb_lower"]
    else:
        # Price closes at or above the upper band
        mask = df["close"] >= df["bb_upper"]

    signals = df[mask]
    if signals.empty:
        return pd.DataFrame()

    # Take the FIRST touch
    first = signals.iloc[0]
    entry = _enrich_signal_row(first, daily_row, direction,
                                f"bb_touch_{bb_period}_{bb_std}", signal_date=signal_date)
    entry["bb_mid"] = float(first["bb_mid"])
    entry["bb_upper"] = float(first["bb_upper"])
    entry["bb_lower"] = float(first["bb_lower"])
    return _build_signal_df([entry])


def generate_bollinger_signals(enriched_daily, intraday_data_dict,
                                bb_configs=None, directions=None):
    """
    Generate Bollinger Band touch signals.

    bb_configs: list of (period, std_dev) tuples
    Returns dict of {(direction, f"bb_touch_{period}_{std}"): DataFrame}
    """
    if bb_configs is None:
        bb_configs = [(20, 2.0), (20, 2.5), (50, 2.0)]
    if directions is None:
        directions = ["below", "above"]

    daily_dates = list(enriched_daily["date"])
    daily_lookup = {row["date"]: row for _, row in enriched_daily.iterrows()}
    sorted_dates = sorted(intraday_data_dict.keys())

    all_signals = {}
    for direction in directions:
        for period, std in bb_configs:
            key = (direction, f"bb_touch_{period}_{std}")
            signals = []

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
                sig = identify_bollinger_signals_for_day(
                    intraday_df, daily_row, direction, period, std, signal_date=date_obj
                )
                if not sig.empty:
                    signals.append(sig)

            if signals:
                all_signals[key] = pd.concat(signals, ignore_index=True)
            else:
                all_signals[key] = pd.DataFrame()

            count = len(all_signals[key])
            if count > 0:
                dir_label = "LOWER BAND (long)" if direction == "below" else "UPPER BAND (short)"
                print(f"  BB({period},{std}) {dir_label}: {count} signals")

    return all_signals


# ═══════════════════════════════════════════════════════════════════════════
#  SIGNAL 4: VOLUME-SPIKE CAPITULATION
# ═══════════════════════════════════════════════════════════════════════════

def identify_volume_spike_signals_for_day(intraday_df, daily_row, direction="below",
                                           vol_mult=3.0, lookback=20, signal_date=None):
    """
    Volume-spike capitulation: a bar with extreme volume AND a new session
    extreme in price → panic selling/buying exhaustion → mean-reversion.

    - direction="below": Volume spike + new session LOW → capitulation selling,
      enter long for mean-reversion bounce.
    - direction="above": Volume spike + new session HIGH → euphoric buying,
      enter short for mean-reversion fade.

    vol_mult: volume must be >= vol_mult * rolling avg volume.
    lookback: rolling window for average volume.
    """
    if intraday_df.empty or pd.isna(daily_row.get("atr")):
        return pd.DataFrame()

    df = intraday_df.copy()
    if "vwap" not in df.columns:
        df = calculate_session_vwap(df)

    # Rolling average volume
    df["avg_vol"] = df["volume"].rolling(window=lookback, min_periods=lookback).mean()
    df["vol_ratio"] = df["volume"] / df["avg_vol"].replace(0, np.nan)

    # Running session high/low
    df["session_high"] = df["high"].cummax()
    df["session_low"] = df["low"].cummin()

    # Drop rows before lookback is ready
    df = df.dropna(subset=["avg_vol"]).copy()
    if df.empty:
        return pd.DataFrame()

    # Volume spike condition
    vol_spike = df["vol_ratio"] >= vol_mult

    if direction == "below":
        # New session low + volume spike = capitulation
        new_low = df["low"] <= df["session_low"]
        mask = vol_spike & new_low
    else:
        # New session high + volume spike = euphoria
        new_high = df["high"] >= df["session_high"]
        mask = vol_spike & new_high

    signals = df[mask]
    if signals.empty:
        return pd.DataFrame()

    # Take the FIRST capitulation bar
    first = signals.iloc[0]
    entry = _enrich_signal_row(first, daily_row, direction,
                                f"vol_spike_{vol_mult}x", signal_date=signal_date)
    entry["vol_ratio"] = float(first["vol_ratio"])
    entry["volume"] = float(first["volume"])
    entry["avg_volume"] = float(first["avg_vol"])
    return _build_signal_df([entry])


def generate_volume_spike_signals(enriched_daily, intraday_data_dict,
                                   vol_configs=None, directions=None):
    """
    Generate volume-spike capitulation signals.

    vol_configs: list of (vol_multiplier, lookback_bars) tuples
    Returns dict of {(direction, f"vol_spike_{mult}x"): DataFrame}
    """
    if vol_configs is None:
        vol_configs = [(3.0, 20), (4.0, 20), (5.0, 20)]
    if directions is None:
        directions = ["below", "above"]

    daily_dates = list(enriched_daily["date"])
    daily_lookup = {row["date"]: row for _, row in enriched_daily.iterrows()}
    sorted_dates = sorted(intraday_data_dict.keys())

    all_signals = {}
    for direction in directions:
        for vol_mult, lookback in vol_configs:
            key = (direction, f"vol_spike_{vol_mult}x")
            signals = []

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
                sig = identify_volume_spike_signals_for_day(
                    intraday_df, daily_row, direction, vol_mult, lookback,
                    signal_date=date_obj
                )
                if not sig.empty:
                    signals.append(sig)

            if signals:
                all_signals[key] = pd.concat(signals, ignore_index=True)
            else:
                all_signals[key] = pd.DataFrame()

            count = len(all_signals[key])
            if count > 0:
                dir_label = "CAPITULATION (long)" if direction == "below" else "EUPHORIA (short)"
                print(f"  Vol Spike {vol_mult}x/{lookback}bar {dir_label}: {count} signals")

    return all_signals


# ═══════════════════════════════════════════════════════════════════════════
#  MASTER SIGNAL SCANNER: RUN ALL GENERATORS
# ═══════════════════════════════════════════════════════════════════════════

def generate_all_v2_signals(enriched_daily, intraday_data_dict):
    """
    Run ALL signal generators and return a unified dict of signals.

    Returns dict of {(direction, signal_label): DataFrame of signals}
    Each DataFrame has the same columns the credit spread pipeline needs.
    """
    print("\n" + "=" * 60)
    print("  MULTI-SIGNAL GENERATOR v2")
    print("=" * 60)

    all_signals = {}

    # ── RSI(2) Signals ──
    print("\n[1/4] RSI(2) Oversold/Overbought Signals...")
    rsi_signals = generate_rsi2_signals(
        enriched_daily, intraday_data_dict,
        rsi_thresholds=[5, 10, 15],
        directions=["below", "above"]
    )
    all_signals.update(rsi_signals)

    # ── Opening Range Breakout Failure ──
    print("\n[2/4] Opening Range Breakout Failure Signals...")
    orb_signals = generate_orb_failure_signals(
        enriched_daily, intraday_data_dict,
        range_minutes_list=[15, 30],
        directions=["below", "above"]
    )
    all_signals.update(orb_signals)

    # ── Bollinger Band Touch ──
    print("\n[3/4] Bollinger Band Touch Signals...")
    bb_signals = generate_bollinger_signals(
        enriched_daily, intraday_data_dict,
        bb_configs=[(20, 2.0), (20, 2.5), (50, 2.0)],
        directions=["below", "above"]
    )
    all_signals.update(bb_signals)

    # ── Volume-Spike Capitulation ──
    print("\n[4/4] Volume-Spike Capitulation Signals...")
    vol_signals = generate_volume_spike_signals(
        enriched_daily, intraday_data_dict,
        vol_configs=[(3.0, 20), (4.0, 20), (5.0, 20)],
        directions=["below", "above"]
    )
    all_signals.update(vol_signals)

    # ── Summary ──
    total = sum(len(df) for df in all_signals.values() if not df.empty)
    non_empty = sum(1 for df in all_signals.values() if not df.empty)
    print(f"\n  TOTAL: {total} signals across {non_empty} signal types")

    # Show per-direction breakdown
    for direction in ["below", "above"]:
        dir_total = sum(len(df) for k, df in all_signals.items()
                       if k[0] == direction and not df.empty)
        dir_label = "BELOW (long)" if direction == "below" else "ABOVE (short)"
        print(f"  {dir_label}: {dir_total} signals")

    return all_signals

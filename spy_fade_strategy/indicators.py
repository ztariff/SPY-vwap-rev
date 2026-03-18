"""
Technical Indicators: Session VWAP, ATR, Consecutive Days
==========================================================
Correct intraday session VWAP calculated from 1-min bars.
"""

import pandas as pd
import numpy as np


def calculate_atr(daily_df, period=14):
    """
    Calculate Average True Range on daily bars.

    True Range = max(H-L, |H-prev_C|, |L-prev_C|)

    Parameters
    ----------
    daily_df : DataFrame with columns: date, open, high, low, close
    period : int, lookback period (default 14)

    Returns
    -------
    DataFrame with added 'atr' column
    """
    df = daily_df.copy()
    df["prev_close"] = df["close"].shift(1)
    df["tr1"] = df["high"] - df["low"]
    df["tr2"] = (df["high"] - df["prev_close"]).abs()
    df["tr3"] = (df["low"] - df["prev_close"]).abs()
    df["true_range"] = df[["tr1", "tr2", "tr3"]].max(axis=1)

    # Wilder's smoothed ATR (EMA-like)
    df["atr"] = np.nan
    # First ATR is simple average
    if len(df) >= period:
        df.iloc[period - 1, df.columns.get_loc("atr")] = df["true_range"].iloc[:period].mean()
        for i in range(period, len(df)):
            df.iloc[i, df.columns.get_loc("atr")] = (
                df.iloc[i - 1, df.columns.get_loc("atr")] * (period - 1) + df.iloc[i, df.columns.get_loc("true_range")]
            ) / period

    df = df.drop(columns=["prev_close", "tr1", "tr2", "tr3", "true_range"])
    return df


def calculate_session_vwap(intraday_df):
    """
    Calculate cumulative session VWAP from intraday bars.

    VWAP = cumulative(typical_price * volume) / cumulative(volume)
    typical_price = (high + low + close) / 3

    This resets at session open (09:30 ET) — proper intraday VWAP.

    Parameters
    ----------
    intraday_df : DataFrame with columns: timestamp, open, high, low, close, volume

    Returns
    -------
    DataFrame with added 'vwap' column (cumulative session VWAP)
    """
    df = intraday_df.copy()
    if df.empty:
        return df

    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_volume"] = df["typical_price"] * df["volume"]
    df["cum_tp_volume"] = df["tp_volume"].cumsum()
    df["cum_volume"] = df["volume"].cumsum()
    df["vwap"] = df["cum_tp_volume"] / df["cum_volume"]

    # Handle zero volume bars
    df["vwap"] = df["vwap"].ffill()

    df = df.drop(columns=["typical_price", "tp_volume", "cum_tp_volume", "cum_volume"])
    return df


def calculate_consecutive_days(daily_df):
    """
    Calculate consecutive up/down days.

    Returns DataFrame with:
    - consecutive_up: count of consecutive up closes (0 if today is down)
    - consecutive_down: count of consecutive down closes (0 if today is up)
    """
    df = daily_df.copy()
    df["daily_return"] = df["close"].pct_change()
    df["up_day"] = (df["close"] > df["close"].shift(1)).astype(int)
    df["down_day"] = (df["close"] < df["close"].shift(1)).astype(int)

    # Count consecutive up days
    consecutive_up = []
    consecutive_down = []
    up_count = 0
    down_count = 0

    for _, row in df.iterrows():
        if row["up_day"] == 1:
            up_count += 1
            down_count = 0
        elif row["down_day"] == 1:
            down_count += 1
            up_count = 0
        else:
            up_count = 0
            down_count = 0
        consecutive_up.append(up_count)
        consecutive_down.append(down_count)

    df["consecutive_up"] = consecutive_up
    df["consecutive_down"] = consecutive_down
    df = df.drop(columns=["daily_return", "up_day", "down_day"])
    return df


def calculate_daily_range_position(daily_df):
    """
    Where does the close sit in the daily range?
    0 = closed at low, 1 = closed at high.
    Useful for gauging overextension.
    """
    df = daily_df.copy()
    daily_range = df["high"] - df["low"]
    df["range_position"] = np.where(
        daily_range > 0,
        (df["close"] - df["low"]) / daily_range,
        0.5
    )
    return df


def calculate_gap(daily_df):
    """
    Calculate overnight gap: today's open vs yesterday's close.
    Positive = gap up, negative = gap down.
    """
    df = daily_df.copy()
    df["gap_pct"] = (df["open"] - df["close"].shift(1)) / df["close"].shift(1) * 100
    return df


def enrich_daily_data(spy_daily, vix_daily=None, tlt_daily=None, atr_period=14):
    """
    Full enrichment pipeline for daily SPY data.
    Adds: ATR, consecutive days, range position, gap, and merges VIX/TLT.
    """
    df = spy_daily.copy()

    # Core indicators
    df = calculate_atr(df, period=atr_period)
    df = calculate_consecutive_days(df)
    df = calculate_daily_range_position(df)
    df = calculate_gap(df)

    # Merge VIX
    if vix_daily is not None and not vix_daily.empty:
        df = df.merge(vix_daily[["date", "vix_close"]], on="date", how="left")
        df["vix_close"] = df["vix_close"].ffill()

        # VIX regime
        df["vix_regime"] = pd.cut(
            df["vix_close"],
            bins=[0, 15, 20, 25, 30, 100],
            labels=["<15", "15-20", "20-25", "25-30", "30+"]
        )
    else:
        df["vix_close"] = np.nan
        df["vix_regime"] = "unknown"

    # Merge TLT (bonds)
    if tlt_daily is not None and not tlt_daily.empty:
        tlt_cols = tlt_daily[["date", "close"]].rename(columns={"close": "tlt_close"})
        df = df.merge(tlt_cols, on="date", how="left")
        df["tlt_close"] = df["tlt_close"].ffill()
        df["tlt_daily_return"] = df["tlt_close"].pct_change()
        # Bond direction: if TLT up (yields down), typically risk-on
        df["bonds_up"] = (df["tlt_daily_return"] > 0).astype(int)
    else:
        df["tlt_close"] = np.nan
        df["tlt_daily_return"] = np.nan
        df["bonds_up"] = np.nan

    # 5-day SPY return (broader trend context)
    df["spy_5d_return"] = df["close"].pct_change(5)

    return df

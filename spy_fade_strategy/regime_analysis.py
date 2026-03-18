"""
Regime Analysis Module
=======================
Breaks down strategy performance by contextual factors:
- VIX regime
- Consecutive up/down days
- Time of day
- Bond direction (TLT)
- Gap direction
- ATR extension level
- Combined factors (e.g., 2+ up days AND high VIX)
"""

import pandas as pd
import numpy as np


def analyze_by_regime(trades_df, group_col, regime_label=None):
    """
    Group trades by a regime column and compute metrics per group.

    Parameters
    ----------
    trades_df : DataFrame of individual trades with pnl_pct and regime columns
    group_col : str, column to group by
    regime_label : str, label for the analysis

    Returns
    -------
    DataFrame with metrics per regime bucket
    """
    if trades_df.empty or group_col not in trades_df.columns:
        return pd.DataFrame()

    results = []
    for group_val, group_df in trades_df.groupby(group_col):
        n = len(group_df)
        winners = group_df[group_df["pnl_pct"] > 0]
        metrics = {
            "regime": group_val,
            "regime_type": regime_label or group_col,
            "n_trades": n,
            "win_rate": len(winners) / n * 100 if n > 0 else 0,
            "avg_pnl": group_df["pnl_pct"].mean(),
            "median_pnl": group_df["pnl_pct"].median(),
            "total_pnl": group_df["pnl_pct"].sum(),
            "std_pnl": group_df["pnl_pct"].std(),
            "best_trade": group_df["pnl_pct"].max(),
            "worst_trade": group_df["pnl_pct"].min(),
        }

        # Sharpe-like ratio (per trade)
        if metrics["std_pnl"] > 0:
            metrics["sharpe_per_trade"] = metrics["avg_pnl"] / metrics["std_pnl"]
        else:
            metrics["sharpe_per_trade"] = 0

        results.append(metrics)

    return pd.DataFrame(results).sort_values("avg_pnl", ascending=False)


def run_full_regime_analysis(stock_trades_df, signals_df):
    """
    Run comprehensive regime analysis on stock trades.
    Returns dict of {analysis_name: DataFrame}.
    """
    print(f"\n{'='*60}")
    print("REGIME ANALYSIS")
    print(f"{'='*60}")

    if stock_trades_df.empty:
        print("  No trades to analyze")
        return {}

    analyses = {}

    # 1. VIX Regime
    if "vix_regime" in stock_trades_df.columns:
        analyses["vix_regime"] = analyze_by_regime(
            stock_trades_df, "vix_regime", "VIX Level"
        )
        print(f"\n  VIX Regime Analysis:")
        _print_regime_summary(analyses["vix_regime"])

    # 2. Consecutive Up Days
    if "consecutive_up" in stock_trades_df.columns:
        # Bucket consecutive up days
        trades = stock_trades_df.copy()
        trades["consec_up_bucket"] = pd.cut(
            trades["consecutive_up"],
            bins=[-1, 0, 1, 2, 3, 100],
            labels=["0 (down/flat)", "1 day up", "2 days up", "3 days up", "4+ days up"]
        )
        analyses["consecutive_up"] = analyze_by_regime(
            trades, "consec_up_bucket", "Consecutive Up Days"
        )
        print(f"\n  Consecutive Up Days Analysis:")
        _print_regime_summary(analyses["consecutive_up"])

    # 3. Time of Day
    if "time_bucket" in stock_trades_df.columns:
        analyses["time_of_day"] = analyze_by_regime(
            stock_trades_df, "time_bucket", "Time of Day"
        )
        print(f"\n  Time of Day Analysis:")
        _print_regime_summary(analyses["time_of_day"])

    # 4. Bond Direction (TLT)
    if "bonds_up" in stock_trades_df.columns:
        trades = stock_trades_df.copy()
        trades["bond_direction"] = trades["bonds_up"].map(
            {1: "Bonds Up (yields down)", 0: "Bonds Down (yields up)"}
        )
        trades = trades.dropna(subset=["bond_direction"])
        if not trades.empty:
            analyses["bonds"] = analyze_by_regime(
                trades, "bond_direction", "Bond Direction"
            )
            print(f"\n  Bond Direction Analysis:")
            _print_regime_summary(analyses["bonds"])

    # 5. Gap direction at open
    if "gap_pct" in stock_trades_df.columns:
        trades = stock_trades_df.copy()
        trades["gap_bucket"] = pd.cut(
            trades["gap_pct"],
            bins=[-100, -0.5, -0.1, 0.1, 0.5, 100],
            labels=["Big gap down", "Small gap down", "Flat open",
                    "Small gap up", "Big gap up"]
        )
        analyses["gap"] = analyze_by_regime(
            trades, "gap_bucket", "Gap at Open"
        )
        print(f"\n  Gap at Open Analysis:")
        _print_regime_summary(analyses["gap"])

    # 6. ATR extension level (how far above VWAP in ATR units)
    if "dist_above_vwap_atr" in stock_trades_df.columns:
        trades = stock_trades_df.copy()
        trades["extension_bucket"] = pd.cut(
            trades["dist_above_vwap_atr"],
            bins=[0, 1.0, 1.25, 1.5, 2.0, 100],
            labels=["1.0x ATR", "1.0-1.25x", "1.25-1.5x", "1.5-2.0x", "2.0x+"]
        )
        analyses["extension"] = analyze_by_regime(
            trades, "extension_bucket", "ATR Extension"
        )
        print(f"\n  ATR Extension Level Analysis:")
        _print_regime_summary(analyses["extension"])

    # ─── COMBINED FACTORS (the nuance you asked about) ────────────────────

    # 7. Consecutive up + VIX (is 2+ up days in high VIX worth 10x risk?)
    if "consecutive_up" in stock_trades_df.columns and "vix_regime" in stock_trades_df.columns:
        trades = stock_trades_df.copy()
        trades["consec_vix"] = (
            trades["consecutive_up"].apply(lambda x: "2+up" if x >= 2 else "0-1up")
            + " | VIX " + trades["vix_regime"].astype(str)
        )
        analyses["consec_up_x_vix"] = analyze_by_regime(
            trades, "consec_vix", "Consecutive Up x VIX"
        )
        print(f"\n  Consecutive Up Days x VIX Combined:")
        _print_regime_summary(analyses["consec_up_x_vix"])

    # 8. Extension level + Consecutive days
    if "dist_above_vwap_atr" in stock_trades_df.columns and "consecutive_up" in stock_trades_df.columns:
        trades = stock_trades_df.copy()
        trades["ext_consec"] = (
            trades["dist_above_vwap_atr"].apply(
                lambda x: "1.5+ ATR" if x >= 1.5 else "1.0-1.5 ATR"
            )
            + " | " + trades["consecutive_up"].apply(
                lambda x: f"{min(x,3)}+ up" if x >= 2 else "0-1 up"
            )
        )
        analyses["extension_x_consec"] = analyze_by_regime(
            trades, "ext_consec", "Extension x Consecutive"
        )
        print(f"\n  Extension Level x Consecutive Days Combined:")
        _print_regime_summary(analyses["extension_x_consec"])

    # 9. Time of day + VIX
    if "time_bucket" in stock_trades_df.columns and "vix_regime" in stock_trades_df.columns:
        trades = stock_trades_df.copy()
        trades["time_vix"] = trades["time_bucket"] + " | VIX " + trades["vix_regime"].astype(str)
        analyses["time_x_vix"] = analyze_by_regime(
            trades, "time_vix", "Time of Day x VIX"
        )
        print(f"\n  Time of Day x VIX Combined:")
        _print_regime_summary(analyses["time_x_vix"])

    # 10. SPY 5-day momentum
    if "spy_5d_return" in stock_trades_df.columns:
        trades = stock_trades_df.copy()
        trades = trades.dropna(subset=["spy_5d_return"])
        if not trades.empty:
            trades["momentum_bucket"] = pd.cut(
                trades["spy_5d_return"] * 100,
                bins=[-100, -2, -0.5, 0.5, 2, 100],
                labels=["Strong 5d down", "Mild 5d down", "Flat 5d",
                        "Mild 5d up", "Strong 5d up"]
            )
            analyses["momentum"] = analyze_by_regime(
                trades, "momentum_bucket", "5-Day Momentum"
            )
            print(f"\n  5-Day SPY Momentum Analysis:")
            _print_regime_summary(analyses["momentum"])

    return analyses


def compute_risk_sizing_recommendation(analyses):
    """
    Based on regime analysis, compute relative risk sizing recommendations.

    Returns dict of {regime_combo: risk_multiplier}
    """
    recommendations = {}

    # Use consecutive up + VIX as primary sizing driver
    if "consec_up_x_vix" in analyses:
        df = analyses["consec_up_x_vix"]
        if not df.empty:
            # Normalize: best regime = 3x, worst = 0.5x, baseline = 1x
            baseline_avg = df["avg_pnl"].mean()
            baseline_std = df["avg_pnl"].std()

            if baseline_std > 0:
                for _, row in df.iterrows():
                    z_score = (row["avg_pnl"] - baseline_avg) / baseline_std
                    # Map z-score to risk multiplier: z=0 → 1x, z=2 → 3x, z=-2 → 0.25x
                    multiplier = max(0.25, min(5.0, 1.0 + z_score * 1.0))
                    recommendations[row["regime"]] = {
                        "risk_multiplier": round(multiplier, 2),
                        "avg_pnl": round(row["avg_pnl"], 4),
                        "n_trades": row["n_trades"],
                        "win_rate": round(row["win_rate"], 1),
                        "confidence": "high" if row["n_trades"] >= 30 else
                                      "medium" if row["n_trades"] >= 15 else "low"
                    }

    return recommendations


def compare_directions(above_trades_df, below_trades_df):
    """
    Compare above-VWAP (fade/short) vs below-VWAP (buy/long) performance
    across all regime dimensions. Returns comparison DataFrame.
    """
    print(f"\n{'='*60}")
    print("DIRECTION COMPARISON: ABOVE vs BELOW VWAP")
    print(f"{'='*60}")

    comparisons = []
    regime_cols = [
        ("vix_regime", "VIX Regime"),
        ("time_bucket", "Time of Day"),
    ]

    for col, label in regime_cols:
        for direction, trades, dir_label in [
            ("above", above_trades_df, "ABOVE (short)"),
            ("below", below_trades_df, "BELOW (long)")
        ]:
            if trades.empty or col not in trades.columns:
                continue
            for val, group in trades.groupby(col):
                n = len(group)
                if n < 5:
                    continue
                winners = group[group["pnl_pct"] > 0]
                comparisons.append({
                    "regime_type": label,
                    "regime_value": str(val),
                    "direction": dir_label,
                    "n_trades": n,
                    "win_rate": len(winners) / n * 100,
                    "avg_pnl": group["pnl_pct"].mean(),
                    "total_pnl": group["pnl_pct"].sum(),
                })

    # Overall comparison
    for direction, trades, dir_label in [
        ("above", above_trades_df, "ABOVE (short)"),
        ("below", below_trades_df, "BELOW (long)")
    ]:
        if trades.empty:
            continue
        n = len(trades)
        winners = trades[trades["pnl_pct"] > 0]
        comparisons.append({
            "regime_type": "OVERALL",
            "regime_value": "All trades",
            "direction": dir_label,
            "n_trades": n,
            "win_rate": len(winners) / n * 100,
            "avg_pnl": trades["pnl_pct"].mean(),
            "total_pnl": trades["pnl_pct"].sum(),
        })

    if not comparisons:
        print("  Insufficient data for comparison")
        return pd.DataFrame()

    df = pd.DataFrame(comparisons)

    # Print summary
    overall = df[df["regime_type"] == "OVERALL"]
    if not overall.empty:
        print("\n  Overall:")
        for _, row in overall.iterrows():
            print(f"    {row['direction']:20s}  N={row['n_trades']:4d}  "
                  f"WR={row['win_rate']:5.1f}%  Avg={row['avg_pnl']:+7.4f}%  "
                  f"Total={row['total_pnl']:+7.2f}%")

    return df


def _print_regime_summary(df):
    """Print a compact summary of regime analysis."""
    if df.empty:
        print("    No data")
        return
    for _, row in df.iterrows():
        print(f"    {row['regime']:30s}  N={row['n_trades']:4d}  "
              f"WR={row['win_rate']:5.1f}%  Avg={row['avg_pnl']:+7.3f}%  "
              f"Sharpe={row['sharpe_per_trade']:+5.2f}")

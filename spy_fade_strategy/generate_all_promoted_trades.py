#!/usr/bin/env python3
"""
Generate per-trade JSON for ALL 5 promoted edges.
Uses real Polygon cached data. Outputs all_promoted_trades.json for the dashboard.

Promoted edges:
1. SPY Bull Put 0.5x Below — 0.30/0.20d, tgt=0.25, sl=2.0, t=15min
2. SPY Bull Put 0.6x Below — 0.20/0.10d, tgt=0.25, sl=1.5, t=60min
3. SPY Bull Put 0.7x Below — 0.20/0.10d, tgt=0.50, sl=2.0, t=EOD
4. SPY Bear Call 0.5x Above — 0.25/0.15d, tgt=0.25, sl=3.0, t=60min
5. SPY Bear Call 0.7x Above — 0.25/0.15d, tgt=0.25, sl=3.0, t=60min

All P&L from real Polygon market prices. No fabrication.
"""

import sys, os, json, time, math
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_all_options_data, pull_options_for_signal_day, OptionsDayData
from backtest_spreads import simulate_credit_spread_trade

# ═══════════════════════════════════════════════════════════════════
#  PROMOTED STRATEGY DEFINITIONS
# ═══════════════════════════════════════════════════════════════════

STRATEGIES = [
    {
        "key": "spy_bull_put_0.5x_030_020",
        "label": "SPY Bull Put 0.30/0.20d @ 0.5x ATR",
        "ticker": "SPY",
        "direction": "below",
        "spread_type": "bull_put_spread",
        "atr_mult": 0.5,
        "option_side": "puts",
        "short_delta": 0.30,
        "long_delta": 0.20,
        "target": 0.25,
        "stop": 2.0,
        "time_exit": 15,
        "verdict": "promoted",
    },
    {
        "key": "spy_bull_put_0.5x_025_015",
        "label": "SPY Bull Put 0.25/0.15d @ 0.5x ATR",
        "ticker": "SPY",
        "direction": "below",
        "spread_type": "bull_put_spread",
        "atr_mult": 0.5,
        "option_side": "puts",
        "short_delta": 0.25,
        "long_delta": 0.15,
        "target": 0.25,
        "stop": 2.0,
        "time_exit": 15,
        "verdict": "promoted",
    },
    {
        "key": "spy_bull_put_0.6x_020_010",
        "label": "SPY Bull Put 0.20/0.10d @ 0.6x ATR",
        "ticker": "SPY",
        "direction": "below",
        "spread_type": "bull_put_spread",
        "atr_mult": 0.6,
        "option_side": "puts",
        "short_delta": 0.20,
        "long_delta": 0.10,
        "target": 0.25,
        "stop": 1.5,
        "time_exit": 60,
        "verdict": "promoted",
    },
    {
        "key": "spy_bull_put_0.7x_020_010",
        "label": "SPY Bull Put 0.20/0.10d @ 0.7x ATR",
        "ticker": "SPY",
        "direction": "below",
        "spread_type": "bull_put_spread",
        "atr_mult": 0.7,
        "option_side": "puts",
        "short_delta": 0.20,
        "long_delta": 0.10,
        "target": 0.50,
        "stop": 2.0,
        "time_exit": "EOD",
        "verdict": "promoted",
    },
    {
        "key": "spy_bear_call_0.5x_025_015",
        "label": "SPY Bear Call 0.25/0.15d @ 0.5x ATR",
        "ticker": "SPY",
        "direction": "above",
        "spread_type": "bear_call_spread",
        "atr_mult": 0.5,
        "option_side": "calls",
        "short_delta": 0.25,
        "long_delta": 0.15,
        "target": 0.25,
        "stop": 3.0,
        "time_exit": 60,
        "verdict": "promoted",
    },
    {
        "key": "spy_bear_call_0.7x_025_015",
        "label": "SPY Bear Call 0.25/0.15d @ 0.7x ATR",
        "ticker": "SPY",
        "direction": "above",
        "spread_type": "bear_call_spread",
        "atr_mult": 0.7,
        "option_side": "calls",
        "short_delta": 0.25,
        "long_delta": 0.15,
        "target": 0.25,
        "stop": 3.0,
        "time_exit": 60,
        "verdict": "promoted",
    },
]

def ts_to_iso(ts):
    if ts is None: return None
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

def ts_to_timestr(ts):
    if ts is None: return None
    return ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)

def safe_float(v):
    if v is None: return None
    f = float(v)
    if math.isnan(f) or math.isinf(f): return None
    return f


def main():
    t0 = time.time()
    print("=" * 70)
    print("  GENERATING PER-TRADE DATA FOR ALL PROMOTED EDGES")
    print("  Real Polygon prices only — no fabrication")
    print("=" * 70)

    # ── Load base data ──
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    # ── Generate signals for all needed ATR levels and directions ──
    needed_mults = sorted(set(s["atr_mult"] for s in STRATEGIES))
    needed_dirs = sorted(set(s["direction"] for s in STRATEGIES))
    print(f"\n  ATR multipliers needed: {needed_mults}")
    print(f"  Directions needed: {needed_dirs}")

    signals_by_key = generate_all_signals(enriched, intraday_data, needed_mults, needed_dirs)

    # ── Pull options data for all signal days ──
    print("\n  Collecting unique signal days...")
    unique_days = {}
    strat_signals = {}

    for strat in STRATEGIES:
        key = (strat["direction"], strat["atr_mult"])
        sig_df = signals_by_key.get(key, pd.DataFrame())
        if sig_df.empty:
            print(f"    {strat['label']}: 0 signals")
            continue
        strat_signals[strat["key"]] = sig_df
        print(f"    {strat['label']}: {len(sig_df)} signals")

        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in unique_days:
                unique_days[date_str] = {
                    "spot": signal["entry_price"],
                    "entry_time": signal["entry_time"],
                }

    print(f"\n  Pulling options for {len(unique_days)} unique signal days...")
    all_options_data = {}
    for i, (date_str, info) in enumerate(sorted(unique_days.items())):
        if (i + 1) % 25 == 0:
            print(f"    [{i + 1}/{len(unique_days)}]...")
        try:
            day_data = pull_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options_data[date_str] = day_data
        except Exception as e:
            print(f"    ERROR {date_str}: {e}")
            all_options_data[date_str] = OptionsDayData(date_str, info["spot"], info["entry_time"])

    print(f"  Got options for {len(all_options_data)} days")

    # ── Simulate trades for each strategy ──
    print(f"\n{'='*70}")
    print("  SIMULATING TRADES")
    print(f"{'='*70}")

    all_trades = []

    for strat in STRATEGIES:
        if strat["key"] not in strat_signals:
            print(f"\n  {strat['label']}: NO SIGNALS — skipping")
            continue

        sig_df = strat_signals[strat["key"]]
        option_side = strat["option_side"]
        short_delta = strat["short_delta"]
        long_delta = strat["long_delta"]
        target = strat["target"]
        stop = strat["stop"]
        time_exit = strat["time_exit"]

        trade_count = 0
        skip_count = 0

        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in all_options_data:
                skip_count += 1
                continue

            day_data = all_options_data[date_str]
            opt_dict = getattr(day_data, option_side)

            if short_delta not in opt_dict or long_delta not in opt_dict:
                skip_count += 1
                continue

            short_info = opt_dict[short_delta]
            long_info = opt_dict[long_delta]

            # Get bars from entry time onward
            sig_entry_time = signal["entry_time"]
            short_all = short_info.get("all_bars", short_info["bars"])
            long_all = long_info.get("all_bars", long_info["bars"])

            short_bars = short_all[short_all["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)
            long_bars = long_all[long_all["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)

            if short_bars.empty or long_bars.empty:
                skip_count += 1
                continue

            short_entry = short_bars.iloc[0]["open"]
            long_entry = long_bars.iloc[0]["open"]
            credit = short_entry - long_entry

            if credit <= 0:
                skip_count += 1
                continue

            spread_width = abs(short_info["strike"] - long_info["strike"])

            result = simulate_credit_spread_trade(
                short_bars, long_bars, short_entry, long_entry,
                target, stop, time_exit, spread_width
            )

            bars_held = result.get("bars_held", 0)
            exit_idx = max(0, min(bars_held - 1, len(short_bars) - 1)) if bars_held > 0 else 0
            exit_bar = short_bars.iloc[exit_idx]

            trade_entry = {
                "date": date_str,
                "direction": strat["direction"],
                "product": strat["spread_type"],
                "strategy_key": strat["key"],
                "strategy_label": strat["label"],
                "atr_mult": float(strat["atr_mult"]),
                "verdict": strat["verdict"],
                "short_delta": float(short_delta),
                "long_delta": float(long_delta),
                "short_strike": safe_float(short_info["strike"]),
                "long_strike": safe_float(long_info["strike"]),
                "spread_width": safe_float(spread_width),
                "short_ticker": short_info.get("ticker"),
                "long_ticker": long_info.get("ticker"),
                "spy_entry_price": safe_float(signal["entry_price"]),
                "entry_time": ts_to_timestr(signal["entry_time"]),
                "entry_time_iso": ts_to_iso(signal["entry_time"]),
                "short_entry_price": safe_float(short_entry),
                "long_entry_price": safe_float(long_entry),
                "credit_received": safe_float(credit),
                "exit_spread_value": safe_float(result.get("exit_spread_value", credit)),
                "exit_time": ts_to_timestr(exit_bar["timestamp"]),
                "exit_time_iso": ts_to_iso(exit_bar["timestamp"]),
                "pnl_pct": safe_float(result.get("pnl_on_risk", result.get("pnl_pct", 0))),
                "pnl_dollar": safe_float(result.get("pnl_dollar", 0)),
                "exit_reason": result.get("exit_reason", "unknown"),
                "minutes_held": safe_float(result.get("minutes_held", 0)),
                "target_pct": float(target),
                "stop_pct": float(stop),
                "time_exit": str(time_exit),
                "vix": str(signal.get("vix_regime", "")) if pd.notna(signal.get("vix_regime", None)) else None,
            }
            all_trades.append(trade_entry)
            trade_count += 1

        print(f"  {strat['label']}: {trade_count} trades ({skip_count} skipped)")

    all_trades.sort(key=lambda t: t["date"])

    # ── Save ──
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_promoted_trades.json")
    with open(output_path, "w") as f:
        json.dump(all_trades, f, indent=2, default=str)

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"  SAVED {len(all_trades)} trades to {output_path}")
    print(f"  Elapsed: {elapsed:.0f}s")
    print(f"{'='*70}")

    # Summary by strategy
    from collections import Counter
    strats = Counter(t["strategy_key"] for t in all_trades)
    for k, v in strats.most_common():
        print(f"    {k}: {v} trades")

    # Summary by year
    years = Counter(t["date"][:4] for t in all_trades)
    for y, c in sorted(years.items()):
        print(f"    {y}: {c} trades")


if __name__ == "__main__":
    main()

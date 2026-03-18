#!/usr/bin/env python3
"""
Generate per-trade JSON for the top promoted stock frontside strategies.
Picks a small set of DIVERSE, non-overlapping configs to show on the dashboard.
All real Polygon 1-min data. No fabrication.
"""
import sys, os, json, time, math
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data, calculate_session_vwap

STOCK_COMM_PCT = 0.002

# Top strategies — pick DIVERSE configs (different dir/mult/target combos)
STRATEGIES = [
    # FADE above VWAP — best Sharpe×sqrt(N) configs
    {"key": "spy_fade_0.4x_t075_T15", "label": "SPY Fade 0.4x ATR | Tgt 0.75% | 15m",
     "dir": "above", "mult": 0.4, "stop": 0.10, "target": 0.75, "te": 15},
    {"key": "spy_fade_0.4x_t050_T5", "label": "SPY Fade 0.4x ATR | Tgt 0.50% | 5m",
     "dir": "above", "mult": 0.4, "stop": 0.10, "target": 0.50, "te": 5},
    {"key": "spy_fade_0.4x_t100_T15", "label": "SPY Fade 0.4x ATR | Tgt 1.00% | 15m",
     "dir": "above", "mult": 0.4, "stop": 0.20, "target": 1.00, "te": 15},
    {"key": "spy_fade_0.5x_t100_T5", "label": "SPY Fade 0.5x ATR | Tgt 1.00% | 5m",
     "dir": "above", "mult": 0.5, "stop": 0.25, "target": 1.00, "te": 5},
    # BUY below VWAP — highest N configs
    {"key": "spy_buy_0.4x_t100_T5", "label": "SPY Buy 0.4x ATR | Tgt 1.00% | 5m",
     "dir": "below", "mult": 0.4, "stop": 1.00, "target": 1.00, "te": 5},
    {"key": "spy_buy_0.4x_t100_T10", "label": "SPY Buy 0.4x ATR | Tgt 1.00% | 10m",
     "dir": "below", "mult": 0.4, "stop": 1.00, "target": 1.00, "te": 10},
    {"key": "spy_buy_0.4x_t075_T5", "label": "SPY Buy 0.4x ATR | Tgt 0.75% | 5m",
     "dir": "below", "mult": 0.4, "stop": 1.00, "target": 0.75, "te": 5},
    {"key": "spy_buy_0.3x_t050_T15", "label": "SPY Buy 0.3x ATR | Tgt 0.50% | 15m",
     "dir": "below", "mult": 0.3, "stop": 1.00, "target": 0.50, "te": 15},
    # Quick scalps — the 0.8x configs that originally passed
    {"key": "spy_buy_0.8x_t005_T15", "label": "SPY Buy 0.8x ATR | Tgt 0.05% | 15m",
     "dir": "below", "mult": 0.8, "stop": 1.00, "target": 0.05, "te": 15},
]


def simulate(bars, entry_price, stop_pct, target_pct, time_exit_min, is_long):
    """Frontside limit order simulation."""
    if bars.empty:
        return {"pnl_pct": 0, "exit_reason": "no_bars", "minutes_held": 0,
                "exit_price": entry_price}
    entry_ts = bars["timestamp"].iloc[0]
    tp = entry_price * (1 + target_pct/100) if is_long else entry_price * (1 - target_pct/100)
    sp = entry_price * (1 - stop_pct/100) if is_long else entry_price * (1 + stop_pct/100)

    for idx in range(len(bars)):
        bar = bars.iloc[idx]
        mins = (bar["timestamp"] - entry_ts).total_seconds() / 60
        if time_exit_min is not None:
            if time_exit_min == "EOD":
                if bar["timestamp"].hour == 15 and bar["timestamp"].minute >= 59:
                    pnl = ((bar["close"]-entry_price)/entry_price*100) if is_long else ((entry_price-bar["close"])/entry_price*100)
                    return {"pnl_pct": pnl, "exit_reason": "time_eod", "minutes_held": mins,
                            "exit_price": bar["close"], "exit_time": bar["timestamp"]}
            elif mins >= time_exit_min:
                pnl = ((bar["close"]-entry_price)/entry_price*100) if is_long else ((entry_price-bar["close"])/entry_price*100)
                return {"pnl_pct": pnl, "exit_reason": f"time_{time_exit_min}m", "minutes_held": mins,
                        "exit_price": bar["close"], "exit_time": bar["timestamp"]}
        if is_long:
            if bar["high"] >= tp:
                return {"pnl_pct": target_pct, "exit_reason": "target", "minutes_held": mins,
                        "exit_price": tp, "exit_time": bar["timestamp"]}
            if bar["low"] <= sp:
                return {"pnl_pct": -stop_pct, "exit_reason": "stop_loss", "minutes_held": mins,
                        "exit_price": sp, "exit_time": bar["timestamp"]}
        else:
            if bar["low"] <= tp:
                return {"pnl_pct": target_pct, "exit_reason": "target", "minutes_held": mins,
                        "exit_price": tp, "exit_time": bar["timestamp"]}
            if bar["high"] >= sp:
                return {"pnl_pct": -stop_pct, "exit_reason": "stop_loss", "minutes_held": mins,
                        "exit_price": sp, "exit_time": bar["timestamp"]}

    last = bars.iloc[-1]
    mins = (last["timestamp"] - entry_ts).total_seconds() / 60
    pnl = ((last["close"]-entry_price)/entry_price*100) if is_long else ((entry_price-last["close"])/entry_price*100)
    return {"pnl_pct": pnl, "exit_reason": "end_of_data", "minutes_held": mins,
            "exit_price": last["close"], "exit_time": last["timestamp"]}


def safe_float(v):
    if v is None: return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except: return None


def main():
    t0 = time.time()
    print("=" * 70)
    print("  GENERATING PER-TRADE DATA FOR STOCK STRATEGIES")
    print("=" * 70)

    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)
    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    daily_lookup = {row["date"]: row for _, row in enriched.iterrows()}
    daily_dates = list(enriched["date"])

    # Pre-compute VWAP
    days = {}
    for ds in sorted(intraday.keys()):
        date_obj = datetime.strptime(ds, "%Y-%m-%d").date()
        prior = [d for d in daily_dates if d < date_obj]
        if not prior: continue
        dr = daily_lookup.get(prior[-1])
        if dr is None or pd.isna(dr.get("atr")): continue
        vdf = calculate_session_vwap(intraday[ds])
        if not vdf.empty:
            days[ds] = {"df": vdf, "atr": float(dr["atr"]), "date_obj": date_obj,
                        "vix_close": dr.get("vix_close", None)}

    print(f"  {len(days)} days with VWAP + ATR")

    all_trades = []

    for strat in STRATEGIES:
        direction = strat["dir"]
        mult = strat["mult"]
        is_long = (direction == "below")
        trade_count = 0

        for ds, info in sorted(days.items()):
            threshold = info["atr"] * mult
            df = info["df"]

            # Find frontside entry
            entry_price = None
            remaining = None
            entry_time = None
            entry_vwap = None

            for idx in range(len(df)):
                bar = df.iloc[idx]
                vwap = bar["vwap"]
                if pd.isna(vwap) or vwap <= 0: continue

                if direction == "below":
                    level = vwap - threshold
                    if bar["low"] <= level:
                        entry_price = level
                        remaining = df.iloc[idx+1:].copy().reset_index(drop=True)
                        entry_time = bar["timestamp"]
                        entry_vwap = vwap
                        break
                else:
                    level = vwap + threshold
                    if bar["high"] >= level:
                        entry_price = level
                        remaining = df.iloc[idx+1:].copy().reset_index(drop=True)
                        entry_time = bar["timestamp"]
                        entry_vwap = vwap
                        break

            if entry_price is None or remaining is None or remaining.empty:
                continue

            result = simulate(remaining, entry_price, strat["stop"], strat["target"],
                            strat["te"], is_long)

            pnl_adj = result["pnl_pct"] - STOCK_COMM_PCT

            trade = {
                "date": ds,
                "direction": direction,
                "product": "stock",
                "strategy_key": strat["key"],
                "strategy_label": strat["label"],
                "atr_mult": mult,
                "verdict": "promoted",
                "ticker": "SPY",
                "spy_entry_price": safe_float(entry_price),
                "entry_time": entry_time.strftime("%H:%M") if entry_time else None,
                "entry_time_iso": str(entry_time) if entry_time else None,
                "exit_price": safe_float(result.get("exit_price")),
                "exit_time": result.get("exit_time", entry_time),
                "exit_time_iso": str(result.get("exit_time", "")) if result.get("exit_time") else None,
                "entry_vwap": safe_float(entry_vwap),
                "atr_value": safe_float(info["atr"]),
                "threshold_level": safe_float(entry_price),
                "pnl_pct": safe_float(result["pnl_pct"]),
                "pnl_adj_pct": safe_float(pnl_adj),
                "pnl_dollar": safe_float(result["pnl_pct"] / 100 * entry_price) if entry_price else None,
                "exit_reason": result["exit_reason"],
                "minutes_held": safe_float(result["minutes_held"]),
                "target_pct": strat["target"],
                "stop_pct": strat["stop"],
                "time_exit": str(strat["te"]),
                "vix": safe_float(info.get("vix_close")),
                "commission_status": "SURVIVES",
            }
            all_trades.append(trade)
            trade_count += 1

        print(f"  {strat['label']}: {trade_count} trades")

    all_trades.sort(key=lambda t: t["date"])

    with open("stock_frontside_trades.json", "w") as f:
        json.dump(all_trades, f, indent=2, default=str)

    print(f"\n  SAVED {len(all_trades)} trades to stock_frontside_trades.json")

    # Summary
    strats = defaultdict(int)
    for t in all_trades:
        strats[t["strategy_key"]] += 1
    for k, v in sorted(strats.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v} trades")

    # By year
    years = defaultdict(int)
    for t in all_trades:
        years[t["date"][:4]] += 1
    for y, c in sorted(years.items()):
        print(f"    {y}: {c} trades")

    elapsed = time.time() - t0
    print(f"\n  Done: {elapsed:.0f}s")


if __name__ == "__main__":
    main()

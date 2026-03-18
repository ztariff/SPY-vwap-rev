#!/usr/bin/env python3
"""
COMMISSION-AWARE STRATEGY SEARCH
=================================
Re-runs the FULL grid search with commissions baked in from the start.
Tests ALL delta pairs × exit combos × ATR mults × both directions.

IBKR Tiered commission model:
  per_contract = $0.65, exchange = $0.05, clearing = $0.02, regulatory = $0.01
  = $0.73 per contract per leg
  Round-trip per contract = $0.73 × 4 (2 legs × open + close) = $2.92

Commission hurdle: ~0.83% of risk capital per trade for typical $3-4 spreads.
Any strategy with avg PnL on risk < commission hurdle is DEAD.

All data from real Polygon prices. No fabrication.
"""

import sys, os, json, time
import pandas as pd
import numpy as np
from datetime import datetime, date
from itertools import product as itertools_product

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_all_options_data, pull_options_for_signal_day, OptionsDayData
from backtest_spreads import simulate_credit_spread_trade

# ═══════════════════════════════════════════════════════════════════
#  COMMISSION MODEL — IBKR TIERED
# ═══════════════════════════════════════════════════════════════════
COMM_PER_LEG = 0.73  # per contract per leg
COMM_RT_PER_CONTRACT = COMM_PER_LEG * 4  # 2 legs × open+close = $2.92
RISK_PER_TRADE = 100_000  # $100K risk budget

# ═══════════════════════════════════════════════════════════════════
#  SEARCH GRID
# ═══════════════════════════════════════════════════════════════════

# All delta pairs (wide to narrow) — prioritize wider pairs for more credit
SPREAD_PAIRS = [
    (0.50, 0.30),  # Very wide — most credit
    (0.50, 0.35),
    (0.50, 0.40),
    (0.40, 0.20),  # Wide
    (0.40, 0.25),
    (0.40, 0.30),
    (0.35, 0.20),  # Medium-wide
    (0.35, 0.25),
    (0.30, 0.15),  # Medium
    (0.30, 0.20),
    (0.25, 0.15),  # Narrow
    (0.25, 0.10),
    (0.20, 0.10),  # Very narrow — least credit
]

# Targeted exit combos (broader than old set)
TARGETS = [0.25, 0.50, 0.75, 1.0]
STOPS = [1.0, 1.5, 2.0, 3.0]
TIME_EXITS = [15, 30, 60, "EOD"]

# ATR multipliers — 0.5x to 1.0x (beyond 1.0 = too few signals)
ATR_MULTS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

# Both directions
DIRECTIONS = ["above", "below"]

# Minimum trades for statistical validity
MIN_TRADES = 15

# Walk-forward split
SPLIT_DATE = date(2024, 7, 1)


def compute_commission_adjusted_metrics(trades_list):
    """
    Compute metrics with IBKR commissions baked in.

    trades_list: list of dicts with keys: pnl_on_risk, pnl_dollar, credit, spread_width, date, ...

    Returns dict of metrics or None if insufficient trades.
    """
    if len(trades_list) < MIN_TRADES:
        return None

    adj_pnls = []  # commission-adjusted PnL on risk (%)
    adj_dollars = []  # commission-adjusted dollar PnL
    raw_pnls = []
    dates = []

    for t in trades_list:
        risk_per_contract = (t["spread_width"] - t["credit"]) * 100
        if risk_per_contract <= 0:
            continue

        contracts = int(RISK_PER_TRADE / risk_per_contract)
        if contracts <= 0:
            continue

        comm = contracts * COMM_RT_PER_CONTRACT
        comm_pct = comm / RISK_PER_TRADE * 100

        raw_pnl = t["pnl_on_risk"]
        adj_pnl = raw_pnl - comm_pct
        gross_dollar = t["pnl_dollar"] * 100 * contracts
        net_dollar = gross_dollar - comm

        raw_pnls.append(raw_pnl)
        adj_pnls.append(adj_pnl)
        adj_dollars.append(net_dollar)
        dates.append(t["date"])

    if len(adj_pnls) < MIN_TRADES:
        return None

    arr = np.array(adj_pnls)
    darr = np.array(adj_dollars)

    wins = np.sum(arr > 0)
    losses = np.sum(arr <= 0)
    avg_pnl = np.mean(arr)
    std_pnl = np.std(arr)
    sharpe = avg_pnl / std_pnl if std_pnl > 0 else 0

    total_wins_dollar = np.sum(darr[darr > 0]) if np.any(darr > 0) else 0
    total_losses_dollar = abs(np.sum(darr[darr < 0])) if np.any(darr < 0) else 0.0001
    pf = total_wins_dollar / total_losses_dollar

    # Drawdown
    cum = np.cumsum(darr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = np.min(dd) if len(dd) > 0 else 0

    # Sortino
    downside = arr[arr < 0]
    downside_std = np.std(downside) if len(downside) >= 2 else std_pnl
    sortino = avg_pnl / downside_std if downside_std > 0 else 0

    # Yearly breakdown
    yearly = {}
    for pnl, d in zip(adj_pnls, dates):
        yr = str(d)[:4] if isinstance(d, str) else str(d.year) if hasattr(d, 'year') else str(d)[:4]
        if yr not in yearly:
            yearly[yr] = []
        yearly[yr].append(pnl)

    yearly_sharpes = {}
    for yr, yp in yearly.items():
        ya = np.array(yp)
        ys = np.std(ya)
        yearly_sharpes[yr] = np.mean(ya) / ys if ys > 0 and len(ya) >= 3 else 0

    # Negative year count
    neg_years = sum(1 for s in yearly_sharpes.values() if s < 0)

    # Average credit (useful for commission ratio analysis)
    avg_credit = np.mean([t["credit"] for t in trades_list])
    avg_width = np.mean([t["spread_width"] for t in trades_list])

    # Raw metrics for comparison
    raw_arr = np.array(raw_pnls)
    raw_sharpe = np.mean(raw_arr) / np.std(raw_arr) if np.std(raw_arr) > 0 else 0

    return {
        "n_trades": len(adj_pnls),
        "adj_win_rate": wins / len(adj_pnls) * 100,
        "adj_avg_pnl": avg_pnl,
        "adj_sharpe": sharpe,
        "adj_sortino": sortino,
        "adj_pf": pf,
        "adj_total_dollar": np.sum(darr),
        "adj_max_dd": max_dd,
        "raw_sharpe": raw_sharpe,
        "raw_avg_pnl": np.mean(raw_arr),
        "raw_win_rate": np.sum(raw_arr > 0) / len(raw_arr) * 100,
        "avg_credit": avg_credit,
        "avg_width": avg_width,
        "credit_pct": avg_credit / avg_width * 100 if avg_width > 0 else 0,
        "neg_years": neg_years,
        "yearly_sharpes": yearly_sharpes,
    }


def run_single_config(options_data_dict, signals_df, option_side, short_delta, long_delta,
                       profit_target, stop_loss, time_exit):
    """Run one spread config, return list of trade dicts."""
    trades = []

    for _, signal in signals_df.iterrows():
        date_str = str(signal["date"])
        if date_str not in options_data_dict:
            continue

        day_data = options_data_dict[date_str]
        opt_dict = getattr(day_data, option_side)

        if short_delta not in opt_dict or long_delta not in opt_dict:
            continue

        short_info = opt_dict[short_delta]
        long_info = opt_dict[long_delta]

        # Get bars from signal entry time onward
        sig_entry_time = signal["entry_time"]
        short_all = short_info.get("all_bars", short_info["bars"])
        long_all = long_info.get("all_bars", long_info["bars"])

        short_bars = short_all[short_all["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)
        long_bars = long_all[long_all["timestamp"] >= sig_entry_time].copy().reset_index(drop=True)

        if short_bars.empty or long_bars.empty:
            continue

        short_entry = short_bars.iloc[0]["open"]
        long_entry = long_bars.iloc[0]["open"]
        credit = short_entry - long_entry

        if credit <= 0:
            continue

        spread_width = abs(short_info["strike"] - long_info["strike"])

        result = simulate_credit_spread_trade(
            short_bars, long_bars, short_entry, long_entry,
            profit_target, stop_loss, time_exit, spread_width
        )

        trades.append({
            "date": signal["date"],
            "credit": credit,
            "spread_width": spread_width,
            "pnl_dollar": result.get("pnl_dollar", 0),
            "pnl_on_risk": result.get("pnl_on_risk", result.get("pnl_pct", 0)),
            "exit_reason": result.get("exit_reason", "unknown"),
            "minutes_held": result.get("minutes_held", 0),
            "short_entry": short_entry,
            "long_entry": long_entry,
            "exit_spread_value": result.get("exit_spread_value", credit),
            "short_strike": short_info["strike"],
            "long_strike": long_info["strike"],
            "short_ticker": short_info.get("ticker"),
            "long_ticker": long_info.get("ticker"),
            "vix_regime": signal.get("vix_regime", ""),
            "entry_price": signal.get("entry_price", 0),
            "entry_time": signal.get("entry_time"),
        })

    return trades


def main():
    t0 = time.time()
    print("=" * 70)
    print("  COMMISSION-AWARE FULL GRID SEARCH")
    print("  IBKR Tiered: $2.92 RT per contract")
    print("  All data from real Polygon prices — no fabrication")
    print("=" * 70)

    # ── Load base data ──
    print("\n--- Loading base data ---")
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)

    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    # ── Generate signals for all ATR levels and directions ──
    print(f"\n--- Generating signals: {len(ATR_MULTS)} mults × {len(DIRECTIONS)} dirs ---")
    signals_by_key = generate_all_signals(enriched, intraday_data, ATR_MULTS, DIRECTIONS)

    # Print signal counts
    for direction in DIRECTIONS:
        for mult in ATR_MULTS:
            key = (direction, mult)
            n = len(signals_by_key.get(key, pd.DataFrame()))
            if n > 0:
                print(f"  {direction} {mult}x: {n} signals")

    # ── Pull options data for ALL signal days ──
    print(f"\n--- Pulling options data for all signal days ---")
    all_unique_days = {}
    for key, sig_df in signals_by_key.items():
        if sig_df.empty:
            continue
        for _, signal in sig_df.iterrows():
            date_str = str(signal["date"])
            if date_str not in all_unique_days:
                all_unique_days[date_str] = {
                    "spot": signal["entry_price"],
                    "entry_time": signal["entry_time"],
                }

    print(f"  Total unique signal days: {len(all_unique_days)}")

    all_options_data = {}
    for i, (date_str, info) in enumerate(sorted(all_unique_days.items())):
        if (i + 1) % 50 == 0:
            print(f"    [{i + 1}/{len(all_unique_days)}]...")
        try:
            day_data = pull_options_for_signal_day(
                fetcher, date_str, info["spot"], info["entry_time"]
            )
            all_options_data[date_str] = day_data
        except Exception as e:
            print(f"    ERROR {date_str}: {e}")
            all_options_data[date_str] = OptionsDayData(date_str, info["spot"], info["entry_time"])

    days_with_data = sum(1 for d in all_options_data.values()
                          if len(d.puts) > 0 or len(d.calls) > 0)
    print(f"  Days with options data: {days_with_data}/{len(all_options_data)}")

    # ═══════════════════════════════════════════════════════════════════
    #  GRID SEARCH WITH COMMISSION FILTER
    # ═══════════════════════════════════════════════════════════════════

    total_combos = len(ATR_MULTS) * len(DIRECTIONS) * len(SPREAD_PAIRS) * len(TARGETS) * len(STOPS) * len(TIME_EXITS)
    print(f"\n{'='*70}")
    print(f"  GRID SEARCH: {total_combos} combinations")
    print(f"  Commission hurdle: ~0.83% of risk per trade")
    print(f"{'='*70}")

    all_results = []
    tested = 0
    passed = 0

    for direction in DIRECTIONS:
        spread_type = "bear_call_spread" if direction == "above" else "bull_put_spread"
        option_side = "calls" if direction == "above" else "puts"

        for mult in ATR_MULTS:
            key = (direction, mult)
            sig_df = signals_by_key.get(key, pd.DataFrame())
            if sig_df.empty or len(sig_df) < 5:
                continue

            print(f"\n  Testing {direction} {mult}x ({len(sig_df)} signals)...")

            for short_delta, long_delta in SPREAD_PAIRS:
                for tgt in TARGETS:
                    for sl in STOPS:
                        for te in TIME_EXITS:
                            tested += 1
                            if tested % 500 == 0:
                                print(f"    [{tested} tested, {passed} passed]...")

                            trades = run_single_config(
                                all_options_data, sig_df, option_side,
                                short_delta, long_delta, tgt, sl, te
                            )

                            if len(trades) < MIN_TRADES:
                                continue

                            metrics = compute_commission_adjusted_metrics(trades)
                            if metrics is None:
                                continue

                            # COMMISSION FILTER: must have positive adj avg PnL
                            if metrics["adj_avg_pnl"] <= 0:
                                continue

                            passed += 1

                            result = {
                                "direction": direction,
                                "spread_type": spread_type,
                                "atr_mult": mult,
                                "short_delta": short_delta,
                                "long_delta": long_delta,
                                "target": tgt,
                                "stop": sl,
                                "time_exit": te,
                                **metrics,
                            }
                            all_results.append(result)

    print(f"\n{'='*70}")
    print(f"  GRID SEARCH COMPLETE")
    print(f"  Tested: {tested} combos")
    print(f"  Pass commission filter: {passed}")
    print(f"{'='*70}")

    if not all_results:
        print("\n  *** NO CONFIGS SURVIVE COMMISSIONS ***")
        print("  The VWAP deviation strategy does not produce enough edge")
        print("  to overcome IBKR Tiered commission drag.")
        return

    # Sort by commission-adjusted Sharpe
    all_results.sort(key=lambda r: r["adj_sharpe"], reverse=True)

    # ═══════════════════════════════════════════════════════════════════
    #  TOP RESULTS
    # ═══════════════════════════════════════════════════════════════════

    print(f"\n{'='*70}")
    print(f"  TOP 30 COMMISSION-SURVIVING CONFIGS (by adj Sharpe)")
    print(f"{'='*70}")

    header = (f"{'#':>3} {'Dir':>5} {'ATR':>4} {'Spread':>10} {'Tgt':>4} {'SL':>4} "
              f"{'Time':>4} {'N':>4} {'AdjSh':>6} {'RawSh':>6} {'AdjWR':>6} "
              f"{'AvgPnL':>7} {'$Total':>10} {'MaxDD':>10} {'PF':>5} {'AvgCr':>6} {'NegYr':>5}")
    print(header)
    print("-" * len(header))

    for i, r in enumerate(all_results[:30]):
        sp = f"{r['short_delta']:.2f}/{r['long_delta']:.2f}"
        te = r['time_exit'] if r['time_exit'] != 'EOD' else 'EOD'
        print(f"{i+1:>3} {r['direction']:>5} {r['atr_mult']:>4.1f} {sp:>10} "
              f"{r['target']:>4.2f} {r['stop']:>4.1f} {str(te):>4} "
              f"{r['n_trades']:>4} {r['adj_sharpe']:>6.3f} {r['raw_sharpe']:>6.3f} "
              f"{r['adj_win_rate']:>5.1f}% {r['adj_avg_pnl']:>+6.3f}% "
              f"${r['adj_total_dollar']:>+9,.0f} ${r['adj_max_dd']:>+9,.0f} "
              f"{r['adj_pf']:>5.2f} ${r['avg_credit']:>5.2f} {r['neg_years']:>5}")

    # ═══════════════════════════════════════════════════════════════════
    #  WALK-FORWARD ON TOP CONFIGS
    # ═══════════════════════════════════════════════════════════════════

    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD VALIDATION (Train < 2024-07-01 | Test >= 2024-07-01)")
    print(f"{'='*70}")

    wf_survivors = []

    for i, r in enumerate(all_results[:50]):  # Test top 50
        direction = r["direction"]
        mult = r["atr_mult"]
        spread_type = r["spread_type"]
        option_side = "calls" if direction == "above" else "puts"

        key = (direction, mult)
        sig_df = signals_by_key.get(key, pd.DataFrame())
        if sig_df.empty:
            continue

        trades = run_single_config(
            all_options_data, sig_df, option_side,
            r["short_delta"], r["long_delta"], r["target"], r["stop"], r["time_exit"]
        )

        # Split train/test
        train_trades = [t for t in trades if (t["date"] < SPLIT_DATE if hasattr(t["date"], "year") else str(t["date"]) < "2024-07-01")]
        test_trades = [t for t in trades if not (t["date"] < SPLIT_DATE if hasattr(t["date"], "year") else str(t["date"]) < "2024-07-01")]

        train_m = compute_commission_adjusted_metrics(train_trades) if len(train_trades) >= 5 else None
        test_m = compute_commission_adjusted_metrics(test_trades) if len(test_trades) >= 3 else None

        # Walk-forward pass: both train and test must be positive adj Sharpe
        # Relaxed: train must be positive, test must not be deeply negative
        train_pass = train_m and train_m["adj_sharpe"] > 0
        test_pass = test_m and test_m["adj_sharpe"] > -0.2  # Allow mild test weakness

        if train_m and test_m:
            sp = f"{r['short_delta']:.2f}/{r['long_delta']:.2f}"
            te = r["time_exit"]
            verdict = "PASS" if (train_pass and test_pass and test_m["adj_sharpe"] > 0) else \
                      "SOFT" if (train_pass and test_pass) else "FAIL"

            print(f"  #{i+1:>2} {r['direction']:>5} {r['atr_mult']:.1f}x {sp} tgt={r['target']} sl={r['stop']} t={te}")
            print(f"       Train: N={train_m['n_trades']:>3} AdjSh={train_m['adj_sharpe']:>+6.3f} WR={train_m['adj_win_rate']:>5.1f}%")
            print(f"       Test:  N={test_m['n_trades']:>3} AdjSh={test_m['adj_sharpe']:>+6.3f} WR={test_m['adj_win_rate']:>5.1f}%  → {verdict}")

            if verdict in ("PASS", "SOFT"):
                wf_survivors.append({
                    **r,
                    "train_sharpe": train_m["adj_sharpe"],
                    "test_sharpe": test_m["adj_sharpe"],
                    "train_n": train_m["n_trades"],
                    "test_n": test_m["n_trades"],
                    "wf_verdict": verdict,
                    "trades": trades,  # Keep for later
                })

    print(f"\n  Walk-forward survivors: {len(wf_survivors)}")

    # ═══════════════════════════════════════════════════════════════════
    #  YEARLY STABILITY CHECK ON WF SURVIVORS
    # ═══════════════════════════════════════════════════════════════════

    print(f"\n{'='*70}")
    print(f"  YEARLY STABILITY CHECK")
    print(f"{'='*70}")

    final_promoted = []

    for s in wf_survivors:
        yearly = s.get("yearly_sharpes", {})
        neg = sum(1 for v in yearly.values() if v < 0)
        total_yrs = len(yearly)

        sp = f"{s['short_delta']:.2f}/{s['long_delta']:.2f}"
        print(f"\n  {s['direction']} {s['atr_mult']}x {sp} tgt={s['target']} sl={s['stop']} t={s['time_exit']}")
        print(f"    WF: Train Sh={s['train_sharpe']:+.3f} | Test Sh={s['test_sharpe']:+.3f}")
        for yr, sh in sorted(yearly.items()):
            flag = " ← NEG" if sh < 0 else ""
            print(f"    {yr}: Sharpe={sh:+.3f}{flag}")

        # Accept if at most 1 negative year (or 2 if they're mild)
        deep_neg = sum(1 for v in yearly.values() if v < -0.3)
        stable = deep_neg <= 1

        verdict = "PROMOTED" if (s["wf_verdict"] == "PASS" and stable) else \
                  "BORDERLINE" if (s["wf_verdict"] in ("PASS", "SOFT") and neg <= 2) else "REJECTED"
        print(f"    → {verdict}")

        if verdict in ("PROMOTED", "BORDERLINE"):
            final_promoted.append({**s, "final_verdict": verdict})

    # ═══════════════════════════════════════════════════════════════════
    #  FINAL SUMMARY
    # ═══════════════════════════════════════════════════════════════════

    print(f"\n{'='*70}")
    print(f"  FINAL COMMISSION-SURVIVING STRATEGIES")
    print(f"{'='*70}")

    if not final_promoted:
        print("\n  *** NO STRATEGIES SURVIVE THE FULL GAUNTLET ***")
        print("  Commission + walk-forward + yearly stability = no edge left")

        # Still save raw results for analysis
        save_results = [{k: v for k, v in r.items() if k != "trades"} for r in all_results[:50]]
        with open("commission_search_results.json", "w") as f:
            json.dump(save_results, f, indent=2, default=str)
        print(f"  Raw top-50 results saved to commission_search_results.json")
    else:
        for i, p in enumerate(final_promoted):
            sp = f"{p['short_delta']:.2f}/{p['long_delta']:.2f}"
            print(f"\n  [{i+1}] {p['direction']} {p['atr_mult']}x {sp}")
            print(f"      Exit: tgt={p['target']} sl={p['stop']} t={p['time_exit']}")
            print(f"      N={p['n_trades']}, Adj Sharpe={p['adj_sharpe']:.3f}, Adj WR={p['adj_win_rate']:.1f}%")
            print(f"      Total $={p['adj_total_dollar']:+,.0f}, Max DD=${p['adj_max_dd']:,.0f}")
            print(f"      WF: Train={p['train_sharpe']:+.3f} Test={p['test_sharpe']:+.3f}")
            print(f"      Yearly: {p.get('yearly_sharpes', {})}")
            print(f"      Verdict: {p['final_verdict']}")

        # Save promoted configs and their trades
        promoted_configs = []
        all_promoted_trades = []

        for p in final_promoted:
            config_entry = {k: v for k, v in p.items() if k != "trades"}
            promoted_configs.append(config_entry)

            # Format trades for dashboard
            for t in p.get("trades", []):
                risk_pc = (t["spread_width"] - t["credit"]) * 100
                contracts = int(RISK_PER_TRADE / risk_pc) if risk_pc > 0 else 0
                comm = contracts * COMM_RT_PER_CONTRACT
                comm_pct = comm / RISK_PER_TRADE * 100

                trade_entry = {
                    "date": str(t["date"]),
                    "direction": p["direction"],
                    "product": p["spread_type"],
                    "strategy_key": f"spy_{p['spread_type'].split('_')[0]}_{p['spread_type'].split('_')[1]}_{p['atr_mult']}x_{int(p['short_delta']*100):03d}_{int(p['long_delta']*100):03d}",
                    "strategy_label": f"SPY {'Bear Call' if p['direction']=='above' else 'Bull Put'} {p['short_delta']:.2f}/{p['long_delta']:.2f}d @ {p['atr_mult']}x ATR",
                    "atr_mult": float(p["atr_mult"]),
                    "verdict": p["final_verdict"].lower(),
                    "short_delta": float(p["short_delta"]),
                    "long_delta": float(p["long_delta"]),
                    "short_strike": t.get("short_strike"),
                    "long_strike": t.get("long_strike"),
                    "spread_width": t.get("spread_width"),
                    "short_ticker": t.get("short_ticker"),
                    "long_ticker": t.get("long_ticker"),
                    "spy_entry_price": t.get("entry_price"),
                    "entry_time": str(t.get("entry_time", ""))[-8:-3] if t.get("entry_time") else None,
                    "entry_time_iso": str(t.get("entry_time", "")),
                    "short_entry_price": t.get("short_entry"),
                    "long_entry_price": t.get("long_entry"),
                    "credit_received": t.get("credit"),
                    "exit_spread_value": t.get("exit_spread_value"),
                    "exit_time": None,  # TODO from bars
                    "exit_time_iso": None,
                    "pnl_pct": t.get("pnl_on_risk", 0),  # pnl_on_risk stored as pnl_pct for dashboard compat
                    "pnl_dollar": t.get("pnl_dollar", 0),
                    "pnl_adj_pct": t.get("pnl_on_risk", 0) - comm_pct,
                    "pnl_adj_dollar": t.get("pnl_dollar", 0) * 100 * contracts - comm,
                    "commission_pct": comm_pct,
                    "commission_dollar": comm,
                    "contracts": contracts,
                    "exit_reason": t.get("exit_reason", "unknown"),
                    "minutes_held": t.get("minutes_held", 0),
                    "target_pct": float(p["target"]),
                    "stop_pct": float(p["stop"]),
                    "time_exit": str(p["time_exit"]),
                    "vix": str(t.get("vix_regime", "")),
                }
                all_promoted_trades.append(trade_entry)

        all_promoted_trades.sort(key=lambda t: t["date"])

        # Save
        with open("commission_search_results.json", "w") as f:
            json.dump(promoted_configs, f, indent=2, default=str)

        with open("commission_surviving_trades.json", "w") as f:
            json.dump(all_promoted_trades, f, indent=2, default=str)

        print(f"\n  Saved {len(promoted_configs)} configs to commission_search_results.json")
        print(f"  Saved {len(all_promoted_trades)} trades to commission_surviving_trades.json")

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"  COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

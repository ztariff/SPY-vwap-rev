#!/usr/bin/env python3
"""
Gap Analysis: Commission Impact, Signal Overlap, Drawdown, Yearly Breakdown
=============================================================================
Uses REAL per-trade data from trades_data.json (Polygon market prices).
Follows CLAUDE.md: no fabricated data, thorough, surface problems.

Outputs: gap_analysis_results.json with all metrics for dashboard consumption.
"""

import sys, os, json
import numpy as np
from collections import defaultdict, Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════════════════════════════════════
#  COMMISSION MODELS (realistic per-contract costs)
# ═══════════════════════════════════════════════════════════════════════════

COMMISSION_MODELS = {
    "ibkr_tiered": {
        "label": "IBKR Tiered",
        "per_contract": 0.65,        # Per contract per leg
        "exchange_fee": 0.05,        # Approximate exchange fee per contract
        "clearing_fee": 0.02,        # Clearing fee per contract
        "regulatory_fee": 0.01,      # Regulatory fee per contract
        # Total per contract per leg: $0.73
    },
    "ibkr_fixed": {
        "label": "IBKR Fixed",
        "per_contract": 0.65,
        "exchange_fee": 0.0,
        "clearing_fee": 0.0,
        "regulatory_fee": 0.0,
    },
    "schwab": {
        "label": "Schwab/TDA",
        "per_contract": 0.65,
        "exchange_fee": 0.0,
        "clearing_fee": 0.0,
        "regulatory_fee": 0.0,
    },
    "zero_comm": {
        "label": "Zero Commission (baseline)",
        "per_contract": 0.0,
        "exchange_fee": 0.0,
        "clearing_fee": 0.0,
        "regulatory_fee": 0.0,
    },
}

RISK_PER_TRADE = 100_000  # $100k risk budget per trade

def calc_commission_per_contract(model):
    """Total commission per contract per leg."""
    m = COMMISSION_MODELS[model]
    return m["per_contract"] + m["exchange_fee"] + m["clearing_fee"] + m["regulatory_fee"]


def commission_adjusted_trade(trade, model_key):
    """Apply commission to a single trade, return adjusted P&L metrics."""
    comm_per_contract = calc_commission_per_contract(model_key)

    credit = trade["credit_received"]
    spread_width = trade["spread_width"]

    # Max risk per contract (dollars)
    max_risk_per_contract = (spread_width - credit) * 100
    if max_risk_per_contract <= 0:
        return None

    # Position size
    contracts = int(RISK_PER_TRADE / max_risk_per_contract)
    if contracts <= 0:
        return None

    # Commission: 2 legs × open + 2 legs × close = 4 leg-transactions
    # (unless exit_reason is expiration/worthless, then only 2 legs to open)
    exit_reason = trade.get("exit_reason", "")
    if exit_reason in ("worthless", "expiration"):
        total_comm = comm_per_contract * 2 * contracts  # Only opening
    else:
        total_comm = comm_per_contract * 4 * contracts  # Open + close

    # Original dollar P&L (no commission)
    raw_dollar_pnl = trade["pnl_dollar"] * 100 * contracts

    # Commission-adjusted
    adj_dollar_pnl = raw_dollar_pnl - total_comm

    # Commission as % of credit received (per-contract)
    credit_dollars = credit * 100  # Per contract in dollars
    comm_pct_of_credit = (comm_per_contract * 4 / credit_dollars * 100) if credit_dollars > 0 else 999

    # P&L on risk
    total_risk = max_risk_per_contract * contracts
    raw_pnl_on_risk = raw_dollar_pnl / total_risk if total_risk > 0 else 0
    adj_pnl_on_risk = adj_dollar_pnl / total_risk if total_risk > 0 else 0

    return {
        "date": trade["date"],
        "strategy_key": trade["strategy_key"],
        "contracts": contracts,
        "raw_dollar_pnl": raw_dollar_pnl,
        "commission": total_comm,
        "adj_dollar_pnl": adj_dollar_pnl,
        "comm_pct_of_credit": comm_pct_of_credit,
        "raw_pnl_on_risk": raw_pnl_on_risk,
        "adj_pnl_on_risk": adj_pnl_on_risk,
        "credit": credit,
        "spread_width": spread_width,
    }


def run_commission_analysis(trades):
    """Run commission analysis across all models for spread trades."""
    spread_trades = [t for t in trades if t.get("product", "").endswith("spread")]

    results = {}
    for model_key in COMMISSION_MODELS:
        model_label = COMMISSION_MODELS[model_key]["label"]
        adjusted = []
        for t in spread_trades:
            adj = commission_adjusted_trade(t, model_key)
            if adj:
                adjusted.append(adj)

        if not adjusted:
            continue

        # Overall metrics
        raw_pnls = [a["raw_pnl_on_risk"] for a in adjusted]
        adj_pnls = [a["adj_pnl_on_risk"] for a in adjusted]

        raw_sharpe = np.mean(raw_pnls) / np.std(raw_pnls) if np.std(raw_pnls) > 0 else 0
        adj_sharpe = np.mean(adj_pnls) / np.std(adj_pnls) if np.std(adj_pnls) > 0 else 0

        raw_wins = sum(1 for p in raw_pnls if p > 0)
        adj_wins = sum(1 for p in adj_pnls if p > 0)

        total_raw_dollar = sum(a["raw_dollar_pnl"] for a in adjusted)
        total_comm = sum(a["commission"] for a in adjusted)
        total_adj_dollar = sum(a["adj_dollar_pnl"] for a in adjusted)

        avg_comm_pct = np.mean([a["comm_pct_of_credit"] for a in adjusted])

        # Per-strategy breakdown
        by_strat = defaultdict(list)
        for a in adjusted:
            by_strat[a["strategy_key"]].append(a)

        strat_results = {}
        for sk, strades in by_strat.items():
            sp = [s["adj_pnl_on_risk"] for s in strades]
            rp = [s["raw_pnl_on_risk"] for s in strades]
            s_adj_sharpe = np.mean(sp) / np.std(sp) if np.std(sp) > 0 else 0
            s_raw_sharpe = np.mean(rp) / np.std(rp) if np.std(rp) > 0 else 0
            s_adj_wins = sum(1 for p in sp if p > 0)
            strat_results[sk] = {
                "n": len(strades),
                "raw_sharpe": round(s_raw_sharpe, 4),
                "adj_sharpe": round(s_adj_sharpe, 4),
                "sharpe_delta": round(s_adj_sharpe - s_raw_sharpe, 4),
                "raw_wr": round(sum(1 for p in rp if p > 0) / len(rp) * 100, 1),
                "adj_wr": round(s_adj_wins / len(sp) * 100, 1),
                "total_commission": round(sum(s["commission"] for s in strades), 2),
                "avg_commission_per_trade": round(np.mean([s["commission"] for s in strades]), 2),
                "avg_comm_pct_of_credit": round(np.mean([s["comm_pct_of_credit"] for s in strades]), 1),
                "verdict_change": "SURVIVES" if s_adj_sharpe > 0 else "KILLED BY COMMISSIONS",
            }

        results[model_key] = {
            "label": model_label,
            "n_trades": len(adjusted),
            "raw_sharpe": round(raw_sharpe, 4),
            "adj_sharpe": round(adj_sharpe, 4),
            "sharpe_delta": round(adj_sharpe - raw_sharpe, 4),
            "raw_wr": round(raw_wins / len(raw_pnls) * 100, 1),
            "adj_wr": round(adj_wins / len(adj_pnls) * 100, 1),
            "total_raw_pnl": round(total_raw_dollar, 2),
            "total_commission": round(total_comm, 2),
            "total_adj_pnl": round(total_adj_dollar, 2),
            "comm_pct_of_raw_pnl": round(total_comm / total_raw_dollar * 100, 1) if total_raw_dollar > 0 else 999,
            "avg_comm_pct_of_credit": round(avg_comm_pct, 1),
            "by_strategy": strat_results,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════
#  SIGNAL OVERLAP ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def run_overlap_analysis(trades):
    """Compute signal co-occurrence between strategies on the same day."""
    # Group trades by date
    by_date = defaultdict(set)
    for t in trades:
        by_date[t["date"]].add(t["strategy_key"])

    # Count co-occurrences
    strat_keys = sorted(set(t["strategy_key"] for t in trades))
    cooccurrence = defaultdict(int)
    total_by_strat = Counter(t["strategy_key"] for t in trades)

    for date, strats in by_date.items():
        strats = sorted(strats)
        for i in range(len(strats)):
            for j in range(i + 1, len(strats)):
                pair = f"{strats[i]} + {strats[j]}"
                cooccurrence[pair] += 1

    # Also compute: on what % of days do multiple strategies fire?
    multi_fire_days = sum(1 for strats in by_date.values() if len(strats) > 1)
    total_trade_days = len(by_date)

    # Compute daily aggregate P&L correlation
    daily_pnl = defaultdict(lambda: defaultdict(float))
    for t in trades:
        daily_pnl[t["date"]][t["strategy_key"]] += t["pnl_dollar"]

    # Build correlation matrix for strategies that overlap
    overlap_results = {
        "total_trade_days": total_trade_days,
        "multi_fire_days": multi_fire_days,
        "multi_fire_pct": round(multi_fire_days / total_trade_days * 100, 1) if total_trade_days > 0 else 0,
        "strategy_trade_counts": dict(total_by_strat),
        "cooccurrence_pairs": {k: v for k, v in sorted(cooccurrence.items(), key=lambda x: -x[1])},
        "daily_exposure": {},
    }

    # Max daily exposure (how many trades fire on worst day)
    max_same_day = max(len(strats) for strats in by_date.values()) if by_date else 0
    dates_by_count = Counter(len(strats) for strats in by_date.values())
    overlap_results["max_same_day_trades"] = max_same_day
    overlap_results["distribution"] = {str(k): v for k, v in sorted(dates_by_count.items())}

    return overlap_results


# ═══════════════════════════════════════════════════════════════════════════
#  DRAWDOWN & STREAK ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def run_drawdown_analysis(trades):
    """Compute max drawdown, consecutive losses, recovery time."""
    if not trades:
        return {}

    # Sort by date
    sorted_trades = sorted(trades, key=lambda t: t["date"])

    # Overall equity curve
    cum_pnl = 0
    peak = 0
    max_dd = 0
    dd_start = None
    dd_end = None
    worst_dd_start = None
    worst_dd_end = None

    equity_curve = []
    for t in sorted_trades:
        pnl = t["pnl_dollar"]
        # Size it properly
        credit = t.get("credit_received", 0)
        spread_width = t.get("spread_width", 1)
        max_risk_per = (spread_width - credit) * 100
        contracts = int(RISK_PER_TRADE / max_risk_per) if max_risk_per > 0 else 0
        dollar_pnl = pnl * 100 * contracts

        cum_pnl += dollar_pnl
        equity_curve.append({"date": t["date"], "cum_pnl": cum_pnl, "dollar_pnl": dollar_pnl})

        if cum_pnl > peak:
            peak = cum_pnl
            dd_start = t["date"]

        dd = peak - cum_pnl
        if dd > max_dd:
            max_dd = dd
            worst_dd_start = dd_start
            worst_dd_end = t["date"]

    # Consecutive losses
    max_consec_loss = 0
    current_streak = 0
    max_consec_win = 0
    current_win_streak = 0

    for t in sorted_trades:
        pnl = t["pnl_dollar"]
        if pnl < 0:
            current_streak += 1
            max_consec_loss = max(max_consec_loss, current_streak)
            current_win_streak = 0
        else:
            current_win_streak += 1
            max_consec_win = max(max_consec_win, current_win_streak)
            current_streak = 0

    # Per-strategy drawdown
    by_strat = defaultdict(list)
    for t in sorted_trades:
        by_strat[t["strategy_key"]].append(t)

    strat_drawdowns = {}
    for sk, strades in by_strat.items():
        s_cum = 0
        s_peak = 0
        s_max_dd = 0
        s_consec = 0
        s_max_consec = 0
        for st in strades:
            credit = st.get("credit_received", 0)
            sw = st.get("spread_width", 1)
            mrp = (sw - credit) * 100
            c = int(RISK_PER_TRADE / mrp) if mrp > 0 else 0
            dp = st["pnl_dollar"] * 100 * c
            s_cum += dp
            if s_cum > s_peak:
                s_peak = s_cum
            dd = s_peak - s_cum
            s_max_dd = max(s_max_dd, dd)

            if st["pnl_dollar"] < 0:
                s_consec += 1
                s_max_consec = max(s_max_consec, s_consec)
            else:
                s_consec = 0

        strat_drawdowns[sk] = {
            "max_drawdown": round(s_max_dd, 2),
            "max_consecutive_losses": s_max_consec,
            "total_pnl": round(s_cum, 2),
            "n_trades": len(strades),
        }

    return {
        "overall": {
            "max_drawdown": round(max_dd, 2),
            "max_dd_pct_of_risk": round(max_dd / RISK_PER_TRADE * 100, 2),
            "max_consecutive_losses": max_consec_loss,
            "max_consecutive_wins": max_consec_win,
            "worst_dd_period": f"{worst_dd_start} to {worst_dd_end}" if worst_dd_start else "none",
            "final_cum_pnl": round(cum_pnl, 2),
        },
        "by_strategy": strat_drawdowns,
        "equity_curve": equity_curve,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  YEARLY BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════════

def run_yearly_analysis(trades):
    """Break out Sharpe, win rate, expectancy by year for each strategy."""
    by_year_strat = defaultdict(lambda: defaultdict(list))

    for t in trades:
        year = t["date"][:4]
        by_year_strat[year][t["strategy_key"]].append(t)

    results = {}
    for year in sorted(by_year_strat.keys()):
        year_data = {}
        for sk, strades in by_year_strat[year].items():
            pnls = [s.get("pnl_pct", 0) for s in strades]
            wins = sum(1 for p in pnls if p > 0)
            sharpe = np.mean(pnls) / np.std(pnls) if np.std(pnls) > 0 else 0

            year_data[sk] = {
                "n": len(strades),
                "sharpe": round(sharpe, 4),
                "win_rate": round(wins / len(pnls) * 100, 1) if pnls else 0,
                "avg_pnl": round(np.mean(pnls), 4),
                "total_pnl": round(sum(pnls), 4),
                "winners": wins,
                "losers": len(pnls) - wins,
            }
        results[year] = year_data

    return results


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    trades_path = os.path.join(base_dir, "trades_data.json")

    print("=" * 70)
    print("  GAP ANALYSIS: Commission, Overlap, Drawdown, Yearly")
    print("  All data from real Polygon trades — no fabrication")
    print("=" * 70)

    with open(trades_path) as f:
        trades = json.load(f)

    print(f"\n  Loaded {len(trades)} trades from trades_data.json")
    print(f"  Date range: {trades[0]['date']} to {trades[-1]['date']}")

    strat_counts = Counter(t["strategy_key"] for t in trades)
    for k, v in strat_counts.most_common():
        print(f"    {k}: {v} trades")

    # ── 1. Commission Analysis ──
    print(f"\n{'='*70}")
    print("  ANALYSIS 1: COMMISSION IMPACT")
    print(f"{'='*70}")

    commission_results = run_commission_analysis(trades)

    for model_key, mr in commission_results.items():
        print(f"\n  [{mr['label']}]")
        print(f"    N={mr['n_trades']}, Raw Sharpe={mr['raw_sharpe']:.4f}, "
              f"Adj Sharpe={mr['adj_sharpe']:.4f} (Δ={mr['sharpe_delta']:+.4f})")
        print(f"    Raw WR={mr['raw_wr']}%, Adj WR={mr['adj_wr']}%")
        print(f"    Total Raw P&L: ${mr['total_raw_pnl']:,.0f}")
        print(f"    Total Commission: ${mr['total_commission']:,.0f} "
              f"({mr['comm_pct_of_raw_pnl']:.1f}% of raw P&L)")
        print(f"    Total Adj P&L: ${mr['total_adj_pnl']:,.0f}")
        print(f"    Avg comm as % of credit: {mr['avg_comm_pct_of_credit']:.1f}%")

        print(f"\n    Per-Strategy:")
        for sk, sr in sorted(mr["by_strategy"].items()):
            print(f"      {sk}: N={sr['n']}, "
                  f"Raw Sh={sr['raw_sharpe']:.3f} → Adj Sh={sr['adj_sharpe']:.3f} "
                  f"(Δ={sr['sharpe_delta']:+.3f}), "
                  f"Comm/Credit={sr['avg_comm_pct_of_credit']:.1f}%, "
                  f"→ {sr['verdict_change']}")

    # ── 2. Overlap Analysis ──
    print(f"\n{'='*70}")
    print("  ANALYSIS 2: SIGNAL OVERLAP / CORRELATION")
    print(f"{'='*70}")

    overlap_results = run_overlap_analysis(trades)
    print(f"\n  Total trade days: {overlap_results['total_trade_days']}")
    print(f"  Days with multiple signals: {overlap_results['multi_fire_days']} "
          f"({overlap_results['multi_fire_pct']}%)")
    print(f"  Max same-day trades: {overlap_results['max_same_day_trades']}")
    print(f"\n  Distribution of daily trade counts:")
    for count, days in sorted(overlap_results["distribution"].items()):
        print(f"    {count} trade(s)/day: {days} days")

    if overlap_results["cooccurrence_pairs"]:
        print(f"\n  Co-occurrence pairs:")
        for pair, count in list(overlap_results["cooccurrence_pairs"].items())[:10]:
            print(f"    {pair}: {count} days")

    # ── 3. Drawdown Analysis ──
    print(f"\n{'='*70}")
    print("  ANALYSIS 3: DRAWDOWN & STREAK ANALYSIS")
    print(f"{'='*70}")

    drawdown_results = run_drawdown_analysis(trades)
    ov = drawdown_results["overall"]
    print(f"\n  Overall (portfolio of all strategies, $100k risk budget):")
    print(f"    Max Drawdown: ${ov['max_drawdown']:,.0f} "
          f"({ov['max_dd_pct_of_risk']:.1f}% of risk budget)")
    print(f"    Max Consecutive Losses: {ov['max_consecutive_losses']}")
    print(f"    Max Consecutive Wins: {ov['max_consecutive_wins']}")
    print(f"    Worst DD Period: {ov['worst_dd_period']}")
    print(f"    Final Cumulative P&L: ${ov['final_cum_pnl']:,.0f}")

    print(f"\n  By Strategy:")
    for sk, sd in drawdown_results["by_strategy"].items():
        print(f"    {sk}: MaxDD=${sd['max_drawdown']:,.0f}, "
              f"MaxConsecLoss={sd['max_consecutive_losses']}, "
              f"TotalP&L=${sd['total_pnl']:,.0f} (N={sd['n_trades']})")

    # ── 4. Yearly Analysis ──
    print(f"\n{'='*70}")
    print("  ANALYSIS 4: YEARLY BREAKDOWN")
    print(f"{'='*70}")

    yearly_results = run_yearly_analysis(trades)
    for year, year_data in sorted(yearly_results.items()):
        print(f"\n  === {year} ===")
        for sk, yr in sorted(year_data.items()):
            print(f"    {sk}: N={yr['n']}, Sharpe={yr['sharpe']:.3f}, "
                  f"WR={yr['win_rate']:.1f}%, Avg={yr['avg_pnl']:+.3f}%")

    # ── Save all results ──
    output = {
        "generated_at": datetime.now().isoformat(),
        "source": "trades_data.json — real Polygon market prices",
        "risk_budget": RISK_PER_TRADE,
        "n_trades": len(trades),
        "date_range": f"{trades[0]['date']} to {trades[-1]['date']}",
        "commission_analysis": commission_results,
        "overlap_analysis": overlap_results,
        "drawdown_analysis": {
            "overall": drawdown_results["overall"],
            "by_strategy": drawdown_results["by_strategy"],
            # Don't save full equity curve to keep file small; compute in dashboard
        },
        "yearly_analysis": yearly_results,
    }

    output_path = os.path.join(base_dir, "gap_analysis_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print(f"  ALL ANALYSES COMPLETE")
    print(f"  Saved to: {output_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

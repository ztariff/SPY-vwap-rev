#!/usr/bin/env python3
"""
FAST Commission-Aware Strategy Search
=======================================
Optimized version: pre-computes spread bar data per (direction, mult, delta_pair, day),
then rapidly evaluates exit combos without re-fetching.

IBKR Tiered: $2.92 RT per contract.
All data from real Polygon prices. No fabrication.
"""

import sys, os, json, time
import pandas as pd
import numpy as np
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data_fetcher import PolygonFetcher
from indicators import enrich_daily_data
from signal_generator import generate_all_signals
from options_data import pull_options_for_signal_day, OptionsDayData
from backtest_spreads import simulate_credit_spread_trade

# Commission model
COMM_PER_LEG = 0.73
COMM_RT = COMM_PER_LEG * 4  # $2.92 per contract round-trip
RISK_BUDGET = 100_000

# Grid
SPREAD_PAIRS = [
    (0.50, 0.30), (0.50, 0.35), (0.50, 0.40),
    (0.40, 0.20), (0.40, 0.25), (0.40, 0.30),
    (0.35, 0.20), (0.35, 0.25),
    (0.30, 0.15), (0.30, 0.20),
    (0.25, 0.15), (0.25, 0.10),
    (0.20, 0.10),
]
TARGETS = [0.25, 0.50, 0.75, 1.0]
STOPS = [1.0, 1.5, 2.0, 3.0]
TIME_EXITS = [15, 30, 60, "EOD"]
ATR_MULTS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
DIRECTIONS = ["above", "below"]
MIN_TRADES = 15
SPLIT_DATE = date(2024, 7, 1)


def compute_metrics(trades, label=""):
    """Compute commission-adjusted metrics from trade list."""
    if len(trades) < MIN_TRADES:
        return None

    adj_pnls, adj_dollars, raw_pnls, dates = [], [], [], []
    for t in trades:
        rpc = (t["sw"] - t["cr"]) * 100
        if rpc <= 0:
            continue
        c = int(RISK_BUDGET / rpc)
        if c <= 0:
            continue
        comm = c * COMM_RT
        comm_pct = comm / RISK_BUDGET * 100
        raw = t["por"]
        adj = raw - comm_pct
        dollar = t["pd"] * 100 * c - comm
        raw_pnls.append(raw)
        adj_pnls.append(adj)
        adj_dollars.append(dollar)
        dates.append(t["dt"])

    if len(adj_pnls) < MIN_TRADES:
        return None

    a = np.array(adj_pnls)
    d = np.array(adj_dollars)
    s = np.std(a)
    sh = np.mean(a) / s if s > 0 else 0
    wr = np.sum(a > 0) / len(a) * 100
    tw = np.sum(d[d > 0]) if np.any(d > 0) else 0
    tl = abs(np.sum(d[d < 0])) if np.any(d < 0) else 0.0001
    pf = tw / tl

    cum = np.cumsum(d)
    pk = np.maximum.accumulate(cum)
    mdd = np.min(cum - pk) if len(cum) > 0 else 0

    # Yearly
    yearly = {}
    for p, dt in zip(adj_pnls, dates):
        yr = str(dt)[:4] if isinstance(dt, str) else str(getattr(dt, 'year', str(dt)[:4]))
        yearly.setdefault(yr, []).append(p)
    ysh = {yr: np.mean(v)/np.std(v) if np.std(v)>0 and len(v)>=3 else 0 for yr, v in yearly.items()}
    neg_yr = sum(1 for v in ysh.values() if v < 0)

    return {
        "n": len(adj_pnls),
        "adj_sh": sh, "raw_sh": np.mean(raw_pnls)/np.std(raw_pnls) if np.std(raw_pnls)>0 else 0,
        "adj_wr": wr, "adj_avg": np.mean(a), "adj_total": np.sum(d),
        "adj_mdd": mdd, "adj_pf": pf,
        "avg_cr": np.mean([t["cr"] for t in trades]),
        "avg_sw": np.mean([t["sw"] for t in trades]),
        "neg_yr": neg_yr, "ysh": ysh,
    }


def main():
    t0 = time.time()
    print("=" * 70)
    print("  FAST COMMISSION-AWARE SEARCH")
    print("=" * 70)

    # Load data
    print("\n--- Loading data (all cached) ---")
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)
    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    # Signals
    print("\n--- Generating signals ---")
    signals_by_key = generate_all_signals(enriched, intraday_data, ATR_MULTS, DIRECTIONS)

    # Pull options for all signal days
    print("\n--- Pulling options (cached) ---")
    all_unique_days = {}
    for key, sig_df in signals_by_key.items():
        if sig_df.empty:
            continue
        for _, s in sig_df.iterrows():
            ds = str(s["date"])
            if ds not in all_unique_days:
                all_unique_days[ds] = {"spot": s["entry_price"], "entry_time": s["entry_time"]}

    print(f"  {len(all_unique_days)} unique signal days")
    opts = {}
    for i, (ds, info) in enumerate(sorted(all_unique_days.items())):
        if (i+1) % 100 == 0:
            print(f"    [{i+1}/{len(all_unique_days)}]...")
        try:
            opts[ds] = pull_options_for_signal_day(fetcher, ds, info["spot"], info["entry_time"])
        except:
            opts[ds] = OptionsDayData(ds, info["spot"], info["entry_time"])

    print(f"  Options loaded: {sum(1 for d in opts.values() if len(d.puts)>0 or len(d.calls)>0)} days with data")

    # ═══════════════════════════════════════════════════════════════════
    # PRE-COMPUTE: For each (direction, mult, delta_pair, day), cache the
    # bars and entry prices so we can rapidly test exit combos.
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n--- Pre-computing spread data ---")

    # Structure: spread_cache[(dir, mult, sd, ld)] = list of dicts with bars info
    spread_cache = {}
    cache_count = 0

    for direction in DIRECTIONS:
        option_side = "calls" if direction == "above" else "puts"
        for mult in ATR_MULTS:
            key = (direction, mult)
            sig_df = signals_by_key.get(key, pd.DataFrame())
            if sig_df.empty:
                continue

            for sd, ld in SPREAD_PAIRS:
                day_entries = []
                for _, signal in sig_df.iterrows():
                    ds = str(signal["date"])
                    if ds not in opts:
                        continue
                    day_data = opts[ds]
                    od = getattr(day_data, option_side)
                    if sd not in od or ld not in od:
                        continue

                    si = od[sd]
                    li = od[ld]
                    et = signal["entry_time"]
                    sa = si.get("all_bars", si["bars"])
                    la = li.get("all_bars", li["bars"])
                    sb = sa[sa["timestamp"] >= et].copy().reset_index(drop=True)
                    lb = la[la["timestamp"] >= et].copy().reset_index(drop=True)

                    if sb.empty or lb.empty:
                        continue

                    se = sb.iloc[0]["open"]
                    le = lb.iloc[0]["open"]
                    cr = se - le
                    if cr <= 0:
                        continue

                    sw = abs(si["strike"] - li["strike"])

                    day_entries.append({
                        "date": signal["date"],
                        "sb": sb, "lb": lb, "se": se, "le": le,
                        "cr": cr, "sw": sw,
                        "short_strike": si["strike"], "long_strike": li["strike"],
                        "short_ticker": si.get("ticker"), "long_ticker": li.get("ticker"),
                        "vix": signal.get("vix_regime", ""),
                        "entry_price": signal.get("entry_price", 0),
                        "entry_time": et,
                    })
                    cache_count += 1

                if day_entries:
                    spread_cache[(direction, mult, sd, ld)] = day_entries

    print(f"  Cached {cache_count} day-spread entries across {len(spread_cache)} combos")

    # ═══════════════════════════════════════════════════════════════════
    # GRID SEARCH: sweep exit params over cached spread data
    # ═══════════════════════════════════════════════════════════════════
    total_exit_combos = len(TARGETS) * len(STOPS) * len(TIME_EXITS)
    total_tests = len(spread_cache) * total_exit_combos
    print(f"\n--- Grid search: {len(spread_cache)} spread combos × {total_exit_combos} exit combos = {total_tests} tests ---")

    all_results = []
    tested = 0

    for (direction, mult, sd, ld), days in spread_cache.items():
        for tgt in TARGETS:
            for sl in STOPS:
                for te in TIME_EXITS:
                    tested += 1
                    if tested % 2000 == 0:
                        print(f"    [{tested}/{total_tests}] ({len(all_results)} passed)...")

                    trades = []
                    for d in days:
                        result = simulate_credit_spread_trade(
                            d["sb"], d["lb"], d["se"], d["le"],
                            tgt, sl, te, d["sw"]
                        )
                        trades.append({
                            "dt": d["date"],
                            "cr": d["cr"],
                            "sw": d["sw"],
                            "pd": result.get("pnl_dollar", 0),
                            "por": result.get("pnl_on_risk", result.get("pnl_pct", 0)),
                            "er": result.get("exit_reason", ""),
                            "mh": result.get("minutes_held", 0),
                            "se": d["se"], "le": d["le"],
                            "esv": result.get("exit_spread_value", d["cr"]),
                            "ss": d["short_strike"], "ls": d["long_strike"],
                            "st": d["short_ticker"], "lt": d["long_ticker"],
                            "vix": d["vix"], "ep": d["entry_price"],
                            "et": d["entry_time"],
                        })

                    m = compute_metrics(trades)
                    if m is None or m["adj_avg"] <= 0:
                        continue

                    spread_type = "bear_call_spread" if direction == "above" else "bull_put_spread"
                    all_results.append({
                        "dir": direction, "st": spread_type,
                        "mult": mult, "sd": sd, "ld": ld,
                        "tgt": tgt, "sl": sl, "te": te,
                        **m, "trades": trades,
                    })

    all_results.sort(key=lambda r: r["adj_sh"], reverse=True)

    print(f"\n{'='*70}")
    print(f"  GRID COMPLETE: {tested} tested, {len(all_results)} survive commissions")
    print(f"{'='*70}")

    if not all_results:
        print("\n  *** NO CONFIGS SURVIVE COMMISSIONS ***")
        elapsed = time.time() - t0
        print(f"  Elapsed: {elapsed:.0f}s")
        return

    # Top 40 results
    print(f"\n  TOP 40 BY ADJ SHARPE:")
    print(f"  {'#':>3} {'Dir':>5} {'ATR':>4} {'Spread':>10} {'Tgt':>4} {'SL':>4} {'T':>4} "
          f"{'N':>4} {'AdjSh':>6} {'RawSh':>6} {'WR':>5} {'AvgPnL':>7} {'$Tot':>10} {'MDD':>10} {'PF':>5} {'AvgCr':>6} {'NY':>3}")
    for i, r in enumerate(all_results[:40]):
        sp = f"{r['sd']:.2f}/{r['ld']:.2f}"
        print(f"  {i+1:>3} {r['dir']:>5} {r['mult']:>4.1f} {sp:>10} "
              f"{r['tgt']:>4.2f} {r['sl']:>4.1f} {str(r['te']):>4} "
              f"{r['n']:>4} {r['adj_sh']:>6.3f} {r['raw_sh']:>6.3f} "
              f"{r['adj_wr']:>4.1f}% {r['adj_avg']:>+6.3f}% "
              f"${r['adj_total']:>+9,.0f} ${r['adj_mdd']:>+9,.0f} "
              f"{r['adj_pf']:>5.2f} ${r['avg_cr']:>5.2f} {r['neg_yr']:>3}")

    # Walk-forward on top 50
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD (Train < 2024-07-01 | Test >= 2024-07-01)")
    print(f"{'='*70}")

    wf_results = []
    for i, r in enumerate(all_results[:80]):
        train = [t for t in r["trades"] if (t["dt"] < SPLIT_DATE if hasattr(t["dt"], "year") else str(t["dt"]) < "2024-07-01")]
        test = [t for t in r["trades"] if not (t["dt"] < SPLIT_DATE if hasattr(t["dt"], "year") else str(t["dt"]) < "2024-07-01")]

        tm = compute_metrics(train) if len(train) >= 5 else None
        sm = compute_metrics(test) if len(test) >= 3 else None

        if tm and sm:
            tp = tm["adj_sh"] > 0
            sp_bool = sm["adj_sh"] > 0
            verdict = "PASS" if (tp and sp_bool) else "SOFT" if (tp and sm["adj_sh"] > -0.2) else "FAIL"

            if verdict != "FAIL":
                sp = f"{r['sd']:.2f}/{r['ld']:.2f}"
                print(f"  #{i+1:>2} {r['dir']:>5} {r['mult']:.1f}x {sp} tgt={r['tgt']} sl={r['sl']} t={r['te']}")
                print(f"       Train: N={tm['n']:>3} Sh={tm['adj_sh']:>+.3f} WR={tm['adj_wr']:>5.1f}%")
                print(f"       Test:  N={sm['n']:>3} Sh={sm['adj_sh']:>+.3f} WR={sm['adj_wr']:>5.1f}%  → {verdict}")

                wf_results.append({
                    **{k: v for k, v in r.items() if k != "trades"},
                    "train_sh": tm["adj_sh"], "test_sh": sm["adj_sh"],
                    "train_n": tm["n"], "test_n": sm["n"],
                    "wf": verdict, "trades": r["trades"],
                })

    print(f"\n  WF survivors: {len(wf_results)}")

    # Yearly stability on WF survivors
    print(f"\n{'='*70}")
    print(f"  YEARLY STABILITY")
    print(f"{'='*70}")

    final = []
    for s in wf_results:
        ysh = s.get("ysh", {})
        deep_neg = sum(1 for v in ysh.values() if v < -0.3)
        neg = sum(1 for v in ysh.values() if v < 0)

        stable = deep_neg <= 1
        verdict = "PROMOTED" if (s["wf"] == "PASS" and stable) else \
                  "BORDERLINE" if (neg <= 2) else "REJECTED"

        sp = f"{s['sd']:.2f}/{s['ld']:.2f}"
        print(f"\n  {s['dir']} {s['mult']}x {sp} tgt={s['tgt']} sl={s['sl']} t={s['te']}  WF={s['wf']}")
        for yr, sh in sorted(ysh.items()):
            flag = " ← NEG" if sh < 0 else ""
            print(f"    {yr}: Sh={sh:+.3f}{flag}")
        print(f"    → {verdict}")

        if verdict in ("PROMOTED", "BORDERLINE"):
            final.append({**s, "verdict": verdict})

    # ═══════════════════════════════════════════════════════════════════
    #  SAVE RESULTS
    # ═══════════════════════════════════════════════════════════════════

    print(f"\n{'='*70}")
    print(f"  FINAL PROMOTED STRATEGIES: {len(final)}")
    print(f"{'='*70}")

    all_trades_out = []
    configs_out = []

    for p in final:
        sp_label = f"{p['sd']:.2f}/{p['ld']:.2f}"
        bc = "bear_call" if p["dir"] == "above" else "bull_put"
        strat_key = f"spy_{bc}_{p['mult']}x_{int(p['sd']*100):03d}_{int(p['ld']*100):03d}"
        strat_label = f"SPY {'Bear Call' if p['dir']=='above' else 'Bull Put'} {sp_label}d @ {p['mult']}x ATR"

        configs_out.append({
            "key": strat_key, "label": strat_label,
            "direction": p["dir"], "spread_type": p["st"],
            "atr_mult": p["mult"], "short_delta": p["sd"], "long_delta": p["ld"],
            "target": p["tgt"], "stop": p["sl"], "time_exit": p["te"],
            "adj_sharpe": p["adj_sh"], "raw_sharpe": p["raw_sh"],
            "adj_win_rate": p["adj_wr"], "adj_avg_pnl": p["adj_avg"],
            "adj_total_dollar": p["adj_total"], "adj_max_dd": p["adj_mdd"],
            "adj_pf": p["adj_pf"], "n_trades": p["n"],
            "train_sharpe": p["train_sh"], "test_sharpe": p["test_sh"],
            "yearly_sharpes": p["ysh"], "verdict": p["verdict"],
        })

        print(f"\n  [{len(configs_out)}] {strat_label}")
        print(f"      Exit: tgt={p['tgt']} sl={p['sl']} t={p['te']}")
        print(f"      N={p['n']}, Adj Sharpe={p['adj_sh']:.3f}, WR={p['adj_wr']:.1f}%")
        print(f"      Total $={p['adj_total']:+,.0f}, MDD=${p['adj_mdd']:,.0f}, PF={p['adj_pf']:.2f}")
        print(f"      WF: Train={p['train_sh']:+.3f} Test={p['test_sh']:+.3f}")
        print(f"      Verdict: {p['verdict']}")

        for t in p.get("trades", []):
            rpc = (t["sw"] - t["cr"]) * 100
            contracts = int(RISK_BUDGET / rpc) if rpc > 0 else 0
            comm = contracts * COMM_RT
            comm_pct = comm / RISK_BUDGET * 100

            all_trades_out.append({
                "date": str(t["dt"]),
                "direction": p["dir"],
                "product": p["st"],
                "strategy_key": strat_key,
                "strategy_label": strat_label,
                "atr_mult": float(p["mult"]),
                "verdict": p["verdict"].lower(),
                "short_delta": float(p["sd"]),
                "long_delta": float(p["ld"]),
                "short_strike": t.get("ss"),
                "long_strike": t.get("ls"),
                "spread_width": t.get("sw"),
                "short_ticker": t.get("st"),
                "long_ticker": t.get("lt"),
                "spy_entry_price": t.get("ep"),
                "entry_time": str(t.get("et", ""))[-8:-3] if t.get("et") else None,
                "entry_time_iso": str(t.get("et", "")),
                "short_entry_price": t.get("se"),
                "long_entry_price": t.get("le"),
                "credit_received": t.get("cr"),
                "exit_spread_value": t.get("esv"),
                "pnl_pct": t.get("por", 0),
                "pnl_dollar": t.get("pd", 0),
                "pnl_adj_pct": t.get("por", 0) - comm_pct,
                "pnl_adj_dollar": t.get("pd", 0) * 100 * contracts - comm,
                "commission_pct": comm_pct,
                "commission_dollar": comm,
                "contracts": contracts,
                "exit_reason": t.get("er", "unknown"),
                "minutes_held": t.get("mh", 0),
                "target_pct": float(p["tgt"]),
                "stop_pct": float(p["sl"]),
                "time_exit": str(p["te"]),
                "vix": str(t.get("vix", "")),
            })

    all_trades_out.sort(key=lambda t: t["date"])

    with open("commission_search_results.json", "w") as f:
        json.dump(configs_out, f, indent=2, default=str)

    with open("commission_surviving_trades.json", "w") as f:
        json.dump(all_trades_out, f, indent=2, default=str)

    # Also save ALL grid results (top 100) for reference
    top100 = [{k: v for k, v in r.items() if k != "trades"} for r in all_results[:100]]
    with open("commission_grid_top100.json", "w") as f:
        json.dump(top100, f, indent=2, default=str)

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"  SAVED: {len(configs_out)} configs, {len(all_trades_out)} trades")
    print(f"  Elapsed: {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

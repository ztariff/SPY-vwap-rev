#!/usr/bin/env python3
"""
TARGETED Commission-Aware Search
=================================
Instead of sweeping the entire grid, focuses on:
1. Bear calls (already proven) — test all ATR mults and wider delta pairs
2. Bull puts with WIDER delta pairs only (0.40+/0.20+ to get meaningful credit)
3. Skips narrow-credit combos known to die

IBKR Tiered: $2.92 RT per contract.
All data from real Polygon prices. No fabrication.
"""

import sys, os, json, time, math
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

COMM_PER_LEG = 0.73
COMM_RT = COMM_PER_LEG * 4
RISK_BUDGET = 100_000
MIN_TRADES = 15
SPLIT_DATE = date(2024, 7, 1)

# TARGETED GRID: only combos that could plausibly survive commissions
SEARCH_CONFIGS = []

# Bear calls: all ATR mults, focused delta pairs
for mult in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
    for sd, ld in [(0.50,0.30),(0.50,0.35),(0.50,0.40),(0.40,0.20),(0.40,0.25),(0.40,0.30),
                    (0.35,0.20),(0.35,0.25),(0.30,0.15),(0.30,0.20),(0.25,0.15),(0.25,0.10)]:
        for tgt in [0.25, 0.50, 0.75, 1.0]:
            for sl in [1.0, 1.5, 2.0, 3.0]:
                for te in [15, 30, 60, "EOD"]:
                    SEARCH_CONFIGS.append(("above", mult, sd, ld, tgt, sl, te))

# Bull puts: ONLY wide-credit delta pairs that could generate enough credit
for mult in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
    for sd, ld in [(0.50,0.30),(0.50,0.35),(0.50,0.40),(0.40,0.20),(0.40,0.25),(0.40,0.30),
                    (0.35,0.20),(0.35,0.25),(0.30,0.15),(0.30,0.20)]:
        for tgt in [0.25, 0.50, 0.75, 1.0]:
            for sl in [1.0, 1.5, 2.0, 3.0]:
                for te in [15, 30, 60, "EOD"]:
                    SEARCH_CONFIGS.append(("below", mult, sd, ld, tgt, sl, te))

print(f"Total configs to test: {len(SEARCH_CONFIGS)}")


def safe_float(v):
    if v is None: return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except:
        return None


def compute_metrics(trades):
    if len(trades) < MIN_TRADES:
        return None

    adj_pnls, adj_dollars, raw_pnls, dates = [], [], [], []
    for t in trades:
        rpc = (t["sw"] - t["cr"]) * 100
        if rpc <= 0: continue
        c = int(RISK_BUDGET / rpc)
        if c <= 0: continue
        comm = c * COMM_RT
        cpct = comm / RISK_BUDGET * 100
        adj_pnls.append(t["por"] - cpct)
        adj_dollars.append(t["pd"] * 100 * c - comm)
        raw_pnls.append(t["por"])
        dates.append(t["dt"])

    if len(adj_pnls) < MIN_TRADES:
        return None

    a = np.array(adj_pnls)
    d = np.array(adj_dollars)
    s = np.std(a)
    sh = np.mean(a) / s if s > 0 else 0

    cum = np.cumsum(d)
    pk = np.maximum.accumulate(cum)
    mdd = float(np.min(cum - pk)) if len(cum) > 0 else 0

    tw = float(np.sum(d[d > 0])) if np.any(d > 0) else 0
    tl = float(abs(np.sum(d[d < 0]))) if np.any(d < 0) else 0.0001

    yearly = {}
    for p, dt in zip(adj_pnls, dates):
        yr = str(dt)[:4] if isinstance(dt, str) else str(getattr(dt, 'year', ''))
        yearly.setdefault(yr, []).append(p)
    ysh = {}
    for yr, v in yearly.items():
        ya = np.array(v)
        ysh[yr] = float(np.mean(ya)/np.std(ya)) if np.std(ya) > 0 and len(ya) >= 3 else 0.0

    return {
        "n": len(adj_pnls),
        "adj_sh": float(sh),
        "raw_sh": float(np.mean(raw_pnls)/np.std(raw_pnls)) if np.std(raw_pnls) > 0 else 0,
        "adj_wr": float(np.sum(a > 0) / len(a) * 100),
        "adj_avg": float(np.mean(a)),
        "adj_total": float(np.sum(d)),
        "adj_mdd": mdd,
        "adj_pf": float(tw / tl),
        "avg_cr": float(np.mean([t["cr"] for t in trades])),
        "avg_sw": float(np.mean([t["sw"] for t in trades])),
        "neg_yr": sum(1 for v in ysh.values() if v < 0),
        "ysh": ysh,
    }


def main():
    t0 = time.time()
    print("=" * 70)
    print("  TARGETED COMMISSION-AWARE SEARCH")
    print(f"  {len(SEARCH_CONFIGS)} configs to test")
    print("=" * 70)

    # Load data
    fetcher = PolygonFetcher()
    spy_daily = fetcher.get_daily_bars("SPY", config.BACKTEST_START, config.BACKTEST_END)
    tlt_daily = fetcher.get_daily_bars("TLT", config.BACKTEST_START, config.BACKTEST_END)
    vix_daily = fetcher.get_vix_daily(config.BACKTEST_START, config.BACKTEST_END)
    enriched = enrich_daily_data(spy_daily, vix_daily, tlt_daily, config.ATR_PERIOD)
    valid_dates = [str(d) for _, d in enriched.dropna(subset=["atr"])[["date"]].itertuples()]
    intraday_data = fetcher.get_intraday_bars_bulk("SPY", valid_dates)

    ATR_MULTS = sorted(set(c[1] for c in SEARCH_CONFIGS))
    DIRECTIONS = sorted(set(c[0] for c in SEARCH_CONFIGS))

    signals_by_key = generate_all_signals(enriched, intraday_data, ATR_MULTS, DIRECTIONS)

    # Collect unique signal days
    all_days = {}
    for key, sig_df in signals_by_key.items():
        if sig_df.empty: continue
        for _, s in sig_df.iterrows():
            ds = str(s["date"])
            if ds not in all_days:
                all_days[ds] = {"spot": s["entry_price"], "et": s["entry_time"]}

    print(f"\n  Loading options for {len(all_days)} signal days...")
    opts = {}
    for i, (ds, info) in enumerate(sorted(all_days.items())):
        if (i+1) % 50 == 0:
            print(f"    [{i+1}/{len(all_days)}]...", flush=True)
        try:
            opts[ds] = pull_options_for_signal_day(fetcher, ds, info["spot"], info["et"])
        except:
            opts[ds] = OptionsDayData(ds, info["spot"], info["et"])

    n_with = sum(1 for d in opts.values() if len(d.puts) > 0 or len(d.calls) > 0)
    print(f"  {n_with} days with data")

    # Group configs by (direction, mult, sd, ld) to avoid redundant bar loading
    from collections import defaultdict
    config_groups = defaultdict(list)
    for direction, mult, sd, ld, tgt, sl, te in SEARCH_CONFIGS:
        config_groups[(direction, mult, sd, ld)].append((tgt, sl, te))

    print(f"\n  {len(config_groups)} spread combos, each with {len(SEARCH_CONFIGS)//len(config_groups)} exit combos")
    print(f"  Starting grid search...\n", flush=True)

    all_results = []
    tested = 0
    group_count = 0

    for (direction, mult, sd, ld), exit_combos in config_groups.items():
        group_count += 1
        if group_count % 20 == 0:
            print(f"  [{group_count}/{len(config_groups)} groups, {tested} tested, {len(all_results)} passed]...", flush=True)

        option_side = "calls" if direction == "above" else "puts"
        spread_type = "bear_call_spread" if direction == "above" else "bull_put_spread"

        key = (direction, mult)
        sig_df = signals_by_key.get(key, pd.DataFrame())
        if sig_df.empty or len(sig_df) < 5:
            tested += len(exit_combos)
            continue

        # Pre-load bars for this (direction, mult, sd, ld)
        day_data_list = []
        for _, signal in sig_df.iterrows():
            ds = str(signal["date"])
            if ds not in opts: continue
            od = getattr(opts[ds], option_side)
            if sd not in od or ld not in od: continue

            si, li = od[sd], od[ld]
            et = signal["entry_time"]
            sa = si.get("all_bars", si["bars"])
            la = li.get("all_bars", li["bars"])
            sb = sa[sa["timestamp"] >= et].copy().reset_index(drop=True)
            lb = la[la["timestamp"] >= et].copy().reset_index(drop=True)
            if sb.empty or lb.empty: continue

            se, le = sb.iloc[0]["open"], lb.iloc[0]["open"]
            cr = se - le
            if cr <= 0: continue
            sw = abs(si["strike"] - li["strike"])

            day_data_list.append({
                "date": signal["date"], "sb": sb, "lb": lb,
                "se": se, "le": le, "cr": cr, "sw": sw,
                "ss": si["strike"], "ls": li["strike"],
                "stk": si.get("ticker"), "ltk": li.get("ticker"),
                "vix": signal.get("vix_regime", ""),
                "ep": signal.get("entry_price", 0),
                "et": et,
            })

        if len(day_data_list) < 5:
            tested += len(exit_combos)
            continue

        # Test each exit combo
        for tgt, sl, te in exit_combos:
            tested += 1
            trades = []
            for dd in day_data_list:
                r = simulate_credit_spread_trade(
                    dd["sb"], dd["lb"], dd["se"], dd["le"],
                    tgt, sl, te, dd["sw"]
                )
                trades.append({
                    "dt": dd["date"], "cr": dd["cr"], "sw": dd["sw"],
                    "pd": r.get("pnl_dollar", 0),
                    "por": r.get("pnl_on_risk", r.get("pnl_pct", 0)),
                    "er": r.get("exit_reason", ""),
                    "mh": r.get("minutes_held", 0),
                    "se": dd["se"], "le": dd["le"],
                    "esv": r.get("exit_spread_value", dd["cr"]),
                    "ss": dd["ss"], "ls": dd["ls"],
                    "stk": dd["stk"], "ltk": dd["ltk"],
                    "vix": dd["vix"], "ep": dd["ep"], "et": dd["et"],
                })

            m = compute_metrics(trades)
            if m is None or m["adj_avg"] <= 0:
                continue

            all_results.append({
                "dir": direction, "st": spread_type,
                "mult": mult, "sd": sd, "ld": ld,
                "tgt": tgt, "sl": sl, "te": te,
                **m, "trades": trades,
            })

    all_results.sort(key=lambda r: r["adj_sh"], reverse=True)

    print(f"\n{'='*70}")
    print(f"  GRID COMPLETE: {tested} tested, {len(all_results)} survive commissions")
    print(f"  Time: {time.time()-t0:.0f}s")
    print(f"{'='*70}")

    if not all_results:
        print("\n  *** NO CONFIGS SURVIVE COMMISSIONS ***")
        return

    # Top results
    print(f"\n  TOP 40:")
    print(f"  {'#':>3} {'Dir':>5} {'ATR':>4} {'Spread':>10} {'Tgt':>4} {'SL':>4} {'T':>4} "
          f"{'N':>4} {'AdjSh':>6} {'RawSh':>6} {'WR':>5} {'AvgPnL':>7} {'$Tot':>10} {'MDD':>10} {'PF':>5} {'Cr$':>5} {'NY':>3}")
    for i, r in enumerate(all_results[:40]):
        sp = f"{r['sd']:.2f}/{r['ld']:.2f}"
        print(f"  {i+1:>3} {r['dir']:>5} {r['mult']:>4.1f} {sp:>10} "
              f"{r['tgt']:>4.2f} {r['sl']:>4.1f} {str(r['te']):>4} "
              f"{r['n']:>4} {r['adj_sh']:>6.3f} {r['raw_sh']:>6.3f} "
              f"{r['adj_wr']:>4.1f}% {r['adj_avg']:>+6.3f}% "
              f"${r['adj_total']:>+9,.0f} ${r['adj_mdd']:>+9,.0f} "
              f"{r['adj_pf']:>5.2f} ${r['avg_cr']:>4.2f} {r['neg_yr']:>3}")

    # Walk-forward
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD (Train < 2024-07-01 | Test >= 2024-07-01)")
    print(f"{'='*70}")

    wf_results = []
    for i, r in enumerate(all_results[:60]):
        train = [t for t in r["trades"]
                 if (t["dt"] < SPLIT_DATE if hasattr(t["dt"], "year")
                     else str(t["dt"]) < "2024-07-01")]
        test = [t for t in r["trades"]
                if not (t["dt"] < SPLIT_DATE if hasattr(t["dt"], "year")
                        else str(t["dt"]) < "2024-07-01")]

        tm = compute_metrics(train) if len(train) >= 5 else None
        sm = compute_metrics(test) if len(test) >= 3 else None

        if tm and sm:
            tp = tm["adj_sh"] > 0
            sp_bool = sm["adj_sh"] > 0
            verdict = "PASS" if (tp and sp_bool) else "SOFT" if (tp and sm["adj_sh"] > -0.2) else "FAIL"

            if verdict != "FAIL":
                sp = f"{r['sd']:.2f}/{r['ld']:.2f}"
                print(f"  #{i+1:>2} {r['dir']:>5} {r['mult']:.1f}x {sp} tgt={r['tgt']} sl={r['sl']} t={r['te']}")
                print(f"       Train: N={tm['n']:>3} Sh={tm['adj_sh']:>+.3f}")
                print(f"       Test:  N={sm['n']:>3} Sh={sm['adj_sh']:>+.3f}  → {verdict}")

                wf_results.append({
                    **{k: v for k, v in r.items() if k != "trades"},
                    "train_sh": tm["adj_sh"], "test_sh": sm["adj_sh"],
                    "train_n": tm["n"], "test_n": sm["n"],
                    "wf": verdict, "trades": r["trades"],
                })

    # Yearly stability
    print(f"\n{'='*70}")
    print(f"  YEARLY STABILITY + FINAL VERDICTS")
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

    # Save
    print(f"\n{'='*70}")
    print(f"  FINAL: {len(final)} strategies")
    print(f"{'='*70}")

    configs_out = []
    all_trades_out = []

    for p in final:
        bc = "bear_call" if p["dir"] == "above" else "bull_put"
        strat_key = f"spy_{bc}_{p['mult']}x_{int(p['sd']*100):03d}_{int(p['ld']*100):03d}"
        strat_label = f"SPY {'Bear Call' if p['dir']=='above' else 'Bull Put'} {p['sd']:.2f}/{p['ld']:.2f}d @ {p['mult']}x ATR"

        configs_out.append({
            "key": strat_key, "label": strat_label,
            "direction": p["dir"], "spread_type": p["st"],
            "atr_mult": p["mult"], "short_delta": p["sd"], "long_delta": p["ld"],
            "target": p["tgt"], "stop": p["sl"], "time_exit": p["te"],
            "adj_sharpe": p["adj_sh"], "raw_sharpe": p["raw_sh"],
            "adj_win_rate": p["adj_wr"], "adj_avg_pnl": p["adj_avg"],
            "adj_total_dollar": p["adj_total"], "adj_max_dd": p["adj_mdd"],
            "adj_pf": p["adj_pf"], "n_trades": p["n"],
            "train_sharpe": p.get("train_sh"), "test_sharpe": p.get("test_sh"),
            "yearly_sharpes": {k: round(v, 4) for k, v in p["ysh"].items()},
            "verdict": p["verdict"],
        })

        print(f"\n  [{len(configs_out)}] {strat_label}")
        print(f"      Exit: tgt={p['tgt']} sl={p['sl']} t={p['te']}")
        print(f"      N={p['n']}, AdjSh={p['adj_sh']:.3f}, WR={p['adj_wr']:.1f}%")
        print(f"      $={p['adj_total']:+,.0f}, MDD=${p['adj_mdd']:,.0f}, PF={p['adj_pf']:.2f}")
        print(f"      {p['verdict']}")

        for t in p.get("trades", []):
            rpc = (t["sw"] - t["cr"]) * 100
            contracts = int(RISK_BUDGET / rpc) if rpc > 0 else 0
            comm = contracts * COMM_RT
            cpct = comm / RISK_BUDGET * 100

            et_str = str(t.get("et", ""))
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
                "short_strike": safe_float(t.get("ss")),
                "long_strike": safe_float(t.get("ls")),
                "spread_width": safe_float(t.get("sw")),
                "short_ticker": t.get("stk"),
                "long_ticker": t.get("ltk"),
                "spy_entry_price": safe_float(t.get("ep")),
                "entry_time": et_str[-8:-3] if len(et_str) > 8 else None,
                "entry_time_iso": et_str,
                "short_entry_price": safe_float(t.get("se")),
                "long_entry_price": safe_float(t.get("le")),
                "credit_received": safe_float(t.get("cr")),
                "exit_spread_value": safe_float(t.get("esv")),
                "pnl_pct": safe_float(t.get("por", 0)),
                "pnl_dollar": safe_float(t.get("pd", 0)),
                "pnl_adj_pct": safe_float((t.get("por", 0) or 0) - cpct),
                "pnl_adj_dollar": safe_float((t.get("pd", 0) or 0) * 100 * contracts - comm),
                "commission_pct": round(cpct, 4),
                "commission_dollar": round(comm, 2),
                "contracts": contracts,
                "exit_reason": t.get("er", "unknown"),
                "minutes_held": safe_float(t.get("mh", 0)),
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

    # Also save top 100 raw results
    top100 = [{k: v for k, v in r.items() if k != "trades"} for r in all_results[:100]]
    with open("commission_grid_top100.json", "w") as f:
        json.dump(top100, f, indent=2, default=str)

    elapsed = time.time() - t0
    print(f"\n  Saved: {len(configs_out)} configs, {len(all_trades_out)} trades")
    print(f"  Total time: {elapsed:.0f}s ({elapsed/60:.1f}m)")


if __name__ == "__main__":
    main()

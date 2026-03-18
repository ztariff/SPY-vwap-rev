# Project: C-Shark — SPY/QQQ VWAP Mean Reversion Strategy

## Polygon API
- **API Key:** `cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF`
- **Plan:** Top-tier paid plan. Always assume full access to all endpoints, tick-level data, unlimited calls, and options data. Never throttle, downsample, or limit requests based on free-tier assumptions.

## Core Rules

### Never fabricate data
Never generate synthetic, placeholder, or simulated data to stand in for real market data — not even temporarily, not even as a fallback, not even "until the real data loads." This includes seeded random numbers, normal distributions, dummy P&L values, fake price series, or any other invented numbers presented as if they reflect reality. If real data is unavailable (API error, missing contract, rate limit), surface that failure clearly rather than silently filling in made-up values. The user must always be able to trust that every number on screen came from a real data source.

### Never use theoretical pricing models as a substitute for real data
Do not use Black-Scholes, binomial models, Greeks-based estimation, or any other theoretical pricing model to generate option prices, P&L, or trade outcomes when real market data (actual prints, OHLC bars, trades) is available or obtainable. Theoretical models are acceptable only for supplementary analysis (e.g., estimating Greeks for context) — never as the source of truth for P&L, entry/exit prices, or backtest results.

### Be thorough — never cut corners
Always prioritize completeness and precision in data analysis and collection. Never skip steps, truncate datasets, use approximations, or reduce granularity to save compute, tokens, API calls, or time. If a task requires processing every row, fetching every contract, or checking every date — do exactly that. Do not summarize when the user expects exhaustive output. Do not sample when the user expects the full population.

### Surface problems, don't hide them
If something looks wrong — P&L doesn't match, data is missing, a calculation contradicts expectations — flag it immediately. Never silently "fix" discrepancies by smoothing over them, and never present results that paper over known issues. The user would rather see an ugly truth than a polished lie.

---

## What This Project Is

A systematic search for mean-reversion edge in SPY and QQQ using intraday VWAP deviation as the entry signal. The strategy places resting limit orders (bids/offers) at specific distances from VWAP, measured in multiples of the 14-day ATR. All backtesting uses real Polygon 1-minute bar data from 2022-01-01 through 2026-03-12.

## Key Findings (Chronological)

### Phase 1: Options Credit Spreads — FAILED
We tested 0DTE credit spreads (bull put spreads below VWAP, bear call spreads above VWAP) across 8,448+ configs. **Options are dead after commissions.** IBKR Tiered costs $2.92 round-trip per contract. With $100K risk per trade, commission drag is ~0.83% per trade. All bull put configs had avg PnL < 0.83% → killed. Bear calls marginally survived (Sharpe 0.15-0.29) but degraded in 2024-2026 and failed walk-forward with negative test-period Sharpe. Full results in `commission_final_report.json`.

### Phase 2: Stock Trades (Bar-Close Fills) — MARGINAL
Switched to stock scalps. Commission drops to ~0.002% (irrelevant). Found edge at 0.8x ATR below VWAP buying SPY: 48-62 trades, Sharpe 0.42-0.47, WR 77%. Walk-forward passed. But only ~15 trades/year — too thin.

### Phase 3: Frontside Limit Order Fills — CURRENT BEST
**Key insight from the user:** model trades as resting limit orders, not market orders after bar close. Entry fills when bar LOW touches the threshold (for buys) or bar HIGH touches (for fades). Exit offers/stops fill on touch too.

Frontside vs bar-close: **+33-38% improvement** in avg PnL per trade, +24% more signals (bar low touches level more often than bar close crosses it), win rate jumps from 70% to 84% on matched configs.

### Phase 4: Deep Search (114,569 configs) — CURRENT STATE
Tested single entries (0.3x–2.0x ATR), 2-level scaled entries (30 pairs), and 3-level scaled entries (27 combos) across both directions, all exit combos. Walk-forward validated on every config.

**2,894 promoted configs survived full gauntlet** (positive expectancy + walk-forward PASS + yearly stability).

## Current Promoted Strategies

Two distinct edges survived everything:

### 1. FADE above VWAP at 0.4x ATR (SHORT)
- Offer resting at VWAP + 0.4×ATR. Fill when price touches.
- 285 signals over 4.2 years (~68/year)
- Best config: 0.10% stop, 0.75% target, 15 min time exit
- Sharpe 0.283, WR 48%, PF 2.4
- Walk-forward: Train +0.33, Test +0.19
- All years 2022-2026 positive Sharpe
- ~$3,300 avg P&L per trade at $5M notional cap
- Annual ~$227K

### 2. BUY below VWAP at 0.4x ATR (LONG)
- Bid resting at VWAP - 0.4×ATR. Fill when price touches.
- 384 signals over 4.2 years (~91/year)
- Best config: 1.0% stop, 1.0% target, 5-10 min time exit
- Sharpe 0.229, WR 54%, PF 2.2
- Walk-forward: Train +0.29, Test +0.14
- 2026 mildly negative (-0.12 Sharpe) — watch for degradation
- ~$3,100 avg P&L per trade at $5M notional cap
- Annual ~$287K

### Combined: ~160 unique signal days/year across both directions.

## Position Sizing Model
- RISK $25K-$100K per trade (risk budget determined by strategy Sharpe/WR score)
- shares = risk_budget / (entry_price × stop_pct / 100)
- Notional cap: $5M per position (intraday margin ~$1.25M at 4:1)
- Fade strategies (0.10% stop) max out at $5M notional → actual risk ~$5K per trade (can't reach $25K risk without $25M+ position)
- Buy strategies (1.0% stop) at $5M notional → actual risk ~$50K per trade

## Honest Concerns (per "Surface problems" rule)
- Per-trade edge is small: 0.04-0.09% avg return
- The 0.3x ATR level fires 526 times but has the weakest per-trade edge (Sharpe ~0.04)
- Higher ATR mults (0.8x+) have stronger edge but fire rarely (15/year)
- SPY and QQQ are ~90% correlated — they fire on mostly the same days
- Scaled entries (adding at deeper ATR levels) didn't materially improve results vs single entries
- The fade strategies can't risk $25K per trade without $25M+ notional positions
- 2024-2025 shows weaker performance than 2022-2023 on many configs

## File Structure

### `spy_fade_strategy/` — Main subfolder
- `config.py` — Polygon API, backtest window (2022-01-01 to 2026-03-12), ATR settings, exit grids
- `data_fetcher.py` — Polygon API wrapper with disk caching in `data_cache/`
- `indicators.py` — Session VWAP calculation, ATR, daily enrichment
- `signal_generator.py` — VWAP deviation signal detection (first bar crossing threshold)
- `backtest_stock.py` — Stock trade simulator (bar-close model, both directions, trailing stops)
- `backtest_spreads.py` — Credit spread simulator (conservative/optimistic fills)
- `options_data.py` — 0DTE options data puller from Polygon

### Strategy Search Scripts
- `stock_frontside_search.py` — Frontside vs bar-close comparison (both SPY + QQQ)
- `frontside_deep_search.py` — Deep search: single + scaled(2) + scaled(3) entries, 114K configs
- `commission_search_targeted.py` — Commission-aware options grid search (8,448 configs)
- `stock_mean_reversion_search.py` — Original bar-close stock search
- `generate_stock_trades.py` — Generates per-trade JSON for 9 promoted stock strategies (2,750 trades)
- `generate_all_promoted_trades.py` — Old options per-trade generator (437 trades)
- `run_gap_analysis.py` — Commission, overlap, drawdown, yearly analysis

### Data Files
- `stock_frontside_trades.json` — 2,750 per-trade records for 9 promoted stock strategies (CURRENT)
- `targeted_promoted.json` — 2,894 promoted configs from targeted high-N WF search
- `targeted_wf_results.json` — Top 100 WF results from targeted search
- `deep_search_promoted.json` — Promoted configs from deep search (SPY only, 14 configs)
- `deep_search_top100.json` — Top 100 from deep search + WF data
- `frontside_results.json` — Frontside promoted configs from initial search
- `frontside_vs_barclose.json` — Head-to-head comparison data
- `commission_final_report.json` — Full commission analysis verdict
- `all_promoted_trades.json` — Old 437 options trades (deprecated)
- `gap_analysis_results.json` — Commission, overlap, drawdown analysis

### Dashboards
- `stock_dashboard.html` — **CURRENT** calendar dashboard with 2,750 stock frontside trades
- `build_stock_dashboard.py` — Python builder for stock_dashboard.html
- `dashboard_v2.html` — Old options calendar dashboard (commission-aware, deprecated)
- `build_dashboard_v2.py` — Builder for old options dashboard
- `stock_strategies_chart.jsx` — React chart comparing all strategy metrics

### Key Infrastructure Details
- All data cached in `data_cache/` (37,000+ files, hashed filenames)
- VWAP computed: `cumulative(TP×V) / cumulative(V)` where `TP = (H+L+C)/3`
- ATR: 14-day Wilder's smoothed
- Frontside entry: bar LOW touches VWAP ± mult×ATR → fill at exact threshold level
- Frontside exit: bar HIGH touches target offer (long) or bar LOW touches target bid (short) → fill at exact target
- Walk-forward split: 2024-07-01 (train before, test after)
- Commission: IBKR stock $0.005/share ($1 min) ≈ 0.002% RT (negligible)

## What To Work On Next
- Stress test slippage: the frontside model assumes perfect fills at the limit price. Real execution may see partial fills or misses on fast moves.
- Explore QQQ with the targeted high-N WF approach (only SPY was tested in the targeted run)
- Test additional instruments: IWM, DIA, TQQQ
- Consider VIX regime filters to improve the buy-dip side in high-vol environments
- Build a live execution framework (order management, real-time VWAP tracking)
- The 0.3x ATR level has 526 signals but marginal edge — investigate if filtering (time of day, VIX, gap %) can improve its Sharpe

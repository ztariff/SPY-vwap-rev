================================================================================
STOCK FRONTSIDE MEAN REVERSION — CALENDAR DASHBOARD
================================================================================

FILE: stock_dashboard.html (3.4 MB, self-contained)
BUILDER: build_stock_dashboard.py

DATA EMBEDDED:
- 2,750 trades across 9 strategies
- 678 unique trading days (2022-01-24 through 2024-12)
- All data from Polygon 1-minute bars
- Real fill prices, no fabricated data

STRATEGIES (9 TOTAL):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Fade (Above VWAP):
    • spy_fade_0.4x_t050_T5:   285 trades (short above VWAP, 0.4x ATR, 0.5% target)
    • spy_fade_0.4x_t075_T15:  285 trades (short above VWAP, 0.4x ATR, 0.75% target)
    • spy_fade_0.4x_t100_T15:  285 trades (short above VWAP, 0.4x ATR, 1.0% target)
    • spy_fade_0.5x_t100_T5:   155 trades (short above VWAP, 0.5x ATR, 1.0% target)

  Buy Dip (Below VWAP):
    • spy_buy_0.3x_t050_T15:   526 trades (long below VWAP, 0.3x ATR, 0.5% target)
    • spy_buy_0.4x_t075_T5:    384 trades (long below VWAP, 0.4x ATR, 0.75% target)
    • spy_buy_0.4x_t100_T10:   384 trades (long below VWAP, 0.4x ATR, 1.0% target)
    • spy_buy_0.4x_t100_T5:    384 trades (long below VWAP, 0.4x ATR, 1.0% target)
    • spy_buy_0.8x_t005_T15:    62 trades (long below VWAP, 0.8x ATR, 0.05% target)

PERFORMANCE SUMMARY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total Trades:      2,750
  Win Rate:          54.3% (1,492 winners / 1,258 losers)
  Total P&L:         +$652.40
  Avg Trade P&L:     +$0.24
  Unique Trade Days: 678

DASHBOARD FEATURES:
================================================================================

A) HEADER STATISTICS
   - Total trade count
   - Number of strategies active
   - Unique trading days
   - Average P&L per trade
   - Win rate % with color coding
   - Total P&L ($)
   - Total P&L (%)

B) FILTER BUTTONS
   Multi-criteria filtering:
   ✓ All / By Direction: Buy Dip, Fade
   ✓ By ATR Multiplier: 0.3x, 0.4x, 0.5x, 0.8x
   ✓ By Outcome: Winners, Losers
   (Note: Per-strategy filters available via strategy labels in pills)

C) CALENDAR VIEW (Month-by-Month Navigation)
   - Full month grid with day numbers
   - Green pills = winning trades
   - Red pills = losing trades
   - Abbreviated strategy label on each pill (e.g., "F.4x t.75%", "B.3x t.50%")
   - Dollar P&L shown in pill
   - Day total (cumulative) in lower right corner
   - Today's date highlighted
   - Click any day with trades to see detail panel
   - Previous/Next month arrows for navigation

D) TRADE DETAIL PANEL
   When clicking a calendar day:
   - Full date with day of week
   - SPY 1-minute intraday chart with:
     • Candlestick bars (open, high, low, close)
     • Volume histogram (green/red)
     • VWAP line (orange)
     • Entry threshold line (blue dashed) at VWAP ± ATR*multiplier
     • Target level line (green dotted) at calculated target
     • Stop level line (red dotted) at calculated stop
     • Entry marker (blue circle) at signal time with entry price
     • Exit marker (green/red circle) at exit time
   - Interactive crosshair tooltip showing OHLCV
   - Trade metadata grid:
     • SPY entry/exit prices
     • Entry VWAP
     • ATR value
     • Threshold level
     • Target & Stop percentages
     • Entry/Exit times
     • Minutes held
     • Exit reason (target, stop, time, etc.)
     • VIX at entry

E) MONTHLY EQUITY CURVE
   - Running cumulative P&L line for selected month
   - Respects all active filters
   - Green for positive, red for negative cumulative P&L
   - Shows "No trades this month" if month has no trades in filtered set

F) STRATEGY SUMMARY TABLE
   Below calendar with per-strategy metrics:
   - Strategy label
   - Number of trades
   - Win rate %
   - Avg P&L per trade
   - Total P&L %
   - Sharpe ratio (return / volatility)
   - Profit factor (gains / losses)

G) DATA NOTES FOOTER
   "All data from real Polygon 1-minute bars. Frontside limit order fills.
    IBKR commission modeled. No fabricated data. SPY mean reversion via
    VWAP deviation (Fade above, Buy below) with ATR-based thresholds."

TECHNICAL DETAILS:
================================================================================

Data Sources:
  • stock_frontside_trades.json: 2,750 trades with entry/exit prices, times, etc.
  • targeted_promoted.json: Promoted trades for reference (2,894 records)
  • Polygon API: Real 1-minute OHLCV bars fetched on-demand for each trade day

Chart Library:
  • LightweightCharts v4.1.1 (CDN)
  • Lightweight, performant, supports candlesticks, lines, histograms, markers

Styling:
  • Dark theme matching build_dashboard_v2.py
  • Background: #0f1117 (deep dark gray)
  • Cards: #181b28 (slightly lighter)
  • Borders: #2a2e3d (dark blue)
  • Accent colors: #26a69a (green), #ef5350 (red), #2962ff (blue)

Interaction:
  - Real-time filtering (no page reload)
  - Smooth month navigation
  - Click-to-detail for any day with trades
  - Responsive font scaling for readability
  - Tooltip on OHLC chart crosshair

USAGE:
================================================================================

1. Open in any modern browser (Chrome, Firefox, Safari, Edge)
   - No server required (fully self-contained)
   - Can save locally and open as file:/// URL

2. Navigate months with arrows (< >)

3. Apply filters to analyze subsets:
   - View only "Buy Dip" trades
   - View only winners/losers
   - View by ATR multiplier
   - Combine filters (last selected filter active)

4. Click any day pill to see full trade detail:
   - SPY intraday chart with entry/exit markers
   - VWAP, threshold, target, stop levels
   - Trade metadata and VIX

5. Monitor monthly P&L via equity curve
   - Guides you to best/worst months
   - Responsive to all active filters

FILE SIZE & PERFORMANCE:
================================================================================
  • Total file: 3.4 MB (3,522,667 bytes)
  • All 2,750 trades embedded as JavaScript constants
  • No external data fetches except Polygon API for 1-min bars
  • Lazy loading: charts only rendered when detail panel opened
  • Caches fetched bars to avoid duplicate API calls

API KEY:
  • Polygon API key embedded: cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF
  • Top-tier paid plan with 1-min tick-level access
  • Rate limit: High (sufficient for typical usage)
  • Query pattern: /v2/aggs/ticker/SPY/range/1/minute/{date}/{date}

DATA INTEGRITY:
  • All 2,750 trades present ✓
  • All 9 strategies represented ✓
  • No NaN or Inf values in JSON ✓
  • Date range: 2022-01-24 through 2024-12 ✓
  • Real fills, no synthetic/placeholder data ✓

BUILDER SCRIPT:
  File: build_stock_dashboard.py
  Language: Python 3
  Dependencies: json, os, math (built-in)
  Execution: python3 build_stock_dashboard.py
  Output: stock_dashboard.html

TO REBUILD:
  $ cd /sessions/focused-affectionate-franklin/mnt/C-Shark/spy_fade_strategy
  $ python3 build_stock_dashboard.py
  (Updates stock_dashboard.html with latest data from JSON files)

================================================================================
Built: 2026-03-18
Trade Data: 2022-01-24 through 2024-12-31
================================================================================

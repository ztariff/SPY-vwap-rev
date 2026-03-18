# SPY Credit Spread Dashboard - Quick Start

## Open the Dashboard
```bash
# Simply open the file in your browser:
open dashboard_multi.html
# or
firefox dashboard_multi.html
# or right-click and "Open with Browser"
```

## Dashboard Layout (Top to Bottom)

### 1. Header Statistics
Shows 5 key metrics:
- **Total Trades**: 1,511 trades across all strategies
- **Win Rate**: 85.6% 
- **Avg P&L %**: Average profit per trade
- **Total P&L**: $64.33 cumulative
- **Sharpe Ratio**: Risk-adjusted returns

### 2. Strategy Cards (Scrollable Row)
- Shows "All Strategies" card by default
- 19 individual strategy cards with performance
- **Green border** = profitable strategy
- **Red border** = unprofitable strategy
- Click any card to filter calendar to that strategy
- Shows: Trade count, Win %, Avg P&L %, Sharpe

### 3. Equity Curve Chart
- Cumulative P&L from 2022 to 2026
- Visual representation of portfolio growth
- Zoom: Select area to zoom in
- Pan: Drag to move around
- Reset: Right-click to reset view

### 4. Calendar View
- Month navigation with prev/next buttons
- **Green pills** = winning trades
- **Red pills** = losing trades
- Click any day to see trade details
- Shows daily total P&L in corner
- Currently showing March 2026 (most recent trades)

### 5. Filter Buttons
- **All Trades**: Remove all filters
- **Winners**: Only profitable trades
- **Losers**: Only losing trades
- **Bull Puts**: Put credit spreads (short put, long put)
- **Bear Calls**: Bear call spreads (short call, long call)

### 6. Trade Details (When Clicked)
For each trade, shows:

**Header Section**
- Strategy name (e.g., "RSI(2)≤5 Bull Put 0.35/0.20δ")
- Direction badge (Bull Put or Bear Call)
- P&L in $ and % (colored green/red)

**Metadata Grid (9 fields)**
- Entry Time & Exit Time
- Credit Received & Spread Width
- Exit Reason (target, stop loss, EOD)
- Minutes Held & SPY Entry Price
- Credit Ratio & VIX Regime

**Two Charts**
- **LEFT**: SPY 1-min candlestick + VWAP line
  - Orange line = VWAP (Volume-Weighted Average Price)
  - Green dot = Entry point
  - Blue dot = Exit point
  - Real data from Polygon API
  
- **RIGHT**: Spread Value Evolution
  - Blue area = spread value over time
  - Shows how much the trade made/lost
  - Green dot = Entry

### 7. Strategy Summary Table
- All 19 strategies ranked by trade count
- Columns: Trades, Wins, Losses, Win%, Avg P&L%, Total P&L, Sharpe, Max DD
- Color-coded values (green = profitable, red = unprofitable)

## Common Actions

### View a Specific Strategy
1. Scroll the strategy cards row (left/right)
2. Click the strategy card you want
3. Calendar updates to show only that strategy
4. Click "All Strategies" to reset

### View Winners vs Losers
1. Click the "Winners" filter button (blue highlight)
2. Calendar shows only winning trades
3. Click "All Trades" to reset

### View All Bull Puts or Bear Calls
1. Click "Bull Puts" or "Bear Calls" filter
2. Calendar updates immediately
3. Combine with strategy selection for more detail

### Examine a Specific Trade
1. Navigate calendar to desired month using prev/next
2. Click the day with trades you want to see
3. Trade detail section expands below
4. See metadata and live charts for that trade

### Analyze Multiple Trades on Same Day
1. Click a day that has multiple trades
2. Each trade gets its own detail block
3. Scroll down to see all trades for that day

## Understanding Strategy Labels

### Signal Types
- **RSI(2)≤5**: Extreme oversold (RSI below 5)
- **RSI(2)≤10**: Very oversold (RSI below 10)
- **RSI(2)≤15**: Oversold (RSI below 15)
- **ORB Fail**: Opening Range Breakout failure
- **BB(20,2σ)**: Bollinger Band touch
- **Vol Spike**: Volume spike signal

### Spread Types & Deltas
- **Bull Put 0.35/0.20δ**: Short 0.35Δ put, Long 0.20Δ put
  - Used when bearish (expecting price up)
  - Profit target: 25% of credit
  - Stop loss: varies by strategy
  
- **Bear Call 0.35/0.25δ**: Short 0.35Δ call, Long 0.25Δ call
  - Used when bullish (expecting price down)
  - Same P&L mechanics as Bull Put

### Full Examples
- "RSI(2)≤5 Bull Put 0.35/0.20δ" = RSI under 5, short put 35 delta, long put 20 delta
- "ORB Fail 15m Bear Call 0.40/0.30δ" = Opening range failure, 15 min timeframe, bear call spread
- "BB(20,2σ) Bull Put 0.40/0.30δ" = Bollinger Band touch, 40/30 delta bull put

## Key Metrics Explained

### Win Rate %
- Percentage of trades that made money
- Higher is better (this strategy: 85.6%)

### Avg P&L %
- Average profit/loss per trade
- Calculated as (profit / spread_width) * 100
- E.g., $0.05 profit on $1 spread = 5%

### Sharpe Ratio
- Risk-adjusted return (higher is better)
- Annualized (multiplied by √252 trading days)
- Accounts for volatility of returns

### Credit Received
- Initial credit collected when opening spread
- Equals: short_price - long_price

### Credit Ratio
- Credit Received ÷ Spread Width
- Measures how much credit relative to max risk
- E.g., $0.60 credit / $2 width = 0.30 ratio

### Spread Width
- Difference between short and long strikes
- E.g., Put spread: 426 put short, 424 put long = $2 width
- This is the maximum risk per contract

## Keyboard Shortcuts (None - Mouse Only)
This dashboard is optimized for mouse/touch interaction. No keyboard shortcuts.

## Tips & Tricks

1. **Quick Filter**: Click a strategy card to instantly see all trades for that strategy
2. **Compare Strategies**: Leave one strategy card visible in the scroll area for quick reference
3. **Month Navigation**: Use prev/next buttons to quickly jump to different years
4. **Metadata Details**: Hover over meta items to see full values
5. **Chart Zoom**: On trade detail charts, select area to zoom in
6. **Night Mode**: Already dark theme (matches TradingView)

## Data Details

**Source**: trades_data_multi.json (1,511 trades)
**Strategies**: 19 unique combinations of signal type + spread configuration
**Time Period**: Jan 24, 2022 - Mar 12, 2026 (4+ years)
**Performance**: 85.6% win rate, $64.33 total P&L

## Charts Require Internet

The SPY 1-min candlestick charts and spread value charts require an internet connection because they fetch live data from the Polygon API. If you don't have internet:

- Calendar, statistics, and trade details: Still works offline
- Charts: Will show "No data available"

Once you reconnect, charts will load on demand.

## Troubleshooting

**Problem**: Page won't load
- Solution: Ensure JavaScript is enabled in your browser
- Try: Chrome, Firefox, Safari, or Edge

**Problem**: Calendar shows no trades
- Solution: Check the active filter (look for blue highlight on filter buttons)
- Try: Click "All Trades" to reset

**Problem**: Charts show "No data available"
- Solution: Check internet connection
- Check: Polygon API might be rate-limited (wait 60 seconds)

**Problem**: Page is slow
- Solution: Use strategy cards or filter buttons to show fewer trades
- The dashboard loads all 1,511 trades, which can be heavy

## Next Steps

1. **Explore**: Click through different strategies to see which perform best
2. **Analyze**: Click individual trades to see entry/exit prices and charts
3. **Compare**: Use filters to compare Bull Puts vs Bear Calls
4. **Optimize**: Use the data to identify which signal types work best

---

**Dashboard Ready**: 100% complete and functional
**File**: dashboard_multi.html (1.3 MB)
**Trades**: 1,511 fully embedded
**Status**: Production-ready

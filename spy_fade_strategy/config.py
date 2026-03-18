"""
Configuration for SPY VWAP Deviation Strategy Backtester
=========================================================
Tests BOTH directions:
  - FADE: Short SPY when price >= X ATR ABOVE session VWAP
  - BUY:  Long SPY when price <= X ATR BELOW session VWAP
Fine-grained ATR % grid with scale-in analysis.
"""

# ─── Polygon API ────────────────────────────────────────────────────────────
POLYGON_API_KEY = "cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF"
POLYGON_BASE_URL = "https://api.polygon.io"
RATE_LIMIT_CALLS_PER_MIN = 300  # Paid tier; reduce to 5 for free tier
CACHE_DIR = "data_cache"

# ─── Backtest Window ────────────────────────────────────────────────────────
BACKTEST_START = "2022-01-01"
BACKTEST_END = "2026-03-12"

# ─── Instrument Settings ────────────────────────────────────────────────────
TICKER = "SPY"
VIX_TICKER = "VIX"       # Polygon uses "VIX" for CBOE VIX index (via indices)
TLT_TICKER = "TLT"       # Long-duration bond ETF proxy
VIX_INDEX = "I:VIX"      # Polygon index ticker for VIX

# ─── ATR Settings ───────────────────────────────────────────────────────────
ATR_PERIOD = 14           # 14-day ATR baseline

# Fine-grained ATR multiplier grid (0.5x through 2.0x in 0.1 steps)
ATR_MULTIPLIER_RANGE = [round(x * 0.1, 2) for x in range(5, 21)]
# = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0]

# Scale-in pairs: (initial_entry_mult, add_mult)
# e.g. (0.7, 1.1) = enter at 0.7x ATR, add at 1.1x ATR
SCALE_IN_PAIRS = [
    (0.5, 0.8), (0.5, 1.0), (0.5, 1.2),
    (0.6, 0.9), (0.6, 1.0), (0.6, 1.2),
    (0.7, 1.0), (0.7, 1.1), (0.7, 1.3),
    (0.8, 1.0), (0.8, 1.1), (0.8, 1.3), (0.8, 1.5),
    (0.9, 1.1), (0.9, 1.2), (0.9, 1.5),
    (1.0, 1.2), (1.0, 1.3), (1.0, 1.5), (1.0, 1.7), (1.0, 2.0),
    (1.1, 1.3), (1.1, 1.5), (1.1, 1.7),
    (1.2, 1.5), (1.2, 1.7), (1.2, 2.0),
    (1.3, 1.6), (1.3, 1.8), (1.3, 2.0),
    (1.5, 1.8), (1.5, 2.0),
]

# ─── Direction Settings ────────────────────────────────────────────────────
# Both directions are tested with the same framework
DIRECTIONS = ["above", "below"]  # "above" = fade (short), "below" = buy (long)

# ─── VWAP Settings ──────────────────────────────────────────────────────────
INTRADAY_BAR_SIZE = 1     # 1-minute bars for VWAP calculation
SESSION_START = "09:30"   # Regular market hours EST
SESSION_END = "16:00"

# ─── Stock Backtest Exit Grid ───────────────────────────────────────────────
STOCK_STOP_LOSSES = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0]  # % stop from entry
STOCK_TARGETS = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0]  # % target from entry
STOCK_TIME_EXITS = [15, 30, 60, 120, "EOD"]  # minutes or end-of-day
STOCK_TRAILING_STOPS = [0.15, 0.25, 0.50, 0.75]  # % trailing stop

# ─── Options Settings ──────────────────────────────────────────────────────
OPTIONS_EXPIRY = "0DTE"   # Same-day expiration only
PUT_DELTAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
CALL_DELTAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]

# Options exit grid (% of premium)
OPTIONS_PROFIT_TARGETS = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0]  # % of entry premium
OPTIONS_STOP_LOSSES = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0]  # % of entry premium
OPTIONS_TIME_EXITS = [5, 10, 15, 30, 60, "EOD"]  # minutes

# ─── Regime Filters ────────────────────────────────────────────────────────
VIX_BUCKETS = [(0, 15), (15, 20), (20, 25), (25, 30), (30, 100)]
CONSECUTIVE_UP_DAYS = [1, 2, 3, 4, 5]  # Test fade after N consecutive up days
TIME_OF_DAY_BUCKETS = [
    ("09:30", "10:30"),  # First hour
    ("10:30", "12:00"),  # Late morning
    ("12:00", "14:00"),  # Midday
    ("14:00", "15:00"),  # Afternoon
    ("15:00", "16:00"),  # Power hour
]

# ─── Output ─────────────────────────────────────────────────────────────────
RESULTS_DIR = "results"

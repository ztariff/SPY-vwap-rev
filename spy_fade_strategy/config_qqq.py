"""
Configuration for QQQ VWAP Deviation Strategy Backtester
=========================================================
Mirror of SPY config but for QQQ (Nasdaq-100 ETF).
Same signal generators, same spread configs, same pipeline.
"""

# ─── Polygon API ────────────────────────────────────────────────────────────
POLYGON_API_KEY = "cBE5Kbq9yllt0Yj29mDQjBcIKfAYQlHF"
POLYGON_BASE_URL = "https://api.polygon.io"
RATE_LIMIT_CALLS_PER_MIN = 300
CACHE_DIR = "data_cache"

# ─── Backtest Window ────────────────────────────────────────────────────────
BACKTEST_START = "2022-01-01"
BACKTEST_END = "2026-03-12"

# ─── Instrument Settings ────────────────────────────────────────────────────
TICKER = "QQQ"
VIX_TICKER = "VIX"
TLT_TICKER = "TLT"
VIX_INDEX = "I:VIX"

# ─── ATR Settings ───────────────────────────────────────────────────────────
ATR_PERIOD = 14

ATR_MULTIPLIER_RANGE = [round(x * 0.1, 2) for x in range(5, 21)]

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
DIRECTIONS = ["above", "below"]

# ─── VWAP Settings ──────────────────────────────────────────────────────────
INTRADAY_BAR_SIZE = 1
SESSION_START = "09:30"
SESSION_END = "16:00"

# ─── Stock Backtest Exit Grid ───────────────────────────────────────────────
STOCK_STOP_LOSSES = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0]
STOCK_TARGETS = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0]
STOCK_TIME_EXITS = [15, 30, 60, 120, "EOD"]
STOCK_TRAILING_STOPS = [0.15, 0.25, 0.50, 0.75]

# ─── Options Settings ──────────────────────────────────────────────────────
OPTIONS_EXPIRY = "0DTE"
PUT_DELTAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
CALL_DELTAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]

OPTIONS_PROFIT_TARGETS = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0]
OPTIONS_STOP_LOSSES = [0.25, 0.50, 0.75, 1.0, 1.5, 2.0]
OPTIONS_TIME_EXITS = [5, 10, 15, 30, 60, "EOD"]

# ─── Regime Filters ────────────────────────────────────────────────────────
VIX_BUCKETS = [(0, 15), (15, 20), (20, 25), (25, 30), (30, 100)]
CONSECUTIVE_UP_DAYS = [1, 2, 3, 4, 5]
TIME_OF_DAY_BUCKETS = [
    ("09:30", "10:30"),
    ("10:30", "12:00"),
    ("12:00", "14:00"),
    ("14:00", "15:00"),
    ("15:00", "16:00"),
]

# ─── Output ─────────────────────────────────────────────────────────────────
RESULTS_DIR = "results"

"""
SPX Configuration Overlay
=========================
Imports everything from config.py, then overrides for SPX index options.
Signal generation still uses SPY intraday (the underlying we trade against VWAP),
but options are pulled from SPX/SPXW chains instead of SPY.

Key differences:
  - SPX = 10x SPY notional (~5500 vs ~550)
  - 0DTE options use underlying "SPX" on Polygon (weeklies filed as SPXW)
  - Much higher absolute premiums -> far more trades pass fill-realism filter
  - Cash-settled, European exercise, Section 1256 tax treatment
"""

from config import *  # noqa: F401,F403

# Override: options underlying ticker
# Polygon files SPX weeklies (including 0DTE) under "SPX" underlying
# The actual option tickers look like O:SPX250107P05900000 or O:SPXW250107P05900000
# We try "SPX" first; if no contracts, fall back to "SPXW"
OPTIONS_UNDERLYING = "SPX"
OPTIONS_UNDERLYING_FALLBACK = "SPXW"

# SPX spot price is ~10x SPY, so delta-to-strike distance scales accordingly
# The estimate_delta_from_strike function uses % distance, so it's scale-invariant
# But we still need to know this is index options (cash settled)
IS_INDEX_OPTIONS = True

# Results go to a separate directory
RESULTS_DIR = "results_spx"

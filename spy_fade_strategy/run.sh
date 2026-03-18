#!/bin/bash
# SPY VWAP Fade Strategy Backtester
# ==================================
# Run from this directory: ./run.sh
#
# Options:
#   --stock-only       Skip options backtest (much faster)
#   --atr-mult 1.0     Test a single ATR multiplier
#   --start 2023-01-01 Custom start date
#   --end 2026-03-12   Custom end date

set -e

echo "Installing dependencies..."
pip install -r requirements.txt -q

echo ""
echo "Starting backtest..."
python3 main.py "$@"

#!/usr/bin/env python3
"""
Embed trade data into dashboard.html.
Works with both SPY (trades_data.json) and SPX (trades_data_spx.json).

Usage:
    python embed_dashboard.py                   # default: trades_data.json
    python embed_dashboard.py trades_data_spx.json   # use SPX data
"""

import json
import re
import sys
import os

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    trades_file = sys.argv[1] if len(sys.argv) > 1 else "trades_data.json"
    trades_path = os.path.join(base_dir, trades_file)
    dashboard_path = os.path.join(base_dir, "dashboard.html")

    if not os.path.exists(trades_path):
        print(f"ERROR: {trades_path} not found. Run the backtest first.")
        sys.exit(1)

    with open(trades_path) as f:
        data = json.load(f)
    minified = json.dumps(data, separators=(",", ":"))

    with open(dashboard_path) as f:
        html = f.read()

    # Replace embedded data (handles both fresh and previously embedded)
    if "const EMBEDDED_TRADES =" in html:
        html = re.sub(
            r"const EMBEDDED_TRADES\s*=\s*\[.*?\];",
            "const EMBEDDED_TRADES = " + minified + ";",
            html,
            flags=re.DOTALL,
        )
    else:
        html = html.replace(
            "REPLACE_EMBEDDED_DATA_HERE",
            "const EMBEDDED_TRADES = " + minified + ";",
        )

    # Update title based on data source
    if "spx" in trades_file.lower():
        html = html.replace("SPY VWAP Fade", "SPX VWAP Fade")
    else:
        html = html.replace("SPX VWAP Fade", "SPY VWAP Fade")

    with open(dashboard_path, "w") as f:
        f.write(html)

    print(f"Embedded {len(data)} trades from {trades_file}")
    print(f"Dashboard: {dashboard_path}")
    print(f"HTML size: {len(html):,} bytes")


if __name__ == "__main__":
    main()

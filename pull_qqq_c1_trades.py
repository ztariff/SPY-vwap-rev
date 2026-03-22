"""Pull trades from 43 KITE QQQ C1 backtest submissions and combine into one CSV."""
import json
import subprocess
import time
import sys

JSON_FILE = r"C:\Users\n7add\SPX-Intra-Rev\clean_submission_hashes.json"
OUTFILE = r"C:\Users\n7add\SPX-Intra-Rev\kite_qqq_c1_trades.csv"

with open(JSON_FILE) as f:
    data = json.load(f)

hashes = data["qqq_c1"]
total = len(hashes)
print(f"Found {total} hashes to process")

header_written = False
total_trades = 0

with open(OUTFILE, "w", newline="") as outf:
    for i, h in enumerate(hashes):
        count = i + 1
        print(f"[{count}/{total}] Fetching trades for hash: {h}")

        try:
            result = subprocess.run(
                ["kti", "backtest", "trades", h],
                capture_output=True,
                text=True,
                timeout=30
            )
            # Try stdout first, fall back to stderr
            output = result.stdout.strip()
            if not output:
                output = result.stderr.strip()

            if not output:
                print(f"  -> No data returned, skipping")
                if count < total:
                    time.sleep(2.5)
                continue

            lines = output.split("\n")

            if len(lines) <= 1:
                print(f"  -> No trades (header only), skipping")
                if count < total:
                    time.sleep(2.5)
                continue

            trade_count = len(lines) - 1
            total_trades += trade_count

            if not header_written:
                outf.write(output + "\n")
                header_written = True
            else:
                # Skip header line
                data_lines = "\n".join(lines[1:])
                outf.write(data_lines + "\n")

            print(f"  -> {trade_count} trades")

        except subprocess.TimeoutExpired:
            print(f"  -> Timeout, skipping")
        except Exception as e:
            print(f"  -> Error: {e}, skipping")

        if count < total:
            time.sleep(2.5)

print(f"\nDone! Total trades: {total_trades}")
print(f"Output file: {OUTFILE}")

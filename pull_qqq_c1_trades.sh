#!/bin/bash
# Pull trades from 43 KITE QQQ C1 backtest submissions and combine into one CSV

OUTFILE="C:/Users/n7add/SPX-Intra-Rev/kite_qqq_c1_trades.csv"
JSON_FILE="C:/Users/n7add/SPX-Intra-Rev/clean_submission_hashes.json"
TMPFILE="/tmp/kti_trades_tmp.csv"

# Extract hashes using python
mapfile -t HASHES < <(python -c "
import json
with open('$JSON_FILE') as f:
    data = json.load(f)
for h in data['qqq_c1']:
    print(h)
")

HEADER_WRITTEN=0
TOTAL_TRADES=0
TOTAL=${#HASHES[@]}

# Clear output file
> "$OUTFILE"

for i in "${!HASHES[@]}"; do
    HASH="${HASHES[$i]}"
    COUNT=$((i + 1))
    echo "[$COUNT/$TOTAL] Fetching trades for hash: $HASH"

    # Fetch trades to temp file
    kti backtest trades "$HASH" > "$TMPFILE" 2>/dev/null

    # Check if file has content
    if [ ! -s "$TMPFILE" ]; then
        echo "  -> No data returned, skipping"
        if [ $COUNT -lt $TOTAL ]; then
            sleep 2.5
        fi
        continue
    fi

    # Count lines (excluding header)
    LINE_COUNT=$(wc -l < "$TMPFILE" | tr -d ' ')

    if [ "$LINE_COUNT" -le 1 ]; then
        echo "  -> No trades (header only), skipping"
        if [ $COUNT -lt $TOTAL ]; then
            sleep 2.5
        fi
        continue
    fi

    TRADE_COUNT=$((LINE_COUNT - 1))
    TOTAL_TRADES=$((TOTAL_TRADES + TRADE_COUNT))

    if [ $HEADER_WRITTEN -eq 0 ]; then
        # Write header + data
        cat "$TMPFILE" >> "$OUTFILE"
        HEADER_WRITTEN=1
    else
        # Skip header, write data only
        tail -n +2 "$TMPFILE" >> "$OUTFILE"
    fi

    echo "  -> $TRADE_COUNT trades"

    # Rate limit (skip delay after last hash)
    if [ $COUNT -lt $TOTAL ]; then
        sleep 2.5
    fi
done

rm -f "$TMPFILE"

echo ""
echo "Done! Total trades: $TOTAL_TRADES"
echo "Output file: $OUTFILE"

#!/bin/bash
# Download KITE minute bars for SPY, month by month, 6 parallel workers
# Total: 51 months (Jan 2022 - Mar 2026)

export KITE_TOKEN="23684e7f-34a0-44ba-8d88-3ab9626f8fe9"
OUTDIR="C:/Users/n7add/SPX-Intra-Rev/kite_data/minutes"
mkdir -p "$OUTDIR"

MAX_JOBS=6
RUNNING=0

download_month() {
    local START=$1
    local END=$2
    local LABEL=$3
    local OUTFILE="${OUTDIR}/spy_${LABEL}.csv"

    if [ -f "$OUTFILE" ] && [ $(wc -l < "$OUTFILE") -gt 100 ]; then
        echo "SKIP $LABEL (already exists with $(wc -l < "$OUTFILE") lines)"
        return
    fi

    echo "START $LABEL ($START to $END)..."
    kti liberator query --dataset minute_bars --start-date "$START" --end-date "$END" --symbols SPY --format csv > "$OUTFILE" 2>/dev/null
    LINES=$(wc -l < "$OUTFILE")
    if [ "$LINES" -lt 100 ]; then
        echo "FAIL $LABEL - only $LINES lines, retrying..."
        rm -f "$OUTFILE"
        kti liberator query --dataset minute_bars --start-date "$START" --end-date "$END" --symbols SPY --format csv > "$OUTFILE" 2>/dev/null
        LINES=$(wc -l < "$OUTFILE")
    fi
    echo "DONE $LABEL -> $LINES lines"
}

# Generate all month ranges
MONTHS=()
for YEAR in 2022 2023 2024 2025; do
    for MONTH in 01 02 03 04 05 06 07 08 09 10 11 12; do
        START="${YEAR}-${MONTH}-01"
        if [ "$MONTH" = "12" ]; then
            END="$((YEAR+1))-01-01"
        else
            NEXT_MONTH=$(printf "%02d" $((10#$MONTH + 1)))
            END="${YEAR}-${NEXT_MONTH}-01"
        fi
        MONTHS+=("${START}|${END}|${YEAR}_${MONTH}")
    done
done
# Add 2026 Jan-Mar
MONTHS+=("2026-01-01|2026-02-01|2026_01")
MONTHS+=("2026-02-01|2026-03-01|2026_02")
MONTHS+=("2026-03-01|2026-03-13|2026_03")

echo "Total months to download: ${#MONTHS[@]}"
echo "Using $MAX_JOBS parallel workers"
echo ""

for ENTRY in "${MONTHS[@]}"; do
    IFS='|' read -r START END LABEL <<< "$ENTRY"
    download_month "$START" "$END" "$LABEL" &
    RUNNING=$((RUNNING + 1))

    if [ "$RUNNING" -ge "$MAX_JOBS" ]; then
        wait -n
        RUNNING=$((RUNNING - 1))
    fi
done

wait
echo ""
echo "All downloads complete!"
echo "Files in $OUTDIR:"
ls -la "$OUTDIR"/*.csv | wc -l
echo "Total lines:"
wc -l "$OUTDIR"/*.csv | tail -1

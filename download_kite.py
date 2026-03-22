"""Download KITE minute bars for SPY, month by month, saving to CSV."""
import subprocess
import os
import time

OUTDIR = "C:/Users/n7add/SPX-Intra-Rev/kite_data/minutes"
os.makedirs(OUTDIR, exist_ok=True)

TOKEN = "23684e7f-34a0-44ba-8d88-3ab9626f8fe9"

months = []
for year in range(2022, 2026):
    for month in range(1, 13):
        start = f"{year}-{month:02d}-01"
        if month == 12:
            end = f"{year+1}-01-01"
        else:
            end = f"{year}-{month+1:02d}-01"
        label = f"{year}_{month:02d}"
        months.append((start, end, label))

# 2026 partial
months.append(("2026-01-01", "2026-02-01", "2026_01"))
months.append(("2026-02-01", "2026-03-01", "2026_02"))
months.append(("2026-03-01", "2026-03-13", "2026_03"))

good = 0
failed = []

for start, end, label in months:
    outfile = os.path.join(OUTDIR, f"spy_{label}.csv")

    # Skip if already downloaded
    if os.path.exists(outfile):
        with open(outfile) as f:
            lines = sum(1 for _ in f)
        if lines > 100:
            print(f"SKIP {label} ({lines} lines)")
            good += 1
            continue

    print(f"Downloading {label}...", end=" ", flush=True)

    env = os.environ.copy()
    env["KITE_TOKEN"] = TOKEN

    for attempt in range(3):
        try:
            result = subprocess.run(
                ["kti", "liberator", "query",
                 "--dataset", "minute_bars",
                 "--start-date", start,
                 "--end-date", end,
                 "--symbols", "SPY",
                 "--format", "csv",
                 "--limit", "500000",
                 "--no-cache",
                 "--wait"],
                capture_output=True, text=True, env=env, timeout=300
            )

            with open(outfile, "w") as f:
                f.write(result.stdout)

            lines = result.stdout.count("\n")
            if lines > 100:
                print(f"{lines} lines")
                good += 1
                break
            else:
                print(f"attempt {attempt+1} got {lines} lines", end=" ", flush=True)
                time.sleep(5)
        except subprocess.TimeoutExpired:
            print(f"timeout attempt {attempt+1}", end=" ", flush=True)
            time.sleep(5)
    else:
        print("FAILED after 3 attempts")
        failed.append(label)

    time.sleep(1)

print(f"\nDone: {good}/{len(months)} months OK")
if failed:
    print(f"Failed: {failed}")

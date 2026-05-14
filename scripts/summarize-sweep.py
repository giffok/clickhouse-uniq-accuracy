"""Summarise precision-sweep.csv: stderr, mean, median time per (N, p)."""
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

CSV = Path(r"C:\Users\admin\YandexDisk\проекты\clickhouse-uniq-accuracy\results\precision-sweep.csv")

groups = defaultdict(list)
times = defaultdict(list)

for r in csv.DictReader(CSV.open(encoding="utf-8")):
    n = int(r["n"])
    p = int(r["precision"])
    if int(r["salt"]) == 0:
        continue  # baseline single-shot, skip from distribution
    groups[(n, p)].append(float(r["rel_error"]))
    times[(n, p)].append(float(r["server_elapsed_s"]))

# baseline: uniq stderr from main run
UNIQ_STD = {
    10**6: 0.346, 10**8: 0.441, 10**10: 0.512,  # %
}

print("| N      | p  | m  | mean       | stderr   | min        | max        | median_t  |")
print("|--------|----|----|------------|----------|------------|------------|-----------|")
Ns = sorted({n for n, _ in groups})
for n in Ns:
    ps = sorted({p for nn, p in groups if nn == n})
    for p in ps:
        xs = groups[(n, p)]
        ts = times[(n, p)]
        if not xs:
            continue
        mean = statistics.fmean(xs) * 100
        std = statistics.pstdev(xs) * 100 if len(xs) > 1 else float("nan")
        mn = min(xs) * 100
        mx = max(xs) * 100
        med_t = statistics.median(ts)
        marker = ""
        if n in UNIQ_STD and not math.isnan(std):
            ratio = std / UNIQ_STD[n]
            marker = f"  ratio_vs_uniq={ratio:.2f}"
        print(f"| 10^{int(math.log10(n))} | {p} | {len(xs):>2} | "
              f"{mean:+8.4f}% | {std:6.4f}% | {mn:+8.4f}% | {mx:+8.4f}% | "
              f"{med_t:>7.2f}s |{marker}")

print(f"\n(uniq() stderr baseline from main run: "
      f"10^6={UNIQ_STD[10**6]}%, 10^8={UNIQ_STD[10**8]}%, 10^10={UNIQ_STD[10**10]}%)")

# Theoretical stderr table
print("\nTheoretical stderr by precision:")
print("  p    1.04/sqrt(2^p)")
for p in range(12, 21):
    th = 1.04 / math.sqrt(2**p) * 100
    print(f"  {p}   {th:.4f}%")

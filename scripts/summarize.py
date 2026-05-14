"""Summarise raw.csv into per-(estimator, N) distribution stats.

Prints two TSV blocks ready to paste into HTML:
  - distribution table for each estimator (uniq, uniqCombined64)
  - the "what happens on 10^11" comparison

Designed to run on a partial CSV — skips groups that are still in progress
or have FAIL rows.
"""
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

CSV = Path(r"C:\Users\admin\YandexDisk\проекты\clickhouse-uniq-accuracy\results\raw.csv")


def q(xs_sorted, p):
    if not xs_sorted:
        return None
    k = p * (len(xs_sorted) - 1)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return xs_sorted[lo]
    return xs_sorted[lo] * (hi - k) + xs_sorted[hi] * (k - lo)


def main():
    by_group = defaultdict(list)  # (experiment, n, estimator) -> [rel_err]
    one_shots = {}                # (experiment, n, estimator) -> dict of one row
    for row in csv.DictReader(CSV.open(encoding="utf-8")):
        exp = row["experiment"]
        n = int(row["n"])
        est = row["estimator"]
        if row["result"] == "FAIL":
            one_shots[(exp, n, est)] = {"status": "FAIL", **row}
            continue
        rel = float(row["rel_error"]) if row["rel_error"] else None
        if exp.startswith("A_"):
            one_shots[(exp, n, est)] = {
                "status": "OK", "result": int(row["result"]),
                "rel": rel, "elapsed": float(row["server_elapsed_s"]),
                "wall": float(row["wall_s"]),
            }
        else:
            if rel is not None:
                by_group[(exp, n, est)].append(rel)

    Ns = [10**5, 10**6, 10**7, 10**8, 10**9, 10**10, 10**11]
    OVERFLOW = 10.0  # |rel| > 10 means overflow

    print("=== Distribution rows (B_salted) ===")
    for est in ("uniq", "uniqCombined64"):
        print(f"\n-- {est} --")
        for n in Ns:
            xs = by_group.get(("B_salted", n, est), [])
            if not xs:
                print(f"  N={n}: no data")
                continue
            sane = sorted(r for r in xs if abs(r) <= OVERFLOW)
            ovf = len(xs) - len(sane)
            if sane:
                mean = statistics.fmean(sane)
                std = statistics.pstdev(sane)
                mn, mx = sane[0], sane[-1]
                p5, p50, p95 = q(sane, .05), q(sane, .50), q(sane, .95)
                print(f"  N=10^{int(math.log10(n))}  m={len(xs)}  "
                      f"mean={mean*100:+.4f}%  std={std*100:.4f}%  "
                      f"min={mn*100:+.4f}%  p5={p5*100:+.4f}%  "
                      f"p50={p50*100:+.4f}%  p95={p95*100:+.4f}%  "
                      f"max={mx*100:+.4f}%  overflow={ovf}")
            else:
                print(f"  N=10^{int(math.log10(n))}  m={len(xs)}  ALL OVERFLOW  ovf={ovf}")

    print("\n=== Slice A_unsalted (one-shot) ===")
    for n in Ns:
        print(f"\n-- N=10^{int(math.log10(n))} --")
        for est in ("uniq", "uniqCombined64"):
            o = one_shots.get(("A_unsalted", n, est))
            if o is None:
                print(f"  {est}: no data")
                continue
            if o.get("status") == "FAIL":
                print(f"  {est}: FAIL")
                continue
            print(f"  {est}: result={o['result']}  rel={o['rel']*100:+.4f}%  "
                  f"server={o['elapsed']:.2f}s  wall={o['wall']:.2f}s")

    print("\n=== Slice A_exact (uniqExact) ===")
    for n in Ns:
        o = one_shots.get(("A_exact", n, "uniqExact"))
        if o is None:
            print(f"  N=10^{int(math.log10(n))}: no data")
            continue
        if o.get("status") == "FAIL":
            print(f"  N=10^{int(math.log10(n))}: FAIL wall={o.get('wall_s','?')}")
            continue
        print(f"  N=10^{int(math.log10(n))}: result={o['result']}  "
              f"server={o['elapsed']:.2f}s")


if __name__ == "__main__":
    main()

"""Precision sweep for uniqCombined64(p).

Find at which HLL precision p the estimator is equivalent to uniq() in
accuracy and speed. Theoretical stderr of uniqCombined64(p) is
1.04/sqrt(2^p); uniq() is K-min-values with K=65536 giving 1/256 ≈ 0.391%.
Equivalence is expected near p ≈ 16.

For each (N, p): m queries with cityHash64(number, salt) to derive distribution.
Plus one unsalted run for time baseline.

Output: results/precision-sweep.csv
"""
import csv
import math
import statistics
import sys
import time
from pathlib import Path

from clickhouse_driver import Client

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
CA_PATH = PROJECT_ROOT / "YandexInternalRootCA.crt"
OUT_PATH = PROJECT_ROOT / "results" / "precision-sweep.csv"
ENV_PATH = Path(r"C:\Users\admin\YandexDisk\infra\.env")

PRECISIONS = [12, 13, 14, 15, 16, 17, 18, 19, 20]

PLAN = [
    # (N, m) — keep total time reasonable
    (10**6,  30),
    (10**8,  20),
    (10**10, 5),
]


def load_env():
    creds = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("CH_EXPERIMENT_"):
            k, _, v = line.partition("=")
            creds[k.strip()] = v.strip().strip('"')
    return creds


def make_client(env):
    return Client(
        host=env["CH_EXPERIMENT_HOST"], port=9440,
        user=env["CH_EXPERIMENT_USER"], password=env["CH_EXPERIMENT_PASSWORD"],
        database="experiment", secure=True, ca_certs=str(CA_PATH), verify=True,
        connect_timeout=60, send_receive_timeout=3600,
    )


def connect_retry(env, attempts=8):
    last = None
    for i in range(1, attempts + 1):
        try:
            c = make_client(env)
            c.execute("SELECT 1")
            return c
        except Exception as e:
            last = e
            print(f"  connect attempt {i} failed; sleeping 15s", flush=True)
            time.sleep(15)
    raise last


def exec_retry(client_box, env, q, max_attempts=4):
    last = None
    for i in range(1, max_attempts + 1):
        try:
            rows = client_box[0].execute(q)
            return rows, client_box[0].last_query
        except Exception as e:
            last = e
            print(f"    attempt {i} failed ({type(e).__name__}); reconnecting",
                  flush=True)
            try:
                client_box[0].disconnect()
            except Exception:
                pass
            time.sleep(min(60, 10 * i))
            try:
                client_box[0] = connect_retry(env, attempts=4)
            except Exception as e2:
                last = e2
    raise last


def main():
    env = load_env()
    client = connect_retry(env)
    client_box = [client]

    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n", "precision", "salt", "estimator",
                    "result", "abs_error", "rel_error",
                    "server_elapsed_s", "wall_s"])

        for n, m in PLAN:
            for p in PRECISIONS:
                print(f"=== N={n} precision={p} m={m} ===", flush=True)
                # unsalted baseline (salt=0)
                q = f"SELECT uniqCombined64({p})(number) FROM numbers_mt({n})"
                t0 = time.monotonic()
                try:
                    rows, last = exec_retry(client_box, env, q)
                except Exception as e:
                    print(f"  unsalted FAIL: {e}", flush=True)
                    continue
                wall = round(time.monotonic() - t0, 3)
                v = int(rows[0][0])
                rel = (v - n) / n
                elapsed = round(last.elapsed or 0.0, 3)
                print(f"  unsalted: rel={rel*100:+.5f}% server={elapsed}s wall={wall}s",
                      flush=True)
                w.writerow([n, p, 0, f"uniqCombined64({p})", v, v - n,
                            f"{rel:.6e}", elapsed, wall])
                f.flush()

                # salted distribution
                for salt in range(1, m + 1):
                    q = (f"SELECT uniqCombined64({p})(cityHash64(number, {salt})) "
                         f"FROM numbers_mt({n})")
                    t0 = time.monotonic()
                    try:
                        rows, last = exec_retry(client_box, env, q)
                    except Exception as e:
                        print(f"  salt {salt} FAIL: {e}", flush=True)
                        continue
                    wall = round(time.monotonic() - t0, 3)
                    v = int(rows[0][0])
                    rel = (v - n) / n
                    elapsed = round(last.elapsed or 0.0, 3)
                    w.writerow([n, p, salt, f"uniqCombined64({p})", v, v - n,
                                f"{rel:.6e}", elapsed, wall])
                    f.flush()

    try:
        client_box[0].disconnect()
    except Exception:
        pass
    print(f"\nDone. {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()

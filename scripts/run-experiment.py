"""Reproducible end-to-end experiment.

Three slices:
  A_unsalted — one-shot per (N, estimator) for uniq and uniqCombined64.
               This is the headline table: side-by-side timing and accuracy.
  A_exact    — uniqExact baseline up to where it OOMs on the 8 GB host.
  B_salted   — uniq(cityHash64(number,salt)) and uniqCombined64(...same...)
               for N=10^5..10^11 with m(N,estimator) per the plan below.
               m>1 lets us derive mean/std/quantiles of the rel_error
               distribution.

All rows streamed to results/raw.csv with columns:
    experiment, n, salt, estimator, result, abs_error, rel_error,
    server_elapsed_s, wall_s, attempts

Truth = N (numbers_mt generates exactly N distinct values 0..N-1).
"""

import csv
import sys
import time
from pathlib import Path

from clickhouse_driver import Client

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
CA_PATH = PROJECT_ROOT / "YandexInternalRootCA.crt"
OUT_PATH = PROJECT_ROOT / "results" / "raw.csv"
ENV_PATH = Path(r"C:\Users\admin\YandexDisk\infra\.env")

NS = [10**5, 10**6, 10**7, 10**8, 10**9, 10**10, 10**11]

# m(N) per estimator for slice B
M_PLAN = {
    "uniq": {
        10**5: 100, 10**6: 100, 10**7: 100, 10**8: 100,
        10**9: 100, 10**10: 30, 10**11: 5,
    },
    "uniqCombined64": {
        10**5: 100, 10**6: 100, 10**7: 100, 10**8: 100,
        10**9: 30, 10**10: 10, 10**11: 5,
    },
}

# uniqExact memory grows linearly with N (~8 bytes/value + hash table overhead);
# on an 8 GB host we expect OOM around 10^9. Probe up to 10^9 anyway to record the
# crash boundary.
UNIQEXACT_NS = [10**5, 10**6, 10**7, 10**8, 10**9]


def load_env() -> dict:
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


def connect_with_retry(env, max_attempts=8):
    last = None
    for i in range(1, max_attempts + 1):
        try:
            c = make_client(env)
            c.execute("SELECT 1")
            return c
        except Exception as e:
            last = e
            wait = min(60, 10 + 5 * i)
            print(f"  connect attempt {i} failed ({type(e).__name__}); sleeping {wait}s",
                  flush=True)
            time.sleep(wait)
    raise last


def run_query(client_box, env, query, max_attempts=4):
    """Returns (rows, last_query, attempts)."""
    last = None
    for i in range(1, max_attempts + 1):
        try:
            rows = client_box[0].execute(query)
            return rows, client_box[0].last_query, i
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
                client_box[0] = connect_with_retry(env, max_attempts=4)
            except Exception as e2:
                last = e2
    raise last


def main():
    env = load_env()
    print(f"Cluster host: {env['CH_EXPERIMENT_HOST']}", flush=True)
    print(f"Output:       {OUT_PATH}", flush=True)
    client = connect_with_retry(env)
    client_box = [client]

    server_version = client.execute("SELECT version()")[0][0]
    print(f"CH version:   {server_version}", flush=True)

    fields = ["experiment", "n", "salt", "estimator", "result",
              "abs_error", "rel_error", "server_elapsed_s", "wall_s", "attempts"]

    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()

        def emit(experiment, n, salt, estimator, query):
            t0 = time.monotonic()
            try:
                rows, last, attempts = run_query(client_box, env, query)
            except Exception as e:
                wall = round(time.monotonic() - t0, 3)
                print(f"  [{experiment}/{estimator}] N={n} salt={salt} "
                      f"GAVE UP after {wall}s: {type(e).__name__}: {e}",
                      flush=True)
                w.writerow({
                    "experiment": experiment, "n": n, "salt": salt,
                    "estimator": estimator, "result": "FAIL",
                    "abs_error": "", "rel_error": "",
                    "server_elapsed_s": "", "wall_s": wall,
                    "attempts": "",
                })
                f.flush()
                return
            wall = round(time.monotonic() - t0, 3)
            r = int(rows[0][0])
            abs_err = r - n
            rel_err = abs_err / n
            elapsed = round(last.elapsed or 0.0, 3)
            print(f"  [{experiment}/{estimator}] N={n:>13d} salt={salt:>4} "
                  f"result={r:>21d}  rel_err={rel_err:+.6e}  "
                  f"server={elapsed}s  wall={wall}s",
                  flush=True)
            w.writerow({
                "experiment": experiment, "n": n, "salt": salt,
                "estimator": estimator, "result": r,
                "abs_error": abs_err, "rel_error": f"{rel_err:.6e}",
                "server_elapsed_s": elapsed, "wall_s": wall,
                "attempts": attempts,
            })
            f.flush()

        # ====== Slice A_unsalted: one-shot per (N, estimator) ======
        print("\n=== Slice A_unsalted — uniq + uniqCombined64 across N ===",
              flush=True)
        for n in NS:
            emit("A_unsalted", n, 0, "uniq",
                 f"SELECT uniq(number) FROM numbers_mt({n})")
            emit("A_unsalted", n, 0, "uniqCombined64",
                 f"SELECT uniqCombined64(number) FROM numbers_mt({n})")

        # ====== Slice A_exact: uniqExact baseline (OOM-probe) ======
        print("\n=== Slice A_exact — uniqExact (OOM-probe up to 10^9) ===",
              flush=True)
        for n in UNIQEXACT_NS:
            emit("A_exact", n, 0, "uniqExact",
                 f"SELECT uniqExact(number) FROM numbers_mt({n})")

        # ====== Slice B: salted distribution ======
        print("\n=== Slice B — salted distribution ===", flush=True)
        for estimator, plan in M_PLAN.items():
            for n in NS:
                m = plan[n]
                for salt in range(1, m + 1):
                    q = (f"SELECT {estimator}(cityHash64(number, {salt})) "
                         f"FROM numbers_mt({n})")
                    emit("B_salted", n, salt, estimator, q)

    try:
        client_box[0].disconnect()
    except Exception:
        pass
    print(f"\nDone. raw.csv: {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()

"""Debug: parallel small queries to characterise hangs.

Run N concurrent SELECT 1 against CH, record per-request:
  req_id, started_at, ended_at, duration_s, status, connect_ms, error_class

Hypothesis under test:
  H1 — pool/keepalive issue (each request opens fresh conn here, so should pass)
  H2 — server-side concurrency limit (would manifest as some requests hanging
       while others succeed)
  H3 — TLS handshake / SNI / cert validation flakiness
  H4 — DNS round-robin returning a stale IP
  H5 — public-IP balancer instability

Writes results/debug-parallel.csv.
"""

import base64
import concurrent.futures
import csv
import http.client
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
CA_PATH = PROJECT_ROOT / "YandexInternalRootCA.crt"
OUT_PATH = PROJECT_ROOT / "results" / "debug-parallel.csv"
ENV_PATH = Path(r"C:\Users\admin\YandexDisk\infra\.env")

N_CONCURRENT = 20
TIMEOUT = 25


def load_env() -> dict:
    creds = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("CH_EXPERIMENT_"):
            k, _, v = line.partition("=")
            creds[k.strip()] = v.strip().strip('"')
    return creds


def run_one(req_id: int, host: str, auth: str, ctx) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    connect_ms = None
    status = None
    error = ""
    error_class = ""
    resolved_ip = ""
    try:
        # DNS resolve
        infos = socket.getaddrinfo(host, 8443, proto=socket.IPPROTO_TCP)
        if infos:
            resolved_ip = infos[0][4][0]

        conn = http.client.HTTPSConnection(host, 8443, context=ctx, timeout=TIMEOUT)
        tc = time.monotonic()
        conn.connect()
        connect_ms = round((time.monotonic() - tc) * 1000, 1)

        conn.request(
            "POST",
            "/?database=experiment",
            body="SELECT 1 AS x FORMAT JSON".encode("utf-8"),
            headers={
                "Authorization": auth,
                "Content-Type": "text/plain; charset=utf-8",
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        conn.close()
        if status != 200:
            error = f"HTTP {status}: {body[:120]!r}"
            error_class = f"http_{status}"
    except Exception as e:
        error = str(e)[:200]
        error_class = type(e).__name__

    duration = round(time.monotonic() - t0, 3)
    ended = datetime.now(timezone.utc).isoformat()
    return {
        "req_id": req_id,
        "started_at": started,
        "ended_at": ended,
        "duration_s": duration,
        "connect_ms": connect_ms if connect_ms is not None else "",
        "status": status if status is not None else "",
        "resolved_ip": resolved_ip,
        "error_class": error_class,
        "error": error,
    }


def main() -> int:
    env = load_env()
    host = env["CH_EXPERIMENT_HOST"]
    user = env["CH_EXPERIMENT_USER"]
    password = env["CH_EXPERIMENT_PASSWORD"]
    auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    ctx = ssl.create_default_context(cafile=str(CA_PATH))

    print(f"Firing {N_CONCURRENT} concurrent requests to {host}", flush=True)
    t_start = time.monotonic()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=N_CONCURRENT) as pool:
        futures = {pool.submit(run_one, i, host, auth, ctx): i for i in range(N_CONCURRENT)}
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            ok = "OK" if r["status"] == 200 else "FAIL"
            print(f"  [{r['req_id']:>2}] {ok} dur={r['duration_s']}s "
                  f"connect_ms={r['connect_ms']} ip={r['resolved_ip']} "
                  f"err={r['error_class']}",
                  flush=True)
            results.append(r)

    elapsed = round(time.monotonic() - t_start, 3)
    print(f"\nTotal wall: {elapsed}s", flush=True)

    fields = ["req_id", "started_at", "ended_at", "duration_s", "connect_ms",
              "status", "resolved_ip", "error_class", "error"]
    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(results, key=lambda r: r["req_id"]))

    ok_count = sum(1 for r in results if r["status"] == 200)
    fail_count = N_CONCURRENT - ok_count
    durations = [r["duration_s"] for r in results if r["status"] == 200]
    print(f"\nSummary: {ok_count} OK, {fail_count} FAIL", flush=True)
    if durations:
        durations.sort()
        print(f"OK durations: min={durations[0]} med={durations[len(durations)//2]} "
              f"max={durations[-1]}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Forward camera sightings (JSON lines on stdin) to the dashboard's ingest endpoint.

    python3 -B -m perception.live_camera --sector G --duration-s 1800 \\
      | python3 -B -m core.camera_bridge --post http://localhost:8000/observations

Each stdin line is one observation, as printed by perception/live_camera.py
(see perception/SIGHTING_FORMAT.md). The bridge POSTs it unchanged and prints
the server's answer to stderr. It never edits, merges or invents fields.
Lines that are not JSON objects are skipped with a warning.

If the dashboard is unreachable, a line is retried until ``--retry-s`` has
passed, then reported as NOT DELIVERED. The camera also appends every line to
sightings.jsonl in its evidence dir, so nothing is lost.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

EXIT_OK, EXIT_UNDELIVERED = 0, 4


def post_json(url: str, obj: dict, timeout: float = 5.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(obj).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:   # 4xx/5xx: the server answered
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        return e.code, body


def forward(lines, url: str, *, retry_s: float = 30.0, sleep=time.sleep, post=post_json,
            log=lambda m: print(m, file=sys.stderr, flush=True)) -> dict:
    stats = {"sent": 0, "new": 0, "duplicate": 0, "rejected": 0, "skipped": 0, "undelivered": 0}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError("not a JSON object")
        except ValueError as e:
            stats["skipped"] += 1
            log(f"bridge: skipped non-observation line ({e}): {line[:80]}")
            continue
        deadline, wait = time.monotonic() + retry_s, 0.5
        while True:
            try:
                status, body = post(url, obj)
                break
            except (urllib.error.URLError, OSError) as e:
                if time.monotonic() >= deadline:
                    status, body = None, {"error": str(e)}
                    break
                log(f"bridge: dashboard unreachable ({e}); retrying {obj.get('obs_id')}")
                sleep(wait)
                wait = min(wait * 2, 5.0)
        oid = obj.get("obs_id")
        if status is None:
            stats["undelivered"] += 1
            log(f"bridge: NOT DELIVERED {oid}: {body['error']} (still in sightings.jsonl)")
            continue
        stats["sent"] += 1
        if status == 200 and body.get("duplicate"):
            stats["duplicate"] += 1
            log(f"bridge: duplicate {oid} (of {body.get('duplicate_of', oid)}); no new alert")
        elif status == 200:
            stats["new"] += 1
            log(f"bridge: delivered {oid} -> track {body.get('track_id')} (UNCONFIRMED)")
        else:
            stats["rejected"] += 1
            log(f"bridge: dashboard rejected {oid}: HTTP {status} {body.get('detail', body)}")
    return stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Forward camera sightings to POST /observations")
    p.add_argument("--post", default="http://localhost:8000/observations",
                   help="ingest URL (default http://localhost:8000/observations)")
    p.add_argument("--retry-s", type=float, default=30.0,
                   help="how long to keep retrying one line while the dashboard is down")
    a = p.parse_args(argv)
    print(f"bridge: forwarding stdin to {a.post}", file=sys.stderr, flush=True)
    stats = forward(iter(sys.stdin.readline, ""), a.post, retry_s=a.retry_s)
    print("bridge: done " + json.dumps(stats), file=sys.stderr, flush=True)
    return EXIT_UNDELIVERED if stats["undelivered"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

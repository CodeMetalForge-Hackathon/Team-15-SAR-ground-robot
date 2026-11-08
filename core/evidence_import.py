"""Import an existing live-camera sighting into the dashboard, with run context.

    python3 -B -m core.evidence_import \\
        --run-dir ~/Team15_evidence/camera_live_test/empty-20261108T020800 \\
        --obs-id D1-b1794121685-000001 \\
        --classification LIVE_HARDWARE_PERSON_PRESENT \\
        --consent-stated-by "Team-15 operator" --consent-stated-at 2026-11-08 \\
        --post http://127.0.0.1:8792

Steps, all of which must pass before anything is sent:
1. read the sighting line for ``--obs-id`` from the run's ``sightings.jsonl``;
2. check the evidence PNG and annotated JPEG exist, and that the PNG's SHA-256
   equals the sighting's ``evidence.frame_sha256``;
3. derive the run numbers from the run's own files (``*_summary.json``,
   ``*_frames.jsonl``, ``run_report.json``), recording each file's SHA-256;
4. write ``run_annotation.json`` once (never overwritten; an identical one is
   reused);
5. POST the annotation to ``/run_annotations`` and the sighting line, unchanged,
   to ``/observations`` through ``core.camera_bridge.post_json``. Re-importing
   is safe: the dashboard reports the sighting as a duplicate.

No image is copied, re-encoded or uploaded anywhere: the dashboard serves the
files in place from its configured evidence directory (localhost only).
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import statistics
import sys
import time
from typing import Optional, Sequence

from contracts import run_annotation as ra
from core.camera_bridge import post_json


class ImportRefused(RuntimeError):
    pass


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_sighting(run_dir: str, obs_id: str) -> tuple[str, dict]:
    path = os.path.join(run_dir, "sightings.jsonl")
    if not os.path.isfile(path):
        raise ImportRefused(f"no sightings.jsonl in {run_dir}")
    for line in open(path, encoding="utf-8"):
        if line.strip() and json.loads(line).get("obs_id") == obs_id:
            return line.rstrip("\n"), json.loads(line)
    raise ImportRefused(f"{obs_id} is not in {path}")


def verify_evidence(s: dict, run_dir: str) -> dict:
    ev = s.get("evidence") or {}
    root = os.path.realpath(run_dir)
    out = {}
    for key in ("frame_ref", "annotated_ref"):
        ref = ev.get(key)
        if not ref or not os.path.isfile(ref):
            raise ImportRefused(f"{key} missing on disk: {ref}")
        if os.path.commonpath([os.path.realpath(ref), root]) != root:
            raise ImportRefused(f"{key} is outside the run folder: {ref}")
        out[key] = sha256_file(ref)
    if out["frame_ref"] != ev.get("frame_sha256"):
        raise ImportRefused(f"evidence PNG checksum {out['frame_ref']} does not match the "
                            f"sighting's frame_sha256 {ev.get('frame_sha256')}")
    return {"frame_sha256": out["frame_ref"], "frame_sha256_matches_sighting": True,
            "annotated_sha256": out["annotated_ref"],
            "annotated_sha256_recorded": "at import (the camera does not record a checksum "
                                         "for the annotated JPEG)"}


def measure(run_dir: str) -> dict:
    """Run numbers, read from the run's own files (nothing typed in)."""
    summ = sorted(glob.glob(os.path.join(run_dir, "*_summary.json")))
    frames = sorted(glob.glob(os.path.join(run_dir, "*_frames.jsonl")))
    if len(summ) != 1 or len(frames) != 1:
        raise ImportRefused("expected exactly one *_summary.json and one *_frames.jsonl")
    summary = json.load(open(summ[0]))
    rows = [json.loads(l) for l in open(frames[0]) if l.strip()]
    if not rows:
        raise ImportRefused("frame log is empty")
    transport = [r["rx"] - r["t"] for r in rows]
    scores = [b["score"] for r in rows if (b := (r.get("best") or {}).get("PERSON_DETECTOR"))]
    m = {"run_id": summary.get("run_id"), "frames": summary.get("frames"),
         # run-level person score over every frame (not the sighting frame's score)
         "person_frames": len(scores),
         "person_score_median": round(statistics.median(scores), 4) if scores else None,
         "person_score_min": min(scores) if scores else None,
         "person_score_max": max(scores) if scores else None,
         "processed_fps": summary.get("fps"),
         "capture_to_rx_s_median": round(statistics.median(transport), 3),
         "capture_to_rx_s_max": round(max(transport), 3),
         "pi_stream": summary.get("pi_stream"),
         "derived_from": {os.path.basename(p): sha256_file(p) for p in (summ[0], frames[0])}}
    report = os.path.join(run_dir, "run_report.json")
    if os.path.isfile(report):
        rep = json.load(open(report))
        m["scene_requested"] = rep.get("scene")
        m["pi_health"] = rep.get("pi_health")
        m["derived_from"]["run_report.json"] = sha256_file(report)
    return m


LIVE_MAX_S = 30.0


def live_delivery(base: str, s: dict, getter=None) -> dict:
    """Capture-to-dashboard latency of a live delivery, read from the dashboard
    that received it (rx_time is its own receive clock)."""
    import urllib.request
    url = base.rstrip("/") + "/state"
    if getter is None:
        def getter(u):
            with urllib.request.urlopen(u, timeout=5) as r:
                return json.loads(r.read())
    st = getter(url)
    views = [v for t in st.get("tracks", []) for v in [t["latest"], *t.get("history", [])]]
    v = next((x for x in views if x["obs_id"] == s["obs_id"]), None)
    if v is None:
        raise ImportRefused(f"{s['obs_id']} is not on {base}")
    lat = v["rx_time"] - v["obs_time"]
    if not 0 <= lat <= LIVE_MAX_S:
        raise ImportRefused(f"{s['obs_id']} reached {base} {lat:.1f} s after capture: not a "
                            "live delivery (it was re-loaded later)")
    return {"capture_to_dashboard_s": round(lat, 3), "dashboard_rx_time": v["rx_time"],
            "obs_time": v["obs_time"],
            "source": f"GET {url}: the dashboard's receive time of the live core.camera_bridge "
                      "delivery"}


def build_annotation(a: argparse.Namespace, run_dir: str, s: dict, evidence: dict,
                     m: dict) -> dict:
    scene = m.pop("scene_requested", None)
    run_id = m.pop("run_id")
    return ra.validate({
        "schema": ra.SCHEMA, "run_id": run_id, "obs_ids": [s["obs_id"]],
        "classification": a.classification, "scene_requested": scene,
        "counts_as_empty_scene": a.classification == "LIVE_HARDWARE_EMPTY_SCENE",
        "consent": {"status": "CONSENTED" if a.consent_stated_by else "NOT_RECORDED",
                    "scope": sorted(a.consent_scope), "stated_by": a.consent_stated_by,
                    "stated_at": a.consent_stated_at, "public_sharing": False},
        "measured": m,
        "evidence": {s["obs_id"]: evidence},
        "written_at": round(time.time(), 3),
    })


def write_once(path: str, ann: dict,
               keys: Sequence[str] = ("run_id", "obs_ids", "classification", "evidence")) -> str:
    """Write a record once; an existing file must agree on ``keys``.

    A run annotation whose identity agrees and whose numbers were recomputed
    from the very same run files (same ``measured.derived_from`` checksums) may
    be rewritten with the added fields; anything else is refused."""
    if os.path.exists(path):
        old = json.load(open(path))
        same = {k: old.get(k) for k in keys} == {k: ann.get(k) for k in keys}
        if not same:
            raise ImportRefused(f"{path} already exists with different content; not overwritten")
        strip = lambda d: {k: v for k, v in d.items() if k != "written_at"}
        if strip(old) == strip(ann):
            return "existing"
        src_old = (old.get("measured") or {}).get("derived_from")
        src_new = (ann.get("measured") or {}).get("derived_from")
        if src_old is None or src_old != src_new:
            return "existing"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ann, f, indent=1)
        return "updated (recomputed from the same run files)"
    with open(path, "x", encoding="utf-8") as f:
        json.dump(ann, f, indent=1)
    return "written"


def main(argv: Optional[Sequence[str]] = None, poster=post_json) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-dir", required=True)
    p.add_argument("--obs-id", required=True)
    p.add_argument("--classification", required=True, choices=sorted(ra.CLASSIFICATIONS))
    p.add_argument("--consent-stated-by", default=None,
                   help="who stated the person's consent (a role, not the person's name)")
    p.add_argument("--consent-stated-at", default=None)
    p.add_argument("--consent-scope", default="capture,storage,dashboard_display",
                   type=lambda v: [x.strip() for x in v.split(",") if x.strip()])
    p.add_argument("--post", default=None, help="dashboard base URL, e.g. http://127.0.0.1:8792")
    p.add_argument("--live-from", default=None,
                   help="dashboard base URL that received this sighting LIVE (through "
                        "core.camera_bridge); its receive time is recorded as the live "
                        "capture-to-dashboard latency before any reload")
    a = p.parse_args(argv)
    run_dir = os.path.realpath(os.path.expanduser(a.run_dir))
    try:
        line, s = find_sighting(run_dir, a.obs_id)
        evidence = verify_evidence(s, run_dir)
        print(f"verified: {os.path.basename(s['evidence']['frame_ref'])} sha256 "
              f"{evidence['frame_sha256']} == sighting frame_sha256", file=sys.stderr)
        print(f"verified: {os.path.basename(s['evidence']['annotated_ref'])} exists, sha256 "
              f"{evidence['annotated_sha256']}", file=sys.stderr)
        m = measure(run_dir)
        path = os.path.join(run_dir, "run_annotation.json")
        if a.live_from:
            m["live_delivery"] = live_delivery(a.live_from, s)
            print(f"live delivery: capture -> dashboard "
                  f"{m['live_delivery']['capture_to_dashboard_s']} s", file=sys.stderr)
        elif os.path.exists(path):
            old_live = (json.load(open(path)).get("measured") or {}).get("live_delivery")
            if old_live:
                m["live_delivery"] = old_live      # keep what was measured live
        ann = build_annotation(a, run_dir, s, evidence, m)
        status = write_once(os.path.join(run_dir, "run_annotation.json"), ann)
        print(f"run_annotation.json {status}", file=sys.stderr)
    except (ImportRefused, ra.InvalidRunAnnotation, OSError, ValueError) as e:
        print(f"REFUSED: {e}. Nothing sent to the dashboard.", file=sys.stderr)
        return 1
    if not a.post:
        return 0
    base = a.post.rstrip("/")
    code, body = poster(f"{base}/run_annotations", ann)
    print(f"POST /run_annotations -> {code} {json.dumps(body)}", file=sys.stderr)
    if code != 200:
        return 1
    code, body = poster(f"{base}/observations", json.loads(line))
    print(f"POST /observations -> {code} {json.dumps(body)}", file=sys.stderr)
    return 0 if code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())

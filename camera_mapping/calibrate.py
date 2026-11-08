"""Tape-measured distance calibration: capture, fit, evaluate.

    # 1. record the measured mount (tape + phone inclinometer)
    python3 -B -m camera_mapping.calibrate set-mount --height-m 0.135 --pitch-deg 4 --by "<name>"
    # 2. at each tape distance (0.50, 1.00, 1.50, 2.00 m, extras welcome), place the object, then:
    python3 -B -m camera_mapping.calibrate capture --source pi --pi-host team15-pi \\
        --distance-m 1.00 --object chair --role eval --frames 10 --samples ~/Team15_evidence/calibration/samples.jsonl
    # 3. (optional) refine pitch from FIT samples only
    python3 -B -m camera_mapping.calibrate fit-pitch --samples .../samples.jsonl
    # 4. report on EVAL samples; --apply sets CALIBRATED only if the gate passes
    python3 -B -m camera_mapping.calibrate report --samples .../samples.jsonl --out .../report --apply

Ground truth = forward floor distance from the point directly below the lens
to the object's nearest floor contact (front chair legs, the person's toes),
measured with a tape along the robot's centreline. Nothing here invents a
measurement: report refuses to run with no samples, and every sample records
the operator-entered distance and who measured it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import CALIBRATED, CALIBRATION_FAILED, load_config, save_config
from .detector import ObjectDetection
from .distance import ESTIMATED, estimate_all, ground_plane, known_height

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "configs", "imx708_robot.json")
GATE = {"median_rel_max": 0.10, "p90_rel_max": 0.20, "failure_max": 0.20, "min_distances": 4}


def percentile(xs: List[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def metrics(rows: List[dict]) -> dict:
    """rows: {gt_m, est_m (None = failure), latency_ms}. Pure; unit-tested."""
    n = len(rows)
    ok = [r for r in rows if r.get("est_m") is not None]
    abs_e = [abs(r["est_m"] - r["gt_m"]) for r in ok]
    rel_e = [abs(r["est_m"] - r["gt_m"]) / r["gt_m"] for r in ok]
    lat = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    r3 = lambda v: None if v is None else round(v, 4)
    return {"n": n, "n_estimated": len(ok), "failure_rate": r3((n - len(ok)) / n) if n else None,
            "median_abs_m": r3(statistics.median(abs_e)) if abs_e else None,
            "p90_abs_m": r3(percentile(abs_e, 0.9)),
            "median_rel": r3(statistics.median(rel_e)) if rel_e else None,
            "p90_rel": r3(percentile(rel_e, 0.9)),
            "mean_signed_m": r3(statistics.mean([r["est_m"] - r["gt_m"] for r in ok])) if ok else None,
            "median_latency_ms": r3(statistics.median(lat)) if lat else None}


def gate(m: dict, n_distances: int) -> tuple:
    why = []
    if m["n_estimated"] == 0:
        return False, ["no estimates"]
    if n_distances < GATE["min_distances"]:
        why.append(f"only {n_distances} distinct distances (< {GATE['min_distances']})")
    if m["median_rel"] > GATE["median_rel_max"]:
        why.append(f"median rel error {m['median_rel']:.1%} > {GATE['median_rel_max']:.0%}")
    if m["p90_rel"] > GATE["p90_rel_max"]:
        why.append(f"P90 rel error {m['p90_rel']:.1%} > {GATE['p90_rel_max']:.0%}")
    if m["failure_rate"] > GATE["failure_max"]:
        why.append(f"failure rate {m['failure_rate']:.0%} > {GATE['failure_max']:.0%}")
    return not why, why


def _load(path: str) -> List[dict]:
    p = Path(path).expanduser()
    if not p.exists():
        raise SystemExit(f"no samples file {p}: run `capture` first (no measurement is ever invented)")
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    if not rows:
        raise SystemExit("samples file is empty")
    return rows


def _best_det(sample: dict) -> Optional[ObjectDetection]:
    d = sample.get("detection")
    return None if not d else ObjectDetection(d["label"], d["bbox"], d["score"])


def evaluate(samples: List[dict], cfg, role: str = "eval") -> dict:
    rows_by_method: Dict[str, List[dict]] = {"FUSED": [], "GROUND_PLANE": [], "KNOWN_HEIGHT": [], "MONO_DEPTH": []}
    per_distance: Dict[str, List[dict]] = {}
    used = [s for s in samples if role == "all" or s.get("role", "eval") == role]
    for s in used:
        gt, lat = float(s["gt_m"]), s.get("latency_ms")
        det = _best_det(s)
        if det is None:
            for k in rows_by_method:
                if k != "MONO_DEPTH" or s.get("mono_depth_m") is not None:
                    rows_by_method[k].append({"gt_m": gt, "est_m": None, "latency_ms": lat})
            per_distance.setdefault(f"{gt:.2f}", []).append({"gt_m": gt, "est_m": None, "latency_ms": lat})
            continue
        others = [o["bbox"] for o in s.get("others", [])]
        fused = estimate_all([det] + [ObjectDetection(o["label"], o["bbox"], o["score"]) for o in s.get("others", [])], cfg)[0]
        gp, kh = ground_plane(det, cfg, others), known_height(det, cfg)
        for k, r in (("FUSED", fused), ("GROUND_PLANE", gp), ("KNOWN_HEIGHT", kh)):
            est = r.distance_m if r.status == ESTIMATED else None
            rows_by_method[k].append({"gt_m": gt, "est_m": est, "latency_ms": lat})
        if s.get("mono_depth_m") is not None:
            rows_by_method["MONO_DEPTH"].append({"gt_m": gt, "est_m": s["mono_depth_m"], "latency_ms": s.get("depth_ms")})
        per_distance.setdefault(f"{gt:.2f}", []).append(
            {"gt_m": gt, "est_m": fused.distance_m if fused.status == ESTIMATED else None, "latency_ms": lat})
    out = {"role": role, "n_samples": len(used), "methods": {k: metrics(v) for k, v in rows_by_method.items() if v},
           "per_distance_fused": {k: metrics(v) for k, v in sorted(per_distance.items())}}
    nd = len(per_distance)
    out["gate"] = {}
    for k in ("FUSED", "MONO_DEPTH"):
        if k in out["methods"]:
            ok, why = gate(out["methods"][k], nd)
            out["gate"][k] = {"pass": ok, "why": why}
    return out


def fit_pitch(samples: List[dict], cfg, lo: float = -10.0, hi: float = 40.0) -> tuple:
    """Grid-search the pitch that minimises median relative ground-plane error on FIT samples."""
    fit = [s for s in samples if s.get("role") == "fit" and s.get("detection")]
    if len(fit) < 3:
        raise SystemExit("need at least 3 FIT samples (capture --role fit) to fit pitch")
    best = None
    saved = (cfg.mount.pitch_deg, cfg.mount.measured)
    cfg.mount.measured = True
    p = lo
    while p <= hi:
        cfg.mount.pitch_deg = p
        errs = []
        for s in fit:
            r = ground_plane(_best_det(s), cfg)
            errs.append(abs(r.distance_m - s["gt_m"]) / s["gt_m"] if r.status == ESTIMATED else 1.0)
        e = statistics.median(errs)
        if best is None or e < best[1]:
            best = (round(p, 2), e)
        p += 0.1
    cfg.mount.pitch_deg, cfg.mount.measured = saved
    return best


def cmd_capture(a) -> int:
    import cv2
    from .detector import TorchObstacleDetector
    from .live import open_source
    cfg = load_config(a.config)
    det = TorchObstacleDetector()
    depth = None
    if a.depth:
        from .depth import METRIC_INDOOR, MonoDepth, box_depths
        depth = MonoDepth(METRIC_INDOOR)
    a.replay, a.replay_fps, a.camera = a.replay or [], 2.0, a.camera
    cap, describe, mode = open_source(a)
    out_dir = Path(a.frames_dir).expanduser()
    from perception.sightings import ensure_evidence_dir
    ensure_evidence_dir(str(out_dir))               # frames may show people: never inside Git
    cap.read()
    got = 0
    with open(Path(a.samples).expanduser(), "a") as f:
        while got < a.frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            t0 = time.perf_counter()
            all_d = det.detect(frame)
            lat = (time.perf_counter() - t0) * 1000
            dets = [d for d in all_d if d.label == a.object]
            others = [d for d in all_d if d.label != a.object] if a.keep_others else []
            best = max(dets, key=lambda d: d.score, default=None)
            stamp = f"cal-{int(time.time() * 1000)}"
            fp = out_dir / f"{stamp}.png"
            cv2.imwrite(str(fp), frame)
            s = {"t": time.time(), "gt_m": a.distance_m, "object": a.object, "role": a.role,
                 "measured_by": a.by, "source_mode": mode, "camera": describe(),
                 "frame_size": [frame.shape[1], frame.shape[0]], "frame_ref": str(fp),
                 "latency_ms": round(lat, 1),
                 "detection": None if best is None else {"label": best.label, "bbox": best.bbox, "score": best.score},
                 "others": [{"label": o.label, "bbox": o.bbox, "score": o.score} for o in others]}
            if depth is not None and best is not None:
                dm = depth.depth_map(frame)
                r = box_depths(dm, [best], depth.metric)[0]
                s["mono_depth_m"], s["depth_ms"] = r.distance_m, round(depth.last_ms or 0, 1)
            f.write(json.dumps(s) + "\n")
            got += 1
            print(f"[{got}/{a.frames}] gt {a.distance_m:.2f} m {a.object}: "
                  f"{'detected' if best else 'NOT DETECTED'} {lat:.0f} ms", file=sys.stderr)
    cap.release()
    return 0


def cmd_set_mount(a) -> int:
    cfg = load_config(a.config)
    cfg.mount.height_m, cfg.mount.pitch_deg = a.height_m, a.pitch_deg
    cfg.mount.measured, cfg.mount.measured_by = True, a.by
    cfg.mount.measured_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    cfg.mount.pitch_source = a.pitch_source
    if a.setback_m is not None:
        cfg.mount.setback_m = a.setback_m
    if a.robot_width_m is not None:
        cfg.robot_width_m, cfg.robot_width_measured = a.robot_width_m, True
    save_config(cfg, a.config)
    print(f"mount recorded in {a.config}: h={a.height_m} m pitch={a.pitch_deg} deg by {a.by}")
    return 0


def cmd_fit(a) -> int:
    cfg = load_config(a.config)
    if cfg.mount.height_m is None:
        raise SystemExit("set-mount --height-m first (height is tape-measured, never fitted)")
    p, e = fit_pitch(_load(a.samples), cfg)
    print(f"best pitch {p} deg (median rel error on FIT samples {e:.1%})")
    if a.apply:
        cfg.mount.pitch_deg, cfg.mount.pitch_source = p, "FITTED_FROM_TAPE"
        save_config(cfg, a.config)
        print(f"pitch written to {a.config}")
    return 0


def cmd_report(a) -> int:
    cfg = load_config(a.config)
    samples = _load(a.samples)
    rep = evaluate(samples, cfg, a.role)
    rep["config"] = {"mount": cfg.mount.__dict__, "intrinsics": cfg.camera.source, "fx": cfg.camera.fx}
    rep["generated_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rep["samples_file"] = str(Path(a.samples).expanduser())
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "calibration_report.json").write_text(json.dumps(rep, indent=1))
    lines = [f"# Camera distance calibration report ({rep['generated_at']})", "",
             f"Samples: {rep['n_samples']} ({a.role}); file `{rep['samples_file']}`", "",
             "| method | n | estimated | failure | median abs (m) | P90 abs (m) | median rel | P90 rel | bias (m) | latency (ms) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, pct=False: "—" if v is None else (f"{v:.1%}" if pct else f"{v:.3f}")
    for k, m in rep["methods"].items():
        lines.append(f"| {k} | {m['n']} | {m['n_estimated']} | {f(m['failure_rate'], True)} | {f(m['median_abs_m'])} | "
                     f"{f(m['p90_abs_m'])} | {f(m['median_rel'], True)} | {f(m['p90_rel'], True)} | {f(m['mean_signed_m'])} | {f(m['median_latency_ms'])} |")
    lines += ["", "| ground truth (m) | n | failure | median abs (m) | median rel |", "|---|---|---|---|---|"]
    for k, m in rep["per_distance_fused"].items():
        lines.append(f"| {k} | {m['n']} | {f(m['failure_rate'], True)} | {f(m['median_abs_m'])} | {f(m['median_rel'], True)} |")
    lines += ["", f"Gate: {json.dumps(rep['gate'])}"]
    (out / "calibration_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if a.apply:
        g = rep["gate"].get("FUSED", {"pass": False})
        cfg.calibration_status = CALIBRATED if g["pass"] else CALIBRATION_FAILED
        cfg.calibration_ref = str(out / "calibration_report.json")
        gd = rep["gate"].get("MONO_DEPTH")
        cfg.depth_model_validated = bool(gd and gd["pass"])
        save_config(cfg, a.config)
        print(f"config {a.config}: calibration_status={cfg.calibration_status}, "
              f"depth_model_validated={cfg.depth_model_validated}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Camera distance calibration (tape-measured)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--source", choices=("pi", "local", "replay"), default="pi")
    c.add_argument("--camera", type=int, default=0)
    c.add_argument("--pi-host", default=None)
    c.add_argument("--pi-user", default=None)
    c.add_argument("--pi-key", default=None)
    c.add_argument("--pi-fps", type=float, default=5.0)
    c.add_argument("--pi-rotation", type=int, default=180)
    c.add_argument("--replay", nargs="*", default=[])
    c.add_argument("--distance-m", type=float, required=True, help="TAPE-MEASURED forward floor distance")
    c.add_argument("--object", default="chair", help="COCO class placed at the distance (chair, person, ...)")
    c.add_argument("--role", choices=("fit", "eval"), default="eval")
    c.add_argument("--by", required=True, help="who measured the distance")
    c.add_argument("--frames", type=int, default=10)
    c.add_argument("--depth", action="store_true", help="also record the metric mono-depth estimate")
    c.add_argument("--keep-others", action="store_true")
    c.add_argument("--samples", default="~/Team15_evidence/calibration/samples.jsonl")
    c.add_argument("--frames-dir", default="~/Team15_evidence/calibration/frames")
    c.set_defaults(fn=cmd_capture)
    m = sub.add_parser("set-mount")
    m.add_argument("--height-m", type=float, required=True)
    m.add_argument("--pitch-deg", type=float, required=True, help="positive = tilted down")
    m.add_argument("--pitch-source", default="INCLINOMETER", choices=("INCLINOMETER", "FITTED_FROM_TAPE"))
    m.add_argument("--setback-m", type=float, default=None)
    m.add_argument("--robot-width-m", type=float, default=None)
    m.add_argument("--by", required=True)
    m.set_defaults(fn=cmd_set_mount)
    f = sub.add_parser("fit-pitch")
    f.add_argument("--samples", required=True)
    f.add_argument("--apply", action="store_true")
    f.set_defaults(fn=cmd_fit)
    r = sub.add_parser("report")
    r.add_argument("--samples", required=True)
    r.add_argument("--role", choices=("eval", "fit", "all"), default="eval")
    r.add_argument("--out", default="~/Team15_evidence/calibration/report")
    r.add_argument("--apply", action="store_true", help="write CALIBRATED / CALIBRATION_FAILED to the config")
    r.set_defaults(fn=cmd_report)
    for sp in (c, m, f, r):
        sp.add_argument("--config", default=DEFAULT_CONFIG)
    a = p.parse_args(argv)
    if a.cmd == "capture":
        Path(a.samples).expanduser().parent.mkdir(parents=True, exist_ok=True)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())

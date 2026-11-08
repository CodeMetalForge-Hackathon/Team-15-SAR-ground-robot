"""Build an object-test record from a ``perception.live_test --scene object`` run.

    python3 -B -m core.object_test_import \\
        --run-dir ~/Team15_evidence/camera_live_test/object-<ts> \\
        --ground-truth "small quadcopter, powered off, battery disconnected" \\
        --post http://127.0.0.1:8792

``--ground-truth-class`` names the model class that genuinely is the object
(e.g. ``chair``). Leave it out when the model has no such class (a drone in
COCO): the result is then UNRECOGNIZED, whatever the model predicted.
``--ground-truth-bbox x,y,w,h`` (operator-drawn, reference-frame pixels)
enables a spatial check of the predicted boxes (IoU).

Checks before anything is written or sent: the reference PNG and annotated
JPEG hash to the SHA-256 recorded by the run. Class frequencies are recomputed
from ``object_frames.jsonl``. The record is written once (``object_test.json``)
and POSTed to ``/object_tests``, a separate list that never creates a person
track or alert.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from typing import Optional, Sequence

from contracts import object_test as ot
from core.camera_bridge import post_json
from core.evidence_import import ImportRefused, sha256_file, write_once


def model_categories(report: dict) -> tuple[list, str]:
    if report.get("model_categories"):
        return report["model_categories"], "run_report.json (recorded at capture)"
    from torchvision.models import detection as tvd
    from perception.detectors import DEFAULT_DNN_MODEL, DNN_MODELS
    w = getattr(tvd, DNN_MODELS[DEFAULT_DNN_MODEL][1]).COCO_V1
    if report.get("model") != f"torchvision_{DEFAULT_DNN_MODEL}_coco":
        raise ImportRefused(f"run used {report.get('model')}; cannot recover its categories")
    return ([c for c in w.meta["categories"] if c not in ("__background__", "N/A")],
            "torchvision weights metadata (read at import; run predates recording)")


def build(a: argparse.Namespace) -> dict:
    from perception.live_test import class_frequency
    run_dir = os.path.realpath(os.path.expanduser(a.run_dir))
    rep_path = os.path.join(run_dir, "run_report.json")
    frames_path = os.path.join(run_dir, "object_frames.jsonl")
    if not (os.path.isfile(rep_path) and os.path.isfile(frames_path)):
        raise ImportRefused(f"{run_dir} is not an object-scene run")
    rep = json.load(open(rep_path))
    if rep.get("scene") != "object":
        raise ImportRefused(f"scene is {rep.get('scene')!r}, not 'object'")
    rows = [json.loads(l) for l in open(frames_path) if l.strip()]
    if not rows:
        raise ImportRefused("no frames in object_frames.jsonl")
    ref = rep.get("reference_frame") or {}
    images = {}
    for key in ("reference", "reference_annotated"):
        info = ref.get(key)
        if not isinstance(info, dict):
            continue                      # withheld (person under no-people consent)
        if not os.path.isfile(info["path"]):
            raise ImportRefused(f"{key} image missing: {info['path']}")
        got = sha256_file(info["path"])
        if got != info["sha256"]:
            raise ImportRefused(f"{key} checksum {got} != recorded {info['sha256']}")
        images[key] = {"path": info["path"], "sha256": got, "verified": True}
    cats, cats_src = model_categories(rep)
    freq = class_frequency(rows)
    gt = {"object": a.ground_truth, "supplied_by": "operator",
          "model_class": a.ground_truth_class, "bbox": a.ground_truth_bbox}
    persons = sum(any(d["label"] == "person" for d in r["detections"]) for r in rows)
    inf = [r["inference_s"] for r in rows]
    c2r = [r["capture_to_result_s"] for r in rows]
    tr = [r["rx"] - r["t_capture"] for r in rows]
    rec = {
        "schema": ot.SCHEMA,
        "test_id": os.path.basename(run_dir),
        "provenance": {"source_mode": "LIVE-HW", "platform": "BENCH",
                       "camera": ref.get("camera"), "consent": rep.get("consent")},
        "ground_truth": gt,
        "model": {"name": rep.get("model"), "device": rep.get("device"),
                  "weights": rep.get("model_weights"), "categories": cats,
                  "categories_source": cats_src,
                  "threshold": rep.get("detection_threshold", 0.5),
                  "has_class_for_object": bool(a.ground_truth_class)},
        "frames": len(rows),
        "frames_with_no_detection": sum(not r["detections"] for r in rows),
        "class_frequency": freq,
        "person_frames": persons,
        "reference": {"capture_time": ref.get("capture_time"),
                      "capture_time_iso": ref.get("capture_time_iso"),
                      "frame_size": ref.get("frame_size"),
                      "detections": ref.get("detections") or [],
                      "rule": rep.get("reference_frame_rule",
                                      f"frame with the highest '{rep.get('object_label')}' score"),
                      "images": images,
                      "withheld": ref.get("image")},
        "performance": {"processed_fps": rep.get("processed_fps"),
                        "inference_s_median": round(statistics.median(inf), 3),
                        "inference_s_max": round(max(inf), 3),
                        "capture_to_result_s_median": round(statistics.median(c2r), 3),
                        "capture_to_result_s_max": round(max(c2r), 3),
                        "capture_to_rx_s_median": round(statistics.median(tr), 3)},
        "pi_health": rep.get("pi_health"),
        "run_files": {os.path.basename(p): sha256_file(p) for p in (rep_path, frames_path)},
    }
    if a.ground_truth_bbox:
        rec["alignment"] = [{"label": d["label"], "score": d["score"], "bbox": d["bbox"],
                             "iou_with_ground_truth": round(ot.iou(d["bbox"], a.ground_truth_bbox), 3)}
                            for d in rec["reference"]["detections"]]
    rec["match"] = ot.compute_match(gt, cats, freq)
    return ot.validate(rec)


def main(argv: Optional[Sequence[str]] = None, poster=post_json) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-dir", required=True)
    p.add_argument("--ground-truth", required=True,
                   help="operator's description of the physical object")
    p.add_argument("--ground-truth-class", default=None,
                   help="model class that genuinely names the object; omit if none")
    p.add_argument("--ground-truth-bbox", default=None,
                   type=lambda v: [int(x) for x in v.split(",")],
                   help="operator-drawn box x,y,w,h in reference-frame pixels")
    p.add_argument("--post", default=None, help="dashboard base URL")
    a = p.parse_args(argv)
    try:
        rec = build(a)
        path = os.path.join(os.path.realpath(os.path.expanduser(a.run_dir)), "object_test.json")
        status = write_once(path, rec, keys=("test_id", "ground_truth", "match",
                                             "class_frequency", "reference"))
        print(f"object_test.json {status}: {rec['test_id']} -> {rec['match']['status']}",
              file=sys.stderr)
    except (ImportRefused, ot.InvalidObjectTest, OSError, ValueError) as e:
        print(f"REFUSED: {e}. Nothing sent.", file=sys.stderr)
        return 1
    if not a.post:
        return 0
    code, body = poster(a.post.rstrip("/") + "/object_tests", rec)
    print(f"POST /object_tests -> {code} {json.dumps(body)}", file=sys.stderr)
    return 0 if code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())

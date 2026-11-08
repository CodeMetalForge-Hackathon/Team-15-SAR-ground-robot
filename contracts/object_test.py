"""Object test record: what the detector saw when a known object was in view.

An object test is a bench experiment, not a rescue observation: it never
creates a track, an alert or a route. The dashboard shows it on a separate page
(``/object-tests``). Records are built by ``core.object_test_import`` from a
``perception.live_test --scene object`` run.

The operator supplies the ground truth: a free-text description of the
physical object, and optionally the model class that genuinely names it
(``ground_truth.model_class``, e.g. "chair"). The match is computed here, never
supplied:

    MATCH          model_class is a model category and is predicted in at
                   least MATCH_MIN_FRAC of the frames
    NOT_DETECTED   model_class is a model category but is predicted less often
    UNRECOGNIZED   no model class names the object (e.g. a drone in COCO).
                   Predicted classes are shown as-is; none is renamed. An
                   "airplane" box on a drone stays "airplane" and is not a match.
"""
from __future__ import annotations

SCHEMA = "team15.object_test/1"
MATCH_MIN_FRAC = 0.5
STATUSES = ("MATCH", "NOT_DETECTED", "UNRECOGNIZED")


class InvalidObjectTest(ValueError):
    pass


def compute_match(ground_truth: dict, categories: list, class_frequency: dict) -> dict:
    gt_class = ground_truth.get("model_class")
    obj = ground_truth.get("object") or "the test object"
    if not gt_class:
        return {"status": "UNRECOGNIZED",
                "explanation": f"The model has no class for {obj}. Predicted classes are "
                               "listed as-is and are not counted as a recognition."}
    if gt_class not in categories:
        raise InvalidObjectTest(f"ground_truth.model_class {gt_class!r} is not a model category")
    f = (class_frequency.get(gt_class) or {}).get("frac_frames", 0.0)
    if f >= MATCH_MIN_FRAC:
        return {"status": "MATCH",
                "explanation": f"'{gt_class}' predicted in {f:.0%} of frames "
                               f"(threshold {MATCH_MIN_FRAC:.0%})."}
    return {"status": "NOT_DETECTED",
            "explanation": f"'{gt_class}' predicted in only {f:.0%} of frames "
                           f"(threshold {MATCH_MIN_FRAC:.0%})."}


def iou(a: list, b: list) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


def validate(rec: dict) -> dict:
    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise InvalidObjectTest(msg)
    need(isinstance(rec, dict) and rec.get("schema") == SCHEMA, f"schema must be {SCHEMA!r}")
    need(isinstance(rec.get("test_id"), str) and rec["test_id"], "test_id is required")
    p = rec.get("provenance") or {}
    need(p.get("source_mode") == "LIVE-HW" and p.get("platform") == "BENCH",
         "provenance must be LIVE-HW / BENCH")
    gt = rec.get("ground_truth") or {}
    need(bool(gt.get("object")) and gt.get("supplied_by") == "operator",
         "ground_truth.object (supplied_by operator) is required")
    m = rec.get("model") or {}
    cats = m.get("categories")
    need(isinstance(cats, list) and cats, "model.categories is required")
    need(isinstance(rec.get("class_frequency"), dict), "class_frequency is required")
    need(isinstance(rec.get("frames"), int) and rec["frames"] > 0, "frames must be > 0")
    expected = compute_match(gt, cats, rec["class_frequency"])
    need((rec.get("match") or {}).get("status") == expected["status"],
         f"match.status must be {expected['status']} (computed, not supplied)")
    for lab in rec["class_frequency"]:
        need(lab in cats, f"predicted class {lab!r} is not a model category (no relabelling)")
    ref = rec.get("reference") or {}
    for d in ref.get("detections") or []:
        need(d.get("label") in cats, f"reference detection {d.get('label')!r} is not a model "
                                     "category (no relabelling)")
    return rec

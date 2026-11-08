"""Bench object tests (e.g. a drone the COCO model has no class for).

Synthetic images only. Covers: no relabelling, computed match status,
checksum verification, isolation from person alerts, image serving, page text.
"""
import hashlib
import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from contracts import object_test as ot
from core import object_test_import as oti
from core.store import MissionStore
from dashboard.app import STATIC, create_app
from perception.live_test import class_frequency

CATS = ["person", "airplane", "bird", "kite", "chair", "surfboard"]
SHA = lambda b: hashlib.sha256(b).hexdigest()


def make_run(tmp_path, frames_dets, *, name="object-20231114T000000", images=True):
    run = tmp_path / "ev" / name
    run.mkdir(parents=True)
    img = np.full((72, 128, 3), 120, np.uint8)
    png, jpg = cv2.imencode(".png", img)[1].tobytes(), cv2.imencode(".jpg", img)[1].tobytes()
    ref = {"capture_time": 1700000000.5, "capture_time_iso": "2023-11-14T22:13:20.500+00:00",
           "frame_size": [128, 72], "detections": frames_dets[len(frames_dets) // 2],
           "camera": {"source": "pi5-imx708", "rotation_deg": 180}}
    if images:
        (run / "object_reference.png").write_bytes(png)
        (run / "object_reference_annotated.jpg").write_bytes(jpg)
        ref["reference"] = {"path": str(run / "object_reference.png"), "sha256": SHA(png)}
        ref["reference_annotated"] = {"path": str(run / "object_reference_annotated.jpg"),
                                      "sha256": SHA(jpg)}
    else:
        ref["image"] = "person detected (score 0.80) under consent 'no-people': image not saved"
    rows = [{"t_capture": 1700000000 + i * 0.2, "rx": 1700000000 + i * 0.2 + 0.19,
             "result_time": 1700000000 + i * 0.2 + 0.44, "inference_s": 0.19,
             "capture_to_result_s": 0.44, "detections": d} for i, d in enumerate(frames_dets)]
    (run / "object_frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (run / "run_report.json").write_text(json.dumps({
        "scene": "object", "consent": "no-people", "model": "torchvision_frcnn_r50_fpn_v2_coco",
        "device": "mps", "object_label": "drone", "object_label_supported": False,
        "model_categories": CATS, "detection_threshold": 0.5, "processed_fps": 5.0,
        "reference_frame_rule": "first frame after the halfway point",
        "reference_frame": ref, "pi_health": {"temp_c": [46.0, 49.0], "ext5v_v": [5.25, 5.27],
                                              "throttled_values": ["0x0"]}}))
    return run, png, jpg


AIRPLANE = {"label": "airplane", "score": 0.95, "bbox": [40, 20, 50, 20]}
CHAIR = {"label": "chair", "score": 0.99, "bbox": [10, 10, 40, 50]}


def args(run, *extra):
    return ["--run-dir", str(run), "--ground-truth", "small quadcopter, powered off", *extra]


def test_drone_predicted_as_airplane_is_unrecognized_not_relabelled(tmp_path):
    run, *_ = make_run(tmp_path, [[AIRPLANE]] * 10)
    assert oti.main(args(run)) == 0
    rec = json.loads((run / "object_test.json").read_text())
    assert rec["match"]["status"] == "UNRECOGNIZED"
    assert set(rec["class_frequency"]) == {"airplane"}           # kept as predicted
    assert rec["class_frequency"]["airplane"]["frac_frames"] == 1.0
    assert "drone" not in json.dumps(rec["class_frequency"])
    assert rec["model"]["has_class_for_object"] is False


def test_nothing_detected_is_recorded_honestly(tmp_path):
    run, *_ = make_run(tmp_path, [[]] * 8)
    assert oti.main(args(run)) == 0
    rec = json.loads((run / "object_test.json").read_text())
    assert rec["frames_with_no_detection"] == 8 and rec["class_frequency"] == {}
    assert rec["match"]["status"] == "UNRECOGNIZED"


@pytest.mark.parametrize("n_hit,status", [(10, "MATCH"), (3, "NOT_DETECTED")])
def test_supported_class_match_is_computed(tmp_path, n_hit, status):
    run, *_ = make_run(tmp_path, [[CHAIR]] * n_hit + [[]] * (10 - n_hit))
    assert oti.main(args(run, "--ground-truth-class", "chair")) == 0
    assert json.loads((run / "object_test.json").read_text())["match"]["status"] == status


def test_contract_rejects_relabelling_and_supplied_match(tmp_path):
    run, *_ = make_run(tmp_path, [[AIRPLANE]] * 4)
    oti.main(args(run))
    rec = json.loads((run / "object_test.json").read_text())
    bad = json.loads(json.dumps(rec))
    bad["class_frequency"]["drone"] = bad["class_frequency"].pop("airplane")
    with pytest.raises(ot.InvalidObjectTest, match="relabelling"):
        ot.validate(bad)
    bad = json.loads(json.dumps(rec))
    bad["match"] = {"status": "MATCH", "explanation": "looks like a drone"}
    with pytest.raises(ot.InvalidObjectTest, match="computed"):
        ot.validate(bad)
    with pytest.raises(ot.InvalidObjectTest, match="not a model category"):
        ot.compute_match({"object": "x", "model_class": "drone"}, CATS, {})


def test_import_refuses_checksum_mismatch(tmp_path):
    run, *_ = make_run(tmp_path, [[AIRPLANE]] * 4)
    (run / "object_reference.png").write_bytes(b"tampered")
    assert oti.main(args(run, "--post", "http://dash"),
                    poster=lambda *a: pytest.fail("must not post")) == 1
    assert not (run / "object_test.json").exists()


def test_withheld_image_is_allowed_and_shown_as_withheld(tmp_path):
    run, *_ = make_run(tmp_path, [[AIRPLANE]] * 4, images=False)
    assert oti.main(args(run)) == 0
    rec = json.loads((run / "object_test.json").read_text())
    assert rec["reference"]["images"] == {} and "not saved" in rec["reference"]["withheld"]


def test_alignment_iou_with_operator_box(tmp_path):
    run, *_ = make_run(tmp_path, [[AIRPLANE]] * 4)
    assert oti.main(args(run, "--ground-truth-bbox", "40,20,50,20")) == 0
    rec = json.loads((run / "object_test.json").read_text())
    assert rec["alignment"][0]["iou_with_ground_truth"] == 1.0
    assert ot.iou([0, 0, 10, 10], [5, 0, 10, 10]) == pytest.approx(50 / 150)


def test_dashboard_isolated_from_person_workflow(tmp_path):
    run, png, jpg = make_run(tmp_path, [[AIRPLANE, {"label": "person", "score": 0.6,
                                                    "bbox": [0, 0, 5, 5]}]] * 4)
    store = MissionStore()
    c = TestClient(create_app(store, evidence_dir=str(run.parent)))
    poster = lambda url, obj: (lambda r: (r.status_code, r.json()))(
        c.post(url.replace("http://dash", ""), json=obj))
    assert oti.main(args(run, "--post", "http://dash"), poster=poster) == 0
    st = c.get("/state").json()
    assert st["tracks"] == [] and st["alerts"] == [] and st["routes"] == []   # no person alert
    tests = c.get("/api/object_tests").json()["object_tests"]
    assert len(tests) == 1 and tests[0]["person_frames"] == 4
    t = tests[0]
    a = c.get(t["image_urls"]["reference_annotated"])
    f = c.get(t["image_urls"]["reference"])
    assert a.content == jpg and f.content == png and f.headers["content-type"] == "image/png"
    assert c.get(f"/object_evidence/{t['test_id']}/../../etc").status_code == 404
    # re-post: duplicate; different content under the same id: conflict
    rec = json.loads((run / "object_test.json").read_text())
    assert c.post("/object_tests", json=rec).json()["duplicate"] is True
    rec["ground_truth"]["object"] = "something else"
    assert c.post("/object_tests", json=rec).status_code == 409
    assert c.get("/object-tests").status_code == 200


def test_class_frequency():
    rows = [{"detections": [AIRPLANE]}, {"detections": []},
            {"detections": [dict(AIRPLANE, score=0.6), CHAIR]}]
    f = class_frequency(rows)
    assert f["airplane"] == {"frames": 2, "frac_frames": 0.667, "score_min": 0.6,
                             "score_median": 0.775, "score_max": 0.95}
    assert f["chair"]["frames"] == 1


def test_page_shows_required_fields():
    html = (STATIC / "object_tests.html").read_text()
    for needle in ("UNKNOWN / UNRECOGNIZED", "Known test object", "ground truth supplied by",
                   "LIVE HARDWARE / BENCH", "no rescue alert", "Prediction matches ground truth",
                   "Raw score", "Bounding box", "Detection frequency", "Captured (reference)",
                   "Actual camera image", "Annotated"):
        assert needle in html, needle

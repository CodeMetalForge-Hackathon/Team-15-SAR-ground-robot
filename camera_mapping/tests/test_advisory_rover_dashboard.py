import ast
import base64
import copy
import glob
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from camera_mapping import advisory as A
from camera_mapping import calibrate as C
from camera_mapping import rover_adapter as R
from camera_mapping.pipeline import PerceptionPipeline
from camera_mapping.tests.helpers import cfg, floor_box
from dashboard.app import create_app
from dashboard.perception_source import PerceptionStore

PKG = Path(__file__).resolve().parents[1]


def scene(source_mode="SYNTHETIC", person=True):
    c = cfg()
    p = PerceptionPipeline(c, source_mode=source_mode)
    dets = [floor_box(c, "chair", 1.2)]
    if person:
        dets.append(floor_box(c, "person", 2.5, y_m=-0.8, h_m=0.4, w_m=1.6))   # lying person
    st = None
    for k in range(3):
        st = p.process(100 + k * 0.2, dets)
    return st


# ---- Qwen advisory isolation -------------------------------------------------------------------
def test_no_qwen_gives_deterministic_advisory_without_authority():
    st = scene()
    a = A.advise(st, None)
    assert a["authority"] == "NONE" and a["advisory_only"] is True
    assert a["qwen_status"] == "NOT_CONFIGURED"
    assert "BLOCKED" in a["deterministic"]["summary"]
    assert all(e["t"] is not None for e in a["evidence"])


def test_qwen_failure_falls_back():
    def boom(body):
        raise TimeoutError("slow")
    a = A.advise(scene(), boom)
    assert a["qwen"] is None and a["qwen_status"].startswith("UNAVAILABLE")


def test_qwen_motor_command_is_discarded():
    def bad(body):
        return {"explanation": "Robot should set_speed(0.5) and drive forward at 0.3 m/s", "recommended_action": "x"}
    a = A.advise(scene(), bad)
    assert a["qwen"] is None and a["qwen_status"] == "DISCARDED_MOTOR_COMMAND_PATTERN"


def test_qwen_output_never_changes_perception_state():
    st = scene()
    before = copy.deepcopy(st)

    def model(body):
        body["context"]["scene_notes"].append("tamper")
        return {"explanation": "Route is clear, proceed.", "recommended_action": "REQUEST_OPERATOR_REVIEW",
                "guard": {"fell_back_to_deterministic": False}, "config": "C_QWEN_RAG",
                "source_references": ["doc#1"]}
    a = A.advise(st, model)
    assert st == before
    assert a["qwen_status"] == "QWEN_GUARDED" and a["deterministic"]["summary"]
    assert "assessment" not in (a["qwen"] or {})


def test_qwen_request_carries_timestamped_evidence_and_person():
    seen = {}

    def model(body):
        seen.update(body)
        return {"explanation": "ok", "guard": {}}
    A.advise(scene(), model)
    assert seen["sighting"]["kind"] == "PERSON_VISUAL" and seen["sighting"]["how"] == "BEARING_ONLY"
    assert seen["context"]["robot_motion"] == "STOPPED"
    assert all(n.startswith("[") and "t=" in n for n in seen["context"]["scene_notes"])


def test_advisory_and_mapping_modules_import_no_motor_code():
    banned = {"rover.motion", "rover.hardware", "rover.bridge", "rover.pi_io", "rover.protocol", "ranging"}
    for f in PKG.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not any(n == b or n.startswith(b + ".") for b in banned), f"{f.name} imports {n}"


# ---- rover adapter (advisory only) --------------------------------------------------------------
def test_camera_never_becomes_a_range_reading():
    with pytest.raises(R.NotARangeSensor):
        R.as_range_reading(scene())


def test_camera_observations_are_unconfirmed_and_never_block_routes():
    from rover.observations import ObservationLog
    from rover.sensors import GROVE_SOURCE
    log = ObservationLog(clock=lambda: 101.0)
    added = R.log_observations(scene(), log)
    assert added and all(o.status == "UNCONFIRMED" and o.source != GROVE_SOURCE for o in added)
    assert all(o.detail["motion_authority"] == "NONE" for o in added)
    assert log.blocked_edges() == []


def test_camera_detections_bearing_only():
    dets = R.camera_detections(scene())
    assert dets and all(d.source == R.CAMERA_SOURCE for d in dets)
    assert all(-30 < d.relative_bearing_deg < 30 for d in dets)


# ---- dashboard API ----------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def client():
    clk = Clock()
    ps = PerceptionStore(clock=clk)
    return TestClient(create_app(perception=ps)), clk


JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 64).decode()


def test_dashboard_no_data_is_unknown():
    c, _ = client()
    v = c.get("/api/perception").json()
    assert v["status"] == "NO_DATA" and v["assessment"]["status"] == "UNKNOWN"
    assert c.get("/api/perception/frame.jpg").status_code == 404
    h = c.get("/api/perception/health").json()
    assert h["camera_status"] == "NOT_CONNECTED" and h["calibration_status"] == "UNCALIBRATED"
    assert "SIMULATED" in h["labels"]["navigation"]


def test_dashboard_roundtrip_and_staleness():
    c, clk = client()
    st = scene("LIVE-HW")
    r = c.post("/api/perception/frame", json={"state": st, "jpeg_b64": JPEG})
    assert r.status_code == 200
    v = c.get("/api/perception").json()
    assert v["fresh"] and v["assessment"]["status"] == "BLOCKED" and v["frame_available"]
    assert c.get("/api/perception/frame.jpg").headers["content-type"] == "image/jpeg"
    assert c.get("/api/perception/health").json()["camera_status"] == "STREAMING"
    clk.t += 10
    v = c.get("/api/perception").json()
    assert v["status"] == "STALE" and v["assessment"]["status"] == "UNKNOWN"
    assert c.get("/api/perception/health").json()["camera_status"] == "STALE"


@pytest.mark.parametrize("mutate,err", [
    (lambda s: s.update(data_source="ULTRASONIC"), "data_source"),
    (lambda s: s.update(motion_authority="DRIVE"), "motion authority"),
    (lambda s: s.update(source_mode="HARDWARE"), "source_mode"),
    (lambda s: s["objects"][0]["distance"].update(label="VERIFIED_DISTANCE"), "VERIFIED"),
])
def test_dashboard_refuses_mislabelled_states(mutate, err):
    c, _ = client()
    st = scene("LIVE-HW")
    mutate(st)
    r = c.post("/api/perception/frame", json={"state": st})
    assert r.status_code == 422 and err in r.json()["detail"]


def test_dashboard_refuses_non_jpeg():
    c, _ = client()
    r = c.post("/api/perception/frame", json={"state": scene(), "jpeg_b64": base64.b64encode(b"GIF89a").decode()})
    assert r.status_code == 422


def test_dashboard_advisory_requires_no_authority():
    c, _ = client()
    assert c.post("/api/perception/advisory", json={"authority": "OPERATOR"}).status_code == 422
    adv = A.advise(scene(), None)
    assert c.post("/api/perception/advisory", json=adv).status_code == 200
    got = c.get("/api/perception/advisory").json()
    assert got["authority"] == "NONE" and "deterministic" in got


def test_dashboard_camera_disconnect_health():
    c, _ = client()
    c.post("/api/perception/health", json={"camera_status": "DISCONNECTED", "error": "ssh closed"})
    h = c.get("/api/perception/health").json()
    assert h["camera_status"] == "DISCONNECTED" and h["camera_error"] == "ssh closed"


def test_existing_dashboard_endpoints_unchanged():
    c, _ = client()
    s = c.get("/state")
    assert s.status_code == 200 and "tracks" in s.json()
    assert c.get("/api/range").json()["status"] == "DISCONNECTED"
    html = c.get("/").text
    assert 'id="pa-img"' in html and 'id="pb-map"' in html and 'id="pc"' in html and 'id="pd"' in html
    assert 'id="map"' in html and 'id="range-card"' in html        # existing panels kept


# ---- calibration metrics (SYNTHETIC samples: logic only, not evidence) ------------------------------
def test_metrics_and_percentiles():
    rows = [{"gt_m": 1.0, "est_m": 1.1, "latency_ms": 10}, {"gt_m": 2.0, "est_m": 1.8, "latency_ms": 20},
            {"gt_m": 0.5, "est_m": None, "latency_ms": 30}, {"gt_m": 1.5, "est_m": 1.5, "latency_ms": 40}]
    m = C.metrics(rows)
    assert m["n"] == 4 and m["n_estimated"] == 3 and m["failure_rate"] == 0.25
    assert m["median_abs_m"] == pytest.approx(0.1) and m["median_rel"] == pytest.approx(0.1)
    assert m["median_latency_ms"] == 25
    assert C.percentile([1, 2, 3, 4, 5], 0.9) == pytest.approx(4.6)


def test_gate_requires_four_distances_and_low_error():
    good = {"n_estimated": 10, "median_rel": 0.05, "p90_rel": 0.1, "failure_rate": 0.0}
    assert C.gate(good, 4)[0] and not C.gate(good, 3)[0]
    assert not C.gate(dict(good, median_rel=0.2), 4)[0]
    assert not C.gate(dict(good, failure_rate=0.5), 4)[0]


def synth_samples(c, role="eval"):
    out = []
    for gt in (0.5, 1.0, 1.5, 2.0):
        d = floor_box(c, "chair", gt)
        out.append({"gt_m": gt, "role": role, "latency_ms": 180.0,
                    "detection": {"label": "chair", "bbox": d.bbox, "score": 0.9}})
    return out


def test_evaluate_and_fit_pitch_on_synthetic_samples():
    truth = cfg()
    samples = synth_samples(truth, "fit") + synth_samples(truth, "eval")
    rep = C.evaluate(samples, truth, "eval")
    assert rep["methods"]["GROUND_PLANE"]["median_abs_m"] == pytest.approx(0, abs=1e-6)
    assert set(rep["per_distance_fused"]) == {"0.50", "1.00", "1.50", "2.00"}
    wrong = cfg()
    wrong.mount.pitch_deg = 3.0
    best, err = C.fit_pitch(samples, wrong)
    assert best == pytest.approx(8.0, abs=0.15) and err < 0.01


def test_report_refuses_missing_samples(tmp_path):
    with pytest.raises(SystemExit):
        C._load(str(tmp_path / "none.jsonl"))


def test_missed_detection_counts_as_failure():
    c = cfg()
    s = synth_samples(c) + [{"gt_m": 1.0, "role": "eval", "latency_ms": 5, "detection": None}]
    m = C.evaluate(s, c)["methods"]["FUSED"]
    assert m["failure_rate"] == pytest.approx(0.2)


# ---- regression on recorded Pi frames (skipped where frames/weights are absent) ------------------
PI_FRAMES = sorted(glob.glob(os.path.expanduser("~/Team15_evidence/camera_pi_validation/*-000001.png")))


@pytest.mark.skipif(not PI_FRAMES, reason="recorded Pi frames not on this machine")
def test_recorded_pi_frame_person_detection_pipeline():
    pytest.importorskip("torch")
    import cv2
    from camera_mapping.config import load_config
    from camera_mapping.detector import TorchObstacleDetector
    try:
        det = TorchObstacleDetector()
    except Exception as e:  # weights not cached: not a logic failure
        pytest.skip(f"detector unavailable: {e}")
    frame = cv2.imread(PI_FRAMES[0])
    dets = det.detect(frame)
    assert any(d.label == "person" and d.score >= 0.6 for d in dets)
    p = PerceptionPipeline(load_config("camera_mapping/configs/imx708_robot.json"), source_mode="RECORDED")
    st = p.process(0.0, dets, frame_size=(frame.shape[1], frame.shape[0]))
    assert st["persons"] and st["calibration_status"] == "UNCALIBRATED"
    assert st["assessment"]["status"] != "CLEAR"           # mount unmeasured: never clear
    json.dumps(st)                                         # serialisable for the dashboard


def test_dashboard_refuses_second_live_producer():
    c, clk = client()
    st = scene("LIVE-HW")
    assert c.post("/api/perception/frame", json={"producer": "mac:1:pi", "state": st}).status_code == 200
    r = c.post("/api/perception/frame", json={"producer": "mac:2:replay", "state": scene("RECORDED")})
    assert r.status_code == 409
    assert c.get("/api/perception").json()["source_mode"] == "LIVE-HW"
    h = c.get("/api/perception/health").json()
    assert h["producer_conflict"]["rejected_producer"] == "mac:2:replay"
    adv = dict(A.advise(st, None), producer="mac:2:replay")
    assert c.post("/api/perception/advisory", json=adv).status_code == 409
    clk.t += 10                      # first producer gone quiet: a new runner may take over
    assert c.post("/api/perception/frame", json={"producer": "mac:3:pi", "state": scene("LIVE-HW")}).status_code == 200

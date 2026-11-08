"""Importing existing live-camera evidence into the dashboard (synthetic images only).

Covers: evidence import and checksum verification, duplicate handling, image
display, provenance and run context, consent rules, operator review.
"""
import hashlib
import json
import os

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from contracts import run_annotation as ra
from core import evidence_import as ei
from core.store import MissionStore
from dashboard.app import STATIC, create_app

OBS_ID = "D1-b1700000000-000001"
T_CAP = 1700000000.5
SHA = lambda b: hashlib.sha256(b).hexdigest()


def make_run(tmp_path, *, frames=10):
    run = tmp_path / "evidence" / "empty-20231114T221320"
    run.mkdir(parents=True)
    img = np.full((72, 128, 3), 90, np.uint8)
    img[10:60, 50:80] = 200                           # synthetic stand-in, no person
    png = cv2.imencode(".png", img)[1].tobytes()
    ann = img.copy()
    cv2.rectangle(ann, (50, 10), (80, 60), (0, 255, 0), 1)
    jpg = cv2.imencode(".jpg", ann)[1].tobytes()
    (run / f"{OBS_ID}.png").write_bytes(png)
    (run / f"{OBS_ID}_annotated.jpg").write_bytes(jpg)
    cam = {"source": "pi5-imx708", "device": "Raspberry Pi camera (remote, bench)",
           "pi_model": "Raspberry Pi 5 Model B Rev 1.1", "sensor_model": "imx708",
           "transport": "ssh-jpeg", "stream_size": [128, 72], "stream_fps": 5.0,
           "jpeg_quality": 80, "rotation_deg": 180, "rotation_applied_by": "receiver",
           "sensor_mount_rotation": 180, "pi_transform": "<libcamera.Transform 'identity'>",
           "capture_clock": "sensor", "pi_frame_seq": 6, "capture_time": T_CAP,
           "rx_time": T_CAP + 0.194, "capture_to_rx_s": 0.194}
    s = {"obs_id": OBS_ID, "drone_id": "D1", "boot_id": "b1700000000", "seq": 1,
         "source_mode": "LIVE-HW", "platform": "BENCH", "sensor": "rgb",
         "kind": "PERSON_VISUAL", "how": "SECTOR_ONLY", "cell": "G",
         "cell_source": "OPERATOR_ASSIGNED", "operator": "bench-validation",
         "obs_time": round(T_CAP, 3), "obs_time_iso": "2023-11-14T22:13:20.500+00:00",
         "confidence": None,
         "evidence": {"frame_ref": str(run / f"{OBS_ID}.png"), "frame_sha256": SHA(png),
                      "annotated_ref": str(run / f"{OBS_ID}_annotated.jpg"),
                      "frame_size": [128, 72], "bbox": [50, 10, 30, 50],
                      "detector": "torchvision_frcnn_r50_fpn_v2_coco",
                      "detector_family": "PERSON_DETECTOR", "detector_score": 0.9996,
                      "detector_score_kind": "frcnn_class_score", "count_in_frame": 1,
                      "camera": cam}}
    (run / "sightings.jsonl").write_text(json.dumps(s) + "\n")
    rows = [{"t": T_CAP + 0.2 * i, "rx": T_CAP + 0.2 * i + 0.25 + 0.01 * i, "all": []}
            for i in range(frames)]
    (run / "D1-b1700000000-empty_frames.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    (run / "D1-b1700000000-empty_summary.json").write_text(json.dumps(
        {"run_id": "D1-b1700000000-empty", "frames": frames, "fps": 4.75,
         "pi_stream": {"frames_received": 12}}))
    (run / "run_report.json").write_text(json.dumps(
        {"scene": "empty", "pi_health": {"temp_c": [47.7, 50.5], "throttled_values": ["0x0"]}}))
    return run, s, png, jpg


ARGS = ["--obs-id", OBS_ID, "--classification", "LIVE_HARDWARE_PERSON_PRESENT",
        "--consent-stated-by", "Team-15 operator", "--consent-stated-at", "2026-11-08"]


def client_for(run):
    store = MissionStore(clock=lambda: T_CAP + 5)
    c = TestClient(create_app(store, evidence_dir=str(run.parent)))

    def poster(url, obj):
        r = c.post(url.replace("http://dash", ""), json=obj)
        return r.status_code, r.json()
    return c, store, poster


def files_digest(run):
    return {p.name: SHA(p.read_bytes()) for p in sorted(run.iterdir())
            if p.name != "run_annotation.json"}


# -- evidence import ----------------------------------------------------------
def test_import_verifies_checksums_and_derives_metrics(tmp_path):
    run, s, png, jpg = make_run(tmp_path)
    before = files_digest(run)
    assert ei.main(["--run-dir", str(run), *ARGS]) == 0
    ann = json.loads((run / "run_annotation.json").read_text())
    assert ann["classification"] == "LIVE_HARDWARE_PERSON_PRESENT"
    assert ann["counts_as_empty_scene"] is False and ann["scene_requested"] == "empty"
    ev = ann["evidence"][OBS_ID]
    assert ev["frame_sha256"] == SHA(png) and ev["frame_sha256_matches_sighting"]
    assert ev["annotated_sha256"] == SHA(jpg)
    m = ann["measured"]
    assert m["processed_fps"] == 4.75                         # from *_summary.json
    assert m["capture_to_rx_s_median"] == pytest.approx(0.295, abs=1e-3)  # from the frame log
    assert set(m["derived_from"]) == {"D1-b1700000000-empty_summary.json",
                                      "D1-b1700000000-empty_frames.jsonl", "run_report.json"}
    assert ann["consent"]["public_sharing"] is False
    assert files_digest(run) == before                        # evidence untouched


def test_import_refuses_checksum_mismatch(tmp_path):
    run, s, *_ = make_run(tmp_path)
    s["evidence"]["frame_sha256"] = "0" * 64
    (run / "sightings.jsonl").write_text(json.dumps(s) + "\n")
    assert ei.main(["--run-dir", str(run), *ARGS, "--post", "http://dash"],
                   poster=lambda *a: pytest.fail("must not post")) == 1
    assert not (run / "run_annotation.json").exists()


def test_import_refuses_missing_annotated_image(tmp_path):
    run, *_ = make_run(tmp_path)
    (run / f"{OBS_ID}_annotated.jpg").unlink()
    assert ei.main(["--run-dir", str(run), *ARGS]) == 1
    assert not (run / "run_annotation.json").exists()


def test_annotation_is_never_overwritten(tmp_path):
    run, *_ = make_run(tmp_path)
    assert ei.main(["--run-dir", str(run), *ARGS]) == 0
    first = (run / "run_annotation.json").read_bytes()
    assert ei.main(["--run-dir", str(run), *ARGS]) == 0          # same content: reused
    other = [x if x != "LIVE_HARDWARE_PERSON_PRESENT" else "LIVE_HARDWARE_OBJECT_SCENE"
             for x in ARGS]
    assert ei.main(["--run-dir", str(run), *other]) == 1          # different: refused
    assert (run / "run_annotation.json").read_bytes() == first


# -- dashboard: provenance, display, duplicates, review ------------------------
def test_dashboard_shows_run_context_and_provenance(tmp_path):
    run, s, png, jpg = make_run(tmp_path)
    c, store, poster = client_for(run)
    assert ei.main(["--run-dir", str(run), *ARGS, "--post", "http://dash"], poster=poster) == 0
    st = c.get("/state").json()
    assert len(st["tracks"]) == 1
    t = st["tracks"][0]
    L = t["latest"]
    assert L["obs_id"] == OBS_ID and L["confirmation"] == "unconfirmed"
    assert L["obs_time"] == s["obs_time"] == pytest.approx(T_CAP, abs=1e-3)
    assert L["detector_score"] == 0.9996 and L["confidence"] is None
    assert L["detected_class"].startswith("person")
    assert L["bbox"] == [50, 10, 30, 50] and L["frame_size"] == [128, 72]
    assert L["cell"] == "G" and L["cell_source"] == "OPERATOR_ASSIGNED" and L["how"] == "SECTOR_ONLY"
    assert L["badge"] == "LIVE-HW (bench)"
    cam = L["camera"]
    assert cam["label"] == "Raspberry Pi 5 IMX708 camera" and cam["rotation_deg"] == 180
    assert cam["capture_clock"] == "sensor"
    r = L["run"]
    assert r["label"] == "LIVE HARDWARE — PERSON PRESENT"
    assert r["counts_as_empty_scene"] is False and r["run_id"] == "D1-b1700000000-empty"
    assert r["processed_fps"] == 4.75 and r["consent_status"] == "CONSENTED"
    assert "SYNTHETIC" in st["graph"]["label"]
    for k in ("lat", "lon", "xy_m", "distance_m"):
        assert k not in L


def test_dashboard_serves_original_and_annotated_images(tmp_path):
    run, s, png, jpg = make_run(tmp_path)
    c, store, poster = client_for(run)
    assert ei.main(["--run-dir", str(run), *ARGS, "--post", "http://dash"], poster=poster) == 0
    L = c.get("/state").json()["tracks"][0]["latest"]
    a = c.get(L["annotated_url"])
    f = c.get(L["frame_url"])
    assert a.status_code == 200 and a.headers["content-type"] == "image/jpeg" and a.content == jpg
    assert f.status_code == 200 and f.headers["content-type"] == "image/png" and f.content == png
    assert SHA(f.content) == L["frame_sha256"]


def test_reimport_is_a_duplicate_not_a_new_record(tmp_path):
    run, s, *_ = make_run(tmp_path)
    c, store, poster = client_for(run)
    seen = []

    def spy(url, obj):
        code, body = poster(url, obj)
        seen.append((url, body))
        return code, body
    for _ in range(2):
        assert ei.main(["--run-dir", str(run), *ARGS, "--post", "http://dash"], poster=spy) == 0
    obs = [b for u, b in seen if u.endswith("/observations")]
    assert obs[0]["duplicate"] is False and obs[1]["duplicate"] is True
    # the same evidence frame under another obs_id is also a duplicate
    s2 = dict(s, obs_id="D1-b1700000000-000002", seq=2)
    assert c.post("/observations", json=s2).json()["duplicate_of"] == OBS_ID
    st = c.get("/state").json()
    assert len(st["tracks"]) == 1 and st["tracks"][0]["n_observations"] == 1
    assert len(st["alerts"]) == 1


def test_operator_review_confirm_and_reject(tmp_path):
    run, *_ = make_run(tmp_path)
    c, store, poster = client_for(run)
    ei.main(["--run-dir", str(run), *ARGS, "--post", "http://dash"], poster=poster)
    assert c.post("/operator_decision", json={"obs_id": OBS_ID, "decision": "CONFIRM",
                                              "operator": ""}).status_code == 422
    assert c.get("/state").json()["tracks"][0]["latest"]["confirmation"] == "unconfirmed"
    r = c.post("/operator_decision", json={"obs_id": OBS_ID, "decision": "REJECT",
                                           "operator": "reviewer"})
    assert r.status_code == 200 and r.json()["confirmation"] == "rejected"
    L = c.get("/state").json()["tracks"][0]["latest"]
    assert L["confirmation"] == "rejected" and L["decided_by"] == "reviewer"
    assert L["run"]["label"] == "LIVE HARDWARE — PERSON PRESENT"     # context kept
    c.post("/operator_decision", json={"obs_id": OBS_ID, "decision": "CONFIRM",
                                       "operator": "reviewer"})
    assert c.get("/state").json()["tracks"][0]["latest"]["confirmation"] == "confirmed"


def test_annotation_with_wrong_checksum_is_not_shown(tmp_path):
    run, s, *_ = make_run(tmp_path)
    c, store, poster = client_for(run)
    ei.main(["--run-dir", str(run), *ARGS])
    ann = json.loads((run / "run_annotation.json").read_text())
    ann["evidence"][OBS_ID]["frame_sha256"] = "f" * 64
    assert c.post("/run_annotations", json=ann).status_code == 200
    assert c.post("/observations", json=s).status_code == 200
    r = c.get("/state").json()["tracks"][0]["latest"]["run"]
    assert r["label"] is None and "does not match" in r["error"]


# -- contract / consent ---------------------------------------------------------
def _ann(tmp_path):
    run, *_ = make_run(tmp_path)
    ei.main(["--run-dir", str(run), *ARGS])
    return json.loads((run / "run_annotation.json").read_text())


@pytest.mark.parametrize("mutate,msg", [
    (lambda a: a.update(counts_as_empty_scene=True), "EMPTY_SCENE"),
    (lambda a: a["consent"].update(status="NOT_RECORDED"), "consent"),
    (lambda a: a["consent"].update(scope=["capture", "storage"]), "dashboard_display"),
    (lambda a: a["consent"].update(public_sharing=True), "public_sharing"),
    (lambda a: a["evidence"][OBS_ID].update(frame_sha256_matches_sighting=False), "verified"),
    (lambda a: a.update(classification="FREE TEXT LABEL"), "classification"),
])
def test_run_annotation_contract_rejects(tmp_path, mutate, msg):
    ann = _ann(tmp_path)
    mutate(ann)
    with pytest.raises(ra.InvalidRunAnnotation, match=msg):
        ra.validate(ann)


def test_import_without_consent_cannot_mark_person_present(tmp_path):
    run, *_ = make_run(tmp_path)
    args = ["--obs-id", OBS_ID, "--classification", "LIVE_HARDWARE_PERSON_PRESENT"]
    assert ei.main(["--run-dir", str(run), *args]) == 1
    assert not (run / "run_annotation.json").exists()


def test_page_renders_run_bbox_links_and_synthetic_sector():
    html = (STATIC / "index.html").read_text()
    for needle in ('id="run-chip"', 'id="bbox"', 'id="detected-class"', 'id="link-original"',
                   'id="link-annotated"', "OPERATOR-ASSIGNED / SYNTHETIC",
                   "Excluded from the empty-scene false-positive rate",
                   "No identity, injury, medical condition or distance is inferred"):
        assert needle in html, needle


# -- run-level score, live delivery latency, primary image ----------------------
def add_person_scores(run, scores):
    p = next(run.glob("*_frames.jsonl"))
    rows = [json.loads(l) for l in p.read_text().splitlines()]
    for r, sc in zip(rows, scores):
        r["best"] = {"PERSON_DETECTOR": {"score": sc, "bbox": [50, 10, 30, 50]} if sc else None}
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_run_score_median_is_separate_from_frame_score(tmp_path):
    run, s, *_ = make_run(tmp_path)
    add_person_scores(run, [0.97, 0.99, 0.98, None, 0.99, 0.99, 0.98, 0.99, 0.99, 0.99])
    c, store, poster = client_for(run)
    assert ei.main(["--run-dir", str(run), *ARGS, "--post", "http://dash"], poster=poster) == 0
    L = c.get("/state").json()["tracks"][0]["latest"]
    assert L["detector_score"] == 0.9996                       # sighting frame
    r = L["run"]
    assert r["person_score_median"] == 0.99 and r["person_frames"] == 9   # whole run
    assert r["person_score_min"] == 0.97 and r["person_score_max"] == 0.99


def _state_with(s, rx_delay):
    return {"tracks": [{"latest": {"obs_id": s["obs_id"], "obs_time": s["obs_time"],
                                   "rx_time": s["obs_time"] + rx_delay}, "history": []}]}


def test_live_delivery_latency_recorded_and_kept_across_reload(tmp_path, monkeypatch):
    run, s, *_ = make_run(tmp_path)
    monkeypatch.setattr(ei, "live_delivery",
                        lambda base, s_: {"capture_to_dashboard_s": 0.499, "source": "test"})
    assert ei.main(["--run-dir", str(run), *ARGS, "--live-from", "http://dash"]) == 0
    ann = json.loads((run / "run_annotation.json").read_text())
    assert ann["measured"]["live_delivery"]["capture_to_dashboard_s"] == 0.499
    # a later import (e.g. after a dashboard restart) without --live-from keeps it
    c, store, poster = client_for(run)
    assert ei.main(["--run-dir", str(run), *ARGS, "--post", "http://dash"], poster=poster) == 0
    r = c.get("/state").json()["tracks"][0]["latest"]["run"]
    assert r["live_capture_to_dashboard_s"] == 0.499


def test_live_delivery_reads_dashboard_and_rejects_reloaded_records(tmp_path):
    run, s, *_ = make_run(tmp_path)
    got = ei.live_delivery("http://dash", s, getter=lambda u: _state_with(s, 0.4988))
    assert got["capture_to_dashboard_s"] == 0.499
    with pytest.raises(ei.ImportRefused, match="not a live delivery"):
        ei.live_delivery("http://dash", s, getter=lambda u: _state_with(s, 1840.6))
    with pytest.raises(ei.ImportRefused, match="not on"):
        ei.live_delivery("http://dash", dict(s, obs_id="D1-b1-000009"),
                         getter=lambda u: _state_with(s, 0.5))


def test_annotation_rewrite_only_from_same_run_files(tmp_path):
    run, *_ = make_run(tmp_path)
    assert ei.main(["--run-dir", str(run), *ARGS]) == 0
    ann_path = run / "run_annotation.json"
    old = json.loads(ann_path.read_text())
    old["measured"].pop("person_score_median")         # an older tool version
    ann_path.write_text(json.dumps(old))
    assert ei.main(["--run-dir", str(run), *ARGS]) == 0  # same files: recomputed, rewritten
    assert "person_score_median" in json.loads(ann_path.read_text())["measured"]
    f = next(run.glob("*_frames.jsonl"))
    f.write_text(f.read_text() + json.dumps({"t": 1, "rx": 2, "all": []}) + "\n")
    before = ann_path.read_text()
    assert ei.main(["--run-dir", str(run), *ARGS]) == 0  # different files: left alone
    assert ann_path.read_text() == before


def test_newest_sighting_is_primary_and_older_stays_in_history(tmp_path):
    run, s, png, jpg = make_run(tmp_path)
    c, store, poster = client_for(run)
    ei.main(["--run-dir", str(run), *ARGS, "--post", "http://dash"], poster=poster)
    newer = json.loads(json.dumps(s))
    newer.update(obs_id="D1-b1700000100-000001", boot_id="b1700000100",
                 obs_time=s["obs_time"] + 100)
    newer["evidence"]["camera"]["capture_time"] = newer["obs_time"]
    newer["evidence"]["frame_sha256"] = "a" * 64
    newer.pop("obs_time_iso")
    assert c.post("/observations", json=newer).json()["duplicate"] is False
    st = c.get("/state").json()
    assert len(st["tracks"]) == 1 and len(st["alerts"]) == 2
    T = st["tracks"][0]
    assert T["latest"]["obs_id"] == newer["obs_id"]
    assert [h["obs_id"] for h in T["history"]] == [OBS_ID]
    assert T["history"][0]["run"]["label"] == "LIVE HARDWARE — PERSON PRESENT"


def test_page_has_run_score_frame_score_and_live_latency():
    html = (STATIC / "index.html").read_text()
    for needle in ('id="run-score"', 'id="frame-score"', 'id="live-latency"',
                   "for this sighting frame only", "measured at live delivery"):
        assert needle in html, needle

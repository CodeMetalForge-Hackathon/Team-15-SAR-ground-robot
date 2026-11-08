"""Issue #4 live path: camera sighting -> bridge -> POST /observations -> /state -> map.

Sightings are built with the camera's own ``perception.sightings.make_sighting``,
so a format change on the camera side breaks these tests.
"""
import hashlib
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from core.camera_bridge import forward
from core.store import MissionStore
from dashboard.app import create_app
from perception.detectors import FACE_ONLY, PERSON_DETECTOR, Detection
from perception.sightings import make_sighting
from planner.graph import load_graph

REPO = Path(__file__).resolve().parents[2]
T0 = 1794081444.6                     # obs_time of a real bench run (empty60f)

OLD_HAAR_OBS = {                      # the first bench observation (PR #3, Haar face)
    "obs_id": "D1-b1-000001", "drone_id": "D1", "source_mode": "LIVE-HW", "platform": "BENCH",
    "sensor": "rgb", "kind": "PERSON_VISUAL", "how": "SECTOR_ONLY", "cell": "G",
    "obs_time": 1794077187.974565, "confidence": None,
    "evidence": {"frame_ref": "PLACEHOLDER", "bbox": [897, 351, 390, 390],
                 "detector": "opencv_haar_frontalface_default",
                 "detector_score": 6.74, "detector_score_kind": "haar_level_weight"},
}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def evdir(tmp_path):
    d = tmp_path / "Team15_evidence" / "camera"
    d.mkdir(parents=True)
    return d


def camera_sighting(evdir: Path, seq: int, obs_time: float, *, boot="b1794081444",
                    sector="G", payload=None):
    """One sighting exactly as perception/live_camera.py emits it, plus its files."""
    obs_id = f"D1-{boot}-{seq:06d}"
    png = evdir / f"{obs_id}.png"
    png.write_bytes(payload if payload is not None else f"png-{obs_id}".encode())
    ann = evdir / f"{obs_id}_annotated.jpg"
    ann.write_bytes(b"\xff\xd8annotated-" + obs_id.encode() + b"\xff\xd9")
    trig = Detection([842, 512, 196, 565], "torchvision_frcnn_r50_fpn_v2_coco", 0.9997,
                     "frcnn_class_score", PERSON_DETECTOR)
    face = Detection([954, 159, 651, 651], "opencv_haar_frontalface_default", 0.16,
                     "haar_level_weight", FACE_ONLY)
    s = make_sighting(drone_id="D1", boot_id=boot, seq=seq, sector=sector, obs_time=obs_time,
                      frame_ref=str(png), frame_sha256=hashlib.sha256(png.read_bytes()).hexdigest(),
                      annotated_ref=str(ann), frame_size=[1920, 1080], trigger=trig,
                      all_dets=[trig, face], operator=None)
    return json.loads(json.dumps(s)), png, ann


@pytest.fixture
def live(evdir, tmp_path):
    old_dir = tmp_path / "Documents" / "Team-15-evidence" / "camera"
    old_dir.mkdir(parents=True)
    old_photo = old_dir / "D1-b1-000001_1794077187.jpg"
    old_photo.write_bytes(b"\xff\xd8old-haar\xff\xd9")
    clock = Clock(T0 + 10)
    store = MissionStore(responder_node="A", clock=clock)
    client = TestClient(create_app(store, evidence_dir=[evdir, old_dir]))
    old = json.loads(json.dumps(OLD_HAAR_OBS))
    old["evidence"]["frame_ref"] = str(old_photo)
    return client, store, clock, old


def via_bridge(client, lines):
    """Run the real bridge, with the HTTP POST going to the in-process app."""
    def post(url, obj):
        r = client.post("/observations", json=obj)
        return r.status_code, r.json()
    return forward(lines, "http://test/observations", post=post, log=lambda m: None)


def test_camera_sighting_reaches_dashboard_through_bridge(live, evdir):
    client, _store, _clock, _old = live
    s, png, ann = camera_sighting(evdir, 1, T0)
    stats = via_bridge(client, [json.dumps(s) + "\n"])
    assert stats["new"] == 1 and stats["undelivered"] == 0

    st = client.get("/state").json()
    [t] = st["tracks"]
    L = t["latest"]
    assert t["label"] == "Candidate in sector G (assigned)"
    assert L["obs_id"] == "D1-b1794081444-000001"
    assert L["badge"] == "LIVE-HW (bench)" and L["platform"] == "BENCH"
    assert L["confirmation"] == "unconfirmed"
    assert L["detector"] == "torchvision_frcnn_r50_fpn_v2_coco"
    assert L["detector_family"] == "PERSON_DETECTOR"
    assert L["detector_score_kind"] == "frcnn_class_score" and L["confidence"] is None
    assert L["cell_source"] == "OPERATOR_ASSIGNED"
    assert L["obs_time"] == T0 and L["obs_time_iso"].startswith("2026-11-07T")
    assert L["age_s"] == pytest.approx(10.0) and L["stale"] is False
    # display photo = annotated JPEG; /frame = the exact PNG evidence
    r = client.get(L["photo_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content == ann.read_bytes()
    r = client.get(L["frame_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content == png.read_bytes()
    assert str(evdir) not in json.dumps(st)    # no local paths published
    [route] = st["routes"]
    assert route["path"] == list("ABCDEFG") and route["length_m"] == 60 and route["active"]


def test_old_haar_observation_kept_as_history(live, evdir):
    client, _store, _clock, old = live
    client.post("/observations", json=old)
    s, _png, _ann = camera_sighting(evdir, 1, T0)
    via_bridge(client, [json.dumps(s)])
    st = client.get("/state").json()
    [t] = st["tracks"]                          # same sector, same candidate: no extra person
    assert t["n_observations"] == 2
    assert t["latest"]["obs_id"] == "D1-b1794081444-000001"
    assert [h["obs_id"] for h in t["history"]] == ["D1-b1-000001"]
    h = t["history"][0]
    assert h["detector"] == "opencv_haar_frontalface_default"
    assert h["detector_family"] is None         # old format never reported it; not invented
    assert client.get(h["photo_url"]).status_code == 200
    assert len(st["routes"]) == 1               # destination unchanged: still v1 A->G 60 m
    assert [a["obs_id"] for a in st["alerts"]] == ["D1-b1-000001", "D1-b1794081444-000001"]


def test_duplicate_lines_and_frames_add_no_person_or_alert(live, evdir):
    client, _store, _clock, _old = live
    s, _png, _ann = camera_sighting(evdir, 1, T0, payload=b"same-frame")
    line = json.dumps(s)
    stats = via_bridge(client, [line, line, line])
    assert (stats["new"], stats["duplicate"]) == (1, 2)
    # same evidence frame re-sent under a new obs_id (e.g. a second boot replaying it)
    again, _p, _a = camera_sighting(evdir, 1, T0 + 1, boot="b1794081999", payload=b"same-frame")
    r = client.post("/observations", json=again).json()
    assert r["duplicate"] is True and r["duplicate_of"] == s["obs_id"]
    st = client.get("/state").json()
    assert len(st["tracks"]) == 1 and st["tracks"][0]["n_observations"] == 1
    assert len(st["alerts"]) == 1 and len(st["routes"]) == 1


def test_sighting_stays_unconfirmed_until_operator_decides(live, evdir):
    client, _store, _clock, _old = live
    s, _png, _ann = camera_sighting(evdir, 1, T0)
    s["confirmation"] = "confirmed"             # a sender cannot self-confirm
    client.post("/observations", json=s)
    latest = lambda: client.get("/state").json()["tracks"][0]["latest"]
    assert latest()["confirmation"] == "unconfirmed"

    oid = s["obs_id"]
    assert client.post("/operator_decision", json={"obs_id": oid, "decision": "CONFIRM"}).status_code == 422
    assert client.post("/operator_decision",
                       json={"obs_id": oid, "decision": "MAYBE", "operator": "OP1"}).status_code == 422
    assert client.post("/operator_decision",
                       json={"obs_id": "D1-b1-999999", "decision": "CONFIRM", "operator": "OP1"}).status_code == 404
    assert latest()["confirmation"] == "unconfirmed"

    r = client.post("/operator_decision", json={"obs_id": oid, "decision": "CONFIRM", "operator": "OP1"})
    assert r.status_code == 200
    assert (latest()["confirmation"], latest()["decided_by"]) == ("confirmed", "OP1")


def test_rejecting_the_only_sighting_drops_the_route_until_a_new_one(live, evdir):
    client, _store, clock, _old = live
    s, _png, _ann = camera_sighting(evdir, 1, T0)
    client.post("/observations", json=s)
    client.post("/operator_decision", json={"obs_id": s["obs_id"], "decision": "REJECT", "operator": "OP1"})
    st = client.get("/state").json()
    assert st["tracks"][0]["latest"]["confirmation"] == "rejected"
    assert not any(r["active"] for r in st["routes"])

    clock.t = T0 + 90
    s2, _p, _a = camera_sighting(evdir, 2, T0 + 80)
    client.post("/observations", json=s2)
    routes = client.get("/state").json()["routes"]
    active = [r for r in routes if r["active"]]
    assert len(active) == 1 and active[0]["version"] == 2 and active[0]["length_m"] == 60


def test_route_follows_new_sector_using_only_known_trail_edges(live, evdir):
    client, _store, _clock, _old = live
    client.post("/observations", json=camera_sighting(evdir, 1, T0)[0])
    client.post("/observations", json=camera_sighting(evdir, 2, T0 + 5, sector="K")[0])
    st = client.get("/state").json()
    assert [t["cell"] for t in st["tracks"]] == ["G", "K"]
    active = [r for r in st["routes"] if r["active"]]
    assert len(active) == 1 and active[0]["to"] == "K" and active[0]["version"] == 2
    known = {frozenset((a, b)) for a, b, _m in load_graph().edges()}
    for a, b in zip(active[0]["path"], active[0]["path"][1:]):
        assert frozenset((a, b)) in known
    assert active[0]["path"] == ["A", "B", "C", "J", "K"] and active[0]["length_m"] == 40


def test_unreachable_sector_reports_no_known_route(live, evdir):
    client, _store, _clock, _old = live
    client.post("/observations", json=camera_sighting(evdir, 1, T0, sector="Y")[0])
    [route] = client.get("/state").json()["routes"]
    assert route["status"] == "NO_KNOWN_ROUTE" and route["path"] == [] and route["length_m"] is None


def test_simulated_sighting_is_badged_simulated(live, evdir):
    client, _store, _clock, _old = live
    s, _p, _a = camera_sighting(evdir, 1, T0)
    s.update(source_mode="SIMULATED", platform="SIM")
    client.post("/observations", json=s)
    assert client.get("/state").json()["tracks"][0]["badge"] == "SIMULATED"


def test_bridge_skips_junk_and_reports_undelivered():
    calls = []

    def down(url, obj):
        calls.append(obj["obs_id"])
        raise urllib.error.URLError("connection refused")

    logs = []
    stats = forward(["not json\n", "[1, 2]\n", json.dumps({"obs_id": "D1-b1-000001"})],
                    "http://x/observations", retry_s=0, post=down, sleep=lambda s: None,
                    log=logs.append)
    assert stats["skipped"] == 2 and stats["undelivered"] == 1 and stats["sent"] == 0
    assert any("NOT DELIVERED" in m for m in logs)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_end_to_end_pipe_into_real_server(evdir):
    """Camera stdout piped into the bridge process, over real HTTP, into a running server."""
    store = MissionStore(responder_node="A")
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(store, evidence_dir=evdir),
                                           host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        s1, _p, _a = camera_sighting(evdir, 1, time.time() - 3)
        stdin = "camera warming up\n" + json.dumps(s1) + "\n" + json.dumps(s1) + "\n"
        proc = subprocess.run([sys.executable, "-B", "-m", "core.camera_bridge",
                               "--post", f"http://127.0.0.1:{port}/observations", "--retry-s", "5"],
                              input=stdin, capture_output=True, text=True, cwd=REPO, timeout=30)
        assert proc.returncode == 0, proc.stderr
        assert '"new": 1' in proc.stderr and '"duplicate": 1' in proc.stderr and '"skipped": 1' in proc.stderr
        st = store.state()
        assert st["tracks"][0]["latest"]["obs_id"] == s1["obs_id"]
        assert st["tracks"][0]["latest"]["confirmation"] == "unconfirmed"
        assert st["routes"][0]["length_m"] == 60
    finally:
        server.should_exit = True
        th.join(timeout=5)

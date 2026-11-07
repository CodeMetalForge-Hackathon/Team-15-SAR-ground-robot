"""Pi 5 IMX708 camera -> Mac detector -> bridge -> dashboard (issue #4).

Runs the real ``perception.live_camera --source pi`` and ``PiCameraSource``
(PR #3, ``4d3093d``) against a fake Pi sender that writes the same
T15HELLO/T15FRAME stream as the real sender, so no Pi is needed in CI. The
fake frames are UPSIDE DOWN (bright block bottom-right), as the inverted mount
delivers them, and carry capture times near the dashboard clock, so the tests
can check that the rotation is applied exactly once and that the Pi capture
time survives to the dashboard unchanged.
"""
import contextlib
import hashlib
import io
import json
import sys
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from core.camera_bridge import forward
from core.store import MissionStore
from dashboard.app import create_app
from perception import live_camera
from perception.detectors import FULL_BODY_HOG, Detection
from perception.pi_source import PiCameraSource, open_pi_camera
from perception.sightings import iso_utc, make_sighting

BASE_T = 1794090000.0          # fake Pi capture clock: BASE_T + 0.2 * seq
W, H = 320, 180
PI_LABEL = "Raspberry Pi 5 IMX708 camera"

FAKE_PI_SENDER = r'''
import json, sys, time
import cv2, numpy as np
mode, W, H, BASE_T = sys.argv[1], 320, 180, 1794090000.0
out = sys.stdout.buffer
def jpeg(seq):
    img = np.full((H, W, 3), 40, np.uint8)
    img[H // 2:, W // 2:] = 255                 # camera is mounted upside down:
    cv2.putText(img, str(seq), (5, 30), 0, 1, (0, 0, 255), 2)   # marker arrives bottom-right
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
def frame(seq):
    data = jpeg(seq)
    hdr = {"seq": seq, "t_capture": BASE_T + 0.2 * seq, "clock": "sensor", "len": len(data)}
    out.write(b"T15FRAME " + json.dumps(hdr).encode() + b"\n" + data); out.flush()
out.write(b"T15HELLO " + json.dumps({"sensor_model": "imx708",
          "pi_model": "Raspberry Pi 5 Model B Rev 1.1", "size": [W, H], "fps": 5,
          "jpeg_quality": 90, "clock": "fake"}).encode() + b"\n"); out.flush()
if mode == "stream":
    for seq in range(1, 400):
        frame(seq); time.sleep(0.05)
elif mode == "burst":
    for seq in range(1, 31):
        frame(seq)
    time.sleep(30)
'''


def fake_cmd(mode):
    return [sys.executable, "-u", "-", mode]


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class AlwaysPerson:
    """Stands in for the detectors (CI has no torch): one tall box per frame."""
    name = "fake"

    def detect_all(self, frame):
        h, w = frame.shape[:2]
        return [Detection([w // 4, h // 8, w // 3, int(h * 0.7)], "fake_full_body",
                          1.0, "fake_score", FULL_BODY_HOG)]


def bright_quadrant(img):
    h, w = img.shape[:2]
    q = {"tl": img[: h // 2, : w // 2], "tr": img[: h // 2, w // 2:],
         "bl": img[h // 2:, : w // 2], "br": img[h // 2:, w // 2:]}
    return max(q, key=lambda k: float(q[k].mean()))


@pytest.fixture(scope="module")
def pi_run(tmp_path_factory):
    """One real `live_camera --source pi --once` run against the fake Pi sender."""
    out_dir = tmp_path_factory.mktemp("pi") / "Team15_evidence" / "camera"

    def fake_open(**kw):
        for k in ("host", "user", "key", "port", "size", "fps", "jpeg_quality"):
            kw.pop(k)
        return open_pi_camera(command=fake_cmd("stream"), script=FAKE_PI_SENDER,
                              log=lambda m: None, **kw)

    buf = io.StringIO()
    with pytest.MonkeyPatch.context() as mp, contextlib.redirect_stdout(buf), \
            contextlib.redirect_stderr(io.StringIO()):
        mp.setattr(live_camera, "open_pi_camera", fake_open)
        mp.setattr(live_camera, "OpenCVDetectors", AlwaysPerson)
        rc = live_camera.main(["--source", "pi", "--pi-host", "unused", "--sector", "G",
                               "--no-dnn", "--trigger", "any", "--once",
                               "--duration-s", "20", "--out-dir", str(out_dir)])
    assert rc == live_camera.EXIT_OK
    lines = [l for l in buf.getvalue().splitlines() if l.strip()]
    assert len(lines) == 1                       # stdout is exactly one sighting line
    return lines[0], out_dir


@pytest.fixture
def env(pi_run):
    line, out_dir = pi_run
    s = json.loads(line)
    clock = Clock(s["obs_time"] + 0.9)           # dashboard gets it 0.9 s after capture
    store = MissionStore(responder_node="A", clock=clock)
    client = TestClient(create_app(store, evidence_dir=out_dir))
    return client, store, clock, line, out_dir


def bridge(client, lines):
    def post(url, obj):
        r = client.post("/observations", json=obj)
        return r.status_code, r.json()
    return forward(lines, "http://test/observations", post=post, log=lambda m: None)


# ---- the full chain ------------------------------------------------------------
def test_pi_camera_sighting_reaches_dashboard_with_pi_capture_time(env):
    client, _store, _clock, line, _out = env
    s = json.loads(line)
    assert bridge(client, [line])["new"] == 1

    st = client.get("/state").json()
    [t] = st["tracks"]
    L = t["latest"]
    pi_seq = s["evidence"]["camera"]["pi_frame_seq"]
    assert L["obs_time"] == pytest.approx(BASE_T + 0.2 * pi_seq, abs=1e-3)  # Pi capture time
    assert L["obs_time"] == s["obs_time"]                                   # unchanged
    assert L["obs_time_iso"] == iso_utc(s["obs_time"])
    assert L["rx_time"] == pytest.approx(s["obs_time"] + 0.9)               # kept separately
    assert L["capture_to_ingest_s"] == pytest.approx(0.9)
    assert L["age_s"] == pytest.approx(0.9) and L["clock_skew"] is False
    cam = L["camera"]
    assert (cam["kind"], cam["source"], cam["label"]) == ("PI", "pi5-imx708", PI_LABEL)
    assert cam["pi_model"] == "Raspberry Pi 5 Model B Rev 1.1" and cam["sensor_model"] == "imx708"
    assert (cam["transport"], cam["capture_clock"]) == ("ssh-jpeg", "sensor")
    assert cam["capture_clock_label"].startswith("Pi sensor timestamp")
    assert (cam["rotation_deg"], cam["rotation_applied_by"]) == (180, "receiver")
    assert cam["frame_seq"] == pi_seq and cam["capture_to_rx_s"] > 0
    assert (L["badge"], L["platform"], L["how"], L["cell_source"]) == \
        ("LIVE-HW (bench)", "BENCH", "SECTOR_ONLY", "OPERATOR_ASSIGNED")
    assert L["confirmation"] == "unconfirmed"
    assert t["label"] == "Candidate in sector G (assigned)"
    assert st["alerts"][-1]["camera"] == PI_LABEL
    [route] = st["routes"]
    assert route["path"] == list("ABCDEFG") and route["length_m"] == 60
    # evidence photo: served, and upright (rotated exactly once, by the receiver)
    r = client.get(L["frame_url"])
    assert r.status_code == 200
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (H, W) and bright_quadrant(img) == "tl"
    assert client.get(L["photo_url"]).status_code == 200


def test_every_camera_field_is_kept_unchanged(env):
    client, store, _clock, line, _out = env
    s = json.loads(line)
    client.post("/observations", json=s)
    stored = store.observation(s["obs_id"])
    for k, v in s.items():
        assert stored[k] == v, k


def test_local_mac_camera_sightings_are_still_accepted(env):
    client, _store, clock, line, out_dir = env
    pi = json.loads(line)
    png = out_dir / "mac-test.png"
    cv2.imwrite(str(png), np.full((H, W, 3), 99, np.uint8))
    trig = Detection([10, 10, 50, 120], "torchvision_frcnn_r50_fpn_v2_coco", 0.99,
                     "frcnn_class_score", "PERSON_DETECTOR")
    mac = make_sighting(drone_id="D1", boot_id="b1794090555", seq=1, sector="G",
                        obs_time=pi["obs_time"] + 3, frame_ref=str(png),
                        frame_sha256=hashlib.sha256(png.read_bytes()).hexdigest(),
                        annotated_ref=None, frame_size=[W, H], trigger=trig, all_dets=[trig],
                        camera=live_camera.local_camera_info(0))
    clock.t = pi["obs_time"] + 5
    stats = bridge(client, [line, json.dumps(mac)])
    assert stats["new"] == 2 and stats["rejected"] == 0
    st = client.get("/state").json()
    [t] = st["tracks"]                            # same sector: one candidate, not two people
    assert t["n_observations"] == 2
    assert (t["latest"]["camera"]["kind"], t["latest"]["camera"]["label"]) == ("LOCAL", "MacBook camera")
    assert t["latest"]["camera"]["capture_clock"] == "receiver_wall_at_read"
    assert t["history"][0]["camera"]["label"] == PI_LABEL
    assert [a["camera"] for a in st["alerts"]] == [PI_LABEL, "MacBook camera"]
    assert len(st["routes"]) == 1


def test_repeated_pi_sightings_add_no_person_or_alert(env):
    client, _store, _clock, line, _out = env
    stats = bridge(client, [line, line, line])
    assert (stats["new"], stats["duplicate"]) == (1, 2)
    again = json.loads(line)                      # same evidence frame, new obs_id (restart)
    again["obs_id"], again["boot_id"] = again["obs_id"].replace(again["boot_id"], "b1"), "b1"
    r = client.post("/observations", json=again).json()
    assert r["duplicate"] is True and r["duplicate_of"] == json.loads(line)["obs_id"]
    st = client.get("/state").json()
    assert len(st["tracks"]) == 1 and st["tracks"][0]["n_observations"] == 1
    assert len(st["alerts"]) == 1 and len(st["routes"]) == 1


# ---- what a Pi sighting may never be ------------------------------------------
def _receive_time_instead_of_capture(s):
    rx = s["evidence"]["camera"]["rx_time"]
    s["obs_time"], s["obs_time_iso"] = rx, iso_utc(rx)


@pytest.mark.parametrize("mutate, why", [
    (lambda s: s.update(platform="AIRCRAFT"), "platform"),
    (lambda s: s.update(source_mode="SIMULATED"), "source_mode"),
    (lambda s: s.update(cell_source="MEASURED"), "cell_source"),
    (lambda s: s.update(how="GROUND_PLANE"), "how"),
    (lambda s: s.update(xy_m=[63.0, 4.0]), "coordinates"),
    (lambda s: s.update(lat=42.35, lon=-71.06), "coordinates"),
    (lambda s: s["evidence"]["camera"].update(capture_clock="receiver_wall_at_read"), "Mac clock"),
    (lambda s: s["evidence"]["camera"].update(transport="local"), "transport"),
    (lambda s: s["evidence"]["camera"].update(source="gopro"), "unknown camera"),
    (_receive_time_instead_of_capture, "Mac receive time as obs_time"),
    (lambda s: s.update(obs_time=s["obs_time"] + 5), "obs_time_iso mismatch"),
])
def test_pi_sightings_must_stay_bench_sector_only_and_pi_timed(env, mutate, why):
    client, _store, _clock, line, _out = env
    s = json.loads(line)
    mutate(s)
    r = client.post("/observations", json=s)
    assert r.status_code == 422, why
    assert client.get("/state").json()["tracks"] == []


def test_pi_wall_clock_fallback_is_accepted_and_labelled(env):
    client, _store, _clock, line, _out = env
    s = json.loads(line)
    s["evidence"]["camera"]["capture_clock"] = "pi_wall_at_request"
    assert client.post("/observations", json=s).status_code == 200
    cam = client.get("/state").json()["tracks"][0]["latest"]["camera"]
    assert "sensor timestamp unavailable" in cam["capture_clock_label"]


def test_pi_sighting_cannot_self_confirm(env):
    client, _store, _clock, line, _out = env
    s = json.loads(line)
    s.update(confirmation="confirmed", decided_by="camera")
    client.post("/observations", json=s)
    L = client.get("/state").json()["tracks"][0]["latest"]
    assert (L["confirmation"], L["decided_by"]) == ("unconfirmed", None)


def test_future_capture_time_is_flagged_not_hidden(env):
    client, _store, clock, line, _out = env
    s = json.loads(line)
    clock.t = s["obs_time"] - 10                  # Pi clock 10 s ahead of the dashboard
    client.post("/observations", json=s)
    L = client.get("/state").json()["tracks"][0]["latest"]
    assert L["clock_skew"] is True and L["obs_time"] == s["obs_time"]


def test_old_sightings_without_camera_still_accepted(env):
    client, _store, _clock, line, _out = env
    s = json.loads(line)
    del s["evidence"]["camera"]
    assert client.post("/observations", json=s).status_code == 200
    cam = client.get("/state").json()["tracks"][0]["latest"]["camera"]
    assert cam["source"] is None and cam["label"] == "camera not reported"


def test_page_shows_camera_provenance(env):
    html = env[0].get("/").text
    for needle in ("camera-chip", "camera-detail", "capture_clock_label", "capture→dashboard"):
        assert needle in html


# ---- PiCameraSource behaviour the dashboard relies on ---------------------------
def test_pi_source_newest_frame_only_rotated_once_with_capture_time():
    src = PiCameraSource(command=fake_cmd("burst"), script=FAKE_PI_SENDER, rotation=180,
                         log=lambda m: None).start()
    try:
        deadline = time.time() + 10
        while src.stats["frames_received"] < 30 and time.time() < deadline:
            time.sleep(0.05)
        ok, frame = src.read(timeout_s=3)
        assert ok and src.last_header["seq"] == 30            # newest of the burst
        assert src.last_capture_time == pytest.approx(BASE_T + 0.2 * 30)
        assert src.last_rx_time != src.last_capture_time      # arrival kept separately
        assert src.stats["frames_dropped_stale"] >= 1
        assert bright_quadrant(frame) == "tl"                 # upright after one rotation
        ok2, _ = src.read(timeout_s=0.5)
        assert not ok2                                        # never the same frame twice
        assert src.camera_info()["source"] == "pi5-imx708"
    finally:
        src.release()

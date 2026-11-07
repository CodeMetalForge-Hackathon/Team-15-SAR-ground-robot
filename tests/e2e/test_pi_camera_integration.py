"""Pi 5 IMX708 camera -> Mac detector -> dashboard (issue #4, contracts/PI_CAMERA_CONTRACT.md).

No Pi needed: ``fake_pi_sender.py`` writes the contract's wire format. The
``PiFrameSource`` acceptance tests run once perception/pi_source.py (T1) exists.
"""
import hashlib
import inspect
import io
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from contracts.pi_frame_stream import (MAC_LOCAL, PI5_IMX708, StreamError,
                                       camera_provenance, encode_record, read_record)
from core.camera_bridge import forward
from core.store import MissionStore
from dashboard.app import create_app
from perception.detectors import PERSON_DETECTOR, Detection
from perception.sightings import iso_utc, make_sighting

HERE = Path(__file__).resolve().parent
FAKE = [sys.executable, "-B", str(HERE / "fake_pi_sender.py")]
T0 = 1794090000.0


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


# ---- wire format -------------------------------------------------------------
def test_wire_format_bytes_are_exactly_as_documented():
    hdr = {"seq": 3, "capture_time": 1.25, "w": 2, "h": 1, "rotation": 180}
    rec = encode_record(hdr, b"JPEG")
    h = json.dumps(hdr, separators=(",", ":")).encode()
    assert rec == b"T15F" + struct.pack(">I", len(h)) + h + struct.pack(">I", 4) + b"JPEG"
    assert read_record(io.BytesIO(rec)) == (hdr, b"JPEG")


@pytest.mark.parametrize("raw, err", [
    (b"", EOFError),
    (b"XXXX" + b"\0" * 8, StreamError),                                  # out of sync
    (encode_record({"seq": 0, "capture_time": 1, "w": 1, "h": 1, "rotation": 0}, b"abc")[:-1],
     EOFError),                                                          # truncated
    (b"T15F" + struct.pack(">I", 2) + b"{}" + struct.pack(">I", 0), StreamError),  # no fields
    (b"T15F" + struct.pack(">I", 10**7), StreamError),                   # absurd header
])
def test_wire_format_rejects_bad_streams(raw, err):
    with pytest.raises(err):
        read_record(io.BytesIO(raw))


def read_fake_stream(*args):
    p = subprocess.run(FAKE + list(args), capture_output=True, timeout=60, check=True)
    s, out = io.BytesIO(p.stdout), []
    while True:
        try:
            out.append(read_record(s))
        except EOFError:
            return out


def test_fake_pi_stream_frames_are_upright_with_capture_times():
    recs = read_fake_stream("--frames", "5", "--t0", str(T0))
    assert [h["seq"] for h, _ in recs] == [0, 1, 2, 3, 4]
    assert [h["capture_time"] for h, _ in recs] == [T0 + i * 0.2 for i in range(5)]
    for h, jpg in recs:
        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        assert img.shape[:2] == (h["h"], h["w"]) == (720, 1280)
        assert h["rotation"] == 180
        assert img[40, 40].mean() > 200 and img[-40, -40].mean() < 150   # marker top-left


# ---- sighting built from a fake Pi frame ------------------------------------
def pi_sighting(evdir: Path, header: dict, jpeg: bytes, *, seq=1, boot="b1794090000",
                rx_time=None, sector="G"):
    """A sighting the way the contract says live_camera must build it for --source pi."""
    frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    obs_id = f"D1-{boot}-{seq:06d}"
    png = evdir / f"{obs_id}.png"
    cv2.imwrite(str(png), frame)
    ann = evdir / f"{obs_id}_annotated.jpg"
    cv2.imwrite(str(ann), frame)
    trig = Detection([400, 100, 200, 500], "torchvision_frcnn_r50_fpn_v2_coco", 0.98,
                     "frcnn_class_score", PERSON_DETECTOR)
    rx = rx_time if rx_time is not None else header["capture_time"] + 0.256
    cam = camera_provenance(source=PI5_IMX708, frame_size=(header["w"], header["h"]),
                            rotation_deg=header["rotation"], host=header.get("host"),
                            frame_seq=header["seq"], capture_to_rx_s=rx - header["capture_time"],
                            jpeg_quality=80)
    kw = dict(drone_id="D1", boot_id=boot, seq=seq, sector=sector,
              obs_time=header["capture_time"], frame_ref=str(png),
              frame_sha256=hashlib.sha256(png.read_bytes()).hexdigest(), annotated_ref=str(ann),
              frame_size=[frame.shape[1], frame.shape[0]], trigger=trig, all_dets=[trig],
              operator=None)
    if "camera" in inspect.signature(make_sighting).parameters:   # after T1's change
        s = make_sighting(**kw, camera=cam)
    else:                                                          # contract shape, until then
        s = make_sighting(**kw)
        s["evidence"]["camera"] = cam
    return json.loads(json.dumps(s))


@pytest.fixture
def env(tmp_path):
    evdir = tmp_path / "Team15_evidence" / "camera"
    evdir.mkdir(parents=True)
    clock = Clock(T0 + 30)
    store = MissionStore(responder_node="A", clock=clock)
    client = TestClient(create_app(store, evidence_dir=evdir))
    return client, store, clock, evdir


def bridge(client, lines):
    def post(url, obj):
        r = client.post("/observations", json=obj)
        return r.status_code, r.json()
    return forward(lines, "http://test/observations", post=post, log=lambda m: None)


def test_pi_frame_to_dashboard_keeps_capture_time_and_provenance(env):
    client, _store, clock, evdir = env
    (h, jpg), = read_fake_stream("--frames", "1", "--t0", str(T0))
    s = pi_sighting(evdir, h, jpg)
    clock.t = T0 + 0.9                         # dashboard receives it 0.9 s after capture
    assert bridge(client, [json.dumps(s)])["new"] == 1

    L = client.get("/state").json()["tracks"][0]["latest"]
    assert L["obs_time"] == T0                 # Pi capture time, not Mac/dashboard time
    assert L["rx_time"] == pytest.approx(T0 + 0.9)
    assert L["capture_to_ingest_s"] == pytest.approx(0.9)
    assert L["age_s"] == pytest.approx(0.9) and L["clock_skew"] is False
    assert L["obs_time_iso"] == iso_utc(T0)
    cam = L["camera"]
    assert cam["source"] == "PI5_IMX708" and cam["label"] == "Raspberry Pi 5 IMX708 camera"
    assert cam["transport"] == "JPEG_OVER_SSH_TAILSCALE"
    assert cam["capture_clock"] == "PI_SENSOR_TIMESTAMP_NTP"
    assert cam["rotation_deg"] == 180 and cam["host"] == "fake-pi" and cam["frame_seq"] == 0
    assert cam["capture_to_rx_s"] == pytest.approx(0.256)
    assert (L["badge"], L["platform"], L["how"], L["cell_source"]) == \
        ("LIVE-HW (bench)", "BENCH", "SECTOR_ONLY", "OPERATOR_ASSIGNED")
    assert L["confirmation"] == "unconfirmed"
    assert L["detector_family"] == "PERSON_DETECTOR"
    st = client.get("/state").json()
    assert st["alerts"][-1]["camera"] == "Raspberry Pi 5 IMX708 camera"
    assert st["routes"][0]["path"] == list("ABCDEFG") and st["routes"][0]["length_m"] == 60
    r = client.get(L["frame_url"])
    assert r.status_code == 200 and r.content == Path(s["evidence"]["frame_ref"]).read_bytes()


def test_existing_sighting_fields_all_survive(env):
    client, store, _clock, evdir = env
    (h, jpg), = read_fake_stream("--frames", "1", "--t0", str(T0))
    s = pi_sighting(evdir, h, jpg)
    client.post("/observations", json=s)
    stored = store.observation(s["obs_id"])
    for k, v in s.items():                      # nothing the camera sent is dropped or rewritten
        assert stored[k] == v, k


def test_pi_and_mac_sightings_in_one_sector_are_one_candidate(env):
    client, _store, clock, evdir = env
    recs = read_fake_stream("--frames", "2", "--t0", str(T0))
    pi = pi_sighting(evdir, *recs[0])
    mac = pi_sighting(evdir, *recs[1], boot="b1794090099")
    mac["evidence"]["camera"] = camera_provenance(source=MAC_LOCAL, frame_size=(1280, 720))
    clock.t = T0 + 5
    bridge(client, [json.dumps(pi), json.dumps(mac)])
    st = client.get("/state").json()
    [t] = st["tracks"]
    assert t["n_observations"] == 2
    assert t["latest"]["camera"]["label"] == "MacBook camera"          # newer capture time
    assert t["history"][0]["camera"]["label"] == "Raspberry Pi 5 IMX708 camera"
    assert [a["camera"] for a in st["alerts"]] == ["Raspberry Pi 5 IMX708 camera", "MacBook camera"]


def test_duplicate_pi_frames_do_not_add_people_or_alerts(env):
    client, _store, _clock, evdir = env
    recs = read_fake_stream("--frames", "2", "--t0", str(T0), "--same-image")
    a = pi_sighting(evdir, *recs[0])
    stats = bridge(client, [json.dumps(a)] * 3)
    assert (stats["new"], stats["duplicate"]) == (1, 2)
    # an identical frame (same PNG bytes) from a restarted stream, under a new obs_id
    b = pi_sighting(evdir, *recs[1], boot="b1794090123")
    assert b["evidence"]["frame_sha256"] == a["evidence"]["frame_sha256"]
    assert client.post("/observations", json=b).json()["duplicate_of"] == a["obs_id"]
    st = client.get("/state").json()
    assert len(st["tracks"]) == 1 and st["tracks"][0]["n_observations"] == 1
    assert len(st["alerts"]) == 1 and len(st["routes"]) == 1


@pytest.mark.parametrize("mutate, why", [
    (lambda s: s.update(platform="AIRCRAFT"), "platform"),
    (lambda s: s.update(source_mode="SIMULATED"), "source_mode"),
    (lambda s: s.update(cell_source="MEASURED"), "cell_source"),
    (lambda s: s.update(how="GROUND_PLANE", xy_m=[63.0, 4.0]), "how"),
    (lambda s: s.update(xy_m=[63.0, 4.0]), "coordinates"),
    (lambda s: s.update(lat=42.35, lon=-71.06), "coordinates"),
    (lambda s: s["evidence"]["camera"].update(capture_clock="MAC_WALL_CLOCK_AT_READ"), "capture_clock"),
    (lambda s: s["evidence"]["camera"].update(source="GOPRO"), "source"),
    (lambda s: s["evidence"]["camera"].update(transport="CARRIER_PIGEON"), "transport"),
    (lambda s: s.update(obs_time=s["obs_time"] + 5), "obs_time_iso"),
])
def test_pi_sightings_must_stay_bench_sector_only(env, mutate, why):
    client, _store, _clock, evdir = env
    (h, jpg), = read_fake_stream("--frames", "1", "--t0", str(T0))
    s = pi_sighting(evdir, h, jpg)
    mutate(s)
    r = client.post("/observations", json=s)
    assert r.status_code == 422, why
    assert client.get("/state").json()["tracks"] == []


def test_pi_sighting_cannot_self_confirm(env):
    client, _store, _clock, evdir = env
    (h, jpg), = read_fake_stream("--frames", "1", "--t0", str(T0))
    s = pi_sighting(evdir, h, jpg)
    s.update(confirmation="confirmed", decided_by="camera")
    client.post("/observations", json=s)
    L = client.get("/state").json()["tracks"][0]["latest"]
    assert (L["confirmation"], L["decided_by"]) == ("unconfirmed", None)


def test_future_capture_time_is_flagged_not_hidden(env):
    client, _store, clock, evdir = env
    (h, jpg), = read_fake_stream("--frames", "1", "--t0", str(T0))
    clock.t = T0 - 10                            # Pi clock 10 s ahead of the dashboard
    client.post("/observations", json=pi_sighting(evdir, h, jpg))
    L = client.get("/state").json()["tracks"][0]["latest"]
    assert L["clock_skew"] is True and L["obs_time"] == T0


def test_old_sightings_without_camera_still_accepted(env):
    client, _store, _clock, evdir = env
    (h, jpg), = read_fake_stream("--frames", "1", "--t0", str(T0))
    s = pi_sighting(evdir, h, jpg)
    del s["evidence"]["camera"]
    assert client.post("/observations", json=s).status_code == 200
    cam = client.get("/state").json()["tracks"][0]["latest"]["camera"]
    assert cam["source"] is None and cam["label"] == "camera not reported"


def test_page_shows_camera_provenance(env):
    html = env[0].get("/").text
    for needle in ("camera-chip", "camera-detail", "PI_SENSOR_TIMESTAMP_NTP", "capture→dashboard"):
        assert needle in html


# ---- acceptance tests for T1's perception/pi_source.py (skip until it exists) ----
def _pi_source():
    return pytest.importorskip("perception.pi_source",
                               reason="perception/pi_source.py not pushed by T1 yet")


def test_pi_source_returns_newest_frame_once_with_capture_time():
    mod = _pi_source()
    src = mod.PiFrameSource(cmd=FAKE + ["--frames", "30", "--fps", "60", "--t0", str(T0)],
                            read_timeout_s=3.0)
    try:
        assert src.isOpened()
        time.sleep(1.5)                          # sender finishes; reader must keep only the newest
        ok, frame = src.read()
        assert ok and frame.shape[:2] == (720, 1280)
        assert src.last_header["seq"] == 29
        assert src.last_capture_time == T0 + 29 * 0.2
        assert isinstance(src.last_rx_time, float)          # Mac receive time, kept separately
        assert src.last_rx_time != src.last_capture_time
        assert src.frames_received == 30 and src.frames_dropped >= 1
        assert frame[40, 40].mean() > 200        # upright: not rotated a second time
        ok2, _ = src.read()                      # same frame is never returned twice
        assert not ok2
        cam = src.camera_info()
        assert cam["source"] == "PI5_IMX708" and cam["rotation_deg"] == 180
        assert cam["capture_clock"] == "PI_SENSOR_TIMESTAMP_NTP"
    finally:
        src.release()


def test_pi_source_reports_broken_stream_instead_of_guessing():
    mod = _pi_source()
    src = mod.PiFrameSource(cmd=FAKE + ["--frames", "5", "--fps", "60", "--garbage-after", "2"],
                            read_timeout_s=2.0)
    try:
        seen = []
        for _ in range(5):
            ok, _f = src.read()
            if ok:
                seen.append(src.last_header["seq"])
        assert seen and max(seen) <= 1           # nothing after the corrupt record
    finally:
        src.release()

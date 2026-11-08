"""PiCameraSource tests with a fake Pi sender (no Pi, no SSH, runs in CI).

The fake sender is fed on stdin exactly like the real SENDER_SCRIPT, but runs
locally with ``python -u -`` instead of ``ssh <pi> python3 -u -``. It writes the
same T15HELLO / T15FRAME stream. Each frame's capture time is
``BASE_T + 0.2 * seq``, far from the real clock, so a test can tell the Pi
capture time from the Mac arrival time. Each frame is bright in its top-left
quadrant only, so a test can see the rotation.
"""
import json
import os
import sys
import time

import cv2
import numpy as np
import pytest

from perception import live_camera
from perception.detectors import FULL_BODY_HOG, Detection
from perception.pi_source import (ENV_HOST, ENV_KEY, ENV_USER, PiCameraSource,
                                  PiSourceError, build_ssh_command, open_pi_camera,
                                  parse_size)

BASE_T = 1_700_000_000.0
W, H = 64, 48

FAKE_SENDER = r'''
import json, sys, time
import cv2, numpy as np
mode = sys.argv[1]
W, H, BASE_T = 64, 48, 1700000000.0
out = sys.stdout.buffer
def jpeg():
    img = np.full((H, W, 3), 40, np.uint8)
    img[: H // 2, : W // 2] = 255          # bright top-left quadrant
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()
def frame(seq, data=None, **extra):
    data = jpeg() if data is None else data
    hdr = {"seq": seq, "t_capture": BASE_T + 0.2 * seq, "clock": "sensor",
           "len": len(data)}
    hdr.update(extra)
    out.write(b"T15FRAME " + json.dumps(hdr).encode() + b"\n" + data); out.flush()
out.write(b"T15HELLO " + json.dumps({"sensor_model": "imx708",
          "pi_model": "Raspberry Pi 5 Model B Rev 1.1", "size": [W, H], "fps": 5,
          "jpeg_quality": 95, "clock": "fake"}).encode() + b"\n"); out.flush()
if mode == "stream":
    for seq in range(1, 2000):
        frame(seq); time.sleep(0.05)
elif mode == "burst":
    for seq in range(1, 31):
        frame(seq)
    time.sleep(30)
elif mode == "malformed":
    out.write(b"garbage line that is not a header\n")
    out.write(b"T15FRAME {not json\n")
    out.write(b"T15FRAME " + json.dumps({"seq": 3, "t_capture": 1.0, "len": 10**9}).encode() + b"\n")
    out.write(b"T15FRAME " + json.dumps({"seq": 4, "len": 5}).encode() + b"\n")
    frame(5, data=b"this is not a jpeg")
    out.flush()
    frame(7)
    time.sleep(30)
elif mode == "two_then_exit":
    frame(1); frame(2)
elif mode == "truncated":
    out.write(b"T15FRAME " + json.dumps({"seq": 1, "t_capture": 2.0, "len": 1000}).encode() + b"\n" + b"short")
    out.flush()
'''


def fake_source(mode, **kw):
    kw.setdefault("rotation", 180)
    return PiCameraSource(command=[sys.executable, "-u", "-", mode], script=FAKE_SENDER,
                          log=lambda m: None, **kw)


def bright_quadrant(img):
    q = {"tl": img[: H // 2, : W // 2], "tr": img[: H // 2, W // 2:],
         "bl": img[H // 2:, : W // 2], "br": img[H // 2:, W // 2:]}
    return max(q, key=lambda k: float(q[k].mean()))


def wait_for(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_capture_timestamp_preserved_not_arrival_time():
    src = fake_source("stream").start()
    try:
        for _ in range(3):
            ok, img = src.read(timeout_s=10)
            assert ok and img.shape == (H, W, 3)
            seq = src.last_header["seq"]
            assert src.last_capture_time == pytest.approx(BASE_T + 0.2 * seq, abs=1e-6)
            assert abs(src.last_rx_time - time.time()) < 5       # arrival is "now"
            assert abs(src.last_rx_time - src.last_capture_time) > 1e6
    finally:
        src.release()


@pytest.mark.parametrize("rotation,expected", [(180, "br"), (0, "tl"), (90, "tr")])
def test_rotation_applied_on_arrival(rotation, expected):
    src = fake_source("stream", rotation=rotation).start()
    try:
        ok, img = src.read(timeout_s=10)
        assert ok
        if rotation == 90:
            assert img.shape[:2] == (W, H)
            q = img[: W // 2, H // 2:]  # top-right after clockwise rotation
            assert float(q.mean()) > 200
        else:
            assert bright_quadrant(img) == expected
    finally:
        src.release()


def test_keeps_only_newest_frame_and_never_repeats():
    src = fake_source("burst").start()
    try:
        assert wait_for(lambda: src.stats["frames_received"] == 30)
        ok, _ = src.read(timeout_s=5)
        assert ok and src.last_header["seq"] == 30
        assert src.stats["frames_dropped_stale"] == 29
        ok, img = src.read(timeout_s=0.5)  # nothing new: no repeat of frame 30
        assert not ok and img is None
        assert src.isOpened()
    finally:
        src.release()


def test_malformed_frames_are_skipped():
    src = fake_source("malformed").start()
    try:
        ok, img = src.read(timeout_s=10)
        assert ok and src.last_header["seq"] == 7
        assert src.last_capture_time == pytest.approx(BASE_T + 1.4)
        assert src.stats["malformed"] >= 3
        assert src.stats["decode_failures"] == 1
    finally:
        src.release()


def test_truncated_frame_then_eof_is_safe():
    src = fake_source("truncated", max_reconnects=0).start()
    try:
        ok, img = src.read(timeout_s=10)
        assert not ok and img is None
        assert wait_for(lambda: not src.isOpened())
    finally:
        src.release()


def test_disconnect_gives_up_after_reconnect_budget():
    src = fake_source("two_then_exit", max_reconnects=1).start()
    try:
        seqs = []
        while True:
            ok, _ = src.read(timeout_s=10)
            if not ok:
                break
            seqs.append(src.last_header["seq"])
        assert not src.isOpened()
        assert src.stats["reconnects"] >= 1     # it did try to reconnect
        assert seqs and set(seqs) <= {1, 2}
        assert len(seqs) >= 2  # frames from the reconnected stream are delivered too
    finally:
        src.release()


def test_ssh_failure_reports_stderr():
    cmd = [sys.executable, "-c",
           "import sys; sys.stderr.write('Host key verification failed.\\n'); sys.exit(255)"]
    with pytest.raises(PiSourceError, match="Host key verification failed"):
        open_pi_camera(command=cmd, max_reconnects=0, startup_timeout_s=10,
                       log=lambda m: None)


def test_ssh_command_is_batch_mode_and_never_weakens_host_keys(monkeypatch):
    cmd = build_ssh_command("100.64.0.9", user="u", key="~/.ssh/k", port=2222,
                            remote_args=[1280, 720, 5.0, 80])
    joined = " ".join(cmd)
    assert cmd[0] == "ssh" and "BatchMode=yes" in joined
    assert "StrictHostKeyChecking" not in joined and "UserKnownHostsFile" not in joined
    assert os.path.expanduser("~/.ssh/k") in cmd and "IdentitiesOnly=yes" in joined
    assert "u@100.64.0.9" in cmd and cmd[-5:] == ["-", "1280", "720", "5.0", "80"]
    with pytest.raises(ValueError):
        build_ssh_command("")
    monkeypatch.setenv(ENV_HOST, "pi.example")
    monkeypatch.setenv(ENV_USER, "envuser")
    monkeypatch.setenv(ENV_KEY, "/tmp/envkey")
    s = PiCameraSource(log=lambda m: None)
    assert "envuser@pi.example" in s._cmd and "/tmp/envkey" in s._cmd


def test_parse_size():
    assert parse_size("1280x720") == (1280, 720)
    with pytest.raises(ValueError):
        parse_size("big")


class _AlwaysPerson:
    """Stands in for OpenCVDetectors: one large box on every frame."""
    name = "fake"

    def detect_all(self, frame):
        h, w = frame.shape[:2]
        return [Detection([w // 4, h // 8, w // 3, int(h * 0.7)], "fake_full_body",
                          1.0, "fake_score", FULL_BODY_HOG)]


def test_live_camera_pi_source_end_to_end(tmp_path, monkeypatch, capsys):
    def fake_open_pi_camera(**kw):
        for k in ("host", "user", "key", "port", "size", "fps", "jpeg_quality"):
            kw.pop(k)
        return open_pi_camera(command=[sys.executable, "-u", "-", "stream"],
                              script=FAKE_SENDER, log=lambda m: None, **kw)

    monkeypatch.setattr(live_camera, "open_pi_camera", fake_open_pi_camera)
    monkeypatch.setattr(live_camera, "OpenCVDetectors", _AlwaysPerson)
    out_dir = tmp_path / "evidence"
    rc = live_camera.main(["--source", "pi", "--pi-host", "unused", "--sector", "g",
                           "--no-dnn", "--trigger", "any", "--once",
                           "--duration-s", "20", "--out-dir", str(out_dir)])
    assert rc == live_camera.EXIT_OK
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 1
    s = json.loads(lines[0])

    # contracts unchanged
    assert (s["source_mode"], s["platform"], s["sensor"], s["kind"], s["how"]) == \
        ("LIVE-HW", "BENCH", "rgb", "PERSON_VISUAL", "SECTOR_ONLY")
    assert s["cell"] == "G" and s["cell_source"] == "OPERATOR_ASSIGNED"
    assert s["confidence"] is None
    assert "status" not in s            # stays UNCONFIRMED until an operator acts
    assert s["obs_id"] == f"{s['drone_id']}-{s['boot_id']}-{s['seq']:06d}"

    # obs_time is the Pi capture time of the evidence frame, not arrival time
    cam = s["evidence"]["camera"]
    pi_seq = cam["pi_frame_seq"]
    assert s["obs_time"] == pytest.approx(BASE_T + 0.2 * pi_seq, abs=1e-3)
    assert cam["rx_time"] - s["obs_time"] > 1e6

    # provenance
    assert cam["source"] == "pi5-imx708" and cam["transport"] == "ssh-jpeg"
    assert cam["sensor_model"] == "imx708" and cam["rotation_deg"] == 180
    keys = set(s) | set(s["evidence"]) | set(cam)
    assert not keys & {"lat", "lon", "latitude", "longitude", "position", "xy"}

    # evidence saved, rotated, and hashed
    png = cv2.imread(s["evidence"]["frame_ref"])
    assert png is not None and png.shape == (H, W, 3)
    assert bright_quadrant(png) == "br"
    assert s["evidence"]["frame_size"] == [W, H]
    assert os.path.exists(s["evidence"]["annotated_ref"])
    with open(out_dir / "sightings.jsonl") as f:
        assert json.loads(f.readline())["obs_id"] == s["obs_id"]
    summary = json.load(open(out_dir / f"{s['drone_id']}-{s['boot_id']}_summary.json"))
    assert summary["source"] == "pi" and summary["pi_stream"]["frames_delivered"] >= 3


def test_live_camera_pi_unreachable_exits_camera_unavailable(monkeypatch, tmp_path):
    def failing(**kw):
        raise PiSourceError("no frame from the Pi within 1s (ssh stderr: timeout)")
    monkeypatch.setattr(live_camera, "open_pi_camera", failing)
    rc = live_camera.main(["--source", "pi", "--pi-host", "x", "--sector", "G",
                           "--no-dnn", "--trigger", "any", "--out-dir",
                           str(tmp_path / "ev")])
    assert rc == live_camera.EXIT_CAMERA_UNAVAILABLE


def test_default_source_is_local(monkeypatch):
    seen = {}
    monkeypatch.setattr(live_camera, "run", lambda a: seen.setdefault("a", a) and 0)
    live_camera.main(["--sector", "G"])
    assert seen["a"].source == "local" and seen["a"].pi_rotation == 180


def test_warm_up_runs_each_detector_once_and_discards():
    calls = []

    class D:
        def detect_all(self, frame):
            calls.append(frame.shape)
            return [Detection([0, 0, 10, 10], "d", 1.0, "k", FULL_BODY_HOG)]

    src = fake_source("stream").start()
    try:
        dt = live_camera.warm_up([D(), D()], src)
        assert dt is not None and calls == [(H, W, 3), (H, W, 3)]
        ok, _ = src.read(timeout_s=10)   # the stream keeps going afterwards
        assert ok
    finally:
        src.release()


def test_warm_up_tolerates_no_frame():
    class Cap:
        def read(self):
            return False, None
    assert live_camera.warm_up([_AlwaysPerson()], Cap()) is None

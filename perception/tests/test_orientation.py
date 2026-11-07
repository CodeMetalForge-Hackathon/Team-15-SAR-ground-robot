"""Orientation regression tests (no Pi, no SSH).

The fake Pi sends what the real Pi sends on the wheeled-robot mount (verified
2026-11-07, orient-1794095449791): an upside-down scene, bright "ceiling" in
the bottom half. With default settings the receiver must deliver it upright,
and exactly once: rotating twice would put the ceiling back at the bottom.
"""
import hashlib
import json
import sys

import cv2
import numpy as np
import pytest

from perception import live_camera, orientation_check
from perception.pi_source import DEFAULT_PI_ROTATION, PiCameraSource

W, H = 64, 48
IDENTITY = "<libcamera.Transform 'identity'>"

ROBOT_MOUNT_SENDER = r'''
import json, sys, time
import cv2, numpy as np
W, H = 64, 48
out = sys.stdout.buffer
img = np.full((H, W, 3), 30, np.uint8)
img[H // 2:] = 230                        # ceiling at the bottom: inverted mount
for x in range(0, W, 8):                  # texture so sharpness is not zero
    img[:, x] = 0
data = cv2.imencode(".png", img)[1].tobytes()
out.write(b"T15HELLO " + json.dumps({"sensor_model": "imx708",
          "pi_model": "Raspberry Pi 5 Model B Rev 1.1", "size": [W, H], "fps": 5,
          "jpeg_quality": 95, "sensor_mount_rotation": 180,
          "pi_transform": "<libcamera.Transform 'identity'>"}).encode() + b"\n")
out.flush()
for seq in range(1, 2000):
    hdr = {"seq": seq, "t_capture": 1700000000.0 + 0.2 * seq, "clock": "sensor",
           "len": len(data), "exposure_us": 10000, "analogue_gain": 1.5}
    out.write(b"T15FRAME " + json.dumps(hdr).encode() + b"\n" + data); out.flush()
    time.sleep(0.05)
'''


def robot_source(**kw):
    return PiCameraSource(command=[sys.executable, "-u", "-"], script=ROBOT_MOUNT_SENDER,
                          log=lambda m: None, **kw)


def top_is_bright(img):
    h = img.shape[0] // 2
    return float(img[:h].mean()) > float(img[h:].mean()) + 50


def test_default_rotation_is_robot_mount_180():
    assert DEFAULT_PI_ROTATION == 180
    assert PiCameraSource(command=["true"]).rotation == 180


def test_cli_default_rotation_matches(monkeypatch):
    seen = {}
    monkeypatch.setattr(live_camera, "run", lambda a: seen.setdefault("a", a) and 0)
    live_camera.main(["--source", "pi", "--sector", "G"])
    assert seen["a"].pi_rotation == DEFAULT_PI_ROTATION


def test_robot_mount_frame_is_upright_with_defaults():
    """The regression: default settings deliver the robot-mount stream upright."""
    src = robot_source().start()
    try:
        ok, img = src.read(timeout_s=10)
        assert ok and img.shape == (H, W, 3)
        assert top_is_bright(img)
        cam = src.camera_info()
        assert cam["rotation_deg"] == 180 and cam["rotation_applied_by"] == "receiver"
        assert cam["sensor_mount_rotation"] == 180
        assert cam["pi_transform"] == IDENTITY
    finally:
        src.release()


@pytest.mark.parametrize("rotation,upright", [(0, False), (180, True)])
def test_single_rotation_only(rotation, upright):
    """0 leaves the robot stream inverted; 180 is applied once, not twice."""
    src = robot_source(rotation=rotation).start()
    try:
        ok, img = src.read(timeout_s=10)
        assert ok and top_is_bright(img) is upright
    finally:
        src.release()


def test_frame_stats_flags_blocked_lens_and_accepts_scene():
    black = np.zeros((H, W, 3), np.uint8)
    s = orientation_check.frame_stats(black)
    assert not s["exposure_ok"] and any("sharpness" in p for p in s["problems"])
    scene = np.full((H, W, 3), 120, np.uint8)
    scene[:, ::4] = 30
    assert orientation_check.frame_stats(scene)["exposure_ok"]


def test_orientation_check_writes_both_rotations_and_never_overwrites(monkeypatch, tmp_path):
    def fake_open(**kw):
        assert kw["rotation"] == 0          # the check always looks at the raw stream
        src = robot_source(rotation=0).start()
        src.wait_first_frame(10)
        return src
    monkeypatch.setattr(orientation_check, "open_pi_camera", fake_open)
    out = tmp_path / "orient"
    assert orientation_check.main(["--out-dir", str(out), "--settle-s", "0.3"]) == 0
    reports = list(out.glob("*_report.json"))
    assert len(reports) == 1
    rep = json.loads(reports[0].read_text())
    rot0 = cv2.imread(rep["files"]["rot0"]["path"])
    rot180 = cv2.imread(rep["files"]["rot180"]["path"])
    assert not top_is_bright(rot0) and top_is_bright(rot180)
    assert rep["pi"]["sensor_mount_rotation"] == 180
    for f in rep["files"].values():
        with open(f["path"], "rb") as fh:
            assert hashlib.sha256(fh.read()).hexdigest() == f["sha256"]

    # existing files are evidence: writing to a taken name fails, bytes unchanged
    path = rep["files"]["rot0"]["path"]
    before = open(path, "rb").read()
    with pytest.raises(FileExistsError):
        orientation_check._write_new(path, b"overwrite attempt")
    assert open(path, "rb").read() == before

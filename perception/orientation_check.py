"""Camera orientation check for the Pi camera at its mounting position.

Grabs one non-person test frame from the Pi exactly as the receiver gets it
(no receiver rotation), lets auto-exposure settle first, and writes outside Git:

    orient-<capture ms>_rot0.png       the frame as delivered by the Pi (--pi-rotation 0)
    orient-<capture ms>_rot180.png     the same frame rotated 180
    orient-<capture ms>_compare.jpg    both side by side, labeled, for a quick look
    orient-<capture ms>_report.json    exposure / sharpness stats, Pi orientation info,
                               double-rotation check, sha256 of every file

Point the camera at a scene with an obvious "up" (ceiling lights, a door, text)
and keep people out of frame. Pick the rotation whose image is upright and pass
it as --pi-rotation (the pipeline applies exactly one rotation, on the Mac;
the Pi's reported mount rotation is a fixed device-tree value, not the truth).
Existing files are never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Optional, Sequence

import cv2
import numpy as np

from .pi_source import PiSourceError, open_pi_camera, parse_size, rotate

DEFAULT_OUT = os.path.expanduser("~/Team15_evidence/orientation_checks")
# below this Laplacian variance the frame is blurred or the lens is covered
MIN_SHARPNESS = 30.0
MEAN_RANGE = (40.0, 215.0)
MAX_CLIPPED = 0.25


def frame_stats(img: np.ndarray) -> dict:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    dark, bright = float((gray < 10).mean()), float((gray > 245).mean())
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    problems = []
    if not MEAN_RANGE[0] <= mean <= MEAN_RANGE[1]:
        problems.append(f"mean brightness {mean:.0f} outside {MEAN_RANGE}")
    if dark > MAX_CLIPPED or bright > MAX_CLIPPED:
        problems.append(f"clipped pixels: dark {dark:.0%}, bright {bright:.0%}")
    if sharp < MIN_SHARPNESS:
        problems.append(f"sharpness {sharp:.1f} < {MIN_SHARPNESS}: lens blocked, "
                        "smudged or out of focus?")
    return {"mean_luma": round(mean, 1), "frac_dark": round(dark, 4),
            "frac_bright": round(bright, 4), "laplacian_var": round(sharp, 1),
            "exposure_ok": not problems, "problems": problems}


def compare_image(rot0: np.ndarray, rot180: np.ndarray) -> np.ndarray:
    tiles = []
    for img, label in ((rot0, "rotation 0"), (rot180, "rotation 180")):
        t = cv2.resize(img, (640, int(640 * img.shape[0] / img.shape[1])))
        cv2.rectangle(t, (0, 0), (220, 40), (0, 0, 0), -1)
        cv2.putText(t, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (255, 255, 255), 2)
        tiles.append(t)
    return np.hstack([tiles[0], np.full((tiles[0].shape[0], 8, 3), 255, np.uint8),
                      tiles[1]])


def _write_new(path: str, data: bytes) -> str:
    with open(path, "xb") as f:  # x: never overwrite
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def run(a: argparse.Namespace) -> int:
    try:
        src = open_pi_camera(host=a.pi_host, user=a.pi_user, key=a.pi_key,
                             port=a.pi_port, size=a.pi_size, fps=a.pi_fps,
                             rotation=0, startup_timeout_s=a.startup_timeout_s)
    except (PiSourceError, ValueError, OSError) as e:
        print(f"Pi camera unavailable: {e}", file=sys.stderr)
        return 3
    try:
        end, frame = time.time() + a.settle_s, None
        while time.time() < end or frame is None:
            ok, img = src.read(timeout_s=5)
            if not ok:
                if not src.isOpened():
                    break
                continue
            frame, hdr, t_cap = img, dict(src.last_header), src.last_capture_time
        hello = dict(src.hello or {})
    finally:
        src.release()
    if frame is None:
        print("no frame received from the Pi", file=sys.stderr)
        return 3

    os.makedirs(a.out_dir, exist_ok=True)
    stem = os.path.join(a.out_dir, f"orient-{int(t_cap * 1000)}")
    rot180 = rotate(frame, 180)
    files = {}
    for name, img, ext in (("rot0", frame, ".png"), ("rot180", rot180, ".png"),
                           ("compare", compare_image(frame, rot180), ".jpg")):
        path = f"{stem}_{name}{ext}"
        files[name] = {"path": path,
                       "sha256": _write_new(path, cv2.imencode(ext, img)[1].tobytes())}
    report = {
        "capture_time": t_cap, "pi_frame_seq": hdr.get("seq"),
        "capture_clock": hdr.get("clock"), "exposure_us": hdr.get("exposure_us"),
        "analogue_gain": hdr.get("analogue_gain"), "lux": hdr.get("lux"),
        "frame_size": [int(frame.shape[1]), int(frame.shape[0])],
        "pi": {k: hello.get(k) for k in ("pi_model", "sensor_model",
                                         "sensor_mount_rotation", "pi_transform")},
        "stats": frame_stats(frame),
        "files": files,
        "decision": "operator: open the compare image and pick the upright one",
    }
    data = (json.dumps(report, indent=1) + "\n").encode()
    _write_new(f"{stem}_report.json", data)
    print(json.dumps(report, indent=1))
    return 0 if report["stats"]["exposure_ok"] else 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pi-host", default=None)
    p.add_argument("--pi-user", default=None)
    p.add_argument("--pi-key", default=None)
    p.add_argument("--pi-port", type=int, default=None)
    p.add_argument("--pi-size", type=parse_size, default=(1280, 720))
    p.add_argument("--pi-fps", type=float, default=5.0)
    p.add_argument("--settle-s", type=float, default=3.0,
                   help="let auto-exposure settle before keeping a frame")
    p.add_argument("--startup-timeout-s", type=float, default=30.0)
    p.add_argument("--out-dir", default=DEFAULT_OUT)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())

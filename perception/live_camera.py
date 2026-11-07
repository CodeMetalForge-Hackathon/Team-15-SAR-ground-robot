"""Live bench camera person detector (LIVE-HW, platform=BENCH).

Captures frames from a local camera (e.g. a MacBook built-in camera), runs
OpenCV's built-in pretrained detectors, and on the first frame containing a
person saves an annotated JPEG and prints one observation JSON line.

This is a bench test with a *declared* drone and cell. It is NOT an aerial
detection claim; location is SECTOR_ONLY (the declared cell), not localized.

Detectors (all bundled with OpenCV, no downloads):
  1. HOG + linear SVM people detector (full body)
  2. Haar frontal-face cascade (fallback; laptop cameras usually see head/shoulders)
  3. Haar upper-body cascade (fallback)

Confidence: none of these detectors produce a calibrated probability, so the
observation's ``confidence`` is null. The raw detector score (HOG SVM margin or
Haar cascade level weight) is recorded in ``evidence.detector_score`` with its
kind, so it is not mistaken for a probability.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

import cv2
import numpy as np

EXIT_OK = 0
EXIT_NO_PERSON = 2
EXIT_CAMERA_UNAVAILABLE = 3

# Mean pixel intensity below this on every warm-up frame => treat as black frames
BLACK_MEAN_THRESHOLD = 2.0


class CameraUnavailable(RuntimeError):
    """Camera could not be opened or returned only empty/black frames."""


CAMERA_HELP = (
    "Camera unavailable: could not obtain real frames. On macOS this is usually "
    "a camera-permission (TCC) denial: allow camera access for your terminal app in "
    "System Settings > Privacy & Security > Camera, then restart the terminal. "
    "Also check no other app holds the camera. No frame was faked."
)


@dataclass
class Detection:
    bbox: List[int]  # [x, y, w, h]
    detector: str
    score: Optional[float]
    score_kind: Optional[str]


def _cascade(name: str) -> cv2.CascadeClassifier:
    path = os.path.join(cv2.data.haarcascades, name)
    c = cv2.CascadeClassifier(path)
    if c.empty():
        raise RuntimeError(f"failed to load Haar cascade {path}")
    return c


class PersonDetector:
    """HOG people detector first, then Haar face and upper-body fallbacks."""

    def __init__(self) -> None:
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.face = _cascade("haarcascade_frontalface_default.xml")
        self.upper = _cascade("haarcascade_upperbody.xml")

    def detect(self, frame: np.ndarray) -> Optional[Detection]:
        """Return the strongest detection from the first detector that fires."""
        if frame is None or frame.size == 0:
            return None
        h, w = frame.shape[:2]
        scale = 640.0 / w if w > 640 else 1.0
        small = cv2.resize(frame, None, fx=scale, fy=scale) if scale != 1.0 else frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
        gray = cv2.equalizeHist(gray)

        def unscale(r: Sequence[int]) -> List[int]:
            return [int(round(v / scale)) for v in r]

        # 1. HOG full-body people detector
        rects, weights = self.hog.detectMultiScale(
            small, winStride=(8, 8), padding=(8, 8), scale=1.05
        )
        if len(rects):
            weights = np.asarray(weights).reshape(-1)
            i = int(np.argmax(weights))
            return Detection(unscale(rects[i]), "opencv_hog_default_people",
                             float(weights[i]), "hog_svm_margin")

        # 2/3. Haar cascades
        for name, casc, min_size in (
            ("opencv_haar_frontalface_default", self.face, (60, 60)),
            ("opencv_haar_upperbody", self.upper, (80, 80)),
        ):
            rects, _levels, lw = casc.detectMultiScale3(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=min_size,
                outputRejectLevels=True,
            )
            if len(rects):
                lw = np.asarray(lw).reshape(-1)
                i = int(np.argmax(lw)) if lw.size == len(rects) else 0
                score = float(lw[i]) if lw.size == len(rects) else None
                return Detection(unscale(rects[i]), name, score,
                                 "haar_level_weight" if score is not None else None)
        return None


def make_observation(*, seq: int, drone_id: str, cell: str, obs_time: float,
                     frame_ref: str, det: Detection) -> dict:
    return {
        "obs_id": f"{drone_id}-b1-{seq:06d}",
        "drone_id": drone_id,
        "source_mode": "LIVE-HW",
        "platform": "BENCH",
        "sensor": "rgb",
        "kind": "PERSON_VISUAL",
        "how": "SECTOR_ONLY",
        "cell": cell,
        "obs_time": obs_time,
        "confidence": None,  # no calibrated probability from these detectors
        "evidence": {
            "frame_ref": frame_ref,
            "bbox": [int(v) for v in det.bbox],
            "detector": det.detector,
            "detector_score": det.score,
            "detector_score_kind": det.score_kind,
        },
    }


def annotate(frame: np.ndarray, det: Detection) -> np.ndarray:
    out = frame.copy()
    x, y, w, h = det.bbox
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 3)
    cv2.putText(out, f"PERSON ({det.detector}) LIVE-HW BENCH", (x, max(20, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return out


def is_black(frame: Optional[np.ndarray]) -> bool:
    return frame is None or frame.size == 0 or float(frame.mean()) < BLACK_MEAN_THRESHOLD


def open_camera(index: int, warmup_s: float = 1.0) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise CameraUnavailable(f"cv2.VideoCapture({index}) failed to open. " + CAMERA_HELP)
    t_end = time.time() + warmup_s
    good = False
    reads = 0
    while time.time() < t_end or reads < 5:
        ok, frame = cap.read()
        reads += 1
        if ok and not is_black(frame):
            good = True
        if reads > 200:
            break
    if not good:
        # give it a little longer before declaring failure
        for _ in range(30):
            ok, frame = cap.read()
            if ok and not is_black(frame):
                good = True
                break
            time.sleep(0.05)
    if not good:
        cap.release()
        raise CameraUnavailable(
            f"camera {index} opened but returned only empty/black frames. " + CAMERA_HELP)
    return cap


def run(camera: int, drone_id: str, cell: str, out_dir: str, timeout_s: float,
        once: bool) -> int:
    detector = PersonDetector()
    try:
        cap = open_camera(camera)
    except CameraUnavailable as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_CAMERA_UNAVAILABLE

    os.makedirs(out_dir, exist_ok=True)
    seq = 0
    deadline = time.time() + timeout_s
    empty_streak = 0
    found_any = False
    try:
        while time.time() < deadline:
            ok, frame = cap.read()
            if not ok or is_black(frame):
                empty_streak += 1
                if empty_streak > 60:
                    print("ERROR: camera stopped delivering frames. " + CAMERA_HELP,
                          file=sys.stderr)
                    return EXIT_CAMERA_UNAVAILABLE
                continue
            empty_streak = 0
            obs_time = time.time()
            det = detector.detect(frame)
            if det is None:
                continue
            seq += 1
            found_any = True
            obs_id = f"{drone_id}-b1-{seq:06d}"
            path = os.path.abspath(os.path.join(out_dir, f"{obs_id}_{int(obs_time)}.jpg"))
            if not cv2.imwrite(path, annotate(frame, det)):
                print(f"ERROR: failed to write {path}", file=sys.stderr)
                return 1
            obs = make_observation(seq=seq, drone_id=drone_id, cell=cell,
                                   obs_time=obs_time, frame_ref=path, det=det)
            print(json.dumps(obs), flush=True)
            if once:
                return EXIT_OK
            time.sleep(1.0)  # simple rate limit in continuous mode
    finally:
        cap.release()
    if found_any:
        return EXIT_OK
    print(f"NO PERSON DETECTED within {timeout_s:.0f}s on camera {camera}; "
          "no picture saved, no observation emitted.", file=sys.stderr)
    return EXIT_NO_PERSON


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--declare-drone", required=True)
    p.add_argument("--declare-cell", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--timeout-s", type=float, default=30.0)
    p.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    return run(a.camera, a.declare_drone, a.declare_cell, a.out_dir, a.timeout_s, a.once)


if __name__ == "__main__":
    sys.exit(main())

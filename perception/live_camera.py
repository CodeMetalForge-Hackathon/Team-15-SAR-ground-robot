"""Live bench camera person detector (LIVE-HW, platform=BENCH).

Captures frames from a local camera (e.g. a MacBook built-in camera) and runs
every detector on every frame, keeping results labeled by family:
PERSON_DETECTOR (COCO-pretrained torchvision Faster R-CNN, class "person"),
FULL_BODY_HOG, UPPER_BODY_HAAR and FACE_ONLY (see perception/detectors.py).

By default only PERSON_DETECTOR hits can raise a sighting. When a candidate is
confirmed, the exact evidence frame is saved losslessly outside Git and ONE
sighting JSON line is printed on stdout (and appended to sightings.jsonl in the
evidence dir). Repeated frames of the same candidate are attached to that
sighting, not re-emitted (see perception/sightings.py for the dedup rule).

This is a bench test with a *declared* drone and an operator-assigned sector.
It is NOT an aerial detection claim; location is SECTOR_ONLY.

``--source pi`` reads the Raspberry Pi 5 camera instead, as timestamped JPEGs
over SSH (see perception/pi_source.py). Frames are rotated on arrival
(``--pi-rotation``, default 180 for the inverted mount), ``obs_time`` is the
Pi's capture time, and ``evidence.camera`` records the camera and transport.
``confidence`` is null: detector scores are recorded with their kind in
``evidence`` and are not calibrated probabilities.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import List, Optional, Sequence

import cv2
import numpy as np

from .detectors import (DEFAULT_DNN_MODEL, DNN_MODELS, FACE_ONLY, FAMILIES,
                        FULL_BODY_HOG, PERSON_DETECTOR, UPPER_BODY_HAAR, Detection,
                        OpenCVDetectors, TorchPersonDetector, _cascade, best)
from .pi_source import ENV_HOST, ENV_KEY, ENV_USER, PiSourceError, open_pi_camera, \
    parse_size, ROTATIONS
from .sightings import (DEFAULT_EVIDENCE_DIR, SightingGate, ensure_evidence_dir,
                        iso_utc, make_sighting, save_evidence, validate_sector)

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


class PersonDetector:
    """Original first-hit OpenCV detector (kept for compatibility; run() uses
    detectors.OpenCVDetectors + TorchPersonDetector instead)."""

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
                             float(weights[i]), "hog_svm_margin", FULL_BODY_HOG)

        # 2/3. Haar cascades
        for fam, name, casc, min_size in (
            (FACE_ONLY, "opencv_haar_frontalface_default", self.face, (60, 60)),
            (UPPER_BODY_HAAR, "opencv_haar_upperbody", self.upper, (80, 80)),
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
                                 "haar_level_weight" if score is not None else None,
                                 fam)
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


FAMILY_COLORS = {PERSON_DETECTOR: (0, 255, 0), FULL_BODY_HOG: (255, 128, 0),
                 UPPER_BODY_HAAR: (0, 200, 255), FACE_ONLY: (255, 0, 255)}
TRIGGERS = {"person": (PERSON_DETECTOR,),
            "any": (PERSON_DETECTOR, FULL_BODY_HOG, UPPER_BODY_HAAR, FACE_ONLY)}


def annotate_all(frame: np.ndarray, dets: List[Detection], trigger: Detection,
                 header: str) -> np.ndarray:
    out = frame.copy()
    for d in dets:
        x, y, w, h = d.bbox
        thick = 4 if d is trigger else 2
        cv2.rectangle(out, (x, y), (x + w, y + h), FAMILY_COLORS[d.family], thick)
        sc = "" if d.score is None else f" {d.score:.2f}"
        cv2.putText(out, f"{d.family}{sc}", (x, max(20, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, FAMILY_COLORS[d.family], 2)
    cv2.putText(out, header, (10, out.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 255, 0), 2)
    return out


def select_trigger(dets: List[Detection], families: Sequence[str],
                   min_box_h: float) -> Optional[Detection]:
    """Best detection from the first family (in priority order) that has one at
    least ``min_box_h`` pixels tall. Smaller boxes are logged but never trigger:
    on the bench they were window reflections (80-130 px in a 1080 px frame)."""
    for f in families:
        trig = best([d for d in dets if d.bbox[3] >= min_box_h], f)
        if trig is not None:
            return trig
    return None


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# --source pi: give up when no frame has arrived for this long
PI_STALL_S = 60.0


def local_camera_info(index: int) -> dict:
    return {"source": "local", "device": f"local camera index {index}",
            "transport": "local", "rotation_deg": 0,
            "capture_clock": "receiver_wall_at_read"}


def open_source(a: argparse.Namespace):
    """Return (cap, describe) where describe() gives evidence.camera for the last
    frame read. Raises CameraUnavailable."""
    if a.source == "local":
        cap = open_camera(a.camera)
        return cap, lambda: local_camera_info(a.camera)
    try:
        cap = open_pi_camera(host=a.pi_host, user=a.pi_user, key=a.pi_key,
                             port=a.pi_port, size=a.pi_size, fps=a.pi_fps,
                             jpeg_quality=a.pi_quality, rotation=a.pi_rotation,
                             startup_timeout_s=a.pi_startup_timeout_s)
    except (PiSourceError, ValueError, OSError) as e:
        raise CameraUnavailable(f"Pi camera unavailable: {e}. Check {ENV_HOST}/"
                                "--pi-host, the SSH key, and that the host key is "
                                "already trusted (ssh once by hand). No frame was "
                                "faked.") from None
    return cap, cap.camera_info


def run(a: argparse.Namespace) -> int:
    try:
        sector = validate_sector(a.sector)
        out_dir = ensure_evidence_dir(a.out_dir)
    except ValueError as e:
        _log(f"ERROR: {e}")
        return 1

    detectors = []
    if not a.no_dnn:
        detectors.append(TorchPersonDetector(a.dnn_model, a.person_thresh))
    detectors.append(OpenCVDetectors())
    trigger_families = TRIGGERS[a.trigger]

    try:
        cap, describe = open_source(a)
    except CameraUnavailable as e:
        _log(f"ERROR: {e}")
        return EXIT_CAMERA_UNAVAILABLE

    if a.start_delay_s > 0:
        _log(f"camera open; ignoring frames for {a.start_delay_s:.0f}s so the "
             "operator can step out of view")
        t_wait = time.time() + a.start_delay_s
        while time.time() < t_wait:
            cap.read()  # keep the stream draining; frames are discarded
        _log("capture started")
    start = time.time()
    boot_id = f"b{int(start)}"  # unique per run so obs_ids never collide across runs
    run_id = f"{a.declare_drone}-{boot_id}" + (f"-{a.label}" if a.label else "")
    frame_log = open(os.path.join(out_dir, f"{run_id}_frames.jsonl"), "w")
    sightings_path = os.path.join(out_dir, "sightings.jsonl")
    gate = SightingGate(confirm_frames=a.confirm_frames, rearm_s=a.rearm_s)
    frames = 0
    frames_with = {f: 0 for f in FAMILIES}
    first_hit_s = {f: None for f in FAMILIES}
    sightings: List[dict] = []
    empty_streak = 0
    last_frame_at = time.time()
    _log(f"run {run_id}: source={a.source} sector={sector} trigger={a.trigger} "
         f"min_box_frac={a.min_box_frac} "
         f"detectors={[getattr(d, 'name', 'opencv') for d in detectors]} "
         f"duration={a.duration_s:.0f}s evidence_dir={out_dir}")
    try:
        while time.time() - start < a.duration_s:
            ok, frame = cap.read()
            rx_time = time.time()
            # Pi: the Pi's capture time of this frame; local: read time (as before)
            cap_t = getattr(cap, "last_capture_time", None) if ok else None
            obs_time = cap_t if cap_t is not None else rx_time
            if a.source == "pi" and not ok:
                if not cap.isOpened() or rx_time - last_frame_at > PI_STALL_S:
                    _log("ERROR: Pi stream lost (SSH closed or no frame for "
                         f"{rx_time - last_frame_at:.0f}s); stopping. "
                         f"stats={getattr(cap, 'stats', {})}")
                    return EXIT_CAMERA_UNAVAILABLE
                continue
            if not ok or is_black(frame):
                empty_streak += 1
                if empty_streak > 60:
                    _log("ERROR: camera stopped delivering frames. " + CAMERA_HELP)
                    return EXIT_CAMERA_UNAVAILABLE
                continue
            empty_streak = 0
            last_frame_at = rx_time
            frames += 1
            dets: List[Detection] = []
            for d in detectors:
                dets.extend(d.detect_all(frame))
            rel = obs_time - start
            for f in FAMILIES:
                if any(d.family == f for d in dets):
                    frames_with[f] += 1
                    if first_hit_s[f] is None:
                        first_hit_s[f] = round(rel, 2)
            frame_log.write(json.dumps({
                "t": round(obs_time, 3), "rel_s": round(rel, 2),
                "rx": round(rx_time, 3),
                "counts": {f: sum(d.family == f for d in dets) for f in FAMILIES},
                "best": {f: (b.to_json() if (b := best(dets, f)) else None)
                         for f in FAMILIES},
                "all": [d.to_json() for d in dets]}) + "\n")

            trig = select_trigger(dets, trigger_families,
                                  a.min_box_frac * frame.shape[0])
            if not gate.update(obs_time, trig is not None):
                continue
            seq = len(sightings) + 1
            obs_id = f"{a.declare_drone}-{boot_id}-{seq:06d}"
            header = (f"{obs_id} LIVE-HW BENCH sector {sector} "
                      f"{iso_utc(obs_time)}")
            frame_ref, sha, ann = save_evidence(
                out_dir, obs_id, frame, annotate_all(frame, dets, trig, header))
            s = make_sighting(drone_id=a.declare_drone, boot_id=boot_id, seq=seq,
                              sector=sector, obs_time=obs_time, frame_ref=frame_ref,
                              frame_sha256=sha, annotated_ref=ann,
                              frame_size=[int(frame.shape[1]), int(frame.shape[0])],
                              trigger=trig, all_dets=dets, operator=a.operator,
                              camera=describe())
            sightings.append(s)
            line = json.dumps(s)
            print(line, flush=True)
            with open(sightings_path, "a") as f:
                f.write(line + "\n")
            _log(f"[+{rel:.1f}s] SIGHTING {obs_id} {trig.family} {trig.detector} "
                 f"score={trig.score:.3f} bbox={trig.bbox} -> {frame_ref}")
            if a.once:
                break
    finally:
        cap.release()
        frame_log.close()

    elapsed = time.time() - start
    summary = {
        "run_id": run_id, "label": a.label, "source": a.source,
        "sector": sector, "trigger": a.trigger,
        "min_box_frac": a.min_box_frac,
        "elapsed_s": round(elapsed, 1), "frames": frames,
        "fps": round(frames / elapsed, 2) if elapsed else 0.0,
        "frames_with": frames_with,
        "frac_frames_with": {f: round(n / frames, 3) if frames else 0.0
                             for f, n in frames_with.items()},
        "first_hit_s": first_hit_s,
        "sightings_emitted": [s["obs_id"] for s in sightings],
        "frames_attached_to_existing_sighting": gate.suppressed_total,
    }
    if a.source == "pi":
        summary["pi_stream"] = dict(getattr(cap, "stats", {}))
        summary["camera"] = describe()
    with open(os.path.join(out_dir, f"{run_id}_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    _log("SUMMARY " + json.dumps(summary))
    if sightings:
        return EXIT_OK
    where = "the Pi camera" if a.source == "pi" else f"camera {a.camera}"
    _log(f"NO SIGHTING within {a.duration_s:.0f}s on {where}; "
         "no picture saved, no sighting emitted.")
    return EXIT_NO_PERSON


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", choices=("local", "pi"), default="local",
                   help="local = this machine's camera (default); pi = Raspberry Pi "
                        "camera as JPEG frames over SSH")
    p.add_argument("--camera", type=int, default=0, help="local camera index")
    g = p.add_argument_group("--source pi (nothing is installed on the Pi)")
    g.add_argument("--pi-host", default=None, help=f"Pi host or IP (or ${ENV_HOST})")
    g.add_argument("--pi-user", default=None, help=f"SSH user (or ${ENV_USER})")
    g.add_argument("--pi-key", default=None, help=f"SSH private key (or ${ENV_KEY})")
    g.add_argument("--pi-port", type=int, default=None)
    g.add_argument("--pi-size", type=parse_size, default=(1280, 720),
                   help="capture size WxH (default 1280x720)")
    g.add_argument("--pi-fps", type=float, default=5.0)
    g.add_argument("--pi-quality", type=int, default=80, help="JPEG quality 1-100")
    g.add_argument("--pi-rotation", type=int, choices=sorted(ROTATIONS), default=180,
                   help="rotate frames on arrival (default 180: camera mounted "
                        "upside down)")
    g.add_argument("--pi-startup-timeout-s", type=float, default=30.0)
    p.add_argument("--declare-drone", default="D1")
    p.add_argument("--sector", "--declare-cell", dest="sector", required=True,
                   help="operator-assigned sector A-Z (SECTOR_ONLY location)")
    p.add_argument("--operator", default=None, help="operator who assigned the sector")
    p.add_argument("--out-dir", default=DEFAULT_EVIDENCE_DIR,
                   help="evidence dir; must be outside any Git work tree")
    p.add_argument("--duration-s", "--timeout-s", dest="duration_s", type=float,
                   default=30.0)
    p.add_argument("--start-delay-s", type=float, default=0.0,
                   help="open the camera, then ignore frames for this long")
    p.add_argument("--once", action="store_true", help="stop after the first sighting")
    p.add_argument("--trigger", choices=sorted(TRIGGERS), default="person",
                   help="person = pretrained person detector only (default); "
                        "any = also HOG / upper-body / face-only")
    p.add_argument("--dnn-model", choices=sorted(DNN_MODELS), default=DEFAULT_DNN_MODEL)
    p.add_argument("--person-thresh", type=float, default=0.6)
    p.add_argument("--no-dnn", action="store_true", help="OpenCV detectors only")
    p.add_argument("--min-box-frac", type=float, default=0.15,
                   help="min box height as a fraction of frame height to trigger a "
                        "sighting (BENCH-tuned: drops window reflections); 0 = off")
    p.add_argument("--confirm-frames", type=int, default=3)
    p.add_argument("--rearm-s", type=float, default=60.0,
                   help="absence needed before the same camera emits a new sighting")
    p.add_argument("--label", default="", help="tag for this run's log files")
    a = p.parse_args(argv)
    if a.trigger == "person" and a.no_dnn:
        p.error("--no-dnn requires --trigger any")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())

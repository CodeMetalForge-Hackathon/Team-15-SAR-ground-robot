"""Live camera perception + mapping runner (advisory; sends nothing to the rover).

    # real Pi camera (same SSH JPEG stream as perception.live_camera):
    python3 -B -m camera_mapping.live --source pi --pi-host team15-pi --dashboard http://127.0.0.1:8000
    # recorded frames (labelled RECORDED, never LIVE):
    python3 -B -m camera_mapping.live --source replay --replay ~/Team15_evidence/camera/*.png

Each processed frame: Faster R-CNN (multi-class COCO) -> distance estimates ->
tracker -> local map -> corridor assessment -> route suggestion. The state and
an annotated JPEG are POSTed to the dashboard (/api/perception/frame). A
background thread asks for a rescue advisory (deterministic + optional guarded
Qwen via rescue_qwen.service) when the assessment changes or every
--advise-every-s seconds. If the camera stops, heartbeats say DISCONNECTED and
the dashboard degrades to UNKNOWN.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sys
import threading
import time
import urllib.request
from typing import List, Optional

import cv2
import numpy as np

from .advisory import advise, http_qwen
from .config import load_config
from .detector import TorchObstacleDetector
from .pipeline import PerceptionPipeline

COLORS = {"person": (0, 200, 0)}
OBST = (0, 140, 255)
UNK = (160, 160, 160)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def post(url: str, body: dict, timeout: float = 3.0) -> Optional[dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:  # noqa: BLE001 - dashboard may be down; keep perceiving
        _log(f"post {url} failed: {type(e).__name__}: {e}")
        return None


def annotate(frame: np.ndarray, st: dict) -> np.ndarray:
    out = frame.copy()
    H, W = out.shape[:2]
    cm = st["camera_model"]
    m = st["mount"]
    if m["measured"]:
        from .geometry import horizon_row
        from .config import CameraModel
        cam = CameraModel(cm["width"], cm["height"], cm["fx"], cm["fy"], cm["cx"], cm["cy"])
        hz = int(horizon_row(cam, m["pitch_deg"]))
        if 0 <= hz < H:
            cv2.line(out, (0, hz), (W, hz), (200, 200, 0), 1)
    for r in st["objects"]:
        x, y, w, h = [int(v) for v in r["bbox"]]
        col = COLORS.get(r["object_class"], OBST)
        if r["validity"] == "TENTATIVE":
            col = UNK
        cv2.rectangle(out, (x, y), (x + w, y + h), col, 3 if r["validity"] == "VALID" else 1)
        fd = r.get("filtered_distance")
        dist = f"~{fd['distance_m']:.2f}m +/-{2 * fd['sigma_m']:.2f}" if fd else "dist UNKNOWN"
        txt = f"{r['object_class']} {r['detection_confidence']:.2f} | {dist}"
        cv2.putText(out, txt, (x + 2, max(18, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(out, txt, (x + 2, max(18, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    a = st["assessment"]["status"]
    banner = f"{st['source_mode']} | corridor {a} | {st['calibration_status']} camera estimates"
    cv2.rectangle(out, (0, H - 30), (W, H), (0, 0, 0), -1)
    cv2.putText(out, banner, (8, H - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return out


class Advisor(threading.Thread):
    def __init__(self, dashboard: str, qwen_url: Optional[str], every_s: float) -> None:
        super().__init__(daemon=True)
        self.dashboard, self.every_s = dashboard, every_s
        self.qwen = http_qwen(qwen_url) if qwen_url else None
        self.qwen_url = qwen_url
        self.latest: Optional[dict] = None
        self.ev = threading.Event()
        self.last_status, self.last_run = None, 0.0

    def offer(self, st: dict) -> None:
        self.latest = st
        sig = (st["assessment"]["status"], len(st["persons"]) > 0)
        if sig != self.last_status or time.time() - self.last_run >= self.every_s:
            self.last_status = sig
            self.ev.set()

    def run(self) -> None:
        while True:
            self.ev.wait()
            self.ev.clear()
            st = self.latest
            if st is None:
                continue
            self.last_run = time.time()
            adv = advise(st, self.qwen)
            adv["qwen_url"] = self.qwen_url
            if self.dashboard:
                post(self.dashboard + "/api/perception/advisory", adv, timeout=3.0)


class ReplaySource:
    """Recorded frames from disk. Always labelled RECORDED; capture time = file mtime."""

    def __init__(self, paths: List[str], fps: float = 2.0, loop: bool = True) -> None:
        self.paths = sorted(p for p in paths if p.lower().endswith((".png", ".jpg", ".jpeg"))
                            and "_annotated" not in p)
        if not self.paths:
            raise FileNotFoundError("no replay frames")
        self.i, self.period, self.loop, self.last_capture_time = 0, 1.0 / fps, loop, None
        self.next_t = time.time()

    def isOpened(self) -> bool:
        return self.loop or self.i < len(self.paths)

    def read(self):
        if self.i >= len(self.paths):
            if not self.loop:
                return False, None
            self.i = 0
        now = time.time()
        if now < self.next_t:
            time.sleep(self.next_t - now)
        self.next_t = time.time() + self.period
        p = self.paths[self.i]
        self.i += 1
        self.last_capture_time = time.time()
        self.current = p
        return True, cv2.imread(p)

    def release(self) -> None:
        pass

    def camera_info(self) -> dict:
        return {"source": "replay", "device": "recorded frames", "transport": "file",
                "frame_ref": getattr(self, "current", None), "capture_clock": "replay_wall",
                "intrinsics_note": "IMX708 intrinsics apply only to frames recorded by the Pi camera; "
                                   "distances on other recordings are not meaningful"}


def open_source(a):
    if a.source == "replay":
        files = [f for pat in a.replay for f in glob.glob(os.path.expanduser(pat))]
        src = ReplaySource(files, fps=a.replay_fps)
        return src, src.camera_info, "RECORDED"
    if a.source == "local":
        from perception.live_camera import local_camera_info, open_camera
        cap = open_camera(a.camera)
        return cap, lambda: local_camera_info(a.camera), "LIVE-HW"
    from perception.pi_source import open_pi_camera
    cap = open_pi_camera(host=a.pi_host, user=a.pi_user, key=a.pi_key, port=None,
                         size=(1280, 720), fps=a.pi_fps, jpeg_quality=80, rotation=a.pi_rotation,
                         startup_timeout_s=30.0)
    return cap, cap.camera_info, "LIVE-HW"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Camera perception + local map runner (advisory)")
    p.add_argument("--source", choices=("pi", "local", "replay"), default="pi")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--pi-host", default=None)
    p.add_argument("--pi-user", default=None)
    p.add_argument("--pi-key", default=None)
    p.add_argument("--pi-fps", type=float, default=5.0)
    p.add_argument("--pi-rotation", type=int, default=180)
    p.add_argument("--replay", nargs="*", default=[])
    p.add_argument("--replay-fps", type=float, default=2.0)
    p.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "configs", "imx708_robot.json"))
    p.add_argument("--dashboard", default="http://127.0.0.1:8000")
    p.add_argument("--qwen-url", default=None, help="rescue_qwen.service base URL, e.g. http://127.0.0.1:8090")
    p.add_argument("--advise-every-s", type=float, default=10.0)
    p.add_argument("--dnn-model", default="frcnn_r50_fpn_v2")
    p.add_argument("--depth", choices=("off", "metric", "relative"), default="off")
    p.add_argument("--depth-every", type=int, default=3, help="run mono-depth every N frames")
    p.add_argument("--duration-s", type=float, default=0, help="0 = until Ctrl-C")
    p.add_argument("--jsonl", default=None, help="append each state (no images) to this file")
    p.add_argument("--jpeg-quality", type=int, default=70)
    a = p.parse_args(argv)

    cfg = load_config(a.config)
    _log(f"config {a.config}: intrinsics {cfg.camera.source}, mount measured={cfg.mount.usable}, "
         f"calibration {cfg.calibration_status}")
    det = TorchObstacleDetector(a.dnn_model)
    depth = None
    if a.depth != "off":
        from .depth import METRIC_INDOOR, RELATIVE_SMALL, MonoDepth
        depth = MonoDepth(METRIC_INDOOR if a.depth == "metric" else RELATIVE_SMALL)
    try:
        cap, describe, mode = open_source(a)
    except Exception as e:  # noqa: BLE001
        _log(f"ERROR camera unavailable: {e}")
        post(a.dashboard + "/api/perception/health", {"camera_status": "DISCONNECTED", "error": str(e)[:300]})
        return 3
    ok, frame = cap.read()
    if ok and frame is not None:
        t = time.perf_counter()
        det.detect(frame)
        _log(f"detector warm-up {time.perf_counter() - t:.2f}s (frame discarded)")
    pipe = PerceptionPipeline(cfg, source_mode=mode, camera_info=describe())
    advisor = Advisor(a.dashboard, a.qwen_url, a.advise_every_s)
    advisor.start()
    jl = open(os.path.expanduser(a.jsonl), "a") if a.jsonl else None
    start, fails, n, last_depth = time.time(), 0, 0, {}
    try:
        while not a.duration_s or time.time() - start < a.duration_s:
            ok, frame = cap.read()
            rx = time.time()
            if not ok or frame is None or frame.size == 0:
                fails += 1
                if fails % 20 == 1:
                    post(a.dashboard + "/api/perception/health",
                         {"camera_status": "NO_FRAMES", "source_mode": mode, "t": rx})
                if not cap.isOpened() or fails > 300:
                    post(a.dashboard + "/api/perception/health",
                         {"camera_status": "DISCONNECTED", "source_mode": mode, "t": rx})
                    _log("ERROR camera stream lost")
                    return 3
                time.sleep(0.05)
                continue
            fails = 0
            n += 1
            cap_t = getattr(cap, "last_capture_time", None) or rx
            t0 = time.perf_counter()
            dets = det.detect(frame)
            det_ms = (time.perf_counter() - t0) * 1000
            lat = {"detector_ms": round(det_ms, 1), "capture_to_rx_ms": round((rx - cap_t) * 1000, 1)}
            dres = None
            if depth is not None and n % a.depth_every == 0:
                from .depth import box_depths
                dm = depth.depth_map(frame)
                dres = box_depths(dm, dets, depth.metric)
                lat["depth_ms"] = round(depth.last_ms or 0, 1)
            st = pipe.process(cap_t, dets, frame_size=(frame.shape[1], frame.shape[0]),
                              latency_ms=lat, frame_seq=n, depth=dres, rx_time=rx)
            st["camera"] = describe()
            st["depth_model"] = None if depth is None else {
                "model": depth.model_id, "kind": "METRIC_UNVALIDATED" if depth.metric else "RELATIVE",
                "used_in_fusion": cfg.depth_model_validated and depth.metric}
            t1 = time.perf_counter()
            ann = annotate(frame, st)
            okj, jpg = cv2.imencode(".jpg", ann, [cv2.IMWRITE_JPEG_QUALITY, a.jpeg_quality])
            st["latency_ms"]["annotate_ms"] = round((time.perf_counter() - t1) * 1000, 1)
            st["latency_ms"]["total_ms"] = round((time.time() - rx) * 1000 + st["latency_ms"]["capture_to_rx_ms"], 1)
            body = {"state": st, "jpeg_b64": base64.b64encode(jpg.tobytes()).decode() if okj else None}
            post(a.dashboard + "/api/perception/frame", body)
            advisor.offer(st)
            if jl:
                jl.write(json.dumps(st) + "\n")
            if n % 10 == 1:
                _log(f"frame {n}: {len(dets)} dets, corridor {st['assessment']['status']}, "
                     f"route {st['route']['status']}, det {det_ms:.0f} ms")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if jl:
            jl.close()
        post(a.dashboard + "/api/perception/health", {"camera_status": "STOPPED", "source_mode": mode,
                                                       "t": time.time()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

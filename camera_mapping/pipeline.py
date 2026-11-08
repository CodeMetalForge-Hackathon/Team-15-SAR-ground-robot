"""Frame -> structured perception state (records, map, assessment, route).

The pipeline is pure given (detections, timestamp): no I/O, no motors. The
camera source, detector and dashboard publisher live in live.py.
"""
from __future__ import annotations

import math
import time
from typing import Dict, List, Optional

from . import SCHEMA_PERCEPTION, SOURCE_LABEL
from .assess import assess, corridor_half, near_bearing_rad, suggest_route
from .candidates import evaluate_candidates
from .config import PerceptionConfig
from .detector import ObjectDetection, UNSUPPORTED_REQUESTED
from .distance import ESTIMATED, MethodResult, estimate_all
from .local_map import LocalMap
from .tracking import Tracker

VALID, TENTATIVE_V, COASTING_V = "VALID", "TENTATIVE", "COASTING"


def corridor_position(lateral_m: Optional[float], half_w_m: float, bearing_deg: float,
                      half: float, bearing_span=None, near_b_deg: Optional[float] = None) -> str:
    if lateral_m is None:
        if bearing_span is not None and near_b_deg is not None:
            lo, hi = bearing_span
            if lo <= near_b_deg and hi >= -near_b_deg:      # same rule as assess.assess
                return "IN_CORRIDOR_BEARING"
        elif abs(bearing_deg) < 6.0:
            return "IN_CORRIDOR_BEARING"
        return "LEFT_BEARING" if bearing_deg > 0 else "RIGHT_BEARING"
    lo, hi = lateral_m - half_w_m, lateral_m + half_w_m
    if hi >= -half and lo <= half:
        return "IN_CORRIDOR"
    return "LEFT_OF_CORRIDOR" if lo > half else "RIGHT_OF_CORRIDOR"


class PerceptionPipeline:
    def __init__(self, cfg: PerceptionConfig, source_mode: str = "LIVE-HW",
                 camera_info: Optional[dict] = None, **tracker_kw) -> None:
        self.cfg = cfg
        self.tracker = Tracker(**tracker_kw)
        self.map = LocalMap(cfg)
        self.source_mode = source_mode            # LIVE-HW | RECORDED | SYNTHETIC
        self.camera_info = dict(camera_info or {})
        self.frames = 0
        self.last_state: Optional[dict] = None

    def process(self, t: float, dets: List[ObjectDetection], *, frame_size=None,
                latency_ms: Optional[Dict[str, float]] = None, frame_seq: Optional[int] = None,
                depth: Optional[Dict[int, MethodResult]] = None, robot_moving: bool = False,
                rx_time: Optional[float] = None) -> dict:
        t0 = time.perf_counter()
        self.frames += 1
        if frame_size and tuple(frame_size) != (self.cfg.camera.width, self.cfg.camera.height):
            self.cfg.camera = self.cfg.camera.scaled(int(frame_size[0]), int(frame_size[1]))
        if robot_moving:
            self.map.reset()                       # no pose: never shift into a guessed frame
            for tr in self.tracker.tracks.values():
                tr.history, tr.pending_jump = [], []
        ests = estimate_all(dets, self.cfg, depth)
        tracks = self.tracker.update(t, dets, ests)
        self.map.update(t, tracks)
        assessment = assess(self.map, tracks, self.cfg)
        route = suggest_route(self.map, self.cfg, assessment)
        candidates = evaluate_candidates(self.map, self.cfg)
        half = corridor_half(self.cfg)
        near_b = math.degrees(near_bearing_rad(self.map, self.cfg))
        records = []
        fp_by_id = {f.track_id: f for f in self.map.footprints}
        for tr in sorted(tracks, key=lambda x: x.track_id):
            if tr.frame_seen != self.tracker.frames and tr.state != "COASTING":
                continue
            e = tr.estimate
            f = tr.filtered()
            fp = fp_by_id.get(tr.track_id)
            fd = None if f is None else {"distance_m": round(f[0], 3), "sigma_m": round(f[1], 3),
                                         "lateral_m": round(f[2], 3), "samples": len(tr.history)}
            records.append({
                "track_id": tr.track_id,
                "object_class": tr.label,
                "category": "PERSON" if tr.label == "person" else "OBSTACLE",
                "bbox": [round(v, 1) for v in tr.bbox],
                "detection_confidence": round(tr.score, 4),
                "confidence_kind": "frcnn_class_score (not a calibrated probability)",
                "distance": e.to_json() if e else None,
                "filtered_distance": fd,
                "distance_method": e.method if e and e.status == ESTIMATED else None,
                "uncertainty_m": None if not fd else fd["sigma_m"],
                "corridor_position": corridor_position(
                    fd["lateral_m"] if fd else None, fp.half_w if fp and fp.range_known else 0.0,
                    e.bearing_deg if e else 0.0, half,
                    None if fp is None else (math.degrees(fp.bearing_lo), math.degrees(fp.bearing_hi)), near_b),
                "timestamp": round(tr.last_t, 3),
                "data_source": SOURCE_LABEL,
                "source_mode": self.source_mode,
                "validity": {"CONFIRMED": VALID, "TENTATIVE": TENTATIVE_V,
                             "COASTING": COASTING_V}[tr.state],
                "track_hits": tr.hits, "rejected_jumps": tr.rejected_jumps,
            })
        proc_ms = (time.perf_counter() - t0) * 1000
        lat = dict(latency_ms or {})
        lat["mapping_ms"] = round(proc_ms, 2)
        st = {
            "schema": SCHEMA_PERCEPTION,
            "t": round(t, 3), "rx_time": None if rx_time is None else round(rx_time, 3),
            "frame_seq": frame_seq, "frames_processed": self.frames,
            "source_mode": self.source_mode, "data_source": SOURCE_LABEL,
            "camera": self.camera_info,
            "camera_model": {"fx": round(self.cfg.camera.fx, 1), "fy": round(self.cfg.camera.fy, 1),
                             "cx": round(self.cfg.camera.cx, 1), "cy": round(self.cfg.camera.cy, 1),
                             "width": self.cfg.camera.width, "height": self.cfg.camera.height,
                             "hfov_deg": round(self.cfg.camera.hfov_deg, 2),
                             "vfov_deg": round(self.cfg.camera.vfov_deg, 2),
                             "intrinsics_source": self.cfg.camera.source},
            "mount": {"measured": self.cfg.mount.usable, "height_m": self.cfg.mount.height_m,
                      "pitch_deg": self.cfg.mount.pitch_deg, "pitch_source": self.cfg.mount.pitch_source,
                      "measured_by": self.cfg.mount.measured_by},
            "calibration_status": self.cfg.calibration_status,
            "calibration_ref": self.cfg.calibration_ref,
            "objects": records,
            "persons": [r for r in records if r["category"] == "PERSON"],
            "map": self.map.to_json(),
            "assessment": assessment,
            "route": route,
            "candidates": candidates,
            "latency_ms": lat,
            "unsupported_classes": UNSUPPORTED_REQUESTED,
            "motion_authority": "NONE",
            "never": "camera distances are estimates, never physical range-sensor measurements",
        }
        self.last_state = st
        return st


def stale_view(state: Optional[dict], now: float, stale_after_s: float = 2.0) -> dict:
    """What the dashboard serves: a stale or missing state degrades to UNKNOWN."""
    if not state:
        return {"schema": SCHEMA_PERCEPTION, "status": "NO_DATA", "fresh": False, "age_s": None,
                "assessment": {"status": "UNKNOWN", "reasons": ["no camera perception data"]},
                "objects": [], "persons": []}
    age = now - (state.get("rx_time") or state.get("t") or 0)
    out = dict(state)
    out["age_s"] = round(age, 2)
    out["fresh"] = age <= stale_after_s and not math.isnan(age)
    if not out["fresh"]:
        out["status"] = "STALE"
        out["assessment"] = dict(state.get("assessment") or {}, status="UNKNOWN",
                                 reasons=[f"perception data stale ({age:.1f} s old)"] +
                                 list((state.get("assessment") or {}).get("reasons") or []))
        out["route"] = dict(state.get("route") or {}, status="STALE_NOT_USABLE", waypoints=[])
        out["candidates"] = [dict(c, status="UNOBSERVED", reasons=["perception data stale"])
                             for c in state.get("candidates") or []]
        m = dict(state.get("map") or {})
        if m.get("rows"):                          # nothing stale is drawn as FREE or OCCUPIED
            m["rows"] = ["U" * len(r) for r in m["rows"]]
            m["footprints"] = []
            m["stale"] = True
        out["map"] = m
    else:
        out["status"] = "LIVE" if state.get("source_mode") == "LIVE-HW" else state.get("source_mode")
    return out

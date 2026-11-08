"""Holds the latest camera-perception state for the dashboard (in memory only).

The runner (camera_mapping.live) POSTs state + annotated JPEG; the dashboard
serves them. Posted states are validated so the page can never show a camera
estimate as a physical measurement:
  * ``data_source`` must be CAMERA_ESTIMATE and ``motion_authority`` NONE;
  * any distance labelled VERIFIED* is refused;
  * ``source_mode`` must be LIVE-HW, RECORDED or SYNTHETIC.
Frames are held in memory only (never written to disk or Git).
"""
from __future__ import annotations

import base64
import binascii
import threading
import time
from typing import Optional

from camera_mapping.pipeline import stale_view

MODES = {"LIVE-HW", "RECORDED", "SYNTHETIC"}
MAX_JPEG = 4 * 1024 * 1024


class InvalidPerception(ValueError):
    pass


def validate_state(st: dict) -> None:
    if not isinstance(st, dict):
        raise InvalidPerception("state must be an object")
    if st.get("schema") != "team15.camera_perception/1":
        raise InvalidPerception("unknown schema")
    if st.get("data_source") != "CAMERA_ESTIMATE":
        raise InvalidPerception("data_source must be CAMERA_ESTIMATE")
    if st.get("motion_authority") != "NONE":
        raise InvalidPerception("camera perception has no motion authority")
    if st.get("source_mode") not in MODES:
        raise InvalidPerception(f"source_mode must be one of {sorted(MODES)}")
    for o in st.get("objects") or []:
        lab = str(((o.get("distance") or {}).get("label")) or "")
        if "VERIFIED" in lab.upper():
            raise InvalidPerception("camera distances can never be VERIFIED")
        if o.get("data_source") != "CAMERA_ESTIMATE":
            raise InvalidPerception("object data_source must be CAMERA_ESTIMATE")
    if not isinstance(st.get("t"), (int, float)):
        raise InvalidPerception("t (capture time) required")


class PerceptionStore:
    def __init__(self, stale_after_s: float = 2.0, clock=time.time) -> None:
        self.lock = threading.Lock()
        self.state: Optional[dict] = None
        self.jpeg: Optional[bytes] = None
        self.advisory: Optional[dict] = None
        self.health: dict = {}
        self.received = 0
        self.received_at: Optional[float] = None
        self.stale_after_s, self.clock = stale_after_s, clock

    def post_frame(self, body: dict) -> dict:
        st = (body or {}).get("state")
        validate_state(st)
        jpg = None
        if body.get("jpeg_b64"):
            try:
                jpg = base64.b64decode(body["jpeg_b64"], validate=True)
            except (binascii.Error, ValueError):
                raise InvalidPerception("jpeg_b64 is not base64") from None
            if len(jpg) > MAX_JPEG or not jpg.startswith(b"\xff\xd8"):
                raise InvalidPerception("frame must be a JPEG under 4 MB")
        with self.lock:
            st = dict(st)
            st["rx_time"] = self.clock()           # freshness is judged on the dashboard clock
            self.state, self.jpeg = st, jpg
            self.received += 1
            self.received_at = st["rx_time"]
            self.health.update({"camera_status": "STREAMING", "source_mode": st["source_mode"]})
        return {"ok": True, "received": self.received}

    def post_advisory(self, adv: dict) -> dict:
        if not isinstance(adv, dict) or adv.get("authority") != "NONE" or adv.get("advisory_only") is not True:
            raise InvalidPerception("advisory must be advisory_only with authority NONE")
        with self.lock:
            self.advisory = dict(adv, received_at=self.clock())
        return {"ok": True}

    def post_health(self, h: dict) -> dict:
        if not isinstance(h, dict):
            raise InvalidPerception("health must be an object")
        with self.lock:
            self.health.update({k: h[k] for k in ("camera_status", "source_mode", "error", "t") if k in h})
            self.health["health_at"] = self.clock()
        return {"ok": True}

    def view(self) -> dict:
        with self.lock:
            v = stale_view(self.state, self.clock(), self.stale_after_s)
            v["frame_available"] = self.jpeg is not None
            return v

    def frame(self) -> Optional[bytes]:
        with self.lock:
            return self.jpeg

    def advisory_view(self) -> dict:
        with self.lock:
            if not self.advisory:
                return {"status": "NO_ADVISORY", "authority": "NONE"}
            a = dict(self.advisory)
            a["age_s"] = round(self.clock() - a["received_at"], 1)
            st_t = a.get("state_t")
            cur = (self.state or {}).get("t")
            a["evidence_current"] = bool(st_t and cur and abs(cur - st_t) < 15)
            return a

    def health_view(self, rover: Optional[dict] = None) -> dict:
        v = self.view()
        with self.lock:
            h = dict(self.health)
        cam = h.get("camera_status") or "NOT_CONNECTED"
        if cam == "STREAMING" and not v.get("fresh"):
            cam = "STALE"
        lat = v.get("latency_ms") or {}
        return {
            "camera_status": cam,
            "camera_error": h.get("error"),
            "source_mode": v.get("source_mode") or h.get("source_mode"),
            "camera": v.get("camera"),
            "perception_latency_ms": lat,
            "map_age_s": v.get("age_s"),
            "map_fresh": bool(v.get("fresh")),
            "frames_received": self.received,
            "calibration_status": v.get("calibration_status") or "UNCALIBRATED",
            "intrinsics_source": (v.get("camera_model") or {}).get("intrinsics_source"),
            "mount_measured": (v.get("mount") or {}).get("measured", False),
            "rover": rover or {"status": "NOT_CONNECTED", "source": "NONE",
                               "note": "no robot status source configured; navigation is SIMULATED only"},
            "labels": {"distances": "CAMERA_ESTIMATE (not a range sensor)",
                       "navigation": "SIMULATED / advisory only", "detections": v.get("source_mode") or "NONE"},
        }

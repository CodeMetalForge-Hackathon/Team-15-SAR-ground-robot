"""SYNTHETIC fixtures for unit tests. They test logic only and are never evidence of
physical distance accuracy (that needs the tape-measured calibration run)."""
from __future__ import annotations

from camera_mapping import geometry as G
from camera_mapping.config import MountGeometry, PerceptionConfig
from camera_mapping.detector import ObjectDetection

H_M, PITCH = 0.15, 8.0


def cfg(measured: bool = True, **kw) -> PerceptionConfig:
    m = MountGeometry(height_m=H_M, pitch_deg=PITCH, measured=measured, measured_by="SYNTHETIC-TEST")
    return PerceptionConfig(mount=m, **kw)


def floor_box(c: PerceptionConfig, label: str, x_m: float, y_m: float = 0.0, h_m: float = 0.88,
              w_m: float = 0.45, score: float = 0.9) -> ObjectDetection:
    """Box of an upright object of height h_m whose floor contact is at (x_m, y_m)."""
    cam = c.camera
    v = G.ground_row(cam, x_m, c.mount.height_m, c.mount.pitch_deg)
    u = cam.cx - cam.fx * (y_m / x_m)
    h = cam.fy * h_m / x_m
    w = cam.fx * w_m / x_m
    return ObjectDetection(label, [u - w / 2, v - h, w, h], score)

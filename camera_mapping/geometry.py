"""Pinhole geometry: pixel rays, ground-plane intersection, known-height range.

Robot frame (used everywhere in this package): origin on the floor directly
below the camera lens; x forward, y LEFT, z up. Camera pitch is positive DOWN.
Image: u right, v down; (cx, cy) principal point.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

from .config import CameraModel


def normalized(cam: CameraModel, u: float, v: float) -> Tuple[float, float]:
    return (u - cam.cx) / cam.fx, (v - cam.cy) / cam.fy


def horizon_row(cam: CameraModel, pitch_deg: float) -> float:
    """Image row of the horizon (rays above it never reach the floor)."""
    return cam.cy - cam.fy * math.tan(math.radians(pitch_deg))


def ground_point(cam: CameraModel, u: float, v: float, height_m: float,
                 pitch_deg: float) -> Optional[Tuple[float, float]]:
    """Floor point (x forward, y left) seen at pixel (u, v), or None when the ray
    is at or above the horizon."""
    a, b = normalized(cam, u, v)
    th = math.radians(pitch_deg)
    down = math.sin(th) + b * math.cos(th)
    if down <= 1e-6:
        return None
    t = height_m / down
    fwd = t * (math.cos(th) - b * math.sin(th))
    if fwd <= 0:
        return None
    return fwd, -t * a


def ground_row(cam: CameraModel, x_fwd: float, height_m: float, pitch_deg: float) -> Optional[float]:
    """Inverse of ground_point for points on the optical-axis column."""
    if x_fwd <= 0:
        return None
    th = math.radians(pitch_deg)
    # angle below horizontal of the ray to the floor point
    phi = math.atan2(height_m, x_fwd)
    b = math.tan(phi - th)
    return cam.cy + b * cam.fy


def nearest_visible_floor(cam: CameraModel, height_m: float, pitch_deg: float) -> Optional[float]:
    """Forward distance of the floor at the bottom image row (the blind zone ends here)."""
    p = ground_point(cam, cam.cx, cam.height - 1, height_m, pitch_deg)
    return p[0] if p else None


def bearing_rad(cam: CameraModel, u: float) -> float:
    """Horizontal angle of image column u, positive LEFT (robot convention)."""
    return -math.atan((u - cam.cx) / cam.fx)


def known_height_range(cam: CameraModel, top_v: float, bottom_v: float,
                       object_h_m: float) -> Optional[float]:
    """Range along the optical axis for an upright object of known height whose
    full extent spans rows top_v..bottom_v (pinhole, small-pitch approximation)."""
    h_px = bottom_v - top_v
    if h_px <= 1:
        return None
    return cam.fy * object_h_m / h_px

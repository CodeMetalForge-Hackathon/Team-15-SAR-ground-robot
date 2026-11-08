"""Per-detection distance estimate with explicit validity and uncertainty.

Methods (each may independently be unavailable):
  GROUND_PLANE   bottom-centre of the box is taken as the floor contact and
                 intersected with the floor using the MEASURED mount height and
                 pitch. Refused when the mount is unmeasured, the class may not
                 stand on the floor, the box is cut by the bottom image edge,
                 the contact row is at/above the horizon, or another box hides
                 the bottom of this one.
  KNOWN_HEIGHT   pinhole range from a class height prior (standing adult,
                 chair). Refused when the box is cut at the top or bottom, the
                 posture is not upright, or no prior exists for the class.
  MONO_DEPTH     optional cross-check (camera_mapping/depth.py); used for the
                 fused value only when the config says it was validated.

Fusion: if two methods agree within 2 sigma they are inverse-variance
combined; if they disagree the estimate is REJECTED (status UNKNOWN). The
result is always ESTIMATED or UNKNOWN; never a verified distance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import geometry as G
from .config import PerceptionConfig
from .detector import FLOOR_CLASSES, ObjectDetection

ESTIMATED = "ESTIMATED"
UNKNOWN = "UNKNOWN"
REJECTED = "REJECTED"

EDGE_MARGIN_PX = 4.0
CONTACT_SIGMA_PX = 4.0          # bottom-edge localisation error of a detector box
BOX_H_SIGMA_FRAC = 0.05         # box height error, as a fraction of the height
MIN_BOX_H_PX = 24.0

# height priors: mean, sigma (m). Chosen wide on purpose.
HEIGHT_PRIORS = {
    "person": (1.70, 0.12),     # standing adult; children are outside this prior
    "chair": (0.88, 0.12),
}
UPRIGHT_MIN_ASPECT = {"person": 1.8, "chair": 0.9}


@dataclass
class MethodResult:
    method: str
    status: str
    distance_m: Optional[float] = None
    sigma_m: Optional[float] = None
    lateral_m: Optional[float] = None
    reason: Optional[str] = None
    upper_bound_m: Optional[float] = None

    def to_json(self) -> dict:
        r = lambda v: None if v is None else round(float(v), 3)
        return {"method": self.method, "status": self.status, "distance_m": r(self.distance_m),
                "sigma_m": r(self.sigma_m), "lateral_m": r(self.lateral_m), "reason": self.reason,
                "upper_bound_m": r(self.upper_bound_m)}


@dataclass
class DistanceEstimate:
    status: str
    distance_m: Optional[float]
    sigma_m: Optional[float]
    lateral_m: Optional[float]
    method: Optional[str]
    calibration_status: str
    methods: List[MethodResult] = field(default_factory=list)
    reason: Optional[str] = None
    upper_bound_m: Optional[float] = None
    bearing_deg: float = 0.0

    def to_json(self) -> dict:
        r = lambda v: None if v is None else round(float(v), 3)
        return {"status": self.status, "distance_m": r(self.distance_m), "sigma_m": r(self.sigma_m),
                "lateral_m": r(self.lateral_m), "method": self.method,
                "calibration_status": self.calibration_status,
                "label": label_for(self), "reason": self.reason,
                "upper_bound_m": r(self.upper_bound_m), "bearing_deg": round(self.bearing_deg, 2),
                "unit": "m", "kind": "CAMERA_ESTIMATE",
                "methods": [m.to_json() for m in self.methods]}


def label_for(e: DistanceEstimate) -> str:
    if e.status != ESTIMATED:
        return "UNKNOWN"
    return f"{e.calibration_status}_ESTIMATE"   # UNCALIBRATED_ESTIMATE | CALIBRATED_ESTIMATE


def _iou_lower_occlusion(box: Sequence[float], others: Sequence[Sequence[float]]) -> bool:
    """True if another box covers the bottom strip of ``box`` and reaches lower
    in the image (so it is likely nearer and hides this box's contact point)."""
    x, y, w, h = box
    strip_top, bottom = y + 0.8 * h, y + h
    for o in others:
        ox, oy, ow, oh = o
        if o is box:
            continue
        ix = max(0.0, min(x + w, ox + ow) - max(x, ox))
        iy = max(0.0, min(bottom, oy + oh) - max(strip_top, oy))
        if ix >= 0.3 * w and iy > 0 and oy + oh > bottom + 2:
            return True
    return False


def _ground_sigma(cfg: PerceptionConfig, u: float, v: float, x0: float) -> float:
    cam, m = cfg.camera, cfg.mount
    terms = []
    for dh, dp, dv in ((m.height_sigma_m, 0, 0), (0, m.pitch_sigma_deg, 0), (0, 0, CONTACT_SIGMA_PX)):
        p = G.ground_point(cam, u, v + dv, m.height_m + dh, m.pitch_deg + dp)
        if p is None:            # perturbation crosses the horizon: unbounded
            return float("inf")
        terms.append(p[0] - x0)
    return math.sqrt(sum(t * t for t in terms))


def ground_plane(det: ObjectDetection, cfg: PerceptionConfig,
                 others: Sequence[Sequence[float]] = ()) -> MethodResult:
    cam, m = cfg.camera, cfg.mount
    name = "GROUND_PLANE"
    if not m.usable:
        return MethodResult(name, UNKNOWN, reason="MOUNT_UNMEASURED")
    if det.label not in FLOOR_CLASSES:
        return MethodResult(name, UNKNOWN, reason="CLASS_MAY_NOT_TOUCH_FLOOR")
    x, y, w, h = det.bbox
    u, v = x + w / 2.0, y + h
    if v >= cam.height - EDGE_MARGIN_PX:
        p = G.ground_point(cam, u, cam.height - 1, m.height_m, m.pitch_deg)
        return MethodResult(name, UNKNOWN, reason="CONTACT_BELOW_FRAME",
                            upper_bound_m=p[0] if p else None)
    if _iou_lower_occlusion(det.bbox, others):
        return MethodResult(name, UNKNOWN, reason="CONTACT_OCCLUDED")
    hz = G.horizon_row(cam, m.pitch_deg)
    if v <= hz + 2:
        return MethodResult(name, UNKNOWN, reason="CONTACT_AT_OR_ABOVE_HORIZON")
    p = G.ground_point(cam, u, v, m.height_m, m.pitch_deg)
    if p is None:
        return MethodResult(name, UNKNOWN, reason="CONTACT_AT_OR_ABOVE_HORIZON")
    sigma = _ground_sigma(cfg, u, v, p[0])
    if not math.isfinite(sigma) or sigma > 0.5 * p[0] + 0.2:
        return MethodResult(name, UNKNOWN, reason="GEOMETRY_TOO_UNCERTAIN")
    return MethodResult(name, ESTIMATED, p[0], sigma, p[1])


def known_height(det: ObjectDetection, cfg: PerceptionConfig) -> MethodResult:
    cam = cfg.camera
    name = "KNOWN_HEIGHT"
    prior = HEIGHT_PRIORS.get(det.label)
    if prior is None:
        return MethodResult(name, UNKNOWN, reason="NO_HEIGHT_PRIOR_FOR_CLASS")
    x, y, w, h = det.bbox
    if h < MIN_BOX_H_PX:
        return MethodResult(name, UNKNOWN, reason="BOX_TOO_SMALL")
    if y <= EDGE_MARGIN_PX or y + h >= cam.height - EDGE_MARGIN_PX:
        return MethodResult(name, UNKNOWN, reason="BOX_TRUNCATED_BY_FRAME")
    if h / max(w, 1.0) < UPRIGHT_MIN_ASPECT.get(det.label, 0.0):
        return MethodResult(name, UNKNOWN, reason="NOT_UPRIGHT_OR_PARTLY_HIDDEN")
    H, sH = prior
    z = G.known_height_range(cam, y, y + h, H)
    if z is None:
        return MethodResult(name, UNKNOWN, reason="BOX_TOO_SMALL")
    # forward distance ~ z for small pitch; add pitch-cosine and box errors
    rel = math.sqrt((sH / H) ** 2 + BOX_H_SIGMA_FRAC ** 2 + 0.03 ** 2)
    a, _ = G.normalized(cam, x + w / 2.0, y + h / 2.0)
    return MethodResult(name, ESTIMATED, z, z * rel, -z * a)


def fuse(results: List[MethodResult]) -> tuple:
    ok = [r for r in results if r.status == ESTIMATED]
    if not ok:
        return None, None, None, None, "NO_METHOD_APPLICABLE"
    if len(ok) == 1:
        r = ok[0]
        return r.distance_m, r.sigma_m, r.lateral_m, r.method, None
    for i, a in enumerate(ok):                     # every pair must agree within 2 sigma
        for b in ok[i + 1:]:
            if abs(a.distance_m - b.distance_m) > 2.0 * math.hypot(a.sigma_m, b.sigma_m):
                return None, None, None, None, (f"INCONSISTENT_METHODS ({a.method} {a.distance_m:.2f} m vs "
                                                f"{b.method} {b.distance_m:.2f} m)")
    ws = [1 / r.sigma_m ** 2 for r in ok]
    d = sum(w * r.distance_m for w, r in zip(ws, ok)) / sum(ws)
    lats = [(w, r.lateral_m / r.distance_m) for w, r in zip(ws, ok) if r.lateral_m is not None]
    # lateral offset scales with range along the same bearing
    lat = d * sum(w * q for w, q in lats) / sum(w for w, _ in lats) if lats else 0.0
    return d, math.sqrt(1 / sum(ws)), lat, "FUSED(" + "+".join(r.method for r in ok) + ")", None


def estimate(det: ObjectDetection, cfg: PerceptionConfig, others: Sequence[Sequence[float]] = (),
             depth_result: Optional[MethodResult] = None) -> DistanceEstimate:
    results = [ground_plane(det, cfg, others), known_height(det, cfg)]
    use = list(results)
    if depth_result is not None:
        results.append(depth_result)
        if cfg.depth_model_validated:
            use.append(depth_result)
    d, s, lat, method, reason = fuse(use)
    x, y, w, h = det.bbox
    bearing = math.degrees(G.bearing_rad(cfg.camera, x + w / 2.0))
    ub = next((r.upper_bound_m for r in results if r.upper_bound_m is not None), None)
    if d is None or d <= 0 or d > cfg.max_range_m * 2:
        status = REJECTED if reason and reason.startswith("INCONSISTENT") else UNKNOWN
        return DistanceEstimate(UNKNOWN if status == UNKNOWN else REJECTED, None, None, None, None,
                                cfg.calibration_status, results, reason or "OUT_OF_RANGE", ub, bearing)
    return DistanceEstimate(ESTIMATED, d, s, lat, method, cfg.calibration_status, results, None, ub, bearing)


def estimate_all(dets: List[ObjectDetection], cfg: PerceptionConfig,
                 depth: Optional[Dict[int, MethodResult]] = None) -> List[DistanceEstimate]:
    boxes = [d.bbox for d in dets]
    out = []
    for i, d in enumerate(dets):
        others = [b for j, b in enumerate(boxes) if j != i]
        out.append(estimate(d, cfg, others, (depth or {}).get(i)))
    return out

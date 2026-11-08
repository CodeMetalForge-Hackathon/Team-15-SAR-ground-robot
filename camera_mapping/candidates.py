"""Candidate paths (STRAIGHT / LEFT / RIGHT) checked against the camera's observed local map. Advisory only.

Each candidate is the area the robot body would sweep: straight through the camera's blind band, then along
a straight segment to (lookahead, lateral offset). A candidate is:

  OBSTRUCTED      an OCCUPIED cell, or a known-range obstacle footprint, lies in the swept area;
  UNOBSERVED      any swept cell (outside the unobservable blind band) is UNKNOWN, or an obstacle at UNKNOWN
                  range has a bearing wedge crossing the swept area, or the mount is unmeasured (then nothing is
                  ever FREE);
  OBSERVED_CLEAR  every swept cell is FREE. FREE means "no DETECTED obstacle" for the detector's classes, from
                  a camera estimate. It is never a range-sensor measurement and never a motion permission.

An absence of detections is never treated as clearance: cells nobody observed stay UNKNOWN, and UNKNOWN
makes the candidate UNOBSERVED.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np

from camera_mapping.assess import corridor_half
from camera_mapping.config import PerceptionConfig
from camera_mapping.local_map import FREE, OCCUPIED, LocalMap

OBSERVED_CLEAR, OBSTRUCTED, UNOBSERVED = "OBSERVED_CLEAR", "OBSTRUCTED", "UNOBSERVED"


def _swept(lm: LocalMap, x0: float, x_end: float, y_end: float, half: float) -> np.ndarray:
    """Cells the body sweeps: straight ahead from the lens to x0 (the camera's blind band), then along the
    segment (x0, 0) -> (x_end, y_end). Swerving only after the blind band keeps the path inside the field of
    view wherever the camera can see the floor at all."""
    stub = (lm.X >= 0) & (lm.X < x0) & (np.abs(lm.Y) <= half)
    dx, dy = x_end - x0, y_end
    t = np.clip(((lm.X - x0) * dx + lm.Y * dy) / (dx * dx + dy * dy), 0.0, 1.0)
    d = np.hypot(lm.X - (x0 + t * dx), lm.Y - t * dy)
    return stub | ((d <= half) & (lm.X >= x0) & (lm.X <= x_end))


def evaluate_candidates(lm: LocalMap, cfg: PerceptionConfig, lateral_offset_m: float | None = None) -> List[dict]:
    half = corridor_half(cfg)
    look = cfg.lookahead_m + max(0.0, cfg.mount.setback_m or 0.0)
    off = lateral_offset_m if lateral_offset_m is not None else round(2 * half + 0.05, 3)
    blind = lm.blind_zone_m()
    out = []
    for name, y_end in (("STRAIGHT", 0.0), ("LEFT", off), ("RIGHT", -off)):
        area = _swept(lm, min(blind or 0.0, look / 2), look, y_end, half)
        observable = area & (lm.X >= (blind if blind is not None else 0.0))
        cells = lm.state[observable]
        n, n_free, n_occ = int(cells.size), int((cells == FREE).sum()), int((lm.state[area] == OCCUPIED).sum())
        reasons, status = [], OBSERVED_CLEAR
        for fp in lm.footprints:
            if fp.range_known:
                fp_mask = ((lm.X >= fp.x_near - lm.res / 2) & (lm.X <= fp.x_far + lm.res / 2)
                           & (np.abs(lm.Y - fp.y) <= fp.half_w + lm.res / 2))
                if (fp_mask & area).any():
                    status = OBSTRUCTED
                    reasons.append(f"{fp.label} #{fp.track_id} at ~{fp.x:.2f} m in the swept path")
            else:
                wedge = (lm.B >= fp.bearing_lo) & (lm.B <= fp.bearing_hi)
                if (wedge & area).any() and status != OBSTRUCTED:
                    status = UNOBSERVED
                    reasons.append(f"{fp.label} #{fp.track_id} at UNKNOWN range crosses the path bearing")
        if n_occ and status != OBSTRUCTED:
            status = OBSTRUCTED
            reasons.append(f"{n_occ} occupied cells in the swept path")
        if status == OBSERVED_CLEAR:
            if not cfg.mount.usable:
                status = UNOBSERVED
                reasons.append("mount height/pitch unmeasured: no cell can be observed free")
            elif blind is None or n == 0 or n_free < n:
                status = UNOBSERVED
                reasons.append(f"only {n_free}/{n} swept cells observed free (rest UNKNOWN: unobserved or "
                               "outside the field of view)")
            else:
                reasons.append(f"all {n} observable swept cells FREE (no detected obstacle); camera estimate only")
        out.append({"name": name, "end_m": [round(look, 2), round(y_end, 2)],
                    "heading_deg": round(math.degrees(math.atan2(y_end, look)), 1),
                    "half_width_m": round(half, 3), "status": status, "reasons": reasons,
                    "observed_free_fraction": round(n_free / n, 3) if n else 0.0,
                    "advisory": True, "validated_for_driving": False})
    return out

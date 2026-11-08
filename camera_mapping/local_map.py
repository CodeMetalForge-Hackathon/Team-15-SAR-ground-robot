"""Robot-relative local grid built from camera tracks (no SLAM, no global frame).

Cell states:
  UNKNOWN   never observed, outside the camera FOV, in the near blind zone,
            beyond the free-space range, behind an obstacle (occlusion
            shadow), inside the wedge of a detection whose range is UNKNOWN,
            or last observed more than ``free_ttl_s`` ago.
  FREE      observed in the current window and no DETECTED obstacle there.
            "Free" only means free of the detector's classes: the camera
            cannot see untrained obstacles, glass, holes or low clutter.
  OCCUPIED  footprint of a confirmed track with an ESTIMATED distance,
            inflated by its 2-sigma uncertainty.

FREE is only ever marked when the mount geometry is measured (otherwise the
blind zone and the floor/range relation are unknown). If the robot moves and
no pose is available, the map is cleared rather than shifted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from . import geometry as G
from .config import PerceptionConfig
from .distance import ESTIMATED
from .tracking import Track

UNKNOWN, FREE, OCCUPIED = 0, 1, 2
STATE_NAMES = {UNKNOWN: "UNKNOWN", FREE: "FREE", OCCUPIED: "OCCUPIED"}

OBSTACLE_DEPTH_M = 0.30     # assumed extent behind the visible face (unknown beyond)
MIN_HALF_WIDTH_M = 0.10


@dataclass
class Footprint:
    track_id: int
    label: str
    x: float
    y: float
    half_w: float
    x_near: float
    x_far: float
    sigma: float
    bearing_lo: float
    bearing_hi: float
    range_known: bool


class LocalMap:
    def __init__(self, cfg: PerceptionConfig, res_m: float = 0.1, y_half_m: float = 2.0,
                 free_ttl_s: float = 1.5, free_max_m: float = 3.0) -> None:
        self.cfg, self.res = cfg, res_m
        self.x_max = cfg.max_range_m
        self.y_half = y_half_m
        self.nx = int(round(self.x_max / res_m))
        self.ny = int(round(2 * y_half_m / res_m))
        self.free_ttl_s, self.free_max_m = free_ttl_s, free_max_m
        self.state = np.zeros((self.nx, self.ny), dtype=np.int8)
        self.last_obs = np.full((self.nx, self.ny), -np.inf)
        self.sigma = np.zeros((self.nx, self.ny), dtype=np.float32)
        xs = (np.arange(self.nx) + 0.5) * res_m
        ys = y_half_m - (np.arange(self.ny) + 0.5) * res_m          # column 0 = far left
        self.X, self.Y = np.meshgrid(xs, ys, indexing="ij")
        self.R = np.hypot(self.X, self.Y)
        self.B = np.arctan2(self.Y, self.X)                           # bearing, + left
        self.footprints: List[Footprint] = []
        self.updated_t: Optional[float] = None
        self.resets = 0

    # -- geometry helpers ---------------------------------------------------
    def cell(self, x: float, y: float):
        i = int(math.floor(x / self.res))
        j = int(math.floor((self.y_half - y) / self.res))
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return i, j
        return None

    def blind_zone_m(self) -> Optional[float]:
        m = self.cfg.mount
        if not m.usable:
            return None
        return G.nearest_visible_floor(self.cfg.camera, m.height_m, m.pitch_deg)

    def reset(self) -> None:
        """Clear everything (robot moved without a pose). The pipeline also clears track histories."""
        self.state[:] = UNKNOWN
        self.last_obs[:] = -np.inf
        self.footprints = []
        self.resets += 1

    # -- update ---------------------------------------------------------------
    def footprint(self, tr: Track) -> Footprint:
        cam = self.cfg.camera
        x, y, w, h = tr.bbox
        b1 = G.bearing_rad(cam, x)
        b2 = G.bearing_rad(cam, x + w)
        lo, hi = min(b1, b2), max(b1, b2)
        f = tr.filtered()
        # Range counts as known only while the CURRENT estimate is valid: an object that is now cut
        # by the frame bottom (or otherwise UNKNOWN) must not keep its old, farther median.
        current_ok = tr.estimate is not None and tr.estimate.status == ESTIMATED
        if f is None or not current_ok:
            return Footprint(tr.track_id, tr.label, math.nan, math.nan, 0, 0, 0, math.inf, lo, hi, False)
        d, s, lat = f
        half_w = max(MIN_HALF_WIDTH_M, d * (w / cam.fx) / 2.0)
        return Footprint(tr.track_id, tr.label, d, lat, half_w, max(0.0, d - 2 * s),
                         d + OBSTACLE_DEPTH_M + 2 * s, s, lo, hi, True)

    def update(self, t: float, tracks: List[Track]) -> None:
        self.updated_t = t
        fov = math.radians(self.cfg.camera.hfov_deg) / 2.0
        blind = self.blind_zone_m()
        observed = np.abs(self.B) <= fov
        if blind is None:
            observed &= False                       # mount unmeasured: never mark FREE
        else:
            observed &= (self.X >= blind) & (self.R <= self.free_max_m)
        self.footprints = []
        masked = np.zeros_like(observed)            # cells that must not be FREE this frame
        occ = np.zeros_like(observed)
        sig = np.zeros(self.state.shape, dtype=np.float32)
        for tr in tracks:
            fp = self.footprint(tr)
            wedge = (self.B >= fp.bearing_lo) & (self.B <= fp.bearing_hi)
            if tr.state == "TENTATIVE":
                masked |= wedge                     # unconfirmed: never call its wedge FREE
                continue
            self.footprints.append(fp)
            if not fp.range_known:
                masked |= wedge                     # something there, range unknown
                continue
            m = ((self.X >= fp.x_near) & (self.X <= fp.x_far) &
                 (np.abs(self.Y - fp.y) <= fp.half_w + 2 * fp.sigma * max(0.2, abs(fp.y) / max(fp.x, 0.1))))
            occ |= m
            sig = np.where(m, np.maximum(sig, fp.sigma), sig)
            masked |= wedge & (self.X >= fp.x_near)        # shadow behind the face
        observed &= ~masked
        self.last_obs[observed] = t
        self.last_obs[masked] = -np.inf             # earlier FREE does not survive behind/inside a detection
        self.state[:] = UNKNOWN
        self.state[(t - self.last_obs) <= self.free_ttl_s] = FREE
        self.state[occ] = OCCUPIED
        self.sigma = sig

    # -- export ---------------------------------------------------------------
    def counts(self) -> dict:
        return {STATE_NAMES[k]: int((self.state == k).sum()) for k in STATE_NAMES}

    def to_json(self) -> dict:
        rows = ["".join("UFO"[v] for v in self.state[i]) for i in range(self.nx)]
        return {
            "frame": "ROBOT_RELATIVE",
            "origin": "floor below the camera lens; x forward, y left",
            "res_m": self.res, "x_max_m": self.x_max, "y_half_m": self.y_half,
            "nx": self.nx, "ny": self.ny,
            "encoding": "rows[i] = x index i (near->far); char j = y from +y_half (left) to -y_half; U/F/O",
            "rows": rows, "counts": self.counts(),
            "hfov_deg": round(self.cfg.camera.hfov_deg, 2),
            "blind_zone_m": None if self.blind_zone_m() is None else round(self.blind_zone_m(), 3),
            "free_space_enabled": self.cfg.mount.usable,
            "free_meaning": "no DETECTED obstacle (detector classes only); not a range-sensor measurement",
            "updated_t": self.updated_t, "resets": self.resets,
            "footprints": [{"track_id": f.track_id, "label": f.label,
                            "x_m": None if not f.range_known else round(f.x, 3),
                            "y_m": None if not f.range_known else round(f.y, 3),
                            "half_w_m": round(f.half_w, 3), "sigma_m": None if not f.range_known else round(f.sigma, 3),
                            "bearing_deg": [round(math.degrees(f.bearing_lo), 1), round(math.degrees(f.bearing_hi), 1)],
                            "range_known": f.range_known} for f in self.footprints],
        }

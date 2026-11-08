"""Deterministic RoverC-Pro simulator on the SYNTHETIC trail graph.

Everything here is synthetic and labelled that way:
  - Distances along edges are the graph weights in metres. They are not measured RoverC travel.
  - SIM_NODE_XY is a made-up layout. It is used ONLY to give each edge a bearing at each node, so that
    in-place rotation and directional scanning have something to aim at. It is not a map.
  - The ultrasonic model is edge-local:
      * Along an edge, obstacles sit at their graph distance.
      * Sideways views mid-edge use per-edge side clearances.
      * Directions with nothing in them return NO_ECHO.
  - Heading comes from simulator ground truth. ``heading_feedback=False`` models the real RoverC,
    which has no calibrated heading source yet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from planner.graph import TrailGraph
from rover.motion import BodyVelocity, ZERO
from rover.sensors import (NO_ECHO, OK, CameraDetection, HeadingReading, PowerReading, RangeReading,
                           ang_diff, norm_deg)

SIM_NODE_XY: dict[str, tuple[float, float]] = {
    "A": (0, 0), "B": (10, 0), "C": (20, 0), "D": (30, 0), "E": (40, 0), "F": (50, 0), "G": (60, 0),
    "H": (0, 10), "I": (10, 10), "J": (20, 10), "K": (30, 10), "L": (40, 10), "M": (50, 10),
    "N": (0, 40), "O": (10, 40), "P": (20, 40), "Q": (30, 40), "R": (40, 40), "S": (50, 40),
    "T": (0, 60), "U": (10, 60), "V": (20, 60), "W": (30, 60), "X": (40, 60), "Y": (50, 60), "Z": (60, 60),
}


def bearing_deg(xy: dict[str, tuple[float, float]], a: str, b: str) -> float:
    (x0, y0), (x1, y1) = xy[a], xy[b]
    return norm_deg(math.degrees(math.atan2(y1 - y0, x1 - x0)))


@dataclass
class SimObstacle:
    obs_id: str
    a: str
    b: str
    at_m: float                 # distance from node a along edge a-b (synthetic metres)
    half_width_m: float = 0.15
    kind: str = "static"        # "static" | "person"
    present: bool = True


class SimDriver:
    name = "sim"
    physical = False

    def __init__(self):
        self.velocity = ZERO
        self.applied: list[BodyVelocity] = []
        self.fail = False

    def apply(self, v: BodyVelocity) -> None:
        if self.fail:
            raise IOError("simulated driver fault")
        self.velocity = v
        self.applied.append(v)

    def stop(self) -> None:
        self.velocity = ZERO


@dataclass
class SimConfig:
    dt: float = 0.05
    lin_mps_per_unit: float = 2.0     # synthetic: 1.0 normalised forward = 2 m/s (0.6 m/s at the 0.3 limit)
    yaw_dps_per_unit: float = 90.0    # synthetic: 1.0 normalised yaw = 90 deg/s
    sensor_max_m: float = 3.5         # Grove ultrasonic datasheet range is ~3.5 m
    beam_half_deg: float = 7.5
    sim_blocked_m: float = 0.35       # simulated ranging-service BLOCKED threshold (PR #7 default blocked_m)
    align_tol_deg: float = 5.0        # driving more than this off an edge bearing leaves the graph
    node_tol_m: float = 0.05
    robot_radius_m: float = 0.10      # SYNTHETIC placeholder; measure the real chassis
    camera_half_fov_deg: float = 33.0
    camera_range_m: float = 8.0


class SimWorld:
    def __init__(self, graph: TrailGraph, start: str, start_heading_deg: Optional[float] = None,
                 obstacles: Optional[list[SimObstacle]] = None, config: SimConfig = SimConfig(),
                 xy: Optional[dict[str, tuple[float, float]]] = None,
                 side_clearance: Optional[dict[tuple[str, str], tuple[Optional[float], Optional[float]]]] = None):
        self.g = graph
        self.cfg = config
        self.xy = xy or SIM_NODE_XY
        self.obstacles = list(obstacles or [])
        self.side_clearance = dict(side_clearance or {})  # (a, b) -> (left, right) when travelling a->b
        self.t = 0.0
        nbrs = sorted(graph.neighbors(start))
        self.edge: tuple[str, str] = (start, nbrs[0]) if nbrs else (start, start)
        self.s = 0.0
        self.heading = norm_deg(start_heading_deg if start_heading_deg is not None
                                else (self.bearing(start, nbrs[0]) if nbrs else 0.0))
        self.lost = False
        self.lost_reason = ""
        self.collision: Optional[str] = None
        self.odometer_m = 0.0
        self.seq = 0
        # fault injection
        self.heading_feedback = True
        self.localization_ok = True
        self.range_dropout = False
        self.power_v: Optional[float] = 4.0

    # --- geometry ---------------------------------------------------------------------
    def bearing(self, a: str, b: str) -> Optional[float]:
        if a not in self.xy or b not in self.xy or a == b:
            return None
        return bearing_deg(self.xy, a, b)

    def length(self, a: str, b: str) -> float:
        return self.g.neighbors(a)[b]

    def node(self) -> Optional[str]:
        a, b = self.edge
        if a == b:
            return a
        if self.s <= self.cfg.node_tol_m:
            return a
        if self.s >= self.length(a, b) - self.cfg.node_tol_m:
            return b
        return None

    def _obstacle_pos(self, o: SimObstacle, a: str, b: str) -> Optional[float]:
        """Position of o measured from a along edge a-b, or None if it is on another edge."""
        if (o.a, o.b) == (a, b):
            return o.at_m
        if (o.a, o.b) == (b, a):
            return self.length(a, b) - o.at_m
        return None

    def _hit(self, dist: float, phi_deg: float, half_width: float) -> bool:
        if dist <= 0 or abs(phi_deg) >= 89:
            return False
        lateral = dist * math.tan(math.radians(abs(phi_deg)))
        spread = dist * math.tan(math.radians(self.cfg.beam_half_deg))
        return lateral - spread <= half_width

    def _range_at(self, h: float) -> Optional[float]:
        hits: list[float] = []
        n = self.node()
        if n is not None:
            for w in self.g.neighbors(n):
                b = self.bearing(n, w)
                if b is None:
                    continue
                phi = ang_diff(h, b)
                for o in self.obstacles:
                    p = self._obstacle_pos(o, n, w) if o.present else None
                    if p is not None and self._hit(p, phi, o.half_width_m):
                        hits.append(p)
        else:
            a, b = self.edge
            bf = self.bearing(a, b)
            phi_f = ang_diff(h, bf)
            phi_b = ang_diff(h, bf + 180.0)
            for o in self.obstacles:
                p = self._obstacle_pos(o, a, b) if o.present else None
                if p is None:
                    continue
                if p > self.s and self._hit(p - self.s, phi_f, o.half_width_m):
                    hits.append(p - self.s)
                if p < self.s and self._hit(self.s - p, phi_b, o.half_width_m):
                    hits.append(self.s - p)
            if 30.0 < abs(phi_f) < 150.0:
                left, right = self._sides(a, b)
                side = left if phi_f > 0 else right
                if side is not None:
                    hits.append(side)
        return min(hits) if hits else None

    def _sides(self, a: str, b: str) -> tuple[Optional[float], Optional[float]]:
        if (a, b) in self.side_clearance:
            return self.side_clearance[(a, b)]
        if (b, a) in self.side_clearance:
            l, r = self.side_clearance[(b, a)]
            return r, l
        return None, None

    # --- sensors ------------------------------------------------------------------------
    def read_range(self) -> Optional[RangeReading]:
        if self.range_dropout:
            return None
        self.seq += 1
        r = self._range_at(self.heading)
        # Issue #9: the simulated ranging service asserts its verdict explicitly (never None), like PR #7's
        # forward_motion_allowed. SIMULATED only: a sim no-echo means open space beyond sensor range.
        if r is None or r > self.cfg.sensor_max_m:
            return RangeReading(self.t, NO_ECHO, None, self.cfg.sensor_max_m, "sim-ultrasonic", self.seq,
                                forward_allowed=True, reason="SIMULATED: no echo within sensor range")
        return RangeReading(self.t, OK, round(r, 4), self.cfg.sensor_max_m, "sim-ultrasonic", self.seq,
                            forward_allowed=r >= self.cfg.sim_blocked_m)

    def read_heading(self) -> Optional[HeadingReading]:
        if not self.heading_feedback:
            return None
        return HeadingReading(self.t, self.heading, "sim-truth")

    def read_power(self) -> Optional[PowerReading]:
        return PowerReading(self.t, self.power_v, "sim")

    def read_camera(self) -> list[CameraDetection]:
        out = []
        if self.lost:
            return out
        n = self.node()
        views: list[tuple[str, str, float]] = []
        if n is not None:
            views = [(n, w, 0.0) for w in self.g.neighbors(n)]
        else:
            a, b = self.edge
            views = [(a, b, self.s)]
            views.append((b, a, self.length(a, b) - self.s))
        for a, b, s in views:
            bb = self.bearing(a, b)
            if bb is None:
                continue
            phi = ang_diff(bb, self.heading)
            if abs(phi) > self.cfg.camera_half_fov_deg:
                continue
            for o in self.obstacles:
                p = self._obstacle_pos(o, a, b) if o.present and o.kind == "person" else None
                if p is not None and 0 < p - s <= self.cfg.camera_range_m:
                    out.append(CameraDetection(self.t, "person", 0.9, phi, "sim-camera"))
        return out

    def pose(self) -> Optional[dict]:
        if self.lost or not self.localization_ok:
            return None
        return {"edge": self.edge, "s": self.s, "node": self.node(), "heading_deg": self.heading}

    # --- dynamics -----------------------------------------------------------------------
    def step(self, v: BodyVelocity) -> None:
        dt = self.cfg.dt
        self.heading = norm_deg(self.heading + v.wz * self.cfg.yaw_dps_per_unit * dt)
        if v.vy != 0:
            self._lose("strafing is not modelled on the graph")
        d = v.vx * self.cfg.lin_mps_per_unit * dt
        if d != 0:
            self._translate(self.heading if d > 0 else self.heading + 180.0, abs(d))
        self.t = round(self.t + dt, 9)

    def _lose(self, why: str) -> None:
        if not self.lost:
            self.lost = True
            self.lost_reason = why

    def _aligned(self, h: float, a: str, b: str) -> bool:
        bb = self.bearing(a, b)
        return bb is not None and abs(ang_diff(h, bb)) <= self.cfg.align_tol_deg

    def _translate(self, h: float, dist: float) -> None:
        self.odometer_m += dist
        if self.lost:
            return
        a, b = self.edge
        if a != b and self._aligned(h, a, b):
            self.s += dist
        elif a != b and self._aligned(h, b, a):
            self.s -= dist
        else:
            n = self.node()
            w = next((w for w in sorted(self.g.neighbors(n)) if self._aligned(h, n, w)), None) if n else None
            if w is None:
                self._lose(f"drove off-graph at heading {h:.1f}")
                return
            self.edge, self.s = (n, w), dist
            a, b = self.edge
        L = self.length(a, b)
        if self.s > L + self.cfg.node_tol_m or self.s < -self.cfg.node_tol_m:
            end = b if self.s > L else a
            over = self.s - L if self.s > L else -self.s
            w = next((w for w in sorted(self.g.neighbors(end)) if self._aligned(h, end, w)), None)
            if w is None:
                self._lose(f"drove past node {end} off-graph")
                return
            self.edge, self.s = (end, w), over
            a, b = self.edge
        for o in self.obstacles:
            p = self._obstacle_pos(o, a, b) if o.present else None
            if p is not None and abs(p - self.s) <= o.half_width_m + self.cfg.robot_radius_m:
                self.collision = o.obs_id

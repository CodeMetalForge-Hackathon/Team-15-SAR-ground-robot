"""Deterministic forward-corridor assessment and advisory route suggestion.

Status (advisory only; the rover's safety supervisor and Grove gate decide motion):
  BLOCKED  a confirmed obstacle with an ESTIMATED range overlaps the corridor
           within the lookahead, or its 2-sigma near edge is inside the stop
           distance, or a detection cut by the bottom frame edge (so nearer
           than the bottom-row floor distance) lies in the corridor.
  CAUTION  an obstacle overlaps the corridor only within its uncertainty
           band, or sits just beyond the lookahead.
  UNKNOWN  any corridor cell between the blind zone and the lookahead is not
           FREE, or a detection with UNKNOWN range lies in the corridor's
           bearing, or the mount geometry is unmeasured.
  CLEAR    every corridor cell from the end of the blind zone to the
           lookahead is FREE and nothing detected overlaps it. CLEAR means
           "no detected obstacle"; it is not a safety clearance.

Route suggestion: A* on the grid. Mode SUPPORTED uses FREE cells only (plus the
blind zone straight ahead). If that fails, mode NEEDS_OBSERVATION allows
UNKNOWN cells at a high cost and the route is labelled as unverified. Every
route is ``advisory: true`` and ``validated_for_driving: false``.
"""
from __future__ import annotations

import heapq
import math
from typing import List, Optional

import numpy as np

from .config import PerceptionConfig
from .local_map import FREE, OCCUPIED, UNKNOWN, LocalMap

CLEAR, CAUTION, BLOCKED = "CLEAR", "CAUTION", "BLOCKED"
STATUS_UNKNOWN = "UNKNOWN"


def corridor_half(cfg: PerceptionConfig) -> float:
    return cfg.robot_width_m / 2.0 + cfg.width_margin_m


def near_bearing_rad(lm: LocalMap, cfg: PerceptionConfig) -> float:
    """Half-angle of the corridor at its nearest observed range (used for unknown-range hits)."""
    return math.atan2(corridor_half(cfg), max(lm.blind_zone_m() or 0.3, 0.3))


def assess(lm: LocalMap, tracks, cfg: PerceptionConfig) -> dict:
    half = corridor_half(cfg)
    # lookahead / stop distance are from the robot's FRONT; map x is from the lens (behind it by setback)
    sb = max(0.0, cfg.mount.setback_m or 0.0)
    look, stop = cfg.lookahead_m + sb, cfg.stop_distance_m + sb
    reasons, blocking = [], []
    status = None

    def escalate(s):
        nonlocal status
        order = {None: 0, CLEAR: 0, STATUS_UNKNOWN: 1, CAUTION: 2, BLOCKED: 3}
        if order[s] > order[status]:
            status = s

    for fp in lm.footprints:
        tr = next((t for t in tracks if t.track_id == fp.track_id), None)
        est = tr.estimate if tr else None
        if not fp.range_known:
            near_b = near_bearing_rad(lm, cfg)
            if fp.bearing_lo <= near_b and fp.bearing_hi >= -near_b:
                ub = est.upper_bound_m if est else None
                if ub is not None and ub <= look:
                    escalate(BLOCKED)
                    reasons.append(f"{fp.label} #{fp.track_id} in corridor, cut by the frame bottom: nearer than {ub:.2f} m")
                else:
                    escalate(STATUS_UNKNOWN)
                    reasons.append(f"{fp.label} #{fp.track_id} in corridor bearing, range UNKNOWN")
                blocking.append(fp.track_id)
            continue
        lat_lo, lat_hi = fp.y - fp.half_w, fp.y + fp.half_w
        band = 2 * fp.sigma * max(0.2, abs(fp.y) / max(fp.x, 0.1))
        core = lat_hi >= -half and lat_lo <= half
        margin = (lat_hi + band) >= -half and (lat_lo - band) <= half
        if not margin:
            continue
        if core and (fp.x <= look or fp.x_near <= stop):
            escalate(BLOCKED)
            blocking.append(fp.track_id)
            reasons.append(f"{fp.label} #{fp.track_id} at ~{fp.x:.2f} m (±{2 * fp.sigma:.2f}) overlaps the corridor")
        elif fp.x_near <= look:
            escalate(CAUTION)
            blocking.append(fp.track_id)
            reasons.append(f"{fp.label} #{fp.track_id} at ~{fp.x:.2f} m near the corridor edge (within uncertainty)")

    blind = lm.blind_zone_m()
    in_corr = (np.abs(lm.Y) <= half) & (lm.X <= look)
    if blind is not None:
        in_corr &= lm.X >= blind
    cells = lm.state[in_corr]
    n = int(cells.size)
    n_free = int((cells == FREE).sum())
    coverage = round(n_free / n, 3) if n else 0.0
    if not cfg.mount.usable:
        escalate(STATUS_UNKNOWN)
        reasons.append("mount height/pitch unmeasured: free space cannot be established")
    elif n == 0 or n_free < n:
        escalate(STATUS_UNKNOWN)
        reasons.append(f"corridor observed free: {coverage:.0%} of cells (rest UNKNOWN or occupied)")
    if status is None:
        status = CLEAR
        reasons.append("no detected obstacle in the observed corridor")
    return {
        "status": status, "reasons": reasons, "blocking_track_ids": sorted(set(blocking)),
        "corridor": {"half_width_m": round(half, 3), "lookahead_m": round(look, 3), "stop_distance_m": round(stop, 3),
                     "measured_from": "lens (lookahead/stop from robot front + setback %.3f m)" % sb,
                     "robot_width_m": cfg.robot_width_m, "robot_width_measured": cfg.robot_width_measured,
                     "blind_zone_m": None if blind is None else round(blind, 3), "coverage_free": coverage},
        "scope": "detector classes only; camera estimate; advisory - never a motion permission",
        "advisory": True,
    }


def _inflate(occ: np.ndarray, cells: int) -> np.ndarray:
    out = occ.copy()
    for di in range(-cells, cells + 1):
        for dj in range(-cells, cells + 1):
            if di * di + dj * dj > cells * cells:
                continue
            out |= np.roll(np.roll(occ, di, 0), dj, 1) & _shift_mask(occ.shape, di, dj)
    return out


def _shift_mask(shape, di, dj):
    m = np.ones(shape, dtype=bool)
    if di > 0:
        m[:di, :] = False
    elif di < 0:
        m[di:, :] = False
    if dj > 0:
        m[:, :dj] = False
    elif dj < 0:
        m[:, dj:] = False
    return m


def _astar(cost: np.ndarray, start, goals: set):
    nx, ny = cost.shape
    openq = [(0.0, 0.0, start)]
    came, g = {start: None}, {start: 0.0}
    gi = max(i for i, _ in goals)
    while openq:
        _, gc, cur = heapq.heappop(openq)
        if cur in goals:
            path = []
            while cur is not None:
                path.append(cur)
                cur = came[cur]
            return path[::-1], gc
        if gc > g.get(cur, math.inf):
            continue
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if not di and not dj:
                    continue
                ni, nj = cur[0] + di, cur[1] + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or not math.isfinite(cost[ni, nj]):
                    continue
                ng = gc + cost[ni, nj] * math.hypot(di, dj)
                if ng < g.get((ni, nj), math.inf):
                    g[(ni, nj)] = ng
                    came[(ni, nj)] = cur
                    heapq.heappush(openq, (ng + abs(gi - ni), ng, (ni, nj)))
    return None, math.inf


def suggest_route(lm: LocalMap, cfg: PerceptionConfig, assessment: dict,
                  goal_x_m: Optional[float] = None) -> dict:
    base = {"advisory": True, "validated_for_driving": False, "frame": "ROBOT_RELATIVE",
            "note": "suggestion for operator review / simulation only"}
    if assessment["status"] == CLEAR:
        return dict(base, mode="DIRECT", status="DIRECT_ROUTE_OBSERVED_FREE",
                    waypoints=[[0.0, 0.0], [cfg.lookahead_m, 0.0]], through_unknown_cells=0,
                    side=None, caveats=_caveats(lm))
    if not cfg.mount.usable:
        return dict(base, mode="NONE", status="NO_SUPPORTED_ROUTE", waypoints=[], through_unknown_cells=None,
                    side=None, caveats=_caveats(lm) + ["mount unmeasured: no free space, so no route is suggested"])
    half = corridor_half(cfg)
    inflate = int(math.ceil(half / lm.res))
    hazard = lm.state == OCCUPIED
    for fp in lm.footprints:
        if not fp.range_known:   # something there at unknown range: never route through its wedge
            hazard |= (lm.B >= fp.bearing_lo) & (lm.B <= fp.bearing_hi)
    occ = _inflate(hazard, inflate)
    blind = lm.blind_zone_m() or 0.0
    goal_x = min(goal_x_m or cfg.lookahead_m + 0.5, lm.x_max - lm.res)
    gi = int(goal_x / lm.res)
    start = lm.cell(lm.res / 2, 0.0)
    blind_corr = (lm.X < blind) & (np.abs(lm.Y) <= half)
    # SUPPORTED: the whole robot footprint (half-width) must lie on FREE cells
    # the blind band is never observable; it must not inflate over the start region
    # footprint check: centre cell +/- floor(half/res) cells spans exactly 2*half laterally
    not_free = _inflate((lm.state != FREE) & ~(lm.X < blind), int(math.floor(half / lm.res + 1e-9)))
    for mode, unknown_cost in (("SUPPORTED", math.inf), ("NEEDS_OBSERVATION", 25.0)):
        cost = np.full(lm.state.shape, math.inf)
        cost[lm.state == FREE] = 1.0
        cost[(lm.state == UNKNOWN)] = unknown_cost
        cost[blind_corr] = 1.0
        if mode == "SUPPORTED":
            cost[not_free] = math.inf
        cost[occ] = math.inf
        goals = {(gi, j) for j in range(lm.ny) if math.isfinite(cost[gi, j])}
        if not goals or not math.isfinite(cost[start]):
            continue
        path, _ = _astar(cost, start, goals)
        if path is None:
            continue
        unk = sum(1 for (i, j) in path if lm.state[i, j] == UNKNOWN and not blind_corr[i, j])
        wps = _simplify([[round(float(lm.X[i, j]), 2), round(float(lm.Y[i, j]), 2)] for i, j in path])
        side_y = float(np.mean([p[1] for p in wps]))
        side = "LEFT" if side_y > 0.05 else "RIGHT" if side_y < -0.05 else "STRAIGHT"
        status = "ALTERNATE_ROUTE_OBSERVED_FREE" if mode == "SUPPORTED" else "ROUTE_THROUGH_UNOBSERVED_SPACE"
        return dict(base, mode=mode, status=status, waypoints=wps, through_unknown_cells=unk,
                    side=side, caveats=_caveats(lm) + (
                        [] if mode == "SUPPORTED" else
                        ["crosses UNKNOWN cells (unobserved or behind obstacles): observe before considering it"]))
    return dict(base, mode="NONE", status="NO_SUPPORTED_ROUTE", waypoints=[], through_unknown_cells=None,
                side=None, caveats=_caveats(lm) + ["not enough observed map to suggest a route"])


def _caveats(lm: LocalMap) -> List[str]:
    c = ["camera estimate only; detector classes only", "not validated for autonomous driving"]
    b = lm.blind_zone_m()
    c.append("blind zone unknown (mount unmeasured)" if b is None else f"first {b:.2f} m not visible to the camera")
    return c


def _simplify(pts: List[list]) -> List[list]:
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) != 0:
            out.append(b)
    out.append(pts[-1])
    return out

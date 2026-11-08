"""Footprint-aware forward-corridor clearance and the orientation monitor.

Corridor (agreed with the rover-navigation owner, 2026-11-08). Returns are transformed from
the SENSOR frame into the ROBOT frame, then measured from the FRONT BUMPER:

    x_b = x_sensor_robot_axes - sensor_to_front_m       longitudinal clearance ahead of the bumper
    y_c = y_sensor_robot_axes + sensor_lateral_offset_m lateral offset from the robot CENTRELINE

    corridor = { 0 < x_b <= lookahead_m,  |y_c| <= robot_width_m/2 + width_margin_m }

where the "robot axes" are the sensor axes rotated by the mount (x forward, y left).

Verdict:
  * a valid return (any quality >= min_quality) inside the corridor with x_b <= blocked_m  -> BLOCKED
  * a valid return inside the robot's own footprint ahead of the sensor (not occluded)  -> BLOCKED
  * Evidence per 1-degree ray crossing the corridor: a valid return with quality >= clearance_min_quality
    at or beyond the ray's exit from the zone, OR an obstacle return inside the corridor (observed).
    Misses, low-quality returns, occluded rays and returns short of the corridor are UNCOVERED, never clear.
  * NEAR zone (x_b <= blocked_m + stopping_distance_m): 100 % of its rays must have evidence.
  * FAR zone (rest of the lookahead): >= corridor_min_coverage, and no contiguous uncovered run wider
    than corridor_max_gap_deg.
  * otherwise UNKNOWN. Unknown footprint / unverified alignment / unverified occlusion windows /
    failed orientation monitor / a near zone inside the sensor's minimum range  -> UNKNOWN.
  * nearest corridor obstacle x_b <= caution_m -> CAUTION, else CLEAR with range = the verified horizon
    (lookahead_m), reported as ``clear_horizon_m`` and never as max_range_m.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .config import LidarConfig
from .scan import SampleStatus, Scan

ORIENTATION_OK, ORIENTATION_FAILED, ORIENTATION_NOT_CONFIGURED = "OK", "FAILED", "NOT_CONFIGURED"
# A valid return at distance d proves the ray free up to d (anything nearer would have returned first).
# A return within this distance of the zone exit counts as observing the whole crossing (bin-centre ray
# approximation). Only used for COVERAGE; the BLOCKED/CAUTION geometry is exact.
EXIT_TOL_M = 0.01


def check_orientation(scan: Scan, cfg: LidarConfig) -> tuple[str, str]:
    """Is the robot-body fiducial where the configured mount predicts it, in this scan?"""
    m = cfg.mount
    if not m.fiducial_configured:
        return ORIENTATION_NOT_CONFIGURED, "no measured body fiducial configured"
    if m.forward_offset_deg is None:
        return ORIENTATION_FAILED, "forward offset unknown"
    want = m.sensor_angle(m.fiducial_robot_bearing_deg)
    for s in scan.samples:
        if s.status is SampleStatus.NON_FINITE or s.distance_m <= 0:
            continue
        d_ang = abs((s.angle_deg - want + 180.0) % 360.0 - 180.0)
        if d_ang <= m.fiducial_tol_deg and abs(s.distance_m - m.fiducial_range_m) <= m.fiducial_tol_m:
            return ORIENTATION_OK, f"fiducial seen at sensor {s.angle_deg:.1f} deg, {s.distance_m:.3f} m"
    return ORIENTATION_FAILED, (f"body fiducial not seen at predicted sensor {want:.1f} deg / "
                                f"{m.fiducial_range_m:.3f} m: offset, CW/CCW sign or mount is wrong")


def _ray_box(c: float, s: float, x0: float, x1: float, y0: float, y1: float) -> Optional[tuple[float, float]]:
    """Slab intersection of the ray t*(c, s), t >= 0, with the box. Returns (t_in, t_out) or None."""
    tmin, tmax = 0.0, math.inf
    for d, lo, hi in ((c, x0, x1), (s, y0, y1)):
        if abs(d) < 1e-12:
            if not (lo <= 0.0 <= hi):
                return None
            continue
        a, b = lo / d, hi / d
        if a > b:
            a, b = b, a
        tmin, tmax = max(tmin, a), min(tmax, b)
        if tmin > tmax:
            return None
    return tmin, tmax


def _max_run(flags: list[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


@dataclass
class CorridorResult:
    status: str                         # CLEAR | CAUTION | BLOCKED | UNKNOWN
    min_clearance_m: Optional[float]    # nearest obstacle ahead of the bumper inside the corridor
    clear_horizon_m: Optional[float]    # verified free distance (CLEAR/CAUTION), = lookahead_m when CLEAR
    near_coverage: Optional[float]
    far_coverage: Optional[float]
    max_gap_deg: Optional[float]
    near_zone_m: Optional[float]
    half_width_m: Optional[float]
    lookahead_m: Optional[float]
    orientation: str
    reason: str
    obstacle: Optional[dict] = None
    diagnosis: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        r = lambda v, n=4: None if v is None else round(v, n)  # noqa: E731
        return {"status": self.status, "reference": "FRONT BUMPER (robot frame, centreline)",
                "min_clearance_m": r(self.min_clearance_m), "clear_horizon_m": r(self.clear_horizon_m),
                "near_coverage_pct": None if self.near_coverage is None else round(self.near_coverage * 100, 1),
                "far_coverage_pct": None if self.far_coverage is None else round(self.far_coverage * 100, 1),
                "max_uncovered_gap_deg": r(self.max_gap_deg, 1), "near_zone_m": r(self.near_zone_m, 3),
                "half_width_m": r(self.half_width_m, 3), "lookahead_m": self.lookahead_m,
                "orientation_monitor": self.orientation, "reason": self.reason, "obstacle": self.obstacle,
                "diagnosis": self.diagnosis}


def _unknown(reason: str, orientation: str, cfg: LidarConfig) -> CorridorResult:
    f = cfg.footprint
    return CorridorResult("UNKNOWN", None, None, None, None, None, None, f.half_width_m,
                          f.lookahead_m, orientation, reason)


def assess_corridor(scan: Scan, cfg: LidarConfig) -> CorridorResult:
    f, p, m = cfg.footprint, cfg.processing, cfg.mount
    orient, orient_why = check_orientation(scan, cfg)
    if not m.aligned:
        return _unknown("sensor-to-robot alignment not verified", orient, cfg)
    if orient == ORIENTATION_FAILED:
        return _unknown(f"orientation monitor FAILED: {orient_why}", orient, cfg)
    if not f.known:
        return _unknown("robot footprint not measured (robot_width_m / sensor_to_front_m / "
                        "footprint_verified_by/_at)", orient, cfg)
    if not m.occlusion_ok:
        return _unknown("self-occlusion windows not signed off (occlusion_verified_by/_at)", orient, cfg)
    F, off, L, h = f.sensor_to_front_m, f.sensor_lateral_offset_m, f.lookahead_m, f.half_width_m
    near = min(L, p.blocked_m + p.stopping_distance_m)
    # Box in sensor-centred robot axes.
    y0, y1 = -h - off, h - off
    if F < p.min_range_m:
        # The corridor starts inside the blind zone: an obstacle at the bumper could be invisible.
        return _unknown(f"sensor_to_front_m {F:.3f} m < min range {p.min_range_m} m: blind zone at the bumper",
                        orient, cfg)

    nbins = int(round(360.0 / p.bin_deg))
    by_bin: dict[int, list] = {}
    hits, body_hits = [], []
    for s in scan.samples:
        rb = m.robot_bearing(s.angle_deg)
        th = math.radians(rb)
        b = int((rb % 360.0) // p.bin_deg) % nbins
        if m.occluded(s.angle_deg):
            continue          # robot body: never an obstacle, never clear evidence (its ray stays UNCOVERED)
        by_bin.setdefault(b, []).append(s)
        if not s.valid:
            continue
        x, y = s.distance_m * math.cos(th), s.distance_m * math.sin(th)
        yc = y + off
        if abs(yc) <= h:
            if F < x <= F + L:
                hits.append((x - F, yc, s))
            elif 0.0 < x <= F:
                body_hits.append((x, yc, s))
    if body_hits:
        x, yc, s = min(body_hits, key=lambda t: t[0])
        return CorridorResult("BLOCKED", 0.0, None, None, None, None, near, h, L, orient,
                              f"return inside the robot footprint ahead of the sensor ({x:.2f} m, y {yc:+.2f} m): "
                              "obstacle at the bumper or unrecorded self-occlusion",
                              {"x_from_bumper_m": 0.0, "y_from_centreline_m": round(yc, 3),
                               "sensor_bearing_deg": round(s.angle_deg, 2), "is_person": None})
    nearest = min(hits, key=lambda t: t[0]) if hits else None
    obstacle = None if nearest is None else {"x_from_bumper_m": round(nearest[0], 4),
                                             "y_from_centreline_m": round(nearest[1], 4),
                                             "sensor_bearing_deg": round(nearest[2].angle_deg, 2), "is_person": None}
    if nearest is not None and nearest[0] <= p.blocked_m:
        return CorridorResult("BLOCKED", nearest[0], None, None, None, None, near, h, L, orient,
                              f"obstacle {nearest[0]:.2f} m ahead of the bumper, {nearest[1]:+.2f} m from "
                              f"centreline (<= {p.blocked_m} m)", obstacle)

    # Coverage: rays (bin centres) crossing the near zone / the far zone.
    near_rays, far_rays = [], []
    for b in range(nbins):
        th = math.radians((b + 0.5) * p.bin_deg)
        c, sn = math.cos(th), math.sin(th)
        ixn = _ray_box(c, sn, F, F + near, y0, y1)
        ixf = _ray_box(c, sn, F + near, F + L, y0, y1) if near < L else None
        samples = by_bin.get(b, [])

        def covered(t_out: float, zone_hi: float) -> bool:
            for s in samples:
                if not s.valid:
                    continue
                th_s = math.radians(m.robot_bearing(s.angle_deg))
                x = s.distance_m * math.cos(th_s)
                yc = s.distance_m * math.sin(th_s) + off
                inside = abs(yc) <= h and F < x <= F + zone_hi
                if inside:
                    return True                          # obstacle observed (decided above / CAUTION below)
                if s.distance_m >= t_out - EXIT_TOL_M and s.quality >= p.clearance_min_quality:
                    return True                          # strong return beyond the zone exit: free through
            return False

        if ixn is not None and ixn[1] > ixn[0]:
            near_rays.append((b, covered(ixn[1], near)))
        if ixf is not None and ixf[1] > ixf[0]:
            far_rays.append((b, covered(ixf[1], L)))
    near_cov = (sum(c for _, c in near_rays) / len(near_rays)) if near_rays else 0.0
    far_cov = (sum(c for _, c in far_rays) / len(far_rays)) if far_rays else 1.0
    far_rays.sort(key=lambda t: ((t[0] * p.bin_deg + 180.0) % 360.0))
    gap = _max_run([not c for _, c in far_rays]) * p.bin_deg
    near_gap = _max_run([not c for _, c in sorted(near_rays, key=lambda t: ((t[0] * p.bin_deg + 180.0) % 360.0))])
    diag = {"near_rays": len(near_rays), "far_rays": len(far_rays), "near_uncovered_max_run_deg": near_gap * p.bin_deg,
            "corridor_hits": len(hits), "clearance_min_quality": p.clearance_min_quality,
            "transform": {"sensor_to_front_m": F, "sensor_lateral_offset_m": off}}
    base = dict(near_coverage=near_cov, far_coverage=far_cov, max_gap_deg=gap, near_zone_m=near,
                half_width_m=h, lookahead_m=L, orientation=orient, obstacle=obstacle, diagnosis=diag)
    if not near_rays or near_cov < 1.0:
        return CorridorResult("UNKNOWN", None if nearest is None else nearest[0], None,
                              reason=f"near zone (<= {near:.2f} m) only {near_cov:.0%} observed: 100 % required "
                                     "(misses, weak returns and occluded rays are not clear space)", **base)
    if far_cov < p.corridor_min_coverage or gap > p.corridor_max_gap_deg:
        return CorridorResult("UNKNOWN", None if nearest is None else nearest[0], None,
                              reason=f"far zone {far_cov:.0%} observed (need {p.corridor_min_coverage:.0%}), "
                                     f"largest gap {gap:.0f} deg (max {p.corridor_max_gap_deg:g})", **base)
    if nearest is not None and nearest[0] <= p.caution_m:
        return CorridorResult("CAUTION", nearest[0], nearest[0],
                              reason=f"obstacle {nearest[0]:.2f} m ahead of the bumper (<= {p.caution_m} m)", **base)
    if nearest is not None:
        return CorridorResult("CLEAR", nearest[0], nearest[0],
                              reason=f"nearest corridor obstacle {nearest[0]:.2f} m ahead of the bumper", **base)
    return CorridorResult("CLEAR", None, L, reason=f"corridor verified free to the {L:g} m horizon", **base)

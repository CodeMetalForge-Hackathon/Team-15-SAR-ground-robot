"""Deterministic SIMULATED 360-degree scan scenarios (no hardware, seeded RNG).

The geometry is a 2D ray cast in the ROBOT frame (x forward, y left). It is then converted
to SENSOR angles through ``SIM_MOUNT``, a simulated mount whose 0 mark points to the
robot's rear (offset 180 deg, clockwise). That makes "sensor 0 = forward" bugs show up
in tests. Every scan, fixture file and payload is labelled SIMULATED.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from .config import FootprintConfig, LidarConfig, MountConfig
from .scan import Scan, ScanCompletion, SourceMode, build_scan

SIM_LABEL = "SIMULATED"
# Simulated robot body: a 2 cm mast at robot (-0.10, +0.10) m, i.e. robot bearing 135 deg (rear-left),
# range 0.141 m. It is the orientation fiducial (asymmetric, so a CW/CCW sign error is caught) and lies
# inside a signed-off self-occlusion window (sensor 45 +- 7 deg for this mount).
SIM_FIDUCIAL_XY = (-0.10, 0.10)
SIM_MOUNT = MountConfig(forward_offset_deg=180.0, sensor_rotation="CW",
                        alignment_verified_by="SIMULATION (not a person)", alignment_verified_at="SIMULATED",
                        alignment_method="synthetic mount: sensor 0 mark faces robot rear",
                        self_occlusion_deg=[[38.0, 52.0]], occlusion_verified_by="SIMULATION (not a person)",
                        occlusion_verified_at="SIMULATED", fiducial_robot_bearing_deg=135.0,
                        fiducial_range_m=round(math.hypot(*SIM_FIDUCIAL_XY), 4),
                        fiducial_measured_by="SIMULATION (not a person)")
# rover/simrun.py SIM_ROBOT_WIDTH_M = 0.20 (SYNTHETIC placeholder); sensor 0.10 m behind the bumper.
SIM_FOOTPRINT = FootprintConfig(robot_width_m=0.20, width_margin_m=0.05, lookahead_m=1.0, sensor_to_front_m=0.10,
                                sensor_lateral_offset_m=0.0, footprint_verified_by="SIMULATION (not a person)",
                                footprint_verified_at="SIMULATED")
POINTS_PER_REV = 500        # ~5 kHz sample rate / 10 Hz (datasheet typical, not measured)
SCAN_PERIOD_NS = 100_000_000


def sim_config(**proc) -> LidarConfig:
    m = dict(vars(SIM_MOUNT))
    m["self_occlusion_deg"] = [list(w) for w in SIM_MOUNT.self_occlusion_deg]
    cfg = LidarConfig(mode="simulated", mount=MountConfig(**m), footprint=FootprintConfig(**vars(SIM_FOOTPRINT)))
    for k, v in proc.items():
        setattr(cfg.processing, k, v)
    return cfg.validate()


# ---- geometry (robot frame, metres) ---------------------------------------
@dataclass
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float
    kind: str = "solid"          # solid | glass (no return) | mirror (spurious long return) | dark (low quality)


def _ray_hit(theta: float, seg: Segment) -> Optional[float]:
    dx, dy = math.cos(theta), math.sin(theta)
    ex, ey = seg.x2 - seg.x1, seg.y2 - seg.y1
    den = dx * ey - dy * ex
    if abs(den) < 1e-12:
        return None
    t = (seg.x1 * ey - seg.y1 * ex) / den
    u = (seg.x1 * dy - seg.y1 * dx) / den
    if t > 1e-6 and 0.0 <= u <= 1.0:
        return t
    return None


def box(cx: float, cy: float, w: float, d: float, kind: str = "solid") -> list[Segment]:
    x0, x1, y0, y1 = cx - d / 2, cx + d / 2, cy - w / 2, cy + w / 2
    return [Segment(x0, y0, x1, y0, kind), Segment(x1, y0, x1, y1, kind),
            Segment(x1, y1, x0, y1, kind), Segment(x0, y1, x0, y0, kind)]


def room(half_x: float = 2.5, half_y: float = 2.0) -> list[Segment]:
    return [Segment(-half_x, -half_y, half_x, -half_y), Segment(half_x, -half_y, half_x, half_y),
            Segment(half_x, half_y, -half_x, half_y), Segment(-half_x, half_y, -half_x, -half_y)]


@dataclass
class World:
    segments: list[Segment] = field(default_factory=list)
    noise_m: float = 0.005
    dropout: float = 0.0                       # fraction of random NO_RETURN samples
    missing_robot_deg: list = field(default_factory=list)   # robot-frame windows with no samples at all
    max_range_m: float = 12.0
    robot_parts: Optional[list] = None   # None = the simulated mast (fiducial); [] = no body parts


def cast(world: World, rng: random.Random, n: int = POINTS_PER_REV, mount: MountConfig = SIM_MOUNT,
         angle_jitter_deg: float = 0.1) -> list[tuple[float, float, int]]:
    """Return (sensor_angle_deg, distance_m, quality) for one revolution, sensor order."""
    out = []
    for i in range(n):
        sensor_a = (i * 360.0 / n + rng.uniform(-angle_jitter_deg, angle_jitter_deg)) % 360.0
        robot_a = mount.robot_bearing(sensor_a)
        if any(_in_window(robot_a, lo, hi) for lo, hi in world.missing_robot_deg):
            continue
        th = math.radians(robot_a)
        best, kind = None, None
        parts = box(SIM_FIDUCIAL_XY[0], SIM_FIDUCIAL_XY[1], 0.02, 0.02) if world.robot_parts is None \
            else world.robot_parts
        for s in list(world.segments) + parts:
            t = _ray_hit(th, s)
            if t is not None and (best is None or t < best):
                best, kind = t, s.kind
        if best is None or best > world.max_range_m or rng.random() < world.dropout:
            out.append((sensor_a, 0.0, 0))
            continue
        if kind == "glass":
            out.append((sensor_a, 0.0, 0))
            continue
        if kind == "mirror":
            out.append((sensor_a, min(world.max_range_m, best + 3.0 + rng.uniform(0, 1)), 12))
            continue
        q = 8 if kind == "dark" else 47
        out.append((sensor_a, max(0.0, best + rng.gauss(0.0, world.noise_m)), q))
    return out


def _in_window(a: float, lo: float, hi: float) -> bool:
    a, lo, hi = a % 360, lo % 360, hi % 360
    return (lo <= a <= hi) if lo <= hi else (a >= lo or a <= hi)


def make_scan(points, seq: int, start_ns: int, cfg: LidarConfig, *, period_ns: int = SCAN_PERIOD_NS,
              wall0: float = 1_794_200_000.0, scenario: str = "", interrupted: bool = False,
              detail: Optional[str] = None) -> Scan:
    return build_scan(points, sensor_id=cfg.sensor_id, frame_id=cfg.frame_id, seq=seq, start_mono_ns=start_ns,
                      end_mono_ns=start_ns + period_ns, start_wall=wall0 + start_ns / 1e9, cfg=cfg.processing,
                      source_mode=SourceMode.SIMULATED,
                      provenance={"driver": "simulation", "scenario": scenario, "label": SIM_LABEL,
                                  "host": None, "generator": "lidar.simulation"},
                      interrupted=interrupted, occluded=cfg.mount.occluded, detail=detail)


# ---- scenarios --------------------------------------------------------------
# Each returns a list of (scan, now_ns) pairs. now_ns is when the consumer assesses it.
Scenario = Callable[[LidarConfig, random.Random], list]


def _series(worlds: list[World], cfg, rng, name, latency_ns=20_000_000, period_ns=SCAN_PERIOD_NS, n=POINTS_PER_REV):
    out = []
    for k, w in enumerate(worlds):
        t0 = 1_000_000_000 + k * period_ns
        out.append((make_scan(cast(w, rng, n), k + 1, t0, cfg, period_ns=period_ns, scenario=name),
                    t0 + period_ns + latency_ns))
    return out


def _steady(world: World, scans: int = 3):
    return lambda cfg, rng, name: _series([world] * scans, cfg, rng, name)


def s_empty_incomplete(cfg, rng, name):
    # Open space: only a far wall behind, nothing in range ahead -> mostly NO_RETURN.
    w = World([Segment(-3.0, -4.0, -3.0, 4.0)], max_range_m=8.0)
    return _series([w] * 3, cfg, rng, name)


def s_obstacle_ahead(cfg, rng, name):
    return _series([World(room() + box(0.30, 0.0, 0.30, 0.10))] * 3, cfg, rng, name)


def s_obstacle_behind(cfg, rng, name):
    return _series([World(room() + box(-0.30, 0.0, 0.30, 0.10))] * 3, cfg, rng, name)


def s_obstacle_left(cfg, rng, name):
    return _series([World(room() + box(0.0, 0.30, 0.10, 0.30))] * 3, cfg, rng, name)


def s_multiple(cfg, rng, name):
    segs = room() + box(0.30, 0.0, 0.3, 0.1) + box(-0.5, 0.3, 0.2, 0.2) + box(0.0, -0.6, 0.1, 0.3)
    return _series([World(segs)] * 3, cfg, rng, name)


def s_doorway(cfg, rng, name):
    # Wall 1.2 m ahead with a 0.8 m gap; door jambs 0.4 m each side of the axis.
    segs = room(3.0, 2.0) + [Segment(1.2, -2.0, 1.2, -0.4), Segment(1.2, 0.4, 1.2, 2.0)]
    return _series([World(segs)] * 3, cfg, rng, name)


def s_wall_one_side(cfg, rng, name):
    segs = room(3.0, 2.0) + [Segment(-3.0, -0.25, 3.0, -0.25)]
    return _series([World(segs)] * 3, cfg, rng, name)


def s_approaching(cfg, rng, name):
    worlds = [World(room(3.0, 2.0) + box(d, 0.0, 0.4, 0.1)) for d in (1.6, 1.2, 0.9, 0.6, 0.4, 0.3)]
    return _series(worlds, cfg, rng, name)


def s_invalid_values(cfg, rng, name):
    pts = cast(World(room()), rng)
    bad = [(a, d, q) for a, d, q in pts]
    for i in range(0, len(bad), 3):
        a, d, q = bad[i]
        bad[i] = (a, [float("nan"), float("inf"), -1.0, 0.01, 50.0, 0.0][(i // 3) % 6], q)
    for i in range(1, len(bad), 3):
        a, d, q = bad[i]
        bad[i] = (a, d, 2)            # LOW_QUALITY
    return [(make_scan(bad, 1, 1_000_000_000, cfg, scenario=name), 1_120_000_000)]


def s_missing_sectors(cfg, rng, name):
    w = World(room(), missing_robot_deg=[(-40.0, 40.0), (150.0, 210.0)])
    return _series([w] * 3, cfg, rng, name)


def s_partial(cfg, rng, name):
    pts = cast(World(room()), rng)[:120]      # revolution cut short
    return [(make_scan(pts, 1, 1_000_000_000, cfg, scenario=name, detail="revolution cut short"), 1_120_000_000)]


def s_stale(cfg, rng, name):
    pts = cast(World(room(3.0, 3.0)), rng)
    s1 = make_scan(pts, 1, 1_000_000_000, cfg, scenario=name)
    return [(s1, 1_000_000_000 + 300_000_000),        # 0.30 s: too old for motion, ok for display
            (s1, 1_000_000_000 + 800_000_000),        # 0.80 s: stale for display too
            (s1, 1_000_000_000 - 200_000_000)]        # from the future: clock fault


def s_wrong_orientation(cfg, rng, name):
    # Real obstacle ahead, but the consumer is (mis)configured with offset 0 (sensor 0 = forward).
    return _series([World(room() + box(0.30, 0.0, 0.30, 0.10))] * 3, cfg, rng, name)


def s_unexpected_rate(cfg, rng, name):
    w = World(room(3.0, 3.0))
    return _series([w] * 4, cfg, rng, name, period_ns=250_000_000, n=500)   # 4 Hz


def s_reflective(cfg, rng, name):
    segs = room(3.0, 2.0) + [Segment(0.9, -0.6, 0.9, 0.6, "glass"), Segment(-0.4, 1.0, 0.4, 1.0, "mirror"),
                             Segment(-0.6, -0.7, 0.6, -0.7, "dark")]
    return _series([World(segs)] * 3, cfg, rng, name)


def s_moving_robot(cfg, rng, name):
    # Robot drives forward at 0.3 m/s towards a stationary box (SIMULATED motion; no odometry exists).
    worlds = [World(room(3.0, 2.0) + box(1.5 - 0.03 * k, 0.0, 0.4, 0.1)) for k in range(8)]
    return _series(worlds, cfg, rng, name)


def s_unsafe_forward(cfg, rng, name):
    # Front sector mostly empty (no return), plus a close obstacle front-left.
    segs = [Segment(-3, -2, -3, 2), Segment(-3, 2, 0.0, 2), Segment(-3, -2, 0.0, -2)] + box(0.25, 0.25, 0.1, 0.1)
    return _series([World(segs, max_range_m=8.0)] * 3, cfg, rng, name)


def _pole(x, y, r=0.02):
    return box(x, y, r, r)


def s_edge_left(cfg, rng, name):
    # Centreline clear (nearest FRONT-sector return 0.42 m: CAUTION, old rule would allow), but a pole
    # 0.30 m ahead of the bumper, 0.14 m left of centre: inside the 0.15 m half-corridor -> BLOCKED.
    return _series([World(room(3.0, 3.0) + _pole(0.40, 0.14))] * 3, cfg, rng, name)


def s_edge_right(cfg, rng, name):
    return _series([World(room(3.0, 3.0) + _pole(0.40, -0.14))] * 3, cfg, rng, name)


def s_pole_outside(cfg, rng, name):
    # Same distance, 0.22 m left: outside the corridor (no over-blocking).
    return _series([World(room(3.0, 3.0) + _pole(0.40, 0.22))] * 3, cfg, rng, name)


def s_narrow_door(cfg, rng, name):
    # 0.24 m opening (narrower than the 0.20 m robot + 2 x 0.05 m margin) approached from 0.7 to 0.3 m
    # ahead of the bumper: the jambs lie inside the corridor -> CAUTION, then BLOCKED before contact.
    worlds = [World(room(3.0, 2.0) + [Segment(F + 0.10, -2.0, F + 0.10, -0.12), Segment(F + 0.10, 0.12, F + 0.10, 2.0)])
              for F in (0.70, 0.50, 0.40, 0.30, 0.25)]
    return _series(worlds, cfg, rng, name)


def s_mirror_ahead(cfg, rng, name):
    # Specular panel across the corridor 0.6 m ahead: weak phantom returns far behind it.
    segs = room(3.0, 2.0) + [Segment(0.70, -0.5, 0.70, 0.5, "mirror")]
    return _series([World(segs)] * 3, cfg, rng, name)


def s_clear_room(cfg, rng, name):
    """Control case: fully covered room, nothing close. The only case that should read CLEAR."""
    return _series([World(room(3.0, 3.0))] * 3, cfg, rng, name)


SCENARIOS: dict[str, Callable] = {
    "01_empty_incomplete_returns": s_empty_incomplete,
    "02_obstacle_ahead": s_obstacle_ahead,
    "03_obstacle_behind": s_obstacle_behind,
    "04_obstacle_left": s_obstacle_left,
    "05_multiple_obstacles": s_multiple,
    "06_narrow_doorway": s_doorway,
    "07_wall_one_side": s_wall_one_side,
    "08_obstacle_approaching": s_approaching,
    "09_invalid_range_values": s_invalid_values,
    "10_missing_angular_sectors": s_missing_sectors,
    "11_partial_scan": s_partial,
    "12_stale_timestamps": s_stale,
    # 13 serial disconnect and 14 device timeout are byte-level: see lidar/tests (MockLidarDevice)
    # and REPLAY_EVENTS below.
    "15_incorrect_orientation": s_wrong_orientation,
    "16_unexpected_scan_frequency": s_unexpected_rate,
    "17_reflective_transparent": s_reflective,
    "18_moving_robot_stationary_obstacle": s_moving_robot,
    # 19 corrupted packets is byte-level (MockLidarDevice corrupt=...).
    "20_unsafe_forward_clearance": s_unsafe_forward,
    "00_clear_room_control": s_clear_room,
    "21_edge_obstacle_left": s_edge_left,
    "22_edge_obstacle_right": s_edge_right,
    "23_pole_just_outside_corridor": s_pole_outside,
    "24_door_narrower_than_robot": s_narrow_door,
    "25_mirror_across_corridor": s_mirror_ahead,
}
BYTE_LEVEL_SCENARIOS = {"13_serial_disconnect", "14_device_timeout", "19_corrupted_packets"}


def generate(name: str, seed: int = 15) -> list:
    rng = random.Random(f"{seed}:{name}")
    cfg = sim_config()
    return SCENARIOS[name](cfg, rng, name)


def load_fixture(path: str, cfg: Optional[LidarConfig] = None) -> list:
    """Rebuild (scan, now_ns, expected) from an exported fixture through the normal build_scan path.

    Refuses any fixture that is not labelled SIMULATED, so a file cannot pass itself off as hardware data.
    """
    import json
    with open(path) as f:
        doc = json.load(f)
    if doc.get("label") != SIM_LABEL or doc.get("source_mode") != "SIMULATED":
        raise ValueError(f"{path}: not a SIMULATED fixture (label={doc.get('label')!r})")
    cfg = cfg or sim_config()
    out = []
    for fr in doc["frames"]:
        h = fr["scan"]
        if h.get("source_mode") != "SIMULATED":
            raise ValueError(f"{path}: frame claims source_mode {h.get('source_mode')!r}")
        scan = build_scan([tuple(p) for p in fr["points"]], sensor_id=h["sensor_id"], frame_id=h["frame_id"],
                          seq=h["seq"], start_mono_ns=h["capture_start_mono_ns"],
                          end_mono_ns=h["capture_end_mono_ns"], start_wall=h["capture_start_wall"],
                          cfg=cfg.processing, source_mode=SourceMode.SIMULATED,
                          provenance={**h.get("provenance", {}), "fixture": path, "label": SIM_LABEL},
                          interrupted=h["completion"] == "INTERRUPTED", occluded=cfg.mount.occluded,
                          detail=h.get("detail"))
        out.append((scan, fr["assess_at_mono_ns"], fr["expected"]))
    return out

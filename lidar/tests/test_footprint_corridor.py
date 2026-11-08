"""Footprint-aware forward-corridor clearance (agreed with the rover-navigation owner, 2026-11-08)."""
import math
import random
import socket

import pytest

from lidar import adapters
from lidar.config import FootprintConfig, LidarConfigError
from lidar.footprint import assess_corridor, check_orientation
from lidar.processing import LidarAssessor, SectorStatus
from lidar.simulation import World, _pole, box, cast, generate, make_scan, room, sim_config

S = SectorStatus


def last(name, cfg=None):
    a = LidarAssessor(cfg or sim_config())
    for scan, now in generate(name):
        r = a.update(scan, now_mono_ns=now)
    return r


def scan_of(world, cfg=None, n=500, seed=3):
    cfg = cfg or sim_config()
    return make_scan(cast(world, random.Random(seed), n), 1, 1_000_000_000, cfg), cfg


# ---- the user's requirement: clear on the centreline, too close to an edge ---------------
@pytest.mark.parametrize("name,side", [("21_edge_obstacle_left", +1), ("22_edge_obstacle_right", -1)])
def test_centreline_clear_but_edge_obstacle_blocks(name, side):
    r = last(name)
    # The old FRONT-wedge rule sees only CAUTION (nearest return ~0.42 m from the sensor) ...
    assert r.sector("FRONT").status is S.CAUTION
    # ... the corridor sees a pole 0.30 m ahead of the bumper, 0.14 m off centre (half-corridor 0.15 m).
    c = r.corridor
    assert c.status == "BLOCKED" and c.min_clearance_m == pytest.approx(0.29, abs=0.02)
    assert side * c.obstacle["y_from_centreline_m"] > 0.12
    assert not r.forward_motion_allowed


def test_centreline_free_ray_is_truly_free_for_edge_case():
    # Prove the centreline itself is unobstructed in scenario 21: no corridor return with |y| < 0.10.
    scan, _ = generate("21_edge_obstacle_left")[-1]
    cfg = sim_config()
    for s in scan.valid_samples:
        th = math.radians(cfg.mount.robot_bearing(s.angle_deg))
        x, y = s.distance_m * math.cos(th), s.distance_m * math.sin(th)
        if 0.1 < x < 1.1:
            assert abs(y) > 0.10 or x > 2.5


def test_pole_just_outside_corridor_does_not_over_block():
    r = last("23_pole_just_outside_corridor")
    assert r.corridor.status == "CLEAR" and r.corridor.clear_horizon_m == 1.0 and r.forward_motion_allowed


@pytest.mark.parametrize("y,expect", [(0.149, "BLOCKED"), (0.151 + 0.01, "CLEAR"), (-0.149, "BLOCKED"),
                                      (-0.161, "CLEAR"), (0.0, "BLOCKED")])
def test_corridor_edge_boundary(y, expect):
    w = World(room(3.0, 3.0) + _pole(0.40, y + (0.01 if y > 0 else -0.01 if y < 0 else 0.0), r=0.02))
    scan, cfg = scan_of(w, n=1440)
    assert assess_corridor(scan, cfg).status == expect


def test_unknown_robot_dimensions_is_unknown():
    for change in ({"robot_width_m": None}, {"sensor_to_front_m": None}, {"footprint_verified_by": None},
                   {"footprint_verified_at": ""}):
        cfg = sim_config()
        for k, v in change.items():
            setattr(cfg.footprint, k, v)
        r = last("00_clear_room_control", cfg)
        assert r.corridor.status == "UNKNOWN" and "footprint not measured" in r.corridor.reason
        assert not r.forward_motion_allowed


def test_footprint_validation():
    with pytest.raises(LidarConfigError):
        FootprintConfig(robot_width_m=2.0).validate()
    with pytest.raises(LidarConfigError):
        FootprintConfig(robot_width_m=0.2, lookahead_m=0.8, rover_max_required_clear_m=1.0).validate()
    FootprintConfig(robot_width_m=0.2, lookahead_m=1.0, rover_max_required_clear_m=1.0).validate()


def test_off_centre_mount_transform():
    # Sensor mounted 0.10 m LEFT of the centreline. A pole 0.20 m to the sensor's right (outside
    # +-0.15 m in sensor axes) is 0.10 m right of the robot centreline: INSIDE the corridor.
    w = World(room(3.0, 3.0) + _pole(0.40, -0.20))
    centred = sim_config()
    scan, _ = scan_of(w, centred, n=1440)
    assert assess_corridor(scan, centred).status == "CLEAR"
    off = sim_config()
    off.footprint.sensor_lateral_offset_m = 0.10
    c = assess_corridor(scan, off)
    assert c.status == "BLOCKED" and c.obstacle["y_from_centreline_m"] == pytest.approx(-0.10, abs=0.02)
    # and a pole 0.20 m to the sensor's LEFT is now outside (0.30 m from centreline)
    scan2, _ = scan_of(World(room(3.0, 3.0) + _pole(0.40, 0.20)), off, n=1440)
    assert assess_corridor(scan2, off).status == "CLEAR"


def test_sensor_to_front_shifts_clearance_reference():
    w = World(room(3.0, 3.0) + _pole(0.60, 0.0))
    cfg = sim_config()
    scan, _ = scan_of(w, cfg, n=1440)
    assert assess_corridor(scan, cfg).min_clearance_m == pytest.approx(0.49, abs=0.02)   # 0.59 - 0.10
    cfg.footprint.sensor_to_front_m = 0.30                    # longer robot (gripper out front)
    c = assess_corridor(scan, cfg)
    assert c.status == "BLOCKED" and c.min_clearance_m == pytest.approx(0.29, abs=0.02)


def test_return_inside_own_footprint_blocks():
    w = World(room(3.0, 3.0) + _pole(0.06 + 0.04, 0.05, r=0.02))   # between sensor and bumper (x 0.08-0.10)
    scan, cfg = scan_of(w, n=1440)
    c = assess_corridor(scan, cfg)
    assert c.status == "BLOCKED" and "inside the robot footprint" in c.reason


def test_blind_zone_at_bumper_is_unknown():
    cfg = sim_config()
    cfg.footprint.sensor_to_front_m = 0.05                     # below min_range 0.08
    scan, _ = generate("00_clear_room_control")[0]
    assert "blind zone" in assess_corridor(scan, cfg).reason


# ---- near zone 100 %, far zone gap limit ----------------------------------------------
def _drop(scan_pts, cfg, lo, hi):
    out = []
    for a, d, q in scan_pts:
        rb = cfg.mount.robot_bearing(a)
        if (lo <= rb <= hi) if lo <= hi else (rb >= lo or rb <= hi):
            out.append((a, 0.0, 0))                                 # NO_RETURN
        else:
            out.append((a, d, q))
    return out


def test_near_zone_single_missing_ray_is_unknown():
    cfg = sim_config()
    pts = cast(World(room(3.0, 3.0)), random.Random(1))
    pts = _drop(pts, cfg, 30.2, 31.6)                                  # one ~1 deg hole in the near zone
    c = assess_corridor(make_scan(pts, 1, 1_000_000_000, cfg), cfg)
    assert c.status == "UNKNOWN" and c.near_coverage < 1.0 and "near zone" in c.reason


def test_far_zone_contiguous_gap_is_unknown_even_if_coverage_high():
    cfg = sim_config()
    pts = cast(World(room(3.0, 3.0)), random.Random(1))
    pts = _drop(pts, cfg, 2.0, 5.9)                                     # ~4 deg hole near the axis
    c = assess_corridor(make_scan(pts, 1, 1_000_000_000, cfg), cfg)
    assert c.status == "UNKNOWN"
    assert c.near_coverage < 1.0 or c.max_gap_deg > cfg.processing.corridor_max_gap_deg


def test_weak_returns_are_not_clear_evidence_but_are_obstacles():
    cfg = sim_config()
    pts = [(a, d, 12 if d > 0 else q) for a, d, q in cast(World(room(3.0, 3.0)), random.Random(1))]
    c = assess_corridor(make_scan(pts, 1, 1_000_000_000, cfg), cfg)
    assert c.status == "UNKNOWN"
    pts2 = [(a, d, 12 if d > 0 else q) for a, d, q in
            cast(World(room(3.0, 3.0) + _pole(0.30, 0.0)), random.Random(1))]
    assert assess_corridor(make_scan(pts2, 1, 1_000_000_000, cfg), cfg).status == "BLOCKED"


def test_mirror_across_corridor_is_unknown():
    r = last("25_mirror_across_corridor")
    assert r.corridor.status == "UNKNOWN" and not r.forward_motion_allowed


def test_occlusion_windows_need_signoff_and_count_as_uncovered():
    cfg = sim_config()
    cfg.mount.occlusion_verified_by = None
    r = last("00_clear_room_control", cfg)
    assert r.corridor.status == "UNKNOWN" and "occlusion" in r.corridor.reason
    # A signed-off window that crosses the near-zone corridor still prevents CLEAR.
    cfg2 = sim_config()
    s0 = cfg2.mount.sensor_angle(10.0)
    cfg2.mount.self_occlusion_deg.append([s0 - 2.0, s0 + 2.0])
    r2 = last("00_clear_room_control", cfg2)
    assert r2.corridor.status == "UNKNOWN" and not r2.forward_motion_allowed


def test_narrow_door_caution_then_blocked_before_contact():
    a = LidarAssessor(sim_config())
    res = [a.update(s, now_mono_ns=n) for s, n in generate("24_door_narrower_than_robot")]
    st = [r.corridor.status for r in res]
    assert st[0] in ("CAUTION", "CLEAR") and st[-1] == "BLOCKED" and "CAUTION" in st
    assert all(r.corridor.min_clearance_m is None or r.corridor.min_clearance_m > 0.1 for r in res)


# ---- orientation monitor ----------------------------------------------------------------
def test_fiducial_missing_from_scan_fails():
    cfg = sim_config()
    scan, _ = scan_of(World(room(3.0, 3.0), robot_parts=[]), cfg)     # mast knocked off / sensor rotated
    assert check_orientation(scan, cfg)[0] == "FAILED"
    scan2, _ = scan_of(World(room(3.0, 3.0)), cfg)
    assert check_orientation(scan2, cfg)[0] == "OK"


def test_small_physical_rotation_beyond_tolerance_fails():
    cfg = sim_config()
    scan, _ = scan_of(World(room(3.0, 3.0)), cfg)
    # Detectable rotation ~ tol (4 deg) + the mast's own half-width (~4 deg at 0.14 m): test 12 deg.
    cfg.mount.forward_offset_deg = 180.0 + 12.0
    assert check_orientation(scan, cfg)[0] == "FAILED"
    cfg.mount.forward_offset_deg = 180.0 + 2.0                      # within tolerance
    assert check_orientation(scan, cfg)[0] == "OK"


# ---- rover / dashboard / Qwen contract for the corridor ----------------------------------
def test_rover_fields_bumper_referenced_horizon_never_max_range():
    r = last("00_clear_room_control")
    f = adapters.to_rover_fields(r, 0.0, this_host=socket.gethostname())
    assert f["status"] == "OK" and f["range_m"] == 1.0 and f["clear_horizon_m"] == 1.0
    assert f["range_reference"] == "FRONT_BUMPER" and f["range_m"] != f["max_range_m"]
    assert f["source_mode"] == "SIMULATED" and f["source"] == "rplidar-c1"


def test_rover_fields_edge_obstacle_is_blocked_with_clearance():
    r = last("21_edge_obstacle_left")
    f = adapters.to_rover_fields(r, 0.0, this_host="pi")
    assert f["status"] == "OK" and f["obstacle_status"] == "BLOCKED" and f["range_m"] < 0.35
    assert f["forward_motion_allowed"] is False and f["clear_horizon_m"] is None


def test_rover_fields_unknown_corridor_is_error():
    cfg = sim_config()
    cfg.footprint.robot_width_m = None
    f = adapters.to_rover_fields(last("00_clear_room_control", cfg), 0.0, this_host="pi")
    assert f["status"] == "ERROR" and f["range_m"] is None and not f["forward_motion_allowed"]


def test_rover_still_rejects_corridor_fields_and_assess_on_allowlist_preview():
    import rover.sensors as rs
    r = last("21_edge_obstacle_left")
    f = adapters.to_rover_fields(r, 0.0, this_host="pi")
    assert rs.from_rover_fields(f, "time.monotonic@pi").status == rs.ERROR        # source rejected today
    rr = rs.from_rover_fields(dict(f, source=rs.GROVE_SOURCE), "time.monotonic@pi")  # Stage D preview only
    assert rs.assess(rr, rr.t, 0.30, 0.20)[0] is rs.Assessment.BLOCKED


def test_dashboard_snapshot_uses_more_restrictive_corridor():
    from core import range_view
    import time
    r = last("21_edge_obstacle_left")
    snap = adapters.to_range_snapshot(r)
    assert snap["obstacle_status"] == "BLOCKED"                 # FRONT wedge alone says CAUTION
    v = range_view.from_snapshot(snap, now=time.time(), fixture=False)
    assert v["status"] == "BLOCKED" and v["badge"] == "SIMULATED"


def test_advisory_carries_corridor_without_authority():
    c = adapters.to_advisory_context(last("21_edge_obstacle_left"))
    assert c["forward_corridor"]["status"] == "BLOCKED" and c["may_authorize_motion"] is False
    assert c["orientation_monitor"] == "OK" and c["person_distance_cm"] is None

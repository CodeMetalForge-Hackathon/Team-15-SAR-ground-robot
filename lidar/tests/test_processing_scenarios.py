"""Sector processing, frames, freshness and the 20 SIMULATED scenarios."""
import copy
import glob
import json
import os

import pytest

from lidar.config import LidarConfig, LidarConfigError, MountConfig
from lidar.processing import Connection, LidarAssessor, SectorStatus, analyze_sectors, sector_of
from lidar.scan import ScanCompletion, SourceMode
from lidar.simulation import (SCENARIOS, SIM_MOUNT, World, box, cast, generate, load_fixture, make_scan, room,
                              sim_config)

FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures")
S = SectorStatus


def run(name, cfg=None):
    cfg = cfg or sim_config()
    a = LidarAssessor(cfg)
    res = [a.update(scan, now_mono_ns=now) for scan, now in generate(name)]
    return res, a


def st(r):
    return {s.name: s.status for s in r.sectors}


# ---- frames and conventions ---------------------------------------------
def test_sensor_cw_to_robot_ccw_with_offset():
    m = MountConfig(forward_offset_deg=180.0, sensor_rotation="CW")
    assert m.robot_bearing(180.0) == 0.0          # sensor 180 = robot forward
    assert m.robot_bearing(90.0) == 90.0          # sensor 90 cw = robot left (ccw +90)
    assert m.robot_bearing(270.0) == 270.0        # robot right
    m2 = MountConfig(forward_offset_deg=0.0, sensor_rotation="CCW")
    assert m2.robot_bearing(30.0) == 30.0
    assert MountConfig().robot_bearing(10.0) is None   # unmeasured offset: no robot bearing at all


@pytest.mark.parametrize("brg,name", [(0, "FRONT"), (22.4, "FRONT"), (22.6, "FRONT_LEFT"), (90, "LEFT"),
                                      (180, "REAR"), (270, "RIGHT"), (337.6, "FRONT"), (337.4, "FRONT_RIGHT"),
                                      (359.9, "FRONT")])
def test_sector_boundaries(brg, name):
    assert sector_of(brg) == name


def test_unaligned_mount_is_unknown_everywhere_even_with_close_obstacle():
    cfg = LidarConfig(mode="simulated")          # forward_offset not measured
    scan, now = generate("02_obstacle_ahead")[0]
    r = LidarAssessor(cfg).update(scan, now_mono_ns=now)
    assert all(s.status is S.UNKNOWN for s in r.sectors) and not r.forward_motion_allowed
    assert r.any_return_within_blocked is True          # orientation-free warning still raised
    assert r.closest["robot_bearing_deg"] is None and r.closest["sensor_bearing_deg"] is not None


def test_offset_without_named_verifier_is_not_aligned():
    cfg = LidarConfig(mode="simulated", mount=MountConfig(forward_offset_deg=180.0))
    assert not cfg.mount.aligned


def test_quality_threshold_and_range_limits():
    cfg = sim_config(min_quality=30)
    pts = [(a, 1.0, 20) for a in range(360)]
    scan = make_scan(pts, 1, 1_000_000_000, cfg)
    assert not scan.valid_samples and scan.status_counts() == {"LOW_QUALITY": 360}
    with pytest.raises(LidarConfigError):
        sim_config(max_range_m=20.0)
    with pytest.raises(LidarConfigError):
        sim_config(blocked_m=1.0, caution_m=0.5)


def test_self_occlusion_window_counts_as_unknown():
    cfg = sim_config()
    cfg.mount.self_occlusion_deg = [[150.0, 210.0]]     # sensor window = robot front +-30
    scan, now = generate("00_clear_room_control")[0]
    scan2 = make_scan([(x.angle_deg, x.distance_m, x.quality) for x in scan.samples], 1, scan.capture_start_mono_ns, cfg)
    r = LidarAssessor(cfg).update(scan2, now_mono_ns=now)
    assert r.sector("FRONT").status is S.UNKNOWN and "SELF_OCCLUDED" in scan2.status_counts()


# ---- freshness ------------------------------------------------------------
def test_12_stale_rules_motion_display_future():
    (r1, r2, r3), _ = run("12_stale_timestamps")
    assert r1.stale_for_motion and not r1.stale_for_display and not r1.forward_motion_allowed
    assert r1.sector("FRONT").status is S.CLEAR          # displayable, but not for motion
    assert r2.stale_for_display and all(s.status is S.UNKNOWN for s in r2.sectors) and r2.closest is None
    assert r3.stale_for_display and "future" in r3.reason and not r3.forward_motion_allowed


def test_motion_limit_is_020_and_display_050():
    p = sim_config().processing
    assert p.motion_max_age_s == 0.20 and p.display_max_age_s == 0.50


def test_age_measured_from_capture_start_not_end():
    cfg = sim_config()
    scan, _ = generate("00_clear_room_control")[0]
    # completed 0.1 s after start; assessed 0.15 s after completion -> 0.25 s old -> too old for motion
    r = LidarAssessor(cfg).update(scan, now_mono_ns=scan.capture_end_mono_ns + 150_000_000)
    assert r.scan_age_s == pytest.approx(0.25) and r.stale_for_motion


def test_connection_loss_reassessment_is_unknown():
    res, a = run("00_clear_room_control")
    assert res[-1].forward_motion_allowed
    r = a.status(Connection.DISCONNECTED, "unplugged", now_mono_ns=generate("00_clear_room_control")[-1][1])
    assert not r.forward_motion_allowed and r.connection is Connection.DISCONNECTED
    assert all(s.status in (S.UNKNOWN, S.BLOCKED) for s in r.sectors)


def test_health_not_good_blocks_motion():
    cfg = sim_config()
    a = LidarAssessor(cfg)
    for scan, now in generate("00_clear_room_control"):
        r = a.update(scan, now_mono_ns=now, health={"status": "WARNING", "error_code": 1})
    assert not r.forward_motion_allowed and r.sector("FRONT").status is S.UNKNOWN


def test_hardware_unverified_source_never_allows_motion():
    a = LidarAssessor(sim_config())
    for scan, now in generate("00_clear_room_control"):
        scan.source_mode = SourceMode.HARDWARE_UNVERIFIED
        r = a.update(scan, now_mono_ns=now)
    assert r.sector("FRONT").status is S.CLEAR and not r.forward_motion_allowed
    assert "not stage-C verified" in r.reason


def test_clear_needs_consecutive_confirmation():
    res, _ = run("00_clear_room_control")
    # scan 1: rate unknown (resets the count); scan 2: 1/2 confirming; scan 3: allowed
    assert [r.forward_motion_allowed for r in res] == [False, False, True]


# ---- the scenarios ----------------------------------------------------------
def test_00_control_clear_room():
    res, _ = run("00_clear_room_control")
    assert all(s is S.CLEAR for s in st(res[-1]).values()) and res[-1].forward_motion_allowed


def test_01_empty_looking_room_is_not_clear():
    res, _ = run("01_empty_incomplete_returns")
    r = res[-1]
    assert r.sector("FRONT").status is S.UNKNOWN and not r.forward_motion_allowed
    assert "no return is not clear space" in r.sector("FRONT").reason
    assert r.valid_coverage < 0.5


def test_02_obstacle_ahead():
    r = run("02_obstacle_ahead")[0][-1]
    assert r.sector("FRONT").status is S.BLOCKED and r.sector("REAR").status is S.CLEAR
    assert not r.forward_motion_allowed and r.closest["robot_sector"] == "FRONT"
    assert r.closest["is_person"] is None


def test_03_obstacle_behind_does_not_block_forward():
    r = run("03_obstacle_behind")[0][-1]
    assert r.sector("REAR").status is S.BLOCKED and r.sector("FRONT").status is S.CLEAR
    assert r.forward_motion_allowed       # SIMULATED only; the rover adapter still rejects it


def test_04_obstacle_left():
    r = run("04_obstacle_left")[0][-1]
    assert r.sector("LEFT").status is S.BLOCKED and r.sector("RIGHT").status is S.CLEAR


def test_05_multiple_obstacles():
    r = st(run("05_multiple_obstacles")[0][-1])
    assert r["FRONT"] is S.BLOCKED and r["REAR_LEFT"] in (S.CAUTION, S.BLOCKED) and r["RIGHT"] is S.CAUTION


def test_06_narrow_doorway_reports_jambs():
    r = run("06_narrow_doorway")[0][-1]
    f = r.sector("FRONT")
    assert f.status is S.CLEAR and 1.2 <= f.min_range_m <= 1.35   # jamb, not the far wall
    assert r.sector("FRONT_LEFT").min_range_m < 2.0


def test_07_wall_one_side():
    r = st(run("07_wall_one_side")[0][-1])
    assert r["RIGHT"] is S.BLOCKED and r["LEFT"] is S.CLEAR


def test_08_obstacle_approaching_sequence():
    res, _ = run("08_obstacle_approaching")
    seq = [r.sector("FRONT").status for r in res]
    assert seq[0] is S.CLEAR and S.CAUTION in seq and seq[-1] is S.BLOCKED
    ranges = [r.sector("FRONT").min_range_m for r in res]
    assert ranges == sorted(ranges, reverse=True)
    assert not res[-1].forward_motion_allowed


def test_09_invalid_values_never_become_ranges():
    (r,), _ = run("09_invalid_range_values")
    scan = generate("09_invalid_range_values")[0][0]
    c = scan.status_counts()
    for k in ("NON_FINITE", "BELOW_MIN_RANGE", "BEYOND_MAX_RANGE", "NO_RETURN", "LOW_QUALITY"):
        assert c.get(k, 0) > 0, k
    assert all(x.range_m is None for x in scan.samples if not x.valid)
    assert not r.forward_motion_allowed


def test_10_missing_sectors():
    r = run("10_missing_angular_sectors")[0][-1]
    assert r.sector("FRONT").status is S.UNKNOWN and r.sector("REAR").status is S.UNKNOWN
    assert not r.forward_motion_allowed


def test_11_partial_scan():
    (r,), _ = run("11_partial_scan")
    assert r.completion == ScanCompletion.PARTIAL.value
    assert all(s.status in (S.UNKNOWN, S.BLOCKED) for s in r.sectors) and not r.forward_motion_allowed


def test_15_incorrect_orientation_is_detectable_and_dangerous():
    good = run("02_obstacle_ahead")[0][-1]
    cfg = sim_config()
    cfg.mount.forward_offset_deg = 0.0           # "sensor 0 = forward" assumption: WRONG for this mount
    bad = run("15_incorrect_orientation", cfg)[0][-1]
    assert good.sector("FRONT").status is S.BLOCKED
    assert bad.sector("FRONT").status is not S.BLOCKED and bad.sector("REAR").status is S.BLOCKED
    # Hence: no default offset exists, and an unverified offset gives UNKNOWN (test above).
    assert MountConfig().forward_offset_deg is None


def test_16_unexpected_scan_frequency():
    r = run("16_unexpected_scan_frequency")[0][-1]
    assert r.scan_rate_hz == pytest.approx(4.0) and not r.forward_motion_allowed and "outside" in r.reason


def test_17_reflective_transparent():
    r = run("17_reflective_transparent")[0][-1]
    assert r.sector("FRONT").status is S.UNKNOWN          # glass: no return -> UNKNOWN, never clear
    assert r.sector("RIGHT").status is S.UNKNOWN          # dark: low quality -> UNKNOWN
    # A mirror gives phantom far returns: indistinguishable in one scan (documented limitation).
    assert r.sector("LEFT").status is S.CLEAR
    assert not r.forward_motion_allowed


def test_18_moving_robot_stationary_obstacle_tracks():
    from lidar.tracking import VisualTracker
    tr = VisualTracker()
    ids = []
    for scan, _ in generate("18_moving_robot_stationary_obstacle"):
        tracks = tr.update(scan)
        near = min(tracks, key=lambda t: t.cluster.range_m)
        ids.append(near.track_id)
    assert len(set(ids)) == 1                              # same blob, frame to frame
    d = tr.to_dict()
    assert d["use"].startswith("VISUALIZATION_ONLY") and all(t["is_person"] is None for t in d["tracks"])


def test_20_unsafe_forward_clearance():
    r = run("20_unsafe_forward_clearance")[0][-1]
    assert r.sector("FRONT_LEFT").status is S.BLOCKED and r.sector("FRONT").status is S.UNKNOWN
    assert not r.forward_motion_allowed


def test_every_scenario_is_simulated_and_deterministic():
    for name in SCENARIOS:
        a, b = generate(name), generate(name)
        for (s1, _), (s2, _) in zip(a, b):
            assert s1.source_mode is SourceMode.SIMULATED and s1.provenance["label"] == "SIMULATED"
            assert [(x.angle_deg, x.distance_m) for x in s1.samples] == [(x.angle_deg, x.distance_m) for x in s2.samples]


def test_no_scenario_ever_reports_a_person_distance():
    for name in SCENARIOS:
        for r in run(name)[0]:
            d = r.to_dict()
            assert d["person_distance_m"] is None and "NOT a distance to a person" in d["range_semantics"]


# ---- committed fixtures ----------------------------------------------------
def test_committed_fixtures_match_current_processing():
    files = sorted(glob.glob(os.path.join(FIX, "[0-9][0-9]_*.json")))
    assert len(files) == len(SCENARIOS)
    for f in files:
        name = os.path.basename(f)[:-5]
        cfg = sim_config()
        if name == "15_incorrect_orientation":
            cfg.mount.forward_offset_deg = 0.0
        a = LidarAssessor(cfg)
        for scan, now, exp in load_fixture(f, cfg):
            r = a.update(scan, now_mono_ns=now)
            assert r.forward_motion_allowed == exp["forward_motion_allowed"], name
            assert {s.name: s.status.value for s in r.sectors} == exp["sectors"], name


def test_fixture_spoofing_refused(tmp_path):
    src = os.path.join(FIX, "02_obstacle_ahead.json")
    doc = json.load(open(src))
    for mutate in (lambda d: d.update(label="HARDWARE"), lambda d: d.update(source_mode="HARDWARE_VERIFIED"),
                   lambda d: d["frames"][0]["scan"].update(source_mode="HARDWARE_VERIFIED")):
        d = copy.deepcopy(doc)
        mutate(d)
        p = tmp_path / "forged.json"
        p.write_text(json.dumps(d))
        with pytest.raises(ValueError):
            load_fixture(str(p))


def test_world_cast_geometry_front_box_distance():
    import random
    w = World(room() + box(1.0, 0.0, 0.4, 0.1))
    pts = cast(w, random.Random(0), n=720, angle_jitter_deg=0.0)
    cfg = sim_config()
    scan = make_scan(pts, 1, 1_000_000_000, cfg)
    f = next(s for s in analyze_sectors(scan, cfg) if s.name == "FRONT")
    assert f.min_range_m == pytest.approx(0.95, abs=0.02)   # box face at x = 1.0 - 0.05
    assert SIM_MOUNT.robot_bearing(180.0) == 0.0

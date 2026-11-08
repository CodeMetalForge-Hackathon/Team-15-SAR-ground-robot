import math

import numpy as np
import pytest

from camera_mapping.assess import BLOCKED, CAUTION, CLEAR, STATUS_UNKNOWN, assess, suggest_route
from camera_mapping.detector import ObjectDetection
from camera_mapping.distance import ESTIMATED, estimate_all
from camera_mapping.local_map import FREE, OCCUPIED, UNKNOWN, LocalMap
from camera_mapping.pipeline import PerceptionPipeline, stale_view
from camera_mapping.tests.helpers import cfg, floor_box
from camera_mapping.tracking import CONFIRMED, COASTING, TENTATIVE, Tracker


def run(pipe, t0, frames, dets_fn, dt=0.2):
    st = None
    for k in range(frames):
        st = pipe.process(t0 + k * dt, dets_fn(k))
    return st


# ---- object tracking & temporal filtering --------------------------------------------------
def test_duplicate_frames_are_one_track():
    c = cfg()
    tr = Tracker()
    d = floor_box(c, "chair", 1.2)
    for k in range(10):
        tracks = tr.update(100 + k * 0.2, [d], estimate_all([d], c))
    assert len(tracks) == 1 and tracks[0].hits == 10 and tracks[0].state == CONFIRMED


def test_track_confirmation_and_coasting_and_expiry():
    c = cfg()
    tr = Tracker(confirm_hits=2, expire_s=1.0)
    d = floor_box(c, "chair", 1.2)
    t = tr.update(0.0, [d], estimate_all([d], c))
    assert t[0].state == TENTATIVE
    t = tr.update(0.2, [d], estimate_all([d], c))
    assert t[0].state == CONFIRMED
    t = tr.update(0.4, [], [])
    assert t[0].state == COASTING
    assert tr.update(1.5, [], []) == []        # expired: stale observation dropped


def test_different_class_is_a_new_track():
    c = cfg()
    tr = Tracker()
    a = floor_box(c, "chair", 1.2)
    b = ObjectDetection("person", a.bbox, 0.9)
    tr.update(0, [a], estimate_all([a], c))
    tracks = tr.update(0.2, [b], estimate_all([b], c))
    assert len(tracks) == 2


def test_single_frame_jump_is_rejected_then_persistent_change_accepted():
    c = cfg()
    tr = Tracker(jump_persist=3)
    d = floor_box(c, "chair", 1.2)
    ests = estimate_all([d], c)
    for k in range(5):
        tr.update(k * 0.2, [d], ests)
    track = list(tr.tracks.values())[0]
    jumped = estimate_all([d], c)[0]
    jumped.distance_m = 3.0                     # one bad estimate on the same box
    tr.update(1.0, [d], [jumped])
    assert track.filtered()[0] == pytest.approx(1.2, rel=1e-6) and track.rejected_jumps == 1
    tr.update(1.2, [d], [jumped])
    tr.update(1.4, [d], [jumped])               # third in a row: genuine scene change
    assert track.filtered()[0] == pytest.approx(3.0)


def test_unknown_estimates_do_not_poison_filter():
    c = cfg(measured=False)
    tr = Tracker()
    d = ObjectDetection("chair", [600, 500, 100, 219], 0.9)
    tr.update(0, [d], estimate_all([d], c))
    assert list(tr.tracks.values())[0].filtered() is None


# ---- map coordinates, FOV, occlusion, staleness ---------------------------------------------
def test_map_cell_coordinates():
    lm = LocalMap(cfg())
    assert lm.cell(0.05, 0.0) == (0, 20)
    assert lm.cell(1.05, 1.95) == (10, 0)          # far left column
    assert lm.cell(1.05, -1.95) == (10, 39)
    assert lm.cell(-0.1, 0) is None and lm.cell(5.0, 0) is None
    i, j = lm.cell(1.25, -0.55)
    assert lm.X[i, j] == pytest.approx(1.25) and lm.Y[i, j] == pytest.approx(-0.55)


def test_empty_scene_unmeasured_mount_never_free():
    p = PerceptionPipeline(cfg(measured=False), source_mode="SYNTHETIC")
    st = run(p, 0, 3, lambda k: [])
    assert st["map"]["counts"]["FREE"] == 0
    assert st["assessment"]["status"] == STATUS_UNKNOWN
    assert st["route"]["status"] != "DIRECT_ROUTE_OBSERVED_FREE"


def test_empty_scene_measured_mount_free_only_inside_fov():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    st = run(p, 0, 3, lambda k: [])
    lm = p.map
    half = math.radians(c.camera.hfov_deg) / 2
    assert (lm.state[np.abs(lm.B) > half + 0.02] == UNKNOWN).all()        # outside FOV
    assert (lm.state[lm.X < lm.blind_zone_m() - 0.05] == UNKNOWN).all()    # blind zone
    assert (lm.state[lm.R > lm.free_max_m + 0.05] == UNKNOWN).all()        # beyond free range
    assert st["assessment"]["status"] == CLEAR
    assert st["route"]["status"] == "DIRECT_ROUTE_OBSERVED_FREE"


def test_obstacle_is_occupied_and_shadow_stays_unknown():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    run(p, 0, 3, lambda k: [floor_box(c, "chair", 1.2)])
    lm = p.map
    assert lm.state[lm.cell(1.25, 0.0)] == OCCUPIED
    assert lm.state[lm.cell(2.5, 0.0)] == UNKNOWN           # behind the chair: not assumed clear
    assert lm.state[lm.cell(0.55, 0.0)] == FREE             # in front of its 2-sigma band


def test_unknown_range_detection_blocks_free_marking_in_its_wedge():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    tv = floor_box(c, "tv", 1.5, h_m=0.5, w_m=0.6)          # range UNKNOWN (not a floor class)
    st = run(p, 0, 3, lambda k: [tv])
    assert p.map.state[p.map.cell(1.0, 0.0)] == UNKNOWN
    assert st["assessment"]["status"] == STATUS_UNKNOWN
    assert any("range UNKNOWN" in r for r in st["assessment"]["reasons"])


def test_free_space_expires_without_new_observations():
    c = cfg()
    lm = LocalMap(c, free_ttl_s=1.0)
    lm.update(0.0, [])
    assert lm.counts()["FREE"] > 0
    # an update that cannot observe anything (e.g. mount flagged unmeasured) lets old FREE expire
    c.mount.measured = False
    lm.update(2.0, [])
    assert lm.counts()["FREE"] == 0


def test_robot_motion_without_pose_resets_map():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    run(p, 0, 3, lambda k: [floor_box(c, "chair", 1.2)])
    p.process(1.0, [], robot_moving=True)
    assert p.map.resets == 1


# ---- assessment ----------------------------------------------------------------------------
def test_in_corridor_obstacle_blocks():
    c = cfg()
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3, lambda k: [floor_box(c, "chair", 1.2)])
    assert st["assessment"]["status"] == BLOCKED
    assert st["assessment"]["blocking_track_ids"] == [1]
    assert st["objects"][0]["corridor_position"] == "IN_CORRIDOR"


def test_far_obstacle_beyond_lookahead_is_not_blocked():
    c = cfg()
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3, lambda k: [floor_box(c, "chair", 2.8)])
    assert st["assessment"]["status"] != BLOCKED


def test_side_obstacle_outside_corridor_is_not_blocking():
    c = cfg()
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3,
             lambda k: [floor_box(c, "chair", 1.5, y_m=0.55, w_m=0.3)])
    assert st["assessment"]["status"] in (CLEAR, STATUS_UNKNOWN, CAUTION)
    assert st["assessment"]["status"] != BLOCKED
    assert st["objects"][0]["corridor_position"] == "LEFT_OF_CORRIDOR"


def test_edge_obstacle_is_caution():
    c = cfg()
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3,
             lambda k: [floor_box(c, "chair", 1.3, y_m=0.40, w_m=0.3)])
    assert st["assessment"]["status"] == CAUTION


def test_bottom_cut_box_in_corridor_is_blocked_by_upper_bound():
    c = cfg()
    near = ObjectDetection("chair", [520, 380, 240, 339], 0.9)
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3, lambda k: [near])
    assert st["assessment"]["status"] == BLOCKED
    assert any("nearer than" in r for r in st["assessment"]["reasons"])


def test_tentative_single_frame_detection_never_clear():
    c = cfg()
    st = PerceptionPipeline(c, source_mode="SYNTHETIC").process(0.0, [floor_box(c, "chair", 1.2)])
    assert st["assessment"]["status"] != CLEAR
    assert st["objects"][0]["validity"] == "TENTATIVE"


# ---- route suggestions -----------------------------------------------------------------------
def test_alternate_route_avoids_obstacle_and_never_enters_occupied():
    c = cfg()
    c.lookahead_m = 1.5
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    st = run(p, 0, 3, lambda k: [floor_box(c, "chair", 2.0, y_m=0.05, w_m=0.25)])
    rt = st["route"]
    assert rt["advisory"] is True and rt["validated_for_driving"] is False
    assert rt["status"] in ("ALTERNATE_ROUTE_OBSERVED_FREE", "ROUTE_THROUGH_UNOBSERVED_SPACE")
    for x, y in rt["waypoints"]:
        cell = p.map.cell(x, y)
        assert p.map.state[cell] != OCCUPIED


def test_route_needs_observation_when_only_unknown_detour():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    st = run(p, 0, 3, lambda k: [floor_box(c, "chair", 1.0, w_m=0.6)])
    rt = st["route"]
    assert rt["status"] in ("ROUTE_THROUGH_UNOBSERVED_SPACE", "NO_SUPPORTED_ROUTE")
    if rt["status"] == "ROUTE_THROUGH_UNOBSERVED_SPACE":
        assert rt["through_unknown_cells"] > 0
        assert any("UNKNOWN" in cv for cv in rt["caveats"])


def test_clear_route_is_direct():
    c = cfg()
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3, lambda k: [])
    assert st["route"]["mode"] == "DIRECT" and st["route"]["validated_for_driving"] is False


# ---- pipeline records, provenance, scene change, disconnect -------------------------------
REQUIRED = {"object_class", "bbox", "detection_confidence", "distance", "distance_method",
            "uncertainty_m", "corridor_position", "timestamp", "data_source", "validity", "source_mode"}


def test_record_fields_and_provenance():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="RECORDED", camera_info={"source": "replay"})
    st = run(p, 50, 3, lambda k: [floor_box(c, "chair", 1.2)])
    r = st["objects"][0]
    assert REQUIRED <= set(r)
    assert r["data_source"] == "CAMERA_ESTIMATE" and r["source_mode"] == "RECORDED"
    assert r["distance_method"] == "GROUND_PLANE" and r["uncertainty_m"] > 0
    assert st["motion_authority"] == "NONE" and st["camera"]["source"] == "replay"
    assert "box" in st["unsupported_classes"]


def test_empty_scene_has_no_records():
    st = run(PerceptionPipeline(cfg(), source_mode="SYNTHETIC"), 0, 2, lambda k: [])
    assert st["objects"] == [] and st["persons"] == []


def test_scene_change_removes_old_obstacle_after_expiry():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    run(p, 0, 3, lambda k: [floor_box(c, "chair", 1.2)])
    st = run(p, 1.0, 15, lambda k: [])     # 3 s of empty frames > expire_s
    assert st["objects"] == [] and st["assessment"]["status"] == CLEAR


def test_camera_disconnect_degrades_to_unknown():
    c = cfg()
    st = run(PerceptionPipeline(c, source_mode="LIVE-HW"), 0, 3, lambda k: [])
    st["rx_time"] = 100.0
    assert stale_view(st, 100.5)["assessment"]["status"] == CLEAR
    v = stale_view(st, 105.0)
    assert v["status"] == "STALE" and v["assessment"]["status"] == "UNKNOWN"
    assert v["route"]["waypoints"] == []
    assert stale_view(None, 0)["status"] == "NO_DATA"


def test_false_positive_low_score_is_filtered_by_detector_thresholds():
    from camera_mapping.detector import TorchObstacleDetector
    d = TorchObstacleDetector.__new__(TorchObstacleDetector)
    d.categories = ["__background__", "person"] + ["x"] * 60 + ["chair"]
    d.categories[62] = "chair"
    d.thresholds, d.obstacle_thresh, d.name = {"person": 0.6}, 0.5, "t"
    boxes = np.array([[0, 0, 10, 10], [0, 0, 10, 10], [0, 0, 10, 10], [0, 0, 10, 10]], float)
    out = d.filter(boxes, np.array([1, 1, 62, 5]), np.array([0.55, 0.9, 0.45, 0.99]))
    assert [(o.label, o.score) for o in out] == [("person", 0.9)]


def test_no_route_when_mount_unmeasured():
    c = cfg(measured=False)
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3, lambda k: [floor_box(cfg(), "person", 2.0, h_m=0.4, w_m=1.2)])
    assert st["route"]["status"] == "NO_SUPPORTED_ROUTE" and st["route"]["waypoints"] == []


def test_route_never_crosses_unknown_range_wedge():
    import math as _m
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    tv = floor_box(c, "tv", 1.5, h_m=0.5, w_m=0.4)       # range UNKNOWN
    st = run(p, 0, 3, lambda k: [tv])
    fp = p.map.footprints[0]
    for x, y in st["route"]["waypoints"]:
        b = _m.atan2(y, x)
        assert not (fp.bearing_lo <= b <= fp.bearing_hi) or x < 0.2


def test_corridor_position_matches_assessment_for_unknown_range():
    c = cfg()
    tv = floor_box(c, "tv", 1.5, y_m=0.12, h_m=0.5, w_m=0.4)
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3, lambda k: [tv])
    in_reason = any("in corridor bearing" in r for r in st["assessment"]["reasons"])
    assert in_reason == (st["objects"][0]["corridor_position"] == "IN_CORRIDOR_BEARING")


# ---- review regressions (PR #16 review) -------------------------------------------------------
def test_tracked_obstacle_cut_by_frame_bottom_is_never_clear():
    c = cfg()
    c.lookahead_m, c.stop_distance_m = 0.6, 0.3
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    far = floor_box(c, "chair", 1.5)
    run(p, 0, 4, lambda k: [far])
    x, y, w, h = far.bbox
    near = ObjectDetection("chair", [x - 100, 300, w + 200, 720 - 300], 0.9)   # now fills the bottom
    st = run(p, 1.0, 3, lambda k: [near])
    near_rec = [o for o in st["objects"] if o["bbox"][1] + o["bbox"][3] >= 716]
    assert near_rec and near_rec[0]["distance"]["status"] == "UNKNOWN"
    assert near_rec[0]["distance"]["upper_bound_m"] is not None
    assert st["assessment"]["status"] == BLOCKED
    assert p.map.state[p.map.cell(0.45, 0.0)] != FREE


def test_space_behind_new_obstacle_loses_old_free_immediately():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    run(p, 0, 3, lambda k: [])                                   # all FREE before
    st = p.process(1.0, [floor_box(c, "chair", 1.0)])            # first, tentative frame
    assert st["assessment"]["status"] != CLEAR
    st = run(p, 1.2, 3, lambda k: [floor_box(c, "chair", 1.0)])  # confirmed
    lm = p.map
    fp = lm.footprints[0]
    behind = (lm.B >= fp.bearing_lo) & (lm.B <= fp.bearing_hi) & (lm.X > fp.x_far)
    assert behind.any() and not (lm.state[behind] == FREE).any()


def test_stale_view_draws_no_free_or_occupied_cells():
    c = cfg()
    st = run(PerceptionPipeline(c, source_mode="LIVE-HW"), 0, 3, lambda k: [floor_box(c, "chair", 1.2)])
    st["rx_time"] = 0.0
    v = stale_view(st, 10.0)
    assert all(set(r) == {"U"} for r in v["map"]["rows"]) and v["map"]["footprints"] == []


def test_supported_route_found_around_side_obstacle():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    st = run(p, 0, 3, lambda k: [floor_box(c, "chair", 1.5, y_m=0.3, w_m=0.4)])
    assert st["assessment"]["status"] == BLOCKED
    rt = st["route"]
    assert rt["mode"] == "SUPPORTED" and rt["status"] == "ALTERNATE_ROUTE_OBSERVED_FREE", rt
    assert rt["through_unknown_cells"] == 0 and rt["side"] == "RIGHT"
    for x, y in rt["waypoints"]:
        assert p.map.state[p.map.cell(x, y)] != OCCUPIED


def test_motion_reset_clears_track_histories():
    c = cfg()
    p = PerceptionPipeline(c, source_mode="SYNTHETIC")
    run(p, 0, 3, lambda k: [floor_box(c, "chair", 1.2)])
    p.process(1.0, [], robot_moving=True)
    assert all(not t.history for t in p.tracker.tracks.values())


def test_three_methods_fuse_only_if_all_agree():
    from camera_mapping.distance import MethodResult, fuse
    a = MethodResult("A", ESTIMATED, 2.0, 0.2, 0.0)
    b = MethodResult("B", ESTIMATED, 2.1, 0.2, 0.0)
    good = MethodResult("C", ESTIMATED, 2.05, 0.3, None)
    bad = MethodResult("C", ESTIMATED, 4.0, 0.3, None)
    assert fuse([a, b, good])[3] == "FUSED(A+B+C)"
    assert fuse([a, b, bad])[0] is None


def test_setback_extends_corridor_from_robot_front():
    c = cfg()
    c.mount.setback_m = 0.0
    c.stop_distance_m, c.lookahead_m = 0.0, 0.5
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3, lambda k: [floor_box(c, "chair", 1.6)])
    assert st["assessment"]["status"] != BLOCKED
    c.mount.setback_m = 1.2           # lens far behind the front: same chair is now within lookahead
    st = run(PerceptionPipeline(c, source_mode="SYNTHETIC"), 0, 3, lambda k: [floor_box(c, "chair", 1.6)])
    assert st["assessment"]["status"] == BLOCKED

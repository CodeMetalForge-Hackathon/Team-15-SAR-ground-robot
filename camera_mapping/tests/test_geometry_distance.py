import math

import pytest

from camera_mapping import geometry as G
from camera_mapping.config import (CameraModel, MountGeometry, PerceptionConfig, load_config,
                                   nominal_imx708_fx, save_config)
from camera_mapping.detector import ObjectDetection
from camera_mapping.distance import (ESTIMATED, REJECTED, UNKNOWN, MethodResult, estimate,
                                     estimate_all, fuse, ground_plane, known_height)
from camera_mapping.tests.helpers import cfg, floor_box


# ---- camera calibration logic --------------------------------------------------------------
def test_nominal_imx708_intrinsics_from_measured_crop():
    c = CameraModel()
    assert c.fx == pytest.approx(1410.71, abs=0.05)
    assert c.hfov_deg == pytest.approx(48.8, abs=0.1)
    assert c.vfov_deg == pytest.approx(28.6, abs=0.1)
    assert c.source == "NOMINAL_DATASHEET"
    # full-sensor crop would be a wider lens: proves the crop matters
    assert nominal_imx708_fx(1280, 4608) < c.fx


def test_scaled_camera_keeps_fov():
    c = CameraModel().scaled(640, 360)
    assert c.fx == pytest.approx(705.36, abs=0.05)
    assert c.hfov_deg == pytest.approx(CameraModel().hfov_deg, abs=1e-6)


def test_config_roundtrip(tmp_path):
    c = cfg()
    p = tmp_path / "c.json"
    save_config(c, str(p))
    back = load_config(str(p))
    assert back.mount.height_m == c.mount.height_m and back.mount.usable
    assert back.calibration_status == "UNCALIBRATED"


def test_mount_needs_measurement_flag():
    assert not MountGeometry(height_m=0.1, pitch_deg=5).usable
    assert MountGeometry(height_m=0.1, pitch_deg=5, measured=True).usable
    assert not MountGeometry(height_m=None, pitch_deg=5, measured=True).usable


def test_shipped_config_is_uncalibrated_and_unmeasured():
    c = load_config("camera_mapping/configs/imx708_robot.json")
    assert c.calibration_status == "UNCALIBRATED"
    assert not c.mount.usable
    assert not c.depth_model_validated


# ---- geometric distance ----------------------------------------------------------------------
@pytest.mark.parametrize("x", [0.5, 1.0, 1.5, 2.0, 3.0])
def test_ground_point_inverts_ground_row(x):
    c = cfg()
    v = G.ground_row(c.camera, x, 0.15, 8.0)
    p = G.ground_point(c.camera, c.camera.cx, v, 0.15, 8.0)
    assert p[0] == pytest.approx(x, rel=1e-9)
    assert p[1] == pytest.approx(0.0, abs=1e-9)


def test_rays_above_horizon_never_hit_floor():
    c = cfg()
    hz = G.horizon_row(c.camera, 8.0)
    assert G.ground_point(c.camera, 640, hz - 5, 0.15, 8.0) is None
    assert G.ground_point(c.camera, 640, hz + 5, 0.15, 8.0) is not None


def test_lateral_sign_left_is_positive():
    c = cfg()
    v = G.ground_row(c.camera, 1.0, 0.15, 8.0)
    left = G.ground_point(c.camera, 300, v, 0.15, 8.0)
    right = G.ground_point(c.camera, 1000, v, 0.15, 8.0)
    assert left[1] > 0 > right[1]
    assert G.bearing_rad(c.camera, 300) > 0


def test_blind_zone_positive():
    c = cfg()
    b = G.nearest_visible_floor(c.camera, 0.15, 8.0)
    assert 0.2 < b < 0.6


@pytest.mark.parametrize("x", [0.8, 1.2, 2.0])
def test_ground_plane_recovers_distance_with_uncertainty(x):
    c = cfg()
    r = ground_plane(floor_box(c, "chair", x), c)
    assert r.status == ESTIMATED
    assert r.distance_m == pytest.approx(x, rel=1e-6)
    assert 0 < r.sigma_m < 0.5 * x


def test_uncertainty_grows_with_distance():
    c = cfg()
    s = [ground_plane(floor_box(c, "chair", x), c).sigma_m for x in (0.8, 1.5, 2.5)]
    assert s[0] < s[1] < s[2]


# ---- unknown-depth handling and edge cases -----------------------------------------------------
def test_unmeasured_mount_gives_unknown_ground_plane():
    c = cfg(measured=False)
    r = ground_plane(floor_box(cfg(), "chair", 1.0), c)
    assert r.status == UNKNOWN and r.reason == "MOUNT_UNMEASURED"


def test_box_cut_by_bottom_edge_gives_upper_bound_only():
    c = cfg()
    d = ObjectDetection("chair", [500, 400, 200, 319], 0.9)  # bottom at 719
    r = ground_plane(d, c)
    assert r.status == UNKNOWN and r.reason == "CONTACT_BELOW_FRAME"
    assert r.upper_bound_m is not None and r.upper_bound_m < 0.6


def test_contact_above_horizon_is_unknown():
    c = cfg()
    hz = G.horizon_row(c.camera, 8.0)
    r = ground_plane(ObjectDetection("chair", [600, hz - 100, 80, 95], 0.9), c)
    assert r.status == UNKNOWN and r.reason == "CONTACT_AT_OR_ABOVE_HORIZON"


def test_non_floor_class_never_uses_ground_plane():
    c = cfg()
    b = floor_box(c, "tv", 1.0)
    assert ground_plane(b, c).reason == "CLASS_MAY_NOT_TOUCH_FLOOR"
    assert estimate(b, c).status == UNKNOWN


def test_partial_occlusion_hides_contact_point():
    c = cfg()
    far = floor_box(c, "chair", 2.0)
    near = floor_box(c, "suitcase", 1.0, h_m=0.5, w_m=0.6)   # in front, covers the bottom of far
    r = ground_plane(far, c, [near.bbox])
    assert r.status == UNKNOWN and r.reason == "CONTACT_OCCLUDED"
    # the nearer object itself is not occluded
    assert ground_plane(near, c, [far.bbox]).status == ESTIMATED


def tripod():
    """Camera 1.0 m high, level: a standing adult fits in the 28.6 deg VFOV at 5 m."""
    return PerceptionConfig(mount=MountGeometry(height_m=1.0, pitch_deg=0.0, measured=True))


def test_low_rover_camera_cuts_off_standing_person():
    c = cfg()   # 0.15 m high: head leaves the frame
    assert known_height(floor_box(c, "person", 3.0, h_m=1.70, w_m=0.5), c).reason == "BOX_TRUNCATED_BY_FRAME"


def test_known_height_standing_person():
    t = tripod()
    p = floor_box(t, "person", 5.0, h_m=1.70, w_m=0.5)
    r = known_height(p, cfg(measured=False))
    assert r.status == ESTIMATED
    assert r.distance_m == pytest.approx(5.0, rel=0.01)
    assert r.sigma_m == pytest.approx(5.0 * 0.0916, rel=0.02)


def test_known_height_refuses_seated_or_partial_person():
    c = cfg()
    d = ObjectDetection("person", [500, 200, 300, 300], 0.95)   # aspect 1.0: not upright
    assert known_height(d, c).reason == "NOT_UPRIGHT_OR_PARTLY_HIDDEN"


def test_known_height_refuses_truncated_top():
    c = cfg()
    d = ObjectDetection("person", [600, 0, 100, 400], 0.95)
    assert known_height(d, c).reason == "BOX_TRUNCATED_BY_FRAME"


def test_tiny_box_is_unknown():
    c = cfg()
    assert known_height(ObjectDetection("person", [600, 300, 5, 12], 0.7), c).reason == "BOX_TOO_SMALL"


def test_no_prior_class_is_unknown_for_known_height():
    c = cfg()
    assert known_height(floor_box(c, "suitcase", 1.0, h_m=0.6), c).reason == "NO_HEIGHT_PRIOR_FOR_CLASS"


def test_consistent_methods_fuse_and_reduce_uncertainty():
    c = tripod()
    person = floor_box(c, "person", 5.0, h_m=1.70, w_m=0.5)
    e = estimate(person, c)
    assert e.status == ESTIMATED and e.method.startswith("FUSED")
    gp = ground_plane(person, c)
    assert e.sigma_m < gp.sigma_m
    assert e.distance_m == pytest.approx(5.0, rel=0.02)


def test_inconsistent_methods_are_rejected():
    c = cfg()
    d = floor_box(c, "chair", 1.0, h_m=0.15, w_m=0.1)   # tiny "chair" at 1 m: height prior says ~5.9 m
    e = estimate(d, c)
    assert e.status == REJECTED and "INCONSISTENT" in e.reason
    assert e.distance_m is None


def test_labels_never_claim_verified():
    for measured in (True, False):
        c = cfg(measured=measured)
        for d in (floor_box(cfg(), "chair", 1.2), floor_box(cfg(), "person", 2.5, h_m=1.7, w_m=0.5)):
            j = estimate(d, c).to_json()
            assert "VERIFIED" not in j["label"]
            assert j["kind"] == "CAMERA_ESTIMATE" and j["unit"] == "m"
    c = cfg()
    c.calibration_status = "CALIBRATED"
    assert estimate(floor_box(c, "chair", 1.2), c).to_json()["label"] == "CALIBRATED_ESTIMATE"


def test_unvalidated_depth_is_shown_but_not_fused():
    c = cfg()
    d = floor_box(c, "chair", 1.2)
    mono = MethodResult("MONO_DEPTH", ESTIMATED, 3.0, 0.75, None)
    e = estimate(d, c, depth_result=mono)
    assert e.method == "GROUND_PLANE" and e.distance_m == pytest.approx(1.2, rel=1e-6)
    assert any(m.method == "MONO_DEPTH" for m in e.methods)
    c.depth_model_validated = True
    e2 = estimate(d, c, depth_result=MethodResult("MONO_DEPTH", ESTIMATED, 1.25, 0.3, None))
    assert e2.method.startswith("FUSED") and e2.lateral_m is not None


def test_fuse_with_nothing():
    assert fuse([MethodResult("X", UNKNOWN)])[4] == "NO_METHOD_APPLICABLE"


def test_estimate_all_uses_other_boxes_for_occlusion():
    c = cfg()
    far, near = floor_box(c, "chair", 2.0), floor_box(c, "suitcase", 1.0, h_m=0.5, w_m=0.6)
    e_far, e_near = estimate_all([far, near], c)
    assert e_far.status != ESTIMATED or e_far.method != "GROUND_PLANE"
    assert e_near.status == ESTIMATED

import hashlib
import json
import os
import subprocess

import cv2
import numpy as np
import pytest

from perception.detectors import (FACE_ONLY, PERSON_DETECTOR, Detection,
                                  OpenCVDetectors, best)
from perception.sightings import (SightingGate, ensure_evidence_dir,
                                  inside_git_worktree, make_sighting, save_evidence,
                                  validate_sector)


def feed(gate, pattern, t0=0.0, dt=0.2):
    """pattern: iterable of bools; returns list of times a sighting fired."""
    fired = []
    for i, present in enumerate(pattern):
        t = t0 + i * dt
        if gate.update(t, present):
            fired.append(round(t, 2))
    return fired


def test_needs_consecutive_confirm_frames():
    g = SightingGate(confirm_frames=3, rearm_s=60)
    assert feed(g, [True, False, True, True, False, True]) == []
    g = SightingGate(confirm_frames=3, rearm_s=60)
    assert feed(g, [True, True, True]) == [0.4]


def test_continuous_presence_gives_one_sighting():
    g = SightingGate(confirm_frames=3, rearm_s=60)
    fired = feed(g, [True] * 300)  # 60 s of frames at 5 fps
    assert fired == [0.4]
    assert g.suppressed_total == 297


def test_short_dropouts_and_pose_change_do_not_retrigger():
    # standing -> brief miss while sitting down -> seated/facing away
    g = SightingGate(confirm_frames=3, rearm_s=60)
    pattern = [True] * 50 + [False] * 25 + [True] * 50 + [False] * 10 + [True] * 20
    assert len(feed(g, pattern)) == 1


def test_rearm_after_absence_window():
    g = SightingGate(confirm_frames=3, rearm_s=60)
    assert feed(g, [True] * 5, t0=0) == [0.4]
    assert feed(g, [False] * 10, t0=1.0) == []
    assert feed(g, [True] * 5, t0=30.0) == []          # back within 60 s: same sighting
    assert feed(g, [True] * 5, t0=95.0) == [95.4]      # absent >= 60 s: new sighting


def test_empty_scene_never_fires():
    g = SightingGate()
    assert feed(g, [False] * 300) == []


def test_validate_sector():
    assert validate_sector(" g ") == "G"
    for bad in ("", "AA", "1", "g7"):
        with pytest.raises(ValueError):
            validate_sector(bad)


def _sighting(trigger, dets):
    return make_sighting(drone_id="D1", boot_id="b1794077000", seq=1, sector="G",
                         obs_time=1794077187.9746, frame_ref="/ev/D1-b1794077000-000001.png",
                         frame_sha256="ab" * 32, annotated_ref="/ev/x_annotated.jpg",
                         frame_size=[1920, 1080], trigger=trigger, all_dets=dets,
                         operator="OP1")


def test_sighting_shape_and_labels():
    person = Detection([100, 50, 300, 900], "torchvision_frcnn_r50_fpn_v2_coco", 0.987,
                       "frcnn_class_score", PERSON_DETECTOR)
    face = Detection([200, 80, 120, 120], "opencv_haar_frontalface_default", 5.1,
                     "haar_level_weight", FACE_ONLY)
    s = json.loads(json.dumps(_sighting(person, [person, face])))
    assert s["obs_id"] == "D1-b1794077000-000001"
    assert (s["boot_id"], s["seq"]) == ("b1794077000", 1)
    assert (s["source_mode"], s["platform"]) == ("LIVE-HW", "BENCH")
    assert (s["kind"], s["how"], s["sensor"]) == ("PERSON_VISUAL", "SECTOR_ONLY", "rgb")
    assert (s["cell"], s["cell_source"], s["operator"]) == ("G", "OPERATOR_ASSIGNED", "OP1")
    assert s["obs_time"] == 1794077187.975
    assert s["obs_time_iso"].startswith("2026-11-07T") and s["obs_time_iso"].endswith("+00:00")
    assert s["confidence"] is None
    ev = s["evidence"]
    assert ev["frame_ref"].endswith(".png") and len(ev["frame_sha256"]) == 64
    assert ev["detector_family"] == PERSON_DETECTOR
    assert ev["bbox"] == [100, 50, 300, 900]
    assert ev["count_in_frame"] == 1
    fams = [d["family"] for d in ev["detections_in_frame"]]
    assert fams == [PERSON_DETECTOR, FACE_ONLY]  # face stays labeled separately


def test_best_filters_by_family():
    a = Detection([0, 0, 1, 1], "x", 0.7, "k", PERSON_DETECTOR)
    b = Detection([0, 0, 1, 1], "y", 9.0, "k", FACE_ONLY)
    assert best([a, b], PERSON_DETECTOR) is a
    assert best([b], PERSON_DETECTOR) is None


def test_evidence_dir_refused_inside_git(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert inside_git_worktree(str(repo / "evidence" / "new"))
    with pytest.raises(ValueError):
        ensure_evidence_dir(str(repo / "evidence"))
    outside = tmp_path / "outside" / "ev"
    assert ensure_evidence_dir(str(outside)) == str(outside)
    assert outside.is_dir()


def test_save_evidence_is_exact_frame(tmp_path):
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, (120, 160, 3), dtype=np.uint8)
    raw, sha, ann = save_evidence(str(tmp_path), "D1-b1-000001", frame, frame.copy())
    assert np.array_equal(cv2.imread(raw), frame)  # lossless: exact pixels
    assert sha == hashlib.sha256(open(raw, "rb").read()).hexdigest()
    assert os.path.exists(ann)


def test_opencv_detectors_blank_frames():
    d = OpenCVDetectors()
    for val in (0, 128, 255):
        assert d.detect_all(np.full((480, 640, 3), val, np.uint8)) == []


def _weights_cached():
    p = os.path.expanduser("~/.cache/torch/hub/checkpoints")
    return os.path.isdir(p) and any(f.startswith("fasterrcnn_mobilenet_v3_large_fpn")
                                    for f in os.listdir(p))


@pytest.mark.skipif(not _weights_cached(), reason="torchvision weights not cached")
def test_person_detector_blank_frames():
    pytest.importorskip("torch")  # CI installs OpenCV only
    from perception.detectors import TorchPersonDetector
    d = TorchPersonDetector("frcnn_mbv3_fpn", device="cpu")
    for val in (0, 128, 255):
        assert d.detect_all(np.full((360, 640, 3), val, np.uint8)) == []


def test_small_boxes_never_trigger():
    from perception.live_camera import select_trigger
    refl = Detection([573, 711, 78, 82], "frcnn", 0.99, "k", PERSON_DETECTOR)
    real = Detection([842, 512, 196, 565], "frcnn", 0.95, "k", PERSON_DETECTOR)
    face = Detection([10, 10, 300, 300], "haar", 5.0, "k", FACE_ONLY)
    h = 0.15 * 1080
    assert select_trigger([refl], (PERSON_DETECTOR,), h) is None
    assert select_trigger([refl, real], (PERSON_DETECTOR,), h) is real
    assert select_trigger([face], (PERSON_DETECTOR,), h) is None  # face never triggers by default
    assert select_trigger([face], (PERSON_DETECTOR, FACE_ONLY), h) is face

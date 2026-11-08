"""perception.live_test: consent gate and countdown (no camera, no Pi, no SSH)."""
import json

import pytest

from perception import live_test as lt

BASE = ["--pi-host", "pi.invalid", "--duration-s", "5"]


def _scene_must_not_run(*a, **k):
    raise AssertionError("camera scene started")


@pytest.fixture(autouse=True)
def no_ssh(monkeypatch):
    # health sampling would SSH to the Pi; return a healthy sample instead
    monkeypatch.setattr(lt.HealthMonitor, "sample",
                        lambda self: {"temp_c": 50.0, "throttled": "0x0"})


@pytest.mark.parametrize("scene,consent,refused", [
    ("person", "no-people", True),
    ("empty", "no-people", False),
    ("object", "no-people", False),
    ("person", "all-consented", False),
])
def test_consent_gate(scene, consent, refused):
    assert (lt.check_consent(scene, consent) is not None) is refused


def test_person_scene_refused_without_consent_never_prompts(tmp_path):
    def prompt(_):
        raise AssertionError("must not ask to start")
    rc = lt.main(["--scene", "person", "--consent", "no-people", "--out-dir",
                  str(tmp_path), *BASE], prompt=prompt, scene_runner=_scene_must_not_run)
    assert rc == lt.EXIT_REFUSED
    assert list(tmp_path.iterdir()) == []


def test_countdown_shorter_than_10s_refused(tmp_path):
    rc = lt.main(["--scene", "empty", "--consent", "no-people", "--countdown-s", "3",
                  "--out-dir", str(tmp_path), *BASE], prompt=lambda m: "",
                 scene_runner=_scene_must_not_run)
    assert rc == lt.EXIT_REFUSED


def test_cancel_at_start_prompt_keeps_camera_off(tmp_path):
    def prompt(_):
        raise KeyboardInterrupt
    rc = lt.main(["--scene", "empty", "--consent", "no-people", "--out-dir",
                  str(tmp_path), *BASE], prompt=prompt, scene_runner=_scene_must_not_run)
    assert rc == lt.EXIT_CANCELLED and list(tmp_path.iterdir()) == []


def test_cancel_during_countdown_keeps_camera_off(tmp_path, capsys):
    ticks = []

    def sleep(_):
        ticks.append(1)
        if len(ticks) == 4:
            raise KeyboardInterrupt
    rc = lt.main(["--scene", "object", "--consent", "no-people", "--out-dir",
                  str(tmp_path), *BASE], prompt=lambda m: "", sleep=sleep,
                 scene_runner=_scene_must_not_run)
    assert rc == lt.EXIT_CANCELLED
    assert list(tmp_path.iterdir()) == []          # nothing saved
    err = capsys.readouterr().err
    assert "starting in 10 s" in err and "starting in  7 s" in err
    assert "camera ON" not in err and "CANCELLED" in err


def test_scene_starts_only_after_full_countdown(tmp_path, capsys):
    events = []

    def sleep(_):
        events.append("tick")

    def runner(a, run_dir, mon):
        events.append("scene")
        return {"frames": 3}
    rc = lt.main(["--scene", "empty", "--consent", "no-people", "--out-dir",
                  str(tmp_path), *BASE], prompt=lambda m: events.append("start") or "",
                 sleep=sleep, scene_runner=runner)
    assert rc == lt.EXIT_OK
    assert events == ["start"] + ["tick"] * 10 + ["scene"]
    (run_dir,) = tmp_path.iterdir()
    rep = json.loads((run_dir / "run_report.json").read_text())
    assert rep["scene"] == "empty" and rep["countdown_s"] == 10
    assert rep["sector_source"].startswith("OPERATOR_ASSIGNED")
    assert (run_dir / "pi_health.jsonl").exists()


def test_health_breach_and_parse():
    h = lt.parse_health("temp=49.4'C\nthrottled=0x0\n     EXT5V_V volt(24)=5.26352000V\n"
                        "mem_used_mb=799\n")
    assert h == {"temp_c": 49.4, "throttled": "0x0", "ext5v_v": 5.264, "mem_used_mb": 799}
    assert lt.health_breach(h) is None
    assert "throttling" in lt.health_breach({**h, "throttled": "0x50005"})
    assert "temperature" in lt.health_breach({**h, "temp_c": 81.0})


def test_object_frame_withheld_if_person_without_consent():
    dets = [{"label": "chair", "score": 0.9, "bbox": [0, 0, 1, 1]},
            {"label": "person", "score": 0.8, "bbox": [0, 0, 1, 1]}]
    assert lt.withhold_reason(dets, "no-people")
    assert lt.withhold_reason(dets, "all-consented") is None
    assert lt.withhold_reason(dets[:1], "no-people") is None


# -- consent enforcement: empty/object scenes store no person image ------------
def _ns(scene):
    import argparse
    return argparse.Namespace(scene=scene, pi_host="h", pi_user=None, pi_key=None,
                              pi_rotation=180, sector="G", operator="op", duration_s=20.0)


def test_empty_scene_pipeline_cannot_raise_sightings_or_save_images():
    cmd = lt.person_pipeline_cmd(_ns("empty"), "/tmp/x")
    i = cmd.index("--min-box-frac")
    assert float(cmd[i + 1]) > 1.0              # no box can reach the trigger height
    assert "--min-box-frac" not in lt.person_pipeline_cmd(_ns("person"), "/tmp/x")


def test_empty_scene_min_box_frac_blocks_every_possible_box():
    from perception.detectors import PERSON_DETECTOR, Detection
    from perception.live_camera import select_trigger
    h = 720
    full = Detection([0, 0, 1280, h], "frcnn", 1.0, "k", PERSON_DETECTOR)
    assert select_trigger([full], [PERSON_DETECTOR],
                          float(lt.EMPTY_SCENE_NO_SAVE_MIN_BOX_FRAC) * h) is None
    assert select_trigger([full], [PERSON_DETECTOR], 0.15 * h) is full


def test_empty_scene_false_detections_counted_from_log(tmp_path):
    def row(t, boxes):
        return {"t": t, "all": [{"family": "PERSON_DETECTOR", "bbox": b, "score": s}
                                for b, s in boxes]}
    big, small = ([0, 0, 50, 200], 0.97), ([0, 0, 20, 60], 0.71)
    rows = [row(0.0, []), row(0.2, [small]), row(0.4, [big]), row(0.6, [big]),
            row(0.8, [big]), row(1.0, [big]), row(1.2, [])]
    p = tmp_path / "f.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    r = lt.empty_scene_analysis(str(p), frame_h=720)
    assert r == {"frames": 7, "frames_with_person_box": 5,
                 "frames_with_trigger_size_person_box": 4,
                 "false_sightings_pipeline_would_raise": 1,
                 "max_person_score": 0.97, "images_saved": 0}


def test_object_scene_withholds_any_returned_person_box():
    dets = [{"label": "chair", "score": 0.9, "bbox": [0, 0, 1, 1]},
            {"label": "person", "score": lt.OBJECT_THRESH, "bbox": [0, 0, 1, 1]}]
    assert lt.withhold_reason(dets, "no-people")


# -- person scene: consent confirmed at capture time ---------------------------
@pytest.mark.parametrize("answer,ok", [("YES", True), ("yes\n", True), ("", False), ("\n", False),
                                       ("y", False), ("no", False)])
def test_person_scene_needs_typed_yes(tmp_path, answer, ok):
    ran = []
    rc = lt.main(["--scene", "person", "--consent", "all-consented", "--out-dir",
                  str(tmp_path), *BASE], prompt=lambda m: answer, sleep=lambda s: None,
                 scene_runner=lambda a, d, m: ran.append(1) or {"sightings": [1]})
    assert (rc == lt.EXIT_OK) is ok and bool(ran) is ok
    if not ok:
        assert rc == lt.EXIT_CANCELLED and list(tmp_path.iterdir()) == []
    else:
        (run_dir,) = tmp_path.iterdir()
        assert json.loads((run_dir / "run_report.json").read_text())["consent_confirmed_at"]


def test_person_prompt_mentions_background_and_local_only(tmp_path):
    seen = []
    lt.main(["--scene", "person", "--consent", "all-consented", "--out-dir", str(tmp_path),
             *BASE], prompt=lambda m: seen.append(m) or "no", scene_runner=_scene_must_not_run)
    assert "background" in seen[0] and "local Team-15 test dashboard" in seen[0]


def test_person_scene_analysis(tmp_path):
    def row(t, score, bbox=(10, 20, 30, 200)):
        b = {"score": score, "bbox": list(bbox)} if score else None
        return {"t": t, "best": {"PERSON_DETECTOR": b},
                "counts": {"PERSON_DETECTOR": int(bool(b)), "FULL_BODY_HOG": 0},
                "detect_s": {"torchvision_frcnn_r50_fpn_v2_coco": 0.19, "opencv": 0.01}}
    rows = [row(0.0, 0.99), row(0.2, None), row(0.4, 0.97, (12, 20, 30, 210)), row(0.6, 0.98)]
    p = tmp_path / "f.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    r = lt.person_scene_analysis(str(p), [{"obs_time": 0.6}])
    assert r["person_frames"] == 3 and r["missed_frames"] == 1
    assert r["score_min_median_max"] == [0.97, 0.98, 0.99]
    assert r["bbox_range"]["x"] == [10, 12] and r["bbox_range"]["h"] == [200, 210]
    assert r["frcnn_s_median_max"] == [0.19, 0.19] and r["detect_s_total_median_max"] == [0.2, 0.2]
    assert r["first_person_frame_to_sighting_s"] == 0.6


def test_extra_box_on_same_person_is_not_a_second_person():
    main = {"score": 0.99, "bbox": [76, 290, 1076, 195]}
    strip = {"score": 0.65, "bbox": [584, 305, 171, 41]}       # inside the main box
    other = {"score": 0.98, "bbox": [0, 211, 60, 150]}          # elsewhere: another person
    assert lt.distinct_people([main, strip]) == 1
    assert lt.distinct_people([main, other]) == 2
    assert lt.distinct_people([strip, main, other]) == 2       # order does not matter
    assert lt.distinct_people([]) == 0
    enclosing = {"score": 0.63, "bbox": [22, 169, 1088, 316]}  # weaker but encloses main
    assert lt.distinct_people([main, enclosing]) == 1
    # Test 7 frame at 10.79 s: upper-body box strongest, whole-body box, weak leg box.
    # The leg box overlaps the whole body but not the upper body: still one person.
    upper = {"score": 0.994, "bbox": [603, 270, 474, 188]}
    whole = {"score": 0.992, "bbox": [108, 280, 989, 194]}
    legs = {"score": 0.619, "bbox": [145, 327, 653, 140]}
    assert lt.distinct_people([upper, whole, legs]) == 1
    assert lt.distinct_people([upper, whole, legs, other]) == 2


def test_person_scene_analysis_reports_same_person_boxes(tmp_path):
    main = {"family": "PERSON_DETECTOR", "score": 0.99, "bbox": [76, 290, 1076, 195]}
    strip = {"family": "PERSON_DETECTOR", "score": 0.65, "bbox": [584, 305, 171, 41]}
    other = {"family": "PERSON_DETECTOR", "score": 0.98, "bbox": [0, 211, 60, 150]}
    def row(t, dets):
        return {"t": t, "rel_s": t, "all": dets,
                "best": {"PERSON_DETECTOR": max(dets, key=lambda d: d["score"]) if dets else None},
                "counts": {"PERSON_DETECTOR": len(dets), "FULL_BODY_HOG": 0}}
    rows = [row(0.0, [main]), row(0.2, [main, strip]), row(0.4, [main, other])]
    p = tmp_path / "f.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    r = lt.person_scene_analysis(str(p), [])
    assert r["frames_with_extra_boxes"] == 2
    assert r["frames_with_extra_boxes_same_person"] == 1
    assert r["frames_with_separate_person_boxes"] == 1
    assert r["max_distinct_people_estimate"] == 2 and r["separate_person_box_frames_rel_s"] == [0.4]

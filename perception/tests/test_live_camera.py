import json

import numpy as np

from perception.live_camera import (Detection, PersonDetector, is_black,
                                    make_observation)


def test_observation_json_shape():
    det = Detection([10, 20, 30, 40], "opencv_haar_frontalface_default", 3.2,
                    "haar_level_weight")
    obs = make_observation(seq=1, drone_id="D1", cell="G", obs_time=1700000000.5,
                           frame_ref="/tmp/x.jpg", det=det)
    obs = json.loads(json.dumps(obs))
    assert obs["obs_id"] == "D1-b1-000001"
    assert obs["drone_id"] == "D1"
    assert obs["source_mode"] == "LIVE-HW"
    assert obs["platform"] == "BENCH"
    assert obs["sensor"] == "rgb"
    assert obs["kind"] == "PERSON_VISUAL"
    assert obs["how"] == "SECTOR_ONLY"
    assert obs["cell"] == "G"
    assert obs["obs_time"] == 1700000000.5
    assert obs["confidence"] is None
    ev = obs["evidence"]
    assert ev["frame_ref"] == "/tmp/x.jpg"
    assert ev["bbox"] == [10, 20, 30, 40]
    assert ev["detector"] == "opencv_haar_frontalface_default"


def test_blank_image_no_person():
    d = PersonDetector()
    for val in (0, 128, 255):
        img = np.full((480, 640, 3), val, dtype=np.uint8)
        assert d.detect(img) is None


def test_black_frame_flagged():
    assert is_black(np.zeros((10, 10, 3), np.uint8))
    assert is_black(None)
    assert not is_black(np.full((10, 10, 3), 100, np.uint8))

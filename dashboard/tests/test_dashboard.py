"""Issue #4: the bench camera sighting at G and route v1 A→G on the dashboard."""
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.ingest import InvalidObservation, normalise
from core.store import MissionStore
from dashboard.app import create_app

REPO = Path(__file__).resolve().parents[2]
OBS_TIME = 1794077187.974565

# The observation printed by perception/live_camera.py in the PR #3 bench run.
BENCH_OBS = {
    "obs_id": "D1-b1-000001", "drone_id": "D1", "source_mode": "LIVE-HW", "platform": "BENCH",
    "sensor": "rgb", "kind": "PERSON_VISUAL", "how": "SECTOR_ONLY", "cell": "G",
    "obs_time": OBS_TIME, "confidence": None,
    "evidence": {"frame_ref": "PLACEHOLDER", "bbox": [897, 351, 390, 390],
                 "detector": "opencv_haar_frontalface_default",
                 "detector_score": 6.74, "detector_score_kind": "haar_level_weight"},
}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def evidence(tmp_path):
    d = tmp_path / "evidence"
    d.mkdir()
    photo = d / "D1-b1-000001_1794077187.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-for-test\xff\xd9")
    return d, photo


@pytest.fixture
def setup(evidence):
    d, photo = evidence
    clock = Clock(OBS_TIME + 42.0)
    store = MissionStore(responder_node="A", clock=clock)
    client = TestClient(create_app(store, evidence_dir=d))
    obs = json.loads(json.dumps(BENCH_OBS))
    obs["evidence"]["frame_ref"] = str(photo)
    return client, store, clock, obs, photo


def test_ingest_fills_contract_fields():
    out = normalise(BENCH_OBS, known_cells="ABCDEFG", rx_time=OBS_TIME + 0.4)
    assert out["boot_id"] == "b1" and out["seq"] == 1
    assert out["rx_time"] == OBS_TIME + 0.4
    assert out["stale_after_s"] == 300.0          # RGB TTL, §9.6
    assert out["confidence"] is None               # never invented


@pytest.mark.parametrize("patch", [{"cell": "ZZ"}, {"obs_id": "bad"}, {"drone_id": "D2"},
                                   {"source_mode": "REAL"}, {"obs_time": None}])
def test_ingest_rejects_bad_observations(patch):
    with pytest.raises(InvalidObservation):
        normalise({**BENCH_OBS, **patch}, known_cells="ABCDEFG")


def test_bench_sighting_shows_candidate_in_sector_g_assigned(setup):
    client, _store, _clock, obs, _photo = setup
    r = client.post("/observations", json=obs)
    assert r.status_code == 200 and r.json() == {"obs_id": "D1-b1-000001", "duplicate": False,
                                                 "track_id": "T1"}
    st = client.get("/state").json()
    [t] = st["tracks"]
    assert t["label"] == "Candidate in sector G (assigned)"
    assert t["cell"] == "G" and t["how"] == "SECTOR_ONLY"
    assert t["badge"] == "LIVE-HW (bench)"
    assert t["confirmation"] == "unconfirmed"
    assert t["sources"] == ["D1 RGB"]
    assert t["latest"]["confidence"] is None
    assert t["latest"]["detector_score_kind"] == "haar_level_weight"
    assert "xy_m" not in json.dumps(st)            # no coordinates for a SECTOR_ONLY sighting


def test_sighting_age_counts_from_obs_time(setup):
    client, _store, clock, obs, _photo = setup
    client.post("/observations", json=obs)
    latest = client.get("/state").json()["tracks"][0]["latest"]
    assert latest["age_s"] == pytest.approx(42.0)
    assert latest["stale"] is False
    clock.t = OBS_TIME + 301
    latest = client.get("/state").json()["tracks"][0]["latest"]
    assert latest["age_s"] == pytest.approx(301.0)
    assert latest["stale"] is True


def test_route_v1_a_to_g_is_60_m(setup):
    client, _store, _clock, obs, _photo = setup
    client.post("/observations", json=obs)
    [route] = client.get("/state").json()["routes"]
    assert route["version"] == 1 and route["active"] is True
    assert (route["from"], route["to"], route["track_id"]) == ("A", "G", "T1")
    assert route["status"] == "OK"
    assert route["path"] == ["A", "B", "C", "D", "E", "F", "G"]
    assert route["edges"] == ["A-B", "B-C", "C-D", "D-E", "E-F", "F-G"]
    assert route["length_m"] == 60


def test_duplicate_obs_id_is_idempotent(setup):
    client, _store, _clock, obs, _photo = setup
    client.post("/observations", json=obs)
    r = client.post("/observations", json=obs)
    assert r.json()["duplicate"] is True
    st = client.get("/state").json()
    assert st["tracks"][0]["n_observations"] == 1
    assert len(st["routes"]) == 1


def test_invalid_observation_is_422(setup):
    client = setup[0]
    r = client.post("/observations", json={**BENCH_OBS, "cell": "ZZ"})
    assert r.status_code == 422


def test_state_shows_synthetic_trail_map(setup):
    client = setup[0]
    g = client.get("/state").json()["graph"]
    assert "SYNTHETIC" in g["label"]
    assert len(g["nodes"]) == 26 and len(g["edges"]) == 15
    pos = {n["id"]: (n["col"], n["row"]) for n in g["nodes"]}
    assert pos["A"] == (0, 0) and pos["G"] == (6, 0) and pos["K"] == (3, 1) and pos["Y"] == (3, 3)


def test_photo_served_from_evidence_dir_only(setup, tmp_path):
    client, store, _clock, obs, photo = setup
    client.post("/observations", json=obs)
    st = client.get("/state").json()
    latest = st["tracks"][0]["latest"]
    assert latest["photo_url"] == "/evidence/D1-b1-000001"
    assert str(photo) not in json.dumps(st)        # local path is not published in /state
    r = client.get(latest["photo_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content == photo.read_bytes()

    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"x")
    client.post("/observations", json={**obs, "obs_id": "D1-b1-000002",
                                       "evidence": {"frame_ref": str(outside)}})
    assert client.get("/evidence/D1-b1-000002").status_code == 404
    client.post("/observations", json={**obs, "obs_id": "D1-b1-000003",
                                       "evidence": {"frame_ref": str(photo.parent / ".." / "outside.jpg")}})
    assert client.get("/evidence/D1-b1-000003").status_code == 404
    assert client.get("/evidence/nope").status_code == 404


def test_photo_not_served_without_evidence_dir(evidence):
    _d, photo = evidence
    client = TestClient(create_app(MissionStore(), evidence_dir=None))
    obs = {**BENCH_OBS, "evidence": {"frame_ref": str(photo)}}
    client.post("/observations", json=obs)
    assert client.get("/evidence/D1-b1-000001").status_code == 404


def test_index_page_renders_map_elements(setup):
    html = setup[0].get("/").text
    for needle in ('id="map"', 'id="cand"', 'id="route"', "/state", "SYNTHETIC"):
        assert needle in html


def test_no_photos_tracked_in_git():
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                           check=True).stdout.splitlines()
    photos = [f for f in files if Path(f).suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".mp4", ".mov"}
              and f not in VENDORED_ICONS | BRAND_ICONS | SOFTWARE_SCREENSHOTS]
    assert photos == []


# Leaflet's own UI icons (BSD-2, LICENSE alongside), vendored for the offline fleet map (PR #17).
# They are not photos. Listed by exact path: any other image anywhere still fails this test.
VENDORED_ICONS = {f"team15_starter/fleet/web/leaflet/images/{n}" for n in
                  ("layers.png", "layers-2x.png", "marker-icon.png", "marker-icon-2x.png", "marker-shadow.png")}


# Generated Rescue Signal branding contains no camera captures or people.
# Keep exceptions exact so other photos and recordings remain prohibited.
BRAND_ICONS = {
    "ios/BeaconC1/BeaconC1/Assets.xcassets/AppIcon.appiconset/rescue-signal.png",
    "ios/BeaconC1/BeaconC1/Assets.xcassets/RescueLogo.imageset/rescue-signal.png",
    "mission_control/static/favicon.png",
    "mission_control/static/apple-touch-icon.png",
    "team15_starter/fleet/web/leaflet/rescue-favicon.png",
}

# Retained C3 screenshots show the simulated receiver dashboard, not camera photos.
SOFTWARE_SCREENSHOTS = {
    f"docs/ble-id/runs/c3-20261107T205707Z/browser/{name}"
    for name in ("01_first_verified.png", "02_cycle_10s.png", "03_cycle_22s.png",
                 "04_cycle_40s.png", "05_diagnostics.png")
}

"""Forward obstacle range card: GET /api/range and the page's card.

Everything here is SIMULATED. The robotics fixtures live outside this repo
(~/Documents/Team-15-Robot/fixtures, or TEAM15_ROBOT_FIXTURES); tests that need
them skip when absent. Inline snapshots cover the rules either way.
"""
import copy
import json
import os
import re
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import range_view
from core.store import MissionStore
from dashboard.app import create_app
from dashboard.range_source import RangeSource

RANGE_URL = "http://127.0.0.1:18765/range"
ROBOT_URL = "http://127.0.0.1:8770/robot/status"

FIXTURES = Path(os.environ.get("TEAM15_ROBOT_FIXTURES", "~/Documents/Team-15-Robot/fixtures")).expanduser()
SERIES = FIXTURES / "sim_range_series_approach.json"
SCENARIOS = FIXTURES / "sim_range_snapshots.json"
ROBOT = FIXTURES / "sim_robot_status.json"
need = pytest.mark.skipif(not (SERIES.is_file() and SCENARIOS.is_file() and ROBOT.is_file()),
                          reason="robotics SIMULATED fixtures not on this machine")
PUB = 1794100599.729976


def snap(**over):
    """A minimal SIMULATED team15.range_snapshot/1 (CLEAR at 1.00 m)."""
    s = {
        "schema": "team15.range_snapshot/1", "sensor_id": "grove-us-front",
        "published_at": "2026-11-08T01:16:39.729+00:00", "published_time": PUB,
        "obstacle_status": "CLEAR", "forward_motion_allowed": True, "range_m": 1.0001,
        "valid": True, "stale_after_s": 0.5,
        "freshness": {"age_s": 0.0, "stale": False, "stale_after_s": 0.5},
        "latest": {"schema": "team15.range_reading/1", "distance_m": 1.0001, "valid": True,
                   "timestamp": "2026-11-08T01:16:39.729+00:00", "measurement_status": "VALID"},
        "assessment": {"status": "CLEAR", "reason": "range beyond caution",
                       "thresholds": {"blocked_m": 0.28, "caution_m": 0.68}},
        "provenance": {"source_mode": "SIMULATED", "driver": "simulated", "wiring_verified_by": None},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k] = {**s[k], **v}
        else:
            s[k] = v
    return s


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def client_for(src):
    return TestClient(create_app(MissionStore(), range_source=src))


# --- rules ------------------------------------------------------------------------------

def test_clear_reading_renders_value_unit_and_sensor_time():
    v = range_view.from_snapshot(snap(), now=PUB + 0.1, fixture=False)
    assert v["title"] == "Forward obstacle range"
    assert v["qualification"] == ("nearest reflecting surface in a ~15° forward cone; "
                                  "not the distance to the detected person")
    assert v["status"] == "CLEAR" and v["usable"] is True
    assert v["value_text"] == "100 cm @ 01:16:39Z"
    assert v["badge"] == "SIMULATED" and v["simulated"] is True
    assert v["motion_text"] is None        # never says "motion allowed"


@pytest.mark.parametrize("mstatus", ["NO_ECHO", "OUT_OF_RANGE"])
def test_no_echo_is_unknown_never_clear(mstatus):
    s = snap(obstacle_status="CLEAR", forward_motion_allowed=True,
             latest={"measurement_status": mstatus, "distance_m": None, "valid": False})
    v = range_view.from_snapshot(s, now=PUB + 0.1, fixture=False)
    assert v["status"] == "UNKNOWN" and v["usable"] is False
    assert v["status_text"] == "unknown (no echo)"
    assert v["motion_text"] == "UNKNOWN" and v["value_text"] is None


@pytest.mark.parametrize("age", [0.51, 5.0, -1.5])
def test_live_staleness_recomputed_from_published_time(age):
    # The snapshot's own freshness says fresh; the proxy's clock says otherwise.
    v = range_view.from_snapshot(snap(), now=PUB + age, fixture=False)
    assert v["stale"] is True and v["status"] == "UNKNOWN" and v["usable"] is False
    assert v["status_text"].startswith("stale") and "limit 0.5 s" in v["status_text"]
    assert v["motion_text"] == "UNKNOWN"


def test_live_fresh_within_threshold_and_small_skew():
    for age in (0.0, 0.49, -0.9):
        assert range_view.from_snapshot(snap(), now=PUB + age, fixture=False)["stale"] is False


def test_fixture_uses_its_own_freshness():
    far_future = PUB + 10_000
    assert range_view.from_snapshot(snap(), now=far_future, fixture=True)["stale"] is False
    s = snap(freshness={"stale": True, "age_s": 2.0})
    assert range_view.from_snapshot(s, now=PUB, fixture=True)["status"] == "UNKNOWN"
    s = snap()
    del s["freshness"]                       # missing freshness → stale
    assert range_view.from_snapshot(s, now=PUB, fixture=True)["stale"] is True


def test_motion_not_allowed_never_reads_clear():
    v = range_view.from_snapshot(snap(forward_motion_allowed=False), now=PUB, fixture=False)
    assert v["status"] == "UNKNOWN" and v["motion_text"] == "UNKNOWN"
    b = range_view.from_snapshot(snap(obstacle_status="BLOCKED", forward_motion_allowed=False,
                                      latest={"distance_m": 0.2}), now=PUB, fixture=False)
    assert b["status"] == "BLOCKED" and b["motion_text"] == "BLOCKED" and b["usable"] is True
    assert b["value_text"] == "20 cm @ 01:16:39Z"


def test_hardware_badge_needs_every_allowlisted_check():
    hw = {"source_mode": "LIVE-HW", "driver": "gpiod", "wiring_verified_by": "tech"}
    robot_ok = {"mode": "LIVE", "claims": {"hardware_validated": True}}
    assert range_view.hardware_verified(snap(provenance=hw), None) is True
    assert range_view.hardware_verified(snap(provenance=hw), robot_ok) is True
    for bad in ({"source_mode": "SIMULATED"}, {"driver": "simulated"}, {"wiring_verified_by": None}):
        assert range_view.hardware_verified(snap(provenance={**hw, **bad}), None) is False
    assert range_view.hardware_verified(snap(provenance=hw), {"mode": "SIMULATION",
                                        "claims": {"hardware_validated": True}}) is False
    assert range_view.hardware_verified(snap(provenance=hw), {"mode": "LIVE", "claims": {}}) is False
    assert range_view.hardware_verified(None, None) is False


# --- endpoint ---------------------------------------------------------------------------

def test_api_range_disconnected_when_services_unreachable():
    def refuse(url, timeout):
        raise ConnectionRefusedError(61, "Connection refused")
    c = client_for(RangeSource(range_url=RANGE_URL, robot_url=ROBOT_URL, fetch=refuse, clock=Clock(PUB)))
    v = c.get("/api/range").json()
    assert v["status"] == "DISCONNECTED" and v["usable"] is False
    assert v["badge"] == "SIMULATED" and v["value_text"] is None
    assert "18765" in v["reason"] and "8770" in v["reason"]


def test_no_live_source_by_default_and_nothing_is_fetched():
    calls = []
    v = client_for(RangeSource(fetch=lambda u, t: calls.append(u), clock=Clock(PUB))).get("/api/range").json()
    assert calls == [] and v["status"] == "DISCONNECTED" and "no range source configured" in v["reason"]


@pytest.mark.parametrize("body", [{"schema": "something/else", "status": "ok"}, {"error": "Unauthorized"}])
def test_wrong_schema_reads_disconnected(body):
    v = client_for(RangeSource(range_url=RANGE_URL, fetch=lambda u, t: body,
                               clock=Clock(PUB))).get("/api/range").json()
    assert v["status"] == "DISCONNECTED" and "unexpected schema" in v["reason"]


def test_http_error_reads_disconnected():
    import urllib.error
    def unauthorized(url, timeout):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
    v = client_for(RangeSource(range_url=RANGE_URL, fetch=unauthorized,
                               clock=Clock(PUB))).get("/api/range").json()
    assert v["status"] == "DISCONNECTED" and "Unauthorized" in v["reason"]


def test_api_range_live_proxy_reads_snapshot_and_robot():
    def fake(url, timeout):
        if url.endswith("/range"):
            return snap()
        return {"schema": "team15.robot_status/1", "mode": "SIMULATION",
                "claims": {"hardware_validated": False}}
    v = client_for(RangeSource(range_url=RANGE_URL, robot_url=ROBOT_URL, fetch=fake,
                               clock=Clock(PUB + 0.2))).get("/api/range").json()
    assert v["source"] == "LIVE" and v["status"] == "CLEAR" and v["robot_mode"] == "SIMULATION"
    assert v["badge"] == "SIMULATED"


def test_api_range_malformed_data_is_disconnected_not_clear():
    def junk(url, timeout):
        return {"schema": "team15.range_snapshot/1", "latest": "oops", "stale_after_s": "x"}
    v = client_for(RangeSource(range_url=RANGE_URL, fetch=junk, clock=Clock(PUB))).get("/api/range").json()
    assert v["status"] == "DISCONNECTED" and v["usable"] is False


def test_range_endpoint_leaves_mission_state_untouched():
    from dashboard.tests.test_dashboard import BENCH_OBS
    store = MissionStore(responder_node="A", clock=Clock(PUB))
    c = TestClient(create_app(store, range_source=RangeSource(range_url=RANGE_URL, fetch=lambda u, t: snap(),
                                                               clock=Clock(PUB))))
    c.post("/observations", json=BENCH_OBS)
    before = c.get("/state").json()
    for _ in range(3):
        c.get("/api/range")
    after = c.get("/state").json()
    for k in ("tracks", "routes", "alerts", "decisions", "graph"):
        assert after[k] == before[k]
    [t] = after["tracks"]
    assert t["confirmation"] == "unconfirmed" and t["cell"] == "G"
    assert after["routes"][0]["length_m"] == 60
    assert "range" not in json.dumps(t).lower()


# --- the robotics fixtures (SIMULATED) --------------------------------------------------

@need
def test_every_scenario_fixture_is_badged_simulated():
    src = RangeSource(fixture=SCENARIOS, robot_fixture=ROBOT, clock=Clock(PUB))
    c = client_for(src)
    seen = {}
    for name in json.loads(SCENARIOS.read_text())["scenarios"]:
        v = c.get("/api/range", params={"scenario": name}).json()
        assert v["badge"] == "SIMULATED" and v["simulated"] is True and v["source"] == "FIXTURE"
        assert v["frame"]["scenario"] == name
        seen[name] = v
    assert seen["static_1m"]["status"] == "CLEAR"
    assert seen["static_1m"]["value_text"] == "100 cm @ 01:16:39Z"
    for name in ("open_no_echo", "disconnected"):
        assert seen[name]["status"] == "UNKNOWN"
        assert seen[name]["status_text"] == "unknown (no echo)"
        assert seen[name]["usable"] is False


@need
def test_robot_fixture_alone_is_simulated_and_never_clear():
    v = client_for(RangeSource(robot_fixture=ROBOT, clock=Clock(PUB))).get("/api/range").json()
    assert v["badge"] == "SIMULATED" and v["status"] != "CLEAR"
    assert v["value_text"] == "120 cm @ 21:20:00Z" and v["robot_mode"] == "SIMULATION"


@need
def test_approach_series_all_120_frames():
    series = json.loads(SERIES.read_text())["series"]
    assert len(series) == 120
    c = client_for(RangeSource(fixture=SERIES, robot_fixture=ROBOT, clock=Clock(PUB)))
    statuses, values = Counter(), []
    for i in range(120):
        v = c.get("/api/range", params={"frame": i}).json()
        raw = series[i]
        assert v["badge"] == "SIMULATED" and v["frame"] == {"index": i + 1, "of": 120}
        statuses[v["status"]] += 1
        if v["status"] in ("CLEAR", "CAUTION"):
            assert raw["forward_motion_allowed"] is True and raw["obstacle_status"] == v["status"]
            assert v["motion_text"] is None   # allowed motion is simply not shown
        else:
            assert v["motion_text"] in ("BLOCKED", "UNKNOWN")
        if raw["forward_motion_allowed"] is False:
            assert v["status"] in ("BLOCKED", "UNKNOWN")
        if raw["obstacle_status"] == "UNKNOWN":
            assert v["status"] == "UNKNOWN" and v["usable"] is False
        if v["distance_cm"] is not None:
            values.append(v["distance_cm"])
    assert statuses == Counter({"CLEAR": 47, "CAUTION": 15, "BLOCKED": 54, "UNKNOWN": 4})
    assert min(values) == pytest.approx(18, abs=0.6)


@need
def test_series_cycles_at_0_1_s():
    clock = Clock(PUB)
    src = RangeSource(fixture=SERIES, clock=clock)
    c = client_for(src)
    assert c.get("/api/range").json()["frame"]["index"] == 1
    clock.t += 0.35
    assert c.get("/api/range").json()["frame"]["index"] == 4
    clock.t += 12.0                           # wraps after 120 frames
    assert c.get("/api/range").json()["frame"]["index"] == 4


# --- the page ---------------------------------------------------------------------------

def _range_card_html():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text()
    m = re.search(r'<section class="panel range-card[^>]*>.*?</section>', html, re.S)
    js = re.search(r"function drawRange\(v\) \{.*?\n\}", html, re.S)
    return html, m.group(0), js.group(0)


def test_page_has_separate_range_card_without_person_wording():
    html, card, js = _range_card_html()
    assert "Forward obstacle range" in card and 'id="range-h"' in card
    # The card is its own section, not inside the candidate panel.
    cand = re.search(r'<section class="panel" aria-labelledby="cand-h">.*?</section>', html, re.S).group(0)
    assert "range" not in cand.lower()
    # Visible text never says "person"/"candidate"; the qualification is only the tooltip.
    visible = re.sub(r'title="[^"]*"', "", card + js.replace("v.qualification", ""))
    assert not re.search(r"person|candidate", visible, re.I)
    assert "motion allowed" not in js.lower() and "SIMULATED" in js

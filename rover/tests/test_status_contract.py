"""Dashboard contract: the status fields exist, are JSON-safe, and never over-claim."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rover.simrun import scenario
from rover.status_api import REQUIRED_STATUS_KEYS, rover_router


def test_status_has_contract_fields_and_is_json():
    s = scenario("C").run()
    st = s.nav.status()
    assert set(REQUIRED_STATUS_KEYS) <= set(st)
    json.dumps(st)
    assert st["schema"] == "team15.rover_nav_status/1"
    assert "SYNTHETIC" in st["distances_label"]
    assert st["claims"] == {"autonomous_navigation_operational": False,
                            "physical_motion_verified": False, "localization": "SIMULATED"}
    assert st["motion"]["driver"]["physical"] is False
    assert st["last_reroute_reason"].startswith("edge D-E blocked")


def test_status_mid_mission_shows_remaining_and_sensor_validity():
    s = scenario("A")
    s.run(until=lambda sim: sim.world.t >= 20)
    st = s.nav.status()
    assert st["state"] in ("ADVANCE_IF_SAFE", "TURN_TO_HEADING", "CHECK_SENSORS")
    assert 0 < st["remaining_planned_m"] < 60
    assert st["sensor"]["valid"] is True and st["sensor"]["age_s"] <= 0.2
    assert st["pose"]["source"] == "SIM_TRUTH"


def test_router_status_and_estop_only():
    s = scenario("A")
    s.run(until=lambda sim: sim.world.t >= 5)
    app = FastAPI()
    app.include_router(rover_router(lambda: s.nav), prefix="/rover")
    c = TestClient(app)
    assert c.get("/rover/status").json()["state"] == s.nav.state.value
    r = c.post("/rover/estop", json={"by": "tester"})
    assert r.json()["tripped"] is True and s.driver.velocity.is_zero()
    paths = {route.path for route in app.routes}
    assert not any("reset" in p or "start" in p or "move" in p for p in paths)


def test_router_without_navigator():
    app = FastAPI()
    app.include_router(rover_router(lambda: None), prefix="/rover")
    st = TestClient(app).get("/rover/status").json()
    assert st["state"] == "NOT_RUNNING" and st["pose"] == {"source": "UNKNOWN"}

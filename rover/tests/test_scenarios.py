"""Gates 3 and 4: scenarios A-H on the SYNTHETIC graph with fake (simulated) sensor readings.

All distances are synthetic graph weights in metres. "traveled" here is simulator ground truth.
"""
import pytest

from planner.route import compute_route
from rover.motion import SafetyStop
from rover.navigator import State
from rover.observations import CLEARED, UNCONFIRMED
from rover.simrun import build, scenario
from rover.sim import SimObstacle


def run(name):
    s = scenario(name).run()
    assert s.world.collision is None, f"collision with {s.world.collision}"
    return s, s.nav.status()


def test_A_all_clear_60m():
    s, st = run("A")
    assert st["state"] == "ARRIVED"
    assert st["route"]["path"] == list("ABCDEFG") and st["route"]["length_m"] == 60
    assert st["blocked_edges"] == [] and st["reroutes"] == []
    assert st["remaining_planned_m"] == 0
    assert st["traveled"]["kind"] == "SIMULATED_GROUND_TRUTH"
    assert st["claims"]["autonomous_navigation_operational"] is False


def test_B_blocked_edge_marked_only_with_justification():
    s, st = run("B")
    assert st["blocked_edges"] == ["D-E"]
    blk = st["blockers"][0]
    assert blk["status"] == "CONFIRMED" and blk["dynamic"] is False
    assert len(blk["detail"]["ranges"]) == 3                       # verified by 3 fresh readings
    assert blk["detail"]["at_m"] == pytest.approx(5.0, abs=0.05)   # obstacle placed 5 m from D
    assert "facing along edge" in blk["detail"]["justification"]
    states = [h["state"] for h in s.nav.history]
    for a, b in [("OBSTACLE_DETECTED", "STOP"), ("STOP", "VERIFY_OBSTACLE"),
                 ("VERIFY_OBSTACLE", "MARK_EDGE_BLOCKED_IF_JUSTIFIED")]:
        i = states.index(a)
        assert states[i + 1] == b


def test_C_alternate_route_is_longer_and_completed():
    s, st = run("C")
    assert st["state"] == "ARRIVED"
    rr = st["reroutes"][0]
    assert rr["blocked_edge"] == "D-E"
    assert rr["new_route"] == ["D", "K", "L", "M", "G"] and rr["new_length_m"] == 46
    assert rr["new_remaining_m"] > rr["old_remaining_m"]            # longer detour
    assert rr["retreat_m"] == pytest.approx(4.0, abs=0.1)           # stopped 1 m (lookahead) before the box
    assert st["route"]["path"] == ["D", "K", "L", "M", "G"]
    # cross-check against the planner directly
    assert compute_route("D", "G", blocked={"D-E"}).length_m == 46


def test_D_two_obstacles_two_replans():
    s, st = run("D")
    assert st["state"] == "ARRIVED"
    assert [r["blocked_edge"] for r in st["reroutes"]] == ["D-E", "D-K"]
    assert st["reroutes"][1]["new_route"] == list("DCJKLMG") and st["reroutes"][1]["new_length_m"] == 64


def test_E_no_verified_route_safe_stop_reports_blockers():
    s, st = run("E")
    assert st["state"] == "SAFE_STOP"
    assert st["blocked_edges"] == ["D-E", "G-M"]
    assert "no verified route" in st["safe_stop_reason"] and "G-M" in st["safe_stop_reason"]
    assert st["route"]["status"] == "NO_KNOWN_ROUTE"
    assert st["motion"]["output"] == {"vx": 0.0, "vy": 0.0, "wz": 0.0}
    assert not s.nav.running  # does not restart by itself
    s.run_for(5.0)
    assert s.nav.state == State.SAFE_STOP


def test_F_cleared_edge_independently_verified_recovers_shorter_route():
    s, st = run("F")
    assert st["state"] == "ARRIVED"
    assert st["route"]["path"] == list("DEFG") and st["route"]["length_m"] == 30
    blk = [o for o in s.log.items if o.kind == "ultrasonic_obstacle"][0]
    assert blk.status == CLEARED


def test_F_same_source_cannot_clear_and_before_clearing_route_is_46():
    s = build("D", [SimObstacle("box-DE", "D", "E", 5.0, present=False)])
    s.log.add("ultrasonic_obstacle", "sim-ultrasonic", "CONFIRMED", dynamic=False, edge="D-E")
    assert compute_route("D", "G", blocked=s.log.blocked_edges()).length_m == 46
    with pytest.raises(PermissionError):
        s.log.clear_edge("D-E", source="sim-ultrasonic", operator="op", evidence="same sensor")
    with pytest.raises(PermissionError):
        s.log.clear_edge("D-E", source="camera", operator="", evidence="x")
    s.log.clear_edge("D-E", source="camera", operator="op", evidence="fresh frame")
    assert compute_route("D", "G", blocked=s.log.blocked_edges()).length_m == 30


def test_G_stale_ultrasonic_while_moving_safe_stops_and_latches():
    s, st = run("G")
    assert st["state"] == "SAFE_STOP" and "SENSOR_STALE" in st["safe_stop_reason"]
    assert s.supervisor.latched == SafetyStop.SENSOR_STALE
    assert st["sensor"]["valid"] is False
    s.world.range_dropout = False   # the sensor comes back...
    s.run_for(3.0)
    assert s.nav.state == State.SAFE_STOP and s.driver.velocity.is_zero()  # ...and nothing restarts


def test_H_person_unconfirmed_human_review():
    s, st = run("H")
    assert st["state"] == "CONTINUE_OR_REQUEST_OPERATOR"
    persons = [o for o in st["observations"] if o["kind"] == "camera_person"]
    assert persons and all(o["status"] == UNCONFIRMED and o["dynamic"] for o in persons)
    assert all(o["detail"]["coordinates"].startswith("NONE") for o in persons)
    assert st["blocked_edges"] == []                     # an unconfirmed person never blocks routing
    req = st["operator_requests"][-1]
    assert req["kind"] == "HUMAN_REVIEW" and req["obs_id"] in {o["obs_id"] for o in persons}
    assert s.driver.velocity.is_zero()


def test_scenarios_are_deterministic():
    a = scenario("D").run().nav.status()
    b = scenario("D").run().nav.status()
    assert a["reroutes"] == b["reroutes"] and a["t"] == b["t"]

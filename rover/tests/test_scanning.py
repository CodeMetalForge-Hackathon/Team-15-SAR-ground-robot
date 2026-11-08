"""In-place rotation scanning with the fixed forward ultrasonic and camera (no servo).

Covers: left/right scanning, unknown directions, blocked alternatives, loss of localization,
emergency stops, and the rule that headings are measured (closed loop), never timed.
"""
import pytest

from rover.motion import Command, SafetyStop
from rover.navigator import State
from rover.sensors import NoEchoPolicy, ang_diff
from rover.sim import SimObstacle
from rover.simrun import build

BOX_DE = SimObstacle("box-DE", "D", "E", 5.0)


def _scan_for(s, edge):
    return next(x for x in s.nav.scans if edge in x["trigger"])


def test_left_then_right_then_back_views_with_measured_heading():
    s = build("A", [BOX_DE], side_clearance={("D", "E"): (0.6, 2.0)})
    s.nav.start("G")
    s.run()
    sc = _scan_for(s, "D-E")
    assert list(sc["views"]) == ["left", "right", "back"]          # rotate left, then right, then back
    assert sc["heading_source"] == "sim-truth"
    h0 = sc["heading_at_stop_deg"]
    assert ang_diff(sc["views"]["left"]["bearing_deg"], h0) == pytest.approx(45)
    assert ang_diff(sc["views"]["right"]["bearing_deg"], h0) == pytest.approx(-45)
    assert abs(ang_diff(sc["views"]["back"]["bearing_deg"], h0)) == pytest.approx(180)
    # side clearances observed and compared against the robot width (0.20 m + margins = 0.30 m)
    assert sc["views"]["left"]["min_range_m"] == pytest.approx(0.6)
    assert sc["views"]["right"]["min_range_m"] == pytest.approx(2.0)
    assert sc["comparison"]["left"]["wider_than_robot"] is True
    assert sc["views"]["left"]["status"] == "BLOCKED"              # 0.6 m < 1.0 m lookahead
    assert sc["views"]["right"]["status"] == "CLEAR"
    assert sc["local_bypass"].startswith("NOT_ATTEMPTED")          # side clearances are evidence only
    # each view sweeps centre, +delta and -delta to cover the robot width; every sample a fresh reading
    for v in sc["views"].values():
        assert [x["offset_deg"] for x in v["samples"]][0] == 0 and len(v["samples"]) == 3
        assert v["sweep_half_deg"] > 0
        assert v["camera_request"].startswith("cam-")
    seqs = [x["reading"]["seq"] for v in sc["views"].values() for x in v["samples"]]
    assert len(set(seqs)) == len(seqs)
    # chose the shortest verified alternative via Dijkstra, then reached it
    assert s.nav.reroutes[0]["new_route"] == list("DKLMG")
    assert s.nav.state == State.ARRIVED


def _collapse(states):
    out = []
    for s in states:
        if not out or out[-1] != s:
            out.append(s)
    return out


def test_stop_rotate_scan_replan_sequence():
    s = build("A", [BOX_DE])
    s.nav.start("G")
    trace = []
    s.run(until=lambda sim: trace.append((sim.world.t, sim.driver.velocity.vx)) or not sim.nav.running)
    states = _collapse(h["state"] for h in s.nav.history)
    i = states.index("OBSTACLE_DETECTED")
    seq = states[i:]
    expected_order = ["OBSTACLE_DETECTED", "STOP", "VERIFY_OBSTACLE", "MARK_EDGE_BLOCKED_IF_JUSTIFIED",
                      "SCAN_DIRECTIONS", "TURN_TO_HEADING", "REPLAN_SHORTEST_ROUTE", "VERIFY_DETOUR",
                      "CONTINUE_OR_REQUEST_OPERATOR", "TURN_TO_HEADING", "CHECK_SENSORS", "ADVANCE_IF_SAFE",
                      "PLAN_ROUTE"]
    pos = 0
    for st in seq:
        if pos < len(expected_order) and st == expected_order[pos]:
            pos += 1
    assert pos == len(expected_order), (seq[:20], expected_order[pos:])
    # no forward motion between the obstacle stop and the approved detour
    t_stop = next(h["t"] for h in s.nav.history if h["state"] == "OBSTACLE_DETECTED")
    t_go = next(h["t"] for h in s.nav.history if h["state"] == "CONTINUE_OR_REQUEST_OPERATOR" and h["t"] > t_stop)
    between = [vx for t, vx in trace if t_stop < t <= t_go]
    assert between and all(vx == 0 for vx in between)


def test_scan_waits_for_settle_readings_after_each_rotation():
    s = build("A", [BOX_DE], scan_settle_readings=3)
    s.nav.start("G")
    s.run()
    sc = _scan_for(s, "D-E")
    # each sample must be at least the 3rd fresh reading after the rotation stopped
    for v in sc["views"].values():
        seqs = [x["reading"]["seq"] for x in v["samples"]]
        assert all(b - a >= 3 for a, b in zip(seqs, seqs[1:])), seqs
    assert s.nav.state == State.ARRIVED


def test_rotations_are_bounded_segments():
    s = build("A", [BOX_DE])
    s.nav.start("G")
    s.run()
    # integrate the applied yaw over each continuous rotation (between zero outputs)
    yaw_dps, dt = s.world.cfg.yaw_dps_per_unit, s.world.cfg.dt
    runs, cur = [], 0.0
    for v in s.driver.applied:
        if v.wz == 0:
            if cur:
                runs.append(cur)
            cur = 0.0
        else:
            cur += abs(v.wz) * yaw_dps * dt
    assert runs, "expected rotations"
    assert max(runs) <= s.nav.cfg.max_rotation_segment_deg + 2.0
    # the 180 deg back view therefore needed more than one bounded segment
    assert sum(1 for r in runs if r > 60) >= 2


def test_no_heading_feedback_means_no_scan_and_operator_request():
    """The real RoverC has no calibrated heading source yet, so timed turns must not count as angles."""
    s = build("A", heading_feedback=False)
    s.nav.start("G")
    s.run()
    assert s.nav.state == State.CONTINUE_OR_REQUEST_OPERATOR
    assert s.nav.operator_requests[-1]["kind"] == "HEADING_UNAVAILABLE"
    assert s.world.odometer_m == 0 and s.driver.velocity.is_zero()
    assert not any(v.wz != 0 for v in s.driver.applied)  # never turned blindly


def test_heading_lost_during_scan_stops():
    s = build("A", [BOX_DE])
    s.nav.start("G")
    s.run(until=lambda sim: sim.nav.scanning)
    s.world.heading_feedback = False
    s.run()
    assert s.nav.state == State.CONTINUE_OR_REQUEST_OPERATOR
    assert s.nav.operator_requests[-1]["kind"] in ("HEADING_LOST", "HEADING_UNAVAILABLE")
    assert s.driver.velocity.is_zero()
    assert s.nav.reroutes == []          # no detour chosen without a complete scan


def test_unknown_directions_no_echo_is_not_clear_by_default():
    """With the default policy, a no-echo reading is UNKNOWN, so the robot won't even depart."""
    s = build("A", no_echo_policy=NoEchoPolicy.UNKNOWN)
    s.nav.start("G")
    s.run()
    assert s.nav.state == State.CONTINUE_OR_REQUEST_OPERATOR
    req = s.nav.operator_requests[-1]
    assert req["kind"] == "SENSOR_UNKNOWN" and "no echo" in req["message"]
    assert s.world.odometer_m == 0


def test_unknown_back_direction_blocks_detour():
    """Back view sees nothing (no echo) under the UNKNOWN policy: the retreat is unverified, so stop."""
    s = build("A", [BOX_DE], no_echo_policy=NoEchoPolicy.CLEAR_TO_MAX)
    s.nav.start("G")
    s.run(until=lambda sim: sim.nav.scanning)
    s.nav.cfg = type(s.nav.cfg)(**{**s.nav.cfg.__dict__, "no_echo_policy": NoEchoPolicy.UNKNOWN})
    s.run()
    assert s.nav.state == State.CONTINUE_OR_REQUEST_OPERATOR
    assert s.nav.operator_requests[-1]["kind"] == "DETOUR_UNVERIFIED"
    assert s.nav.reroutes == [] and s.log.blocked_edges() == ["D-E"]


def test_blocked_alternatives_each_verified_before_departure():
    s = build("A", [BOX_DE, SimObstacle("box-DK", "D", "K", 0.6)])  # D-K blocked right at the node
    s.nav.start("G")
    s.run()
    assert s.log.blocked_edges() == ["D-E", "D-K"]
    dk = [o for o in s.log.items if o.edge == "D-K"][0]
    assert dk.detail["robot_progress_m"] == pytest.approx(0, abs=0.05)  # seen from node D, never entered
    assert s.nav.state == State.ARRIVED and s.nav.route.path == list("DCJKLMG")


def test_obstacle_beyond_edge_end_is_not_attributed():
    """An echo that lands at/after the far node can't justify blocking the current edge."""
    s = build("A", [SimObstacle("box-at-B", "A", "B", 9.98)])
    s.nav.start("G")
    s.run()
    assert s.log.blocked_edges() == []
    assert s.nav.state == State.CONTINUE_OR_REQUEST_OPERATOR
    assert s.nav.operator_requests[-1]["kind"] == "OBSTACLE_NOT_ATTRIBUTED"


def test_loss_of_localization_mid_edge_latches():
    s = build("A")
    s.nav.start("G")
    s.hooks.append((5.0, lambda sim: setattr(sim.world, "localization_ok", False)))
    s.run()
    assert s.nav.state == State.SAFE_STOP and "LOCALIZATION_LOST" in s.nav.safe_stop_reason
    assert s.supervisor.latched == SafetyStop.LOCALIZATION_LOST
    assert s.driver.velocity.is_zero()
    assert s.nav.status()["pose"] == {"source": "UNKNOWN"}


def test_loss_of_localization_during_scan_prevents_detour():
    s = build("A", [BOX_DE])
    s.nav.start("G")
    s.run(until=lambda sim: sim.nav.scanning)
    odo_at_scan = s.world.odometer_m
    s.world.localization_ok = False
    s.run()
    assert s.nav.state == State.SAFE_STOP and "LOCALIZATION_LOST" in s.nav.safe_stop_reason
    assert s.supervisor.latched == SafetyStop.LOCALIZATION_LOST
    assert s.driver.velocity.is_zero()
    assert s.world.odometer_m == odo_at_scan  # never drove the retreat
    assert s.nav.reroutes == []


def test_emergency_stop_during_scan_rotation():
    s = build("A", [BOX_DE])
    s.nav.start("G")
    s.run(until=lambda sim: sim.nav.state == State.TURN_TO_HEADING and sim.driver.velocity.wz != 0
          and sim.nav.scans == [] and sim.world.t > 20)
    s.supervisor.command(Command.EMERGENCY_STOP)
    s.run_for(2.0)
    assert s.nav.state == State.SAFE_STOP and "ESTOP" in s.nav.safe_stop_reason
    assert s.driver.velocity.is_zero() and s.supervisor.estop.tripped
    assert not s.nav.running


def test_emergency_stop_while_advancing_then_operator_resume():
    s = build("A")
    s.nav.start("G")
    s.run(until=lambda sim: sim.world.t >= 6.0)
    assert s.driver.velocity.vx > 0
    s.estop.trip("operator button")
    s.run_for(1.0)
    assert s.driver.velocity.is_zero() and s.nav.state == State.SAFE_STOP
    # resuming needs every explicit operator step: e-stop reset, latch reset, approval, resume
    with pytest.raises(PermissionError):
        s.supervisor.approve_motion("op")
    s.estop.reset("op")
    s.supervisor.reset_latch("op")
    s.supervisor.approve_motion("op")
    s.nav.resume("op")
    s.run()
    assert s.nav.state == State.CONTINUE_OR_REQUEST_OPERATOR  # it stopped mid-edge, not at a node
    assert s.nav.operator_requests[-1]["kind"] == "POSE_UNKNOWN"


def test_auto_approve_refused_for_physical_driver():
    from rover.navigator import NavConfig, Navigator
    s = build("A")
    s.driver.physical = True
    with pytest.raises(PermissionError):
        Navigator(s.graph, s.nav.io, s.supervisor, s.log, NavConfig(robot_width_m=0.2, auto_approve=True))


def test_manual_approval_required_before_start():
    s = build("A", auto_approve=False)
    s.nav.start("G")
    s.run_for(2.0)
    assert s.nav.state == State.CONTINUE_OR_REQUEST_OPERATOR and s.world.odometer_m == 0
    req = s.nav.operator_requests[-1]
    assert req["kind"] == "START_ROUTE"
    s.nav.respond(req["id"], True, "op")
    s.run()
    assert s.nav.state == State.ARRIVED

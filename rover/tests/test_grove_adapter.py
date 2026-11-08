"""Consume PR #7's versioned interface (ranging.rover_io, team15.rover_range_fields/1) end to end.

Covers:
  - forward_motion_allowed is ANDed, in the navigator's assessment and independently in the supervisor;
  - BLOCKED, UNKNOWN, ERROR, stale and missing readings stop forward motion;
  - real-hardware no-echo is UNKNOWN under any policy;
  - local monotonic time is used, and other clock domains are rejected;
  - a missing service fails safe;
  - regressions for numerical/status contradictions and malformed input.
"""
import json
import math
import socket
import time

import pytest

from planner.graph import load_graph
from ranging.rover_io import ROVER_FIELDS_SCHEMA, GroveRangeIO, snapshot_to_rover_fields
from ranging.service import RangeClient
from rover.motion import Command, MotionLimits, SafetyStop, SafetySupervisor, ZERO
from rover.navigator import NavConfig, Navigator, State
from rover.observations import ObservationLog
from rover.pi_io import PiRobotIO, clock_domain
from rover.sensors import ERROR, NO_ECHO, OK, Assessment, NoEchoPolicy, PowerReading, assess, from_rover_fields

HOST = "testhost"
DOMAIN = "time.monotonic@" + HOST
NOW = 5000.0  # a time.monotonic()-style value, not an epoch


def snap(obst="CLEAR", ms="VALID", rng=1.8, allowed=True, stale=False, host=HOST,
         mono_ns=int((NOW - 0.03) * 1e9), seq=412, source_mode="LIVE-HW", latest=True):
    s = {"schema": "team15.range_snapshot/1", "obstacle_status": obst, "forward_motion_allowed": allowed,
         "range_m": rng, "freshness": {"stale": stale},
         "assessment": {"reason": "r", "thresholds": {"blocked_m": 0.28}},
         "provenance": {"host": host, "source_mode": source_mode}}
    s["latest"] = {"mono_ns": mono_ns, "measurement_status": ms, "seq": seq} if latest else None
    return s


def reading(**kw):
    """Snapshot -> PR #7 snapshot_to_rover_fields -> our validation."""
    f = snapshot_to_rover_fields(snap(**kw), NOW, 3.0, this_host=HOST)
    return from_rover_fields(f, DOMAIN)


def good_fields(**kw):
    f = snapshot_to_rover_fields(snap(), NOW, 3.0, this_host=HOST)
    f.update(kw)
    return f


def test_pinned_interface_version():
    assert ROVER_FIELDS_SCHEMA == "team15.rover_range_fields/1"
    f = good_fields()
    assert f["schema"] == ROVER_FIELDS_SCHEMA and f["clock"] == DOMAIN


# --- verdict mapping through PR #7's own adapter --------------------------------------------
def test_fresh_clear():
    r = reading()
    assert (r.status, r.range_m, r.forward_allowed, r.hardware, r.service_status) == (OK, 1.8, True, True, "CLEAR")
    assert r.t == pytest.approx(NOW - 0.03)
    assert assess(r, NOW, 1.0, 0.2)[0] == Assessment.CLEAR


def test_caution_is_allowed():
    assert assess(reading(obst="CAUTION", rng=0.6), NOW, 0.5, 0.2)[0] == Assessment.CLEAR


def test_blocked_at_large_range_is_blocked():
    r = reading(obst="BLOCKED", rng=2.5, allowed=False)
    a, why = assess(r, NOW, 1.0, 0.2)
    assert r.status == OK and a == Assessment.BLOCKED and "BLOCKED" in why


def test_unknown_with_valid_range_is_not_clear():
    r = reading(obst="UNKNOWN", rng=1.8, allowed=False)   # e.g. filter window not full
    assert r.status == ERROR and assess(r, NOW, 1.0, 0.2)[0] == Assessment.UNKNOWN


def test_stale_snapshot_is_not_clear():
    r = reading(stale=True)
    assert r.status == ERROR and assess(r, NOW, 1.0, 0.2)[0] == Assessment.UNKNOWN


def test_old_monotonic_reading_is_stale_on_our_clock_too():
    r = reading(mono_ns=int((NOW - 0.25) * 1e9))  # their 0.5 s limit says fresh; ours is 0.2 s
    a, why = assess(r, NOW, 1.0, 0.2)
    assert a == Assessment.UNKNOWN and "stale" in why


def test_other_host_snapshot_rejected():
    r = reading(host="other-pi")
    assert r.status == ERROR and assess(r, NOW, 1.0, 0.2)[0] == Assessment.UNKNOWN


def test_fields_from_another_clock_domain_rejected():
    f = snapshot_to_rover_fields(snap(host="pi-b"), NOW, 3.0, this_host="pi-b")  # valid on pi-b's clock
    r = from_rover_fields(f, DOMAIN)                                               # we are testhost
    assert r.status == ERROR and "clock domain" in r.reason


@pytest.mark.parametrize("policy", list(NoEchoPolicy))
def test_hardware_no_echo_unknown_under_any_policy(policy):
    r = reading(obst="UNKNOWN", ms="NO_ECHO", rng=None, allowed=False)
    assert r.status == NO_ECHO and r.hardware
    a, why = assess(r, NOW, 1.0, 0.2, policy)
    assert a == Assessment.UNKNOWN and "real sensor" in why


@pytest.mark.parametrize("ms", ["ECHO_TIMEOUT", "LINE_STUCK_HIGH", "DRIVER_ERROR", "BELOW_MIN_RANGE", "NOT_STARTED"])
def test_fault_statuses_unknown(ms):
    r = reading(obst="UNKNOWN", ms=ms, rng=None, allowed=False)
    assert r.status == ERROR and assess(r, NOW, 0.3, 0.2)[0] == Assessment.UNKNOWN


def test_required_clearance_never_below_blocked_threshold():
    f = good_fields(range_m=0.30)  # 0.30 >= 0.28 threshold, so allowed stays consistent
    r = from_rover_fields(f, DOMAIN)
    assert assess(r, NOW, 0.05, 0.2)[0] == Assessment.CLEAR
    r2 = from_rover_fields(good_fields(range_m=0.25, forward_motion_allowed=False, obstacle_status="BLOCKED"), DOMAIN)
    assert assess(r2, NOW, 0.05, 0.2)[0] == Assessment.BLOCKED


# --- regression: numerical / status contradictions and malformed input -----------------------
CONTRADICTIONS = [
    dict(status="NO_ECHO", range_m=None, measurement_status="NO_ECHO"),          # allowed=True + NO_ECHO
    dict(obstacle_status="BLOCKED"),                                             # allowed=True + BLOCKED
    dict(obstacle_status="UNKNOWN"),                                             # OK + UNKNOWN verdict
    dict(range_m=0.10),                                                          # allowed below threshold
    dict(status="NO_ECHO", range_m=1.0, forward_motion_allowed=False, measurement_status="NO_ECHO"),
    dict(status="ERROR", range_m=1.0, forward_motion_allowed=False),             # ERROR carrying a range
    dict(range_m=None),                                                          # OK without range
    dict(range_m=-0.5),
    dict(range_m=99.0),                                                          # far beyond max_range_m
    dict(range_m=math.nan),
    dict(range_m=math.inf),
    dict(measurement_status="NO_ECHO"),                                          # OK but raw says no echo
    dict(status="NO_ECHO", range_m=None, forward_motion_allowed=False, measurement_status="VALID"),
]


@pytest.mark.parametrize("bad", CONTRADICTIONS)
def test_contradictions_become_error(bad):
    r = from_rover_fields(good_fields(**bad), DOMAIN)
    assert r.status == ERROR and r.forward_allowed is False and r.t == -math.inf, bad
    assert assess(r, NOW, 0.5, 0.2)[0] == Assessment.UNKNOWN


MALFORMED = [
    dict(schema="team15.rover_range_fields/2"), dict(schema=None), dict(clock="time.time@" + HOST),
    dict(source="other-sensor"), dict(t=math.nan), dict(t=math.inf), dict(t="5000"), dict(t=None),
    dict(seq=-1), dict(seq=True), dict(seq=1.5), dict(status="VALID"), dict(status=None),
    dict(obstacle_status="FINE"), dict(forward_motion_allowed="true"), dict(forward_motion_allowed=1),
    dict(max_range_m=0), dict(max_range_m=None), dict(blocked_threshold_m=-1), dict(blocked_threshold_m="x"),
]


@pytest.mark.parametrize("bad", MALFORMED)
def test_malformed_becomes_error(bad):
    r = from_rover_fields(good_fields(**bad), DOMAIN)
    assert r.status == ERROR and assess(r, NOW, 0.5, 0.2)[0] == Assessment.UNKNOWN, bad


@pytest.mark.parametrize("obj", [None, [], "x", 3, {}, {"error": "unreachable"}])
def test_non_dict_or_empty_becomes_error(obj):
    assert from_rover_fields(obj, DOMAIN).status == ERROR


@pytest.mark.parametrize("key", ["schema", "clock", "t", "status", "range_m", "forward_motion_allowed",
                                 "obstacle_status", "measurement_status", "seq", "source", "max_range_m"])
def test_each_missing_key_becomes_error(key):
    f = good_fields()
    del f[key]
    assert from_rover_fields(f, DOMAIN).status == ERROR


def test_epoch_timestamp_against_monotonic_clock_is_a_clock_fault():
    r = from_rover_fields(good_fields(t=1794094801.12), DOMAIN)
    a, why = assess(r, NOW, 1.0, 0.2)
    assert a == Assessment.UNKNOWN and "future" in why


# --- real PR #7 client on the real monotonic clock; service loss ------------------------------
def _write_snapshot(path, mono_ns, obst="CLEAR", rng=1.5, allowed=True):
    s = snap(obst=obst, rng=rng, allowed=allowed, host=socket.gethostname(), mono_ns=mono_ns)
    s["stale_after_s"] = 0.5
    path.write_text(json.dumps(s))


def test_real_client_real_monotonic_clock(tmp_path):
    p = tmp_path / "team15_range.json"
    _write_snapshot(p, time.monotonic_ns())
    io = PiRobotIO(GroveRangeIO(RangeClient(path=str(p)), max_range_m=3.0).read_fields)
    r = io.read_range()
    assert r.status == OK and io.clock_domain == clock_domain()
    assert assess(r, io.clock(), 1.0, 0.2)[0] == Assessment.CLEAR


def test_missing_service_fails_safe(tmp_path):
    io = PiRobotIO(GroveRangeIO(RangeClient(path=str(tmp_path / "absent.json")), max_range_m=3.0).read_fields)
    r = io.read_range()
    assert r.status == ERROR and r.t == -math.inf
    a, why = assess(r, io.clock(), 0.5, 0.2)
    assert a == Assessment.UNKNOWN and "stale" in why


def test_unreachable_http_service_fails_safe():
    io = PiRobotIO(GroveRangeIO(RangeClient(url="http://127.0.0.1:9/range", timeout_s=0.05), 3.0).read_fields)
    assert io.read_range().status == ERROR


def test_reader_exception_fails_safe():
    def boom():
        raise OSError("shm missing")
    r = PiRobotIO(boom, clock=lambda: NOW, host=HOST).read_range()
    assert r.status == ERROR and assess(r, NOW, 0.5, 0.2)[0] == Assessment.UNKNOWN


def test_default_pi_io_imports_pr7_adapter():
    io = PiRobotIO()
    assert io._range_fields.__self__.__class__ is GroveRangeIO


# --- forward gate in the supervisor (independent of the navigator) and service loss mid-motion ---
class Drv:
    name = "fake"
    physical = False

    def __init__(self):
        self.v = ZERO

    def apply(self, v):
        self.v = v

    def stop(self):
        self.v = ZERO


def _rig(source):
    clock = [NOW]
    io = PiRobotIO(source, clock=lambda: clock[0], host=HOST)
    d = Drv()
    s = SafetySupervisor(d, io.clock, MotionLimits())
    s.approve_motion("tester")

    def feed():
        s.heartbeat()
        r = io.read_range()
        a, why = assess(r, clock[0], 1.0, 0.2)
        s.update_range(r, a, why)
        s.update_power(PowerReading(clock[0], 4.0, "fake"))
    return clock, io, d, s, feed


def test_supervisor_refuses_forward_when_service_says_no_even_if_assessed_clear():
    f = good_fields(forward_motion_allowed=False, obstacle_status="CAUTION")
    clock, io, d, s, feed = _rig(lambda: dict(f, t=clock[0]))
    feed()
    s.update_range(s.range, Assessment.CLEAR, "forced CLEAR")   # simulate a buggy caller
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "forward_motion_allowed" in r.reason


@pytest.mark.parametrize("failure", ["missing", "stale", "blocked", "unknown", "contradiction", "exception"])
def test_forward_motion_stops_on_any_bad_reading(failure):
    state = {"mode": "ok"}

    def source():
        if state["mode"] == "ok":
            return good_fields(t=clock[0])
        if failure == "missing":
            return {"error": "range service unreachable"}
        if failure == "stale":
            return good_fields(t=clock[0] - 1.0)
        if failure == "blocked":
            return good_fields(t=clock[0], obstacle_status="BLOCKED", forward_motion_allowed=False, range_m=2.0)
        if failure == "unknown":
            return good_fields(t=clock[0], status="NO_ECHO", range_m=None, measurement_status="NO_ECHO",
                               obstacle_status="UNKNOWN", forward_motion_allowed=False)
        if failure == "contradiction":
            return good_fields(t=clock[0], obstacle_status="BLOCKED")  # BLOCKED but allowed=True
        raise OSError("reader crashed")

    clock, io, d, s, feed = _rig(source)
    feed()
    assert s.command(Command.MOVE_FORWARD, 0.2, 1.0).accepted
    for _ in range(3):
        clock[0] += 0.05
        feed()
        s.tick()
    assert d.v.vx > 0
    state["mode"] = "bad"
    clock[0] += 0.05
    feed()
    s.tick()
    assert d.v == ZERO and s.output == ZERO, failure
    if failure in ("missing", "stale", "contradiction", "exception"):
        assert s.latched == SafetyStop.SENSOR_STALE   # no usable data while moving: latched, no restart
    feed()
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted


def test_watchdog_and_estop_still_work_with_pi_io():
    clock, io, d, s, feed = _rig(lambda: good_fields(t=clock[0]))
    feed()
    assert s.command(Command.TURN_LEFT, 0.2, 1.0).accepted
    clock[0] += 0.05
    feed()
    s.tick()
    s.command(Command.EMERGENCY_STOP)
    assert d.v == ZERO and s.estop.tripped and s.latched == SafetyStop.ESTOP


# --- navigator on the real Pi IO -------------------------------------------------------------
class NullDriver:
    name = "none"
    physical = True

    def __init__(self):
        self.applied = []

    def apply(self, v):
        self.applied.append(v)

    def stop(self):
        pass


def test_navigator_on_pi_io_refuses_clear_to_max_and_never_moves():
    clock = [NOW]
    io = PiRobotIO(lambda: good_fields(t=clock[0]), clock=lambda: clock[0], host=HOST)
    drv = NullDriver()
    sup = SafetySupervisor(drv, io.clock, MotionLimits())
    log = ObservationLog(io.clock)
    with pytest.raises(PermissionError):
        Navigator(load_graph(), io, sup, log, NavConfig(robot_width_m=0.2, no_echo_policy=NoEchoPolicy.CLEAR_TO_MAX))
    nav = Navigator(load_graph(), io, sup, log, NavConfig(robot_width_m=0.2, scan_settle_readings=3), mode="HARDWARE")
    nav.start("G")
    for _ in range(20):
        clock[0] += 0.05
        nav.tick()
    st = nav.status()
    assert st["state"] == State.CONTINUE_OR_REQUEST_OPERATOR.value
    assert nav.operator_requests[-1]["kind"] == "POSE_UNKNOWN"
    assert st["pose"] == {"source": "UNKNOWN"} and st["heading"]["source"] == "UNKNOWN"
    assert st["traveled"] == {"value_m": None, "kind": "UNKNOWN"}
    assert st["claims"]["localization"] == "NONE"
    assert all(v.is_zero() for v in drv.applied)

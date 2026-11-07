"""Adopt PR #7 ranging/rover_io.py fields. forward_motion_allowed is ANDed in, hardware no-echo is
UNKNOWN, and timestamps are compared on the monotonic clock.

The field dicts below match what PR #7 snapshot_to_rover_fields() returns (commit 19c43d8).
"""
import math

import pytest

from rover.motion import MotionLimits, SafetySupervisor
from rover.navigator import NavConfig, Navigator, State
from rover.observations import ObservationLog
from rover.pi_io import PiRobotIO
from rover.sensors import ERROR, NO_ECHO, OK, Assessment, NoEchoPolicy, assess, from_rover_fields
from planner.graph import load_graph

NOW = 5000.0  # a time.monotonic()-style value, not an epoch


def fields(**kw):
    f = {"t": NOW - 0.03, "status": "OK", "range_m": 1.8, "max_range_m": 3.0, "source": "grove-ultrasonic",
         "seq": 412, "forward_motion_allowed": True, "obstacle_status": "CLEAR", "measurement_status": "VALID",
         "reason": "clear", "blocked_threshold_m": 0.28, "diagnosis": None, "source_mode": "LIVE-HW"}
    f.update(kw)
    return f


def test_valid_clear():
    r = from_rover_fields(fields())
    assert (r.status, r.range_m, r.t, r.seq, r.hardware, r.forward_allowed) == (OK, 1.8, NOW - 0.03, 412, True, True)
    assert assess(r, NOW, 1.0, 0.2)[0] == Assessment.CLEAR


def test_forward_motion_allowed_false_is_never_clear():
    # range looks long enough, but the ranging service says no (e.g. its filter is not settled)
    r = from_rover_fields(fields(forward_motion_allowed=False, obstacle_status="UNKNOWN"))
    a, why = assess(r, NOW, 1.0, 0.2)
    assert a == Assessment.UNKNOWN and "forward_motion_allowed" in why


def test_required_clearance_never_below_grove_blocked_threshold():
    r = from_rover_fields(fields(range_m=0.25, forward_motion_allowed=False, obstacle_status="BLOCKED"))
    assert assess(r, NOW, 0.05, 0.2)[0] == Assessment.BLOCKED  # 0.25 < 0.28 threshold, even though 0.25 > 0.05


@pytest.mark.parametrize("policy", list(NoEchoPolicy))
def test_hardware_no_echo_is_unknown_under_any_policy(policy):
    r = from_rover_fields(fields(status="NO_ECHO", range_m=None, forward_motion_allowed=False,
                                 measurement_status="NO_ECHO"))
    assert r.status == NO_ECHO and r.hardware
    a, why = assess(r, NOW, 1.0, 0.2, policy)
    assert a == Assessment.UNKNOWN and "real sensor" in why


def test_simulated_grove_source_is_not_hardware():
    r = from_rover_fields(fields(source_mode="SIMULATED"))
    assert r.hardware is False


@pytest.mark.parametrize("dt,expected", [(0.0, Assessment.CLEAR), (0.19, Assessment.CLEAR),
                                         (0.21, Assessment.UNKNOWN), (-0.04, Assessment.CLEAR),
                                         (-0.06, Assessment.UNKNOWN)])
def test_monotonic_freshness_and_future_timestamps(dt, expected):
    r = from_rover_fields(fields(t=NOW))
    assert assess(r, NOW + dt, 1.0, 0.2)[0] == expected


def test_epoch_timestamp_on_monotonic_clock_is_rejected():
    """A wall-clock (epoch) t compared against monotonic now looks decades in the future: a clock fault."""
    r = from_rover_fields(fields(t=1794094801.12))
    a, why = assess(r, NOW, 1.0, 0.2)
    assert a == Assessment.UNKNOWN and "future" in why


@pytest.mark.parametrize("bad", [{"t": math.nan}, {"t": math.inf}, {"t": None}, {"status": "VALID"},
                                 {"range_m": None}, {"range_m": -1.0}, {"range_m": math.nan},
                                 {"max_range_m": None}])
def test_malformed_fields_become_stale_error(bad):
    r = from_rover_fields(fields(**bad))
    assert r.status == ERROR and r.forward_allowed is False
    assert assess(r, NOW, 0.5, 0.2)[0] == Assessment.UNKNOWN


def test_missing_key_becomes_error():
    f = fields()
    del f["forward_motion_allowed"]
    assert from_rover_fields(f).status == ERROR


@pytest.mark.parametrize("status", ["ERROR"])
def test_error_status_unknown(status):
    r = from_rover_fields(fields(status=status, range_m=None, forward_motion_allowed=False))
    assert assess(r, NOW, 0.5, 0.2)[0] == Assessment.UNKNOWN


def test_nan_now_unknown():
    r = from_rover_fields(fields())
    assert assess(r, math.nan, 0.5, 0.2)[0] == Assessment.UNKNOWN


# --- PiRobotIO: what the real Pi reports, and the navigator refusing to move ------------------
class NullDriver:
    name = "none"
    physical = True

    def __init__(self):
        self.applied = []

    def apply(self, v):
        self.applied.append(v)

    def stop(self):
        pass


def test_pi_io_reader_exception_is_error_not_clear():
    io = PiRobotIO(lambda: (_ for _ in ()).throw(OSError("shm missing")), clock=lambda: NOW)
    r = io.read_range()
    assert r.status == ERROR and assess(r, NOW, 0.5, 0.2)[0] == Assessment.UNKNOWN


def test_pi_io_navigator_refuses_clear_to_max_and_holds_for_operator():
    clock = [NOW]
    io = PiRobotIO(lambda: fields(t=clock[0]), clock=lambda: clock[0])
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
    assert all(v.is_zero() for v in drv.applied)  # no motion was ever produced

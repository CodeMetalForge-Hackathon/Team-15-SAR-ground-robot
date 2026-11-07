"""Gate 2: simulated motor commands, bounds, watchdog, e-stop, latches. Deterministic fake clock."""
import pytest

from rover.motion import (Command, DirectionEvidence, EmergencyStop, MotionLimits, SafetyStop,
                          SafetySupervisor, ZERO)
from rover.sensors import OK, Assessment, PowerReading, RangeReading


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Drv:
    name = "fake"

    def __init__(self, physical=False):
        self.physical = physical
        self.v = None
        self.stops = 0
        self.fail = False

    def apply(self, v):
        if self.fail:
            raise IOError("bus error")
        self.v = v

    def stop(self):
        self.stops += 1
        self.v = ZERO


def fresh(s, c, clear=True, volts=4.0):
    s.heartbeat()
    s.update_range(RangeReading(c.t, OK, 2.0, 3.5, "fake"), Assessment.CLEAR if clear else Assessment.BLOCKED)
    s.update_power(PowerReading(c.t, volts, "fake"))


def rig(physical=False, limits=MotionLimits(), approve=True):
    c, d = Clock(), Drv(physical)
    s = SafetySupervisor(d, c, limits)
    if approve:
        s.approve_motion("tester")
    fresh(s, c)
    return c, d, s


def advance(c, s, dt, keep_fresh=True, **kw):
    end = c.t + dt
    while c.t < end - 1e-9:
        c.t = round(c.t + 0.05, 6)
        if keep_fresh:
            fresh(s, c, **kw)
        s.tick()


def test_default_output_zero():
    c, d, s = rig(approve=False)
    assert d.stops == 1 and s.output == ZERO and d.v == ZERO


def test_motion_requires_operator_approval():
    c, d, s = rig(approve=False)
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "approval" in r.reason


@pytest.mark.parametrize("speed,dur", [(0.2, 0), (0.2, 1.01), (0.2, -1), (0.31, 0.5), (0, 0.5), (-0.1, 0.5)])
def test_bounded_speed_and_duration(speed, dur):
    c, d, s = rig()
    assert not s.command(Command.MOVE_FORWARD, speed, dur).accepted


def test_command_expires_no_indefinite_motion():
    c, d, s = rig()
    assert s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted
    advance(c, s, 0.3)
    assert s.output.vx > 0
    advance(c, s, 0.3)
    assert s.output == ZERO and "elapsed" in s.last_stop_reason


def test_acceleration_is_ramped_stop_is_immediate():
    c, d, s = rig(limits=MotionLimits(max_accel_per_s=0.5))
    s.command(Command.MOVE_FORWARD, 0.3, 1.0)
    advance(c, s, 0.1)
    assert s.output.vx == pytest.approx(0.05)
    s.command(Command.STOP)
    assert s.output == ZERO and d.v == ZERO


def test_forward_refused_unless_clear_and_stops_when_blocked():
    c, d, s = rig()
    fresh(s, c, clear=False)
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted
    fresh(s, c, clear=True)
    assert s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted
    advance(c, s, 0.2)
    advance(c, s, 0.05, clear=False)
    assert s.output == ZERO and s.latched is None  # an obstacle stop is a normal stop, not a fault


def test_backward_and_strafe_need_operator_evidence():
    c, d, s = rig()
    for cmd in (Command.MOVE_BACKWARD, Command.STRAFE_LEFT, Command.STRAFE_RIGHT):
        r = s.command(cmd, 0.1, 0.3)
        assert not r.accepted and "no sensor covers" in r.reason
    ev = DirectionEvidence(Command.STRAFE_LEFT, c.t, given_by="tester")
    assert s.command(Command.STRAFE_LEFT, 0.1, 0.3, evidence=ev).accepted
    c.t += 3.0
    fresh(s, c)
    assert not s.command(Command.STRAFE_LEFT, 0.1, 0.3, evidence=ev).accepted  # evidence expired


def test_move_to_waypoint_not_a_raw_command():
    c, d, s = rig()
    r = s.command(Command.MOVE_TO_WAYPOINT, 0.1, 0.5)
    assert not r.accepted and "localization" in r.reason


def test_watchdog_lost_heartbeat_latches_and_no_auto_restart():
    c, d, s = rig()
    s.command(Command.MOVE_FORWARD, 0.2, 1.0)
    advance(c, s, 0.1)
    for _ in range(8):  # sensors stay fresh, but the control loop stops calling heartbeat()
        c.t = round(c.t + 0.05, 6)
        s.update_range(RangeReading(c.t, OK, 2.0, 3.5, "fake"), Assessment.CLEAR)
        s.update_power(PowerReading(c.t, 4.0, "fake"))
        s.tick()
    assert s.latched == SafetyStop.COMMS_LOST and s.output == ZERO and d.v == ZERO
    fresh(s, c)
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted       # still latched
    s.reset_latch("tester")
    fresh(s, c)
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted       # approval was revoked
    s.approve_motion("tester")
    assert s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted


def test_stale_sensor_while_moving_latches():
    c, d, s = rig()
    s.command(Command.TURN_LEFT, 0.2, 1.0)
    advance(c, s, 0.1)
    for _ in range(6):
        c.t += 0.05
        s.heartbeat()
        s.tick()
    assert s.latched == SafetyStop.SENSOR_STALE and s.output == ZERO


def test_undervoltage_refuses_and_latches():
    c, d, s = rig(limits=MotionLimits(min_voltage_v=3.6))
    fresh(s, c, volts=3.4)
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "undervoltage" in r.reason
    fresh(s, c, volts=4.0)
    assert s.command(Command.MOVE_FORWARD, 0.2, 1.0).accepted
    advance(c, s, 0.1, volts=3.4)
    assert s.latched == SafetyStop.UNDERVOLTAGE and s.output == ZERO


def test_physical_driver_without_measured_voltage_threshold_refuses():
    c, d, s = rig(physical=True)
    r = s.command(Command.TURN_LEFT, 0.1, 0.3)
    assert not r.accepted and "threshold" in r.reason


def test_emergency_stop_latched_and_resettable_only_by_operator():
    c, d, s = rig()
    s.command(Command.MOVE_FORWARD, 0.2, 1.0)
    advance(c, s, 0.2)
    assert s.command(Command.EMERGENCY_STOP).accepted
    assert s.output == ZERO and d.v == ZERO and s.estop.tripped
    fresh(s, c)
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted
    with pytest.raises(PermissionError):
        s.estop.reset("")
    s.estop.reset("tester")
    s.reset_latch("tester")
    s.approve_motion("tester")
    fresh(s, c)
    assert s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted


def test_estop_trip_runs_all_stops_even_if_one_raises():
    e = EmergencyStop()
    calls = []

    def dead():
        raise IOError("dead link")

    e.register(dead)
    e.register(lambda: calls.append("second"))
    e.trip("test")
    assert e.tripped and calls == ["second"] and e.errors


def test_stop_file_trips_estop(tmp_path):
    f = tmp_path / "STOP"
    c, d = Clock(), Drv()
    s = SafetySupervisor(d, c, estop=EmergencyStop(stop_file=str(f)))
    s.approve_motion("tester")
    fresh(s, c)
    s.command(Command.TURN_LEFT, 0.2, 1.0)
    advance(c, s, 0.1)
    f.write_text("stop")
    advance(c, s, 0.05)
    assert s.estop.tripped and s.output == ZERO
    with pytest.raises(PermissionError):
        s.estop.reset("tester")  # file still present


def test_driver_fault_latches():
    c, d, s = rig()
    s.command(Command.TURN_LEFT, 0.2, 1.0)
    d.fail = True
    advance(c, s, 0.1)
    assert s.latched == SafetyStop.DRIVER_FAULT and d.v == ZERO

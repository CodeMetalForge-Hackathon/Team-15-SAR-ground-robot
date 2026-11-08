"""Issue #9: fail-closed forward motion, plus driver-link and power fail-closed checks.

MOVE_FORWARD needs, all at once: assessment CLEAR, forward_allowed *is True* (None = not asserted),
and a fresh, finite, non-future reading (0.20 s). A hardware reading must also be status OK.
Simulation only: deterministic fake clock and fake drivers. No hardware is touched.
"""
import math
import pathlib

import pytest

from rover.hardware import RecordingTransport, RoverCAdapter
from rover.motion import Command, EmergencyStop, MotionLimits, SafetyStop, SafetySupervisor, ZERO
from rover.protocol import HardwareVerification, WheelMapping
from rover.sensors import ERROR, NO_ECHO, OK, Assessment, PowerReading, RangeReading, _error, from_rover_fields
from rover.simrun import build

MAX_AGE = MotionLimits().sensor_max_age_s


class Clock:
    def __init__(self):
        self.t = 10.0

    def __call__(self):
        return self.t


class Drv:
    name = "fake"

    def __init__(self, physical=False, with_health=True):
        self.physical = physical
        self.v = ZERO
        self.link = ""
        if with_health:
            self.health = lambda: self.link

    def apply(self, v):
        self.v = v

    def stop(self):
        self.v = ZERO


def reading(t, allowed=True, status=OK, rng=2.0, hardware=False):
    return RangeReading(t, status, rng if status == OK else None, 3.5, "fake", forward_allowed=allowed,
                        hardware=hardware)


def rig(allowed=True, assessment=Assessment.CLEAR, physical=False, with_health=True, limits=None):
    c = Clock()
    d = Drv(physical, with_health)
    s = SafetySupervisor(d, c, limits or MotionLimits(min_voltage_v=3.3 if physical else None))
    s.approve_motion("tester")
    feed(s, c, allowed, assessment)
    return c, d, s


def feed(s, c, allowed=True, assessment=Assessment.CLEAR, r=None, volts=4.0):
    s.heartbeat()
    s.update_range(r if r is not None else reading(c.t, allowed), assessment, "test")
    s.update_power(PowerReading(c.t, volts, "fake"))


def step(c, s, n=1, **kw):
    for _ in range(n):
        c.t = round(c.t + 0.05, 6)
        feed(s, c, **kw)
        s.tick()


def moving_forward():
    c, d, s = rig()
    assert s.command(Command.MOVE_FORWARD, 0.2, 1.0).accepted
    step(c, s, 3)
    assert not s.output.is_zero()
    return c, d, s


# --- positive control ------------------------------------------------------------------------------
def test_explicit_true_clear_fresh_is_accepted():
    c, d, s = rig()
    assert s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted
    step(c, s, 2)
    assert s.output.vx > 0 and d.v.vx > 0


# --- forward_allowed must be asserted ---------------------------------------------------------------
def test_forward_allowed_none_refuses_forward():
    c, d, s = rig(allowed=None)
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "not asserted" in r.reason and d.v == ZERO


def test_forward_allowed_false_refuses_forward():
    c, d, s = rig(allowed=False)
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "forward_motion_allowed=false" in r.reason


@pytest.mark.parametrize("allowed", [None, False])
def test_verdict_lost_while_moving_stops(allowed):
    c, d, s = moving_forward()
    step(c, s, 1, allowed=allowed)
    assert s.output == ZERO and d.v == ZERO and s.active == Command.STOP


def test_stop_on_lost_verdict_does_not_restart_when_verdict_returns():
    c, d, s = moving_forward()
    step(c, s, 1, allowed=None)
    step(c, s, 5, allowed=True)
    assert s.output == ZERO and s.active == Command.STOP  # a new command is required


@pytest.mark.parametrize("assessment", [Assessment.UNKNOWN, Assessment.BLOCKED])
def test_true_but_not_clear_refuses(assessment):
    c, d, s = rig(allowed=True, assessment=assessment)
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted


def test_hardware_reading_must_state_a_verdict():
    with pytest.raises(ValueError):
        RangeReading(1.0, OK, 2.0, 3.5, "grove-ultrasonic", hardware=True)  # forward_allowed=None


@pytest.mark.parametrize("bad", [1, 0, "true", "false", 1.0])
def test_forward_allowed_must_be_a_real_bool(bad):
    with pytest.raises(ValueError):
        RangeReading(1.0, OK, 2.0, 3.5, "fake", forward_allowed=bad)


@pytest.mark.parametrize("status", [NO_ECHO, ERROR])
def test_forged_hardware_true_with_non_ok_status_refuses(status):
    c, d, s = rig()
    feed(s, c, r=reading(c.t, True, status=status, hardware=True))
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "cannot authorize" in r.reason


# --- missing / stale / invalid readings ------------------------------------------------------------
def test_missing_reading_refuses_and_latches_while_moving():
    c, d, s = rig()
    s.update_range(None, Assessment.CLEAR)
    assert not s.command(Command.TURN_LEFT, 0.2, 0.5).accepted
    c, d, s = moving_forward()
    s.update_range(None, Assessment.CLEAR)
    c.t += 0.05
    s.tick()
    assert s.latched == SafetyStop.SENSOR_STALE and s.output == ZERO and s.approved_by is None


def test_true_but_stale_refuses_and_latches_while_moving():
    c, d, s = rig()
    s.update_range(reading(c.t - MAX_AGE - 0.01), Assessment.CLEAR)
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "stale" in r.reason
    c, d, s = moving_forward()
    old = s.range
    for _ in range(5):  # verdict stays True and CLEAR, but the reading never refreshes
        c.t = round(c.t + 0.05, 6)
        s.heartbeat()
        s.update_range(old, Assessment.CLEAR)
        s.update_power(PowerReading(c.t, 4.0, "fake"))
        s.tick()
    assert s.latched == SafetyStop.SENSOR_STALE and s.output == ZERO


@pytest.mark.parametrize("t", [math.nan, math.inf, -math.inf])
def test_non_finite_timestamp_refuses(t):
    c, d, s = rig()
    s.update_range(reading(t), Assessment.CLEAR)
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "range" in r.reason


def test_nan_timestamp_while_moving_latches():
    c, d, s = moving_forward()
    s.update_range(reading(math.nan), Assessment.CLEAR)
    c.t += 0.05
    s.tick()
    assert s.latched == SafetyStop.SENSOR_STALE and s.output == ZERO


def test_future_timestamp_is_a_clock_fault():
    c, d, s = rig()
    s.update_range(reading(c.t + 0.2), Assessment.CLEAR)
    r = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "future" in r.reason


def test_error_and_malformed_readings_refuse():
    c, d, s = rig()
    s.update_range(_error("service down"), Assessment.CLEAR)  # even if a caller forges CLEAR
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted
    s.update_range(from_rover_fields({"schema": "garbage"}, "time.monotonic@h"), Assessment.CLEAR)
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted


# --- controller link (driver health) ---------------------------------------------------------------
def test_physical_driver_without_health_refuses():
    c, d, s = rig(physical=True, with_health=False)
    r = s.command(Command.TURN_LEFT, 0.1, 0.3)
    assert not r.accepted and "health" in r.reason


def test_physical_driver_healthy_link_accepts_turn():  # positive control for the link check
    c, d, s = rig(physical=True)
    assert s.command(Command.TURN_LEFT, 0.1, 0.3).accepted


def test_controller_disconnect_refuses_motion():
    c, d, s = rig(physical=True)
    d.link = "no ack from controller for 0.4 s"
    r = s.command(Command.MOVE_FORWARD, 0.1, 0.3)
    assert not r.accepted and "driver fault" in r.reason


def test_controller_disconnect_while_moving_latches_and_never_auto_restarts():
    c, d, s = rig(physical=True)
    assert s.command(Command.MOVE_FORWARD, 0.2, 1.0).accepted
    step(c, s, 2)
    d.link = "serial port closed"
    step(c, s, 1)
    assert s.latched == SafetyStop.DRIVER_FAULT and s.output == ZERO and d.v == ZERO and s.approved_by is None
    d.link = ""  # link comes back
    step(c, s, 5)
    assert s.output == ZERO and not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted
    s.reset_latch("operator")
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted  # approval was revoked
    s.approve_motion("operator")
    feed(s, c)
    assert s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted


def test_health_check_that_raises_is_a_fault():
    c, d, s = rig(physical=True)

    def boom():
        raise OSError("device vanished")
    d.health = boom
    r = s.command(Command.TURN_RIGHT, 0.1, 0.3)
    assert not r.accepted and "health check failed" in r.reason


def test_roverc_adapter_health_needs_transport_health():
    v = HardwareVerification(
        controller_model="TEST", controller_firmware="TEST", roverc_revision="TEST", link="TEST",
        wiring_verified_by="TEST", power_verified_by="TEST", stop_on_link_loss_ms=300,
        wheel_mapping=WheelMapping(1, 1, 1, evidence="TEST FIXTURE - not a real bench result"))
    assert RoverCAdapter(RecordingTransport(), v).health() == ""

    assert "no link health" in RoverCAdapter(RecordingTransport(physical=True), v).health()

    class LinkDown(RecordingTransport):
        def health(self):
            return "no ack for 0.4 s"
    assert RoverCAdapter(LinkDown(physical=True), v).health() == "no ack for 0.4 s"


# --- power -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("volts", [math.nan, math.inf, None])
def test_invalid_power_refuses(volts):
    c, d, s = rig()
    s.update_power(PowerReading(c.t, volts, "fake"))
    assert not s.command(Command.TURN_LEFT, 0.1, 0.3).accepted


def test_future_or_nan_power_timestamp_refuses():
    c, d, s = rig()
    for t in (c.t + 1.0, math.nan):
        s.update_power(PowerReading(t, 4.0, "fake"))
        assert not s.command(Command.TURN_LEFT, 0.1, 0.3).accepted


def test_power_lost_while_moving_latches():
    c, d, s = moving_forward()
    c.t += 0.05
    s.heartbeat()
    s.update_range(reading(c.t), Assessment.CLEAR)
    s.update_power(None)
    s.tick()
    assert s.latched == SafetyStop.POWER_UNKNOWN and s.output == ZERO


# --- e-stop preserved ------------------------------------------------------------------------------
def test_estop_latch_and_operator_reset_preserved():
    c, d, s = moving_forward()
    assert s.command(Command.EMERGENCY_STOP).accepted
    assert s.output == ZERO and s.estop.tripped and s.latched == SafetyStop.ESTOP
    feed(s, c)
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted
    with pytest.raises(PermissionError):
        s.estop.reset("")
    s.estop.reset("operator")
    s.reset_latch("operator")
    assert not s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted  # still needs fresh approval
    s.approve_motion("operator")
    assert s.command(Command.MOVE_FORWARD, 0.2, 0.5).accepted


def test_stop_file_still_trips(tmp_path):
    f = tmp_path / "STOP"
    c = Clock()
    s = SafetySupervisor(Drv(), c, MotionLimits(), EmergencyStop(str(f)))
    s.approve_motion("tester")
    feed(s, c)
    assert s.command(Command.MOVE_FORWARD, 0.2, 1.0).accepted
    f.write_text("stop")
    step(c, s, 1)
    assert s.estop.tripped and s.output == ZERO


# --- simulator asserts explicitly; no model has motor authority ---------------------------------------
def test_sim_readings_always_assert_a_verdict():
    sim = build("A")
    for _ in range(20):
        r = sim.world.read_range()
        assert r is not None and r.forward_allowed in (True, False)
        sim.world.t += 0.05


# Modules allowed to touch the motor path. Everything else (Qwen/LLM glue, dashboard, perception, ranging,
# rover/pi_io.py, rover/status_api.py, any new rover module) must not. Adding a file here needs review.
MOTOR_PATH_ALLOWED = {"rover/motion.py", "rover/hardware.py", "rover/protocol.py", "rover/navigator.py",
                      "rover/sim.py", "rover/simrun.py", "rover/bridge.py",
                      "rover/mac_host.py"}  # Mac host loop: camera veto -> supervisor -> bridge (reviewed PR)
MOTOR_PATH_NAMES = ("rover.motion", "rover.hardware", "rover.protocol", "rover.bridge", "SafetySupervisor",
                    "RoverCAdapter", "BridgeTransport", "open_serial", "encode_motor_block", "approve_motion")


def test_nothing_outside_the_allow_list_can_reach_the_motor_path():
    """No LLM/Qwen, dashboard, perception or ranging code (and no unreviewed rover module) may import the
    supervisor, the hardware driver, the motor protocol or the USB bridge."""
    root = pathlib.Path(__file__).resolve().parents[2]
    offenders = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        top = rel.split("/")[0]
        if top in (".git", ".claude") or "site-packages" in rel or "/tests/" in f"/{rel}" or rel in MOTOR_PATH_ALLOWED:
            continue
        text = p.read_text(errors="ignore")
        offenders += [f"{rel}: {b}" for b in MOTOR_PATH_NAMES if b in text]
    assert offenders == []


def test_dead_link_never_crashes_tick_and_stays_latched():
    """A controller that throws on every write (cable pulled) must not crash the control loop."""
    c, d, s = moving_forward()

    def dead(*_):
        raise OSError("serial port disconnected")
    d.apply = dead
    d.stop = dead
    for _ in range(10):
        c.t = round(c.t + 0.05, 6)
        feed(s, c)
        s.tick()  # must not raise
    assert s.latched == SafetyStop.DRIVER_FAULT and s.output == ZERO and s.approved_by is None
    assert any(e.kind == "DRIVER_STOP_FAILED" for e in s.events)

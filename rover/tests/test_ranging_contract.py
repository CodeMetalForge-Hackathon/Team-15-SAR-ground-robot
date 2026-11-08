"""Rover <- ranging contract (PR #7 at ee56359 or later). Simulation only, no GPIO.

Rover pins only:
  - the corrected ranging copy is present (SIG-idle pull-down gate, <= 1.2 V);
  - the versioned interface team15.rover_range_fields/1 and its fail-safe mapping;
  - navigator behaviour when ranging fails.
The electrical-gate cases themselves are owned and tested in ranging/tests.
"""
import math
import pathlib

import pytest

import ranging
import ranging.rover_io as rio
from ranging import config as rcfg
from ranging.rover_io import ROVER_FIELDS_SCHEMA, snapshot_to_rover_fields
from rover.motion import Command, MotionLimits, SafetySupervisor, ZERO
from rover.pi_io import PiRobotIO
from rover.sensors import ERROR, OK, Assessment, PowerReading, assess, from_rover_fields

REPO = pathlib.Path(__file__).resolve().parents[2]
HOST = "h1"
DOMAIN = "time.monotonic@" + HOST
NOW = 5.1


def test_ranging_package_is_the_in_repo_corrected_copy():
    assert pathlib.Path(ranging.__file__).resolve().parent == REPO / "ranging"
    limit = getattr(rcfg, "SIG_IDLE_MAX_V", None)
    assert limit is not None, "pre-ee56359 ranging copy: no SIG-idle pull-down gate"
    assert limit <= 1.2


def test_rover_interface_version_unchanged():
    assert ROVER_FIELDS_SCHEMA == "team15.rover_range_fields/1"


def _snap(ms="VALID", obst="CLEAR", rng=1.2, stale=False, allowed=True, host=HOST):
    return {"latest": {"mono_ns": 5_000_000_000, "seq": 7, "measurement_status": ms},
            "provenance": {"host": host, "source_mode": "SIMULATED"}, "obstacle_status": obst,
            "freshness": {"stale": stale}, "range_m": rng, "forward_motion_allowed": allowed,
            "assessment": {"thresholds": {"blocked_m": 0.4}}}


@pytest.mark.parametrize("snap,status,allowed", [
    (_snap(), "OK", True),
    (_snap(stale=True), "ERROR", False),
    (_snap(ms="NO_ECHO", obst="UNKNOWN", rng=None, allowed=False), "NO_ECHO", False),
    (_snap(ms="LINE_STUCK_HIGH", obst="UNKNOWN", rng=None, allowed=False), "ERROR", False),
    (_snap(host="other"), "ERROR", False),
    (_snap(allowed=False, obst="BLOCKED", rng=0.2), "OK", False),
])
def test_rover_fields_mapping_fail_safe(snap, status, allowed):
    f = snapshot_to_rover_fields(snap, now_mono_s=NOW, max_range_m=3.5, this_host=HOST)
    assert f["status"] == status and f["forward_motion_allowed"] is allowed
    assert f["schema"] == ROVER_FIELDS_SCHEMA


class _Drv:
    physical = False

    def __init__(self):
        self.v = ZERO

    def apply(self, v):
        self.v = v

    def stop(self):
        self.v = ZERO


def test_navigator_reader_failure_is_error_and_refuses_forward():
    clock = [NOW]
    io = PiRobotIO(range_fields=lambda: (_ for _ in ()).throw(RuntimeError("ranging down")),
                   clock=lambda: clock[0], host=HOST)
    r = io.read_range()
    assert r is not None and r.status == ERROR and not math.isfinite(r.t)
    a, _ = assess(r, clock[0], 1.0, 0.2)
    assert a != Assessment.CLEAR
    s = SafetySupervisor(_Drv(), io.clock, MotionLimits())
    s.approve_motion("tester")
    s.heartbeat()
    s.update_range(r, a, "reader failure")
    s.update_power(PowerReading(clock[0], 4.0, "fake"))
    d = s.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not d.accepted and s.driver.v == ZERO


def test_pi_io_default_reader_consumes_ranging_rover_io(monkeypatch):
    """With no injected reader, PiRobotIO must read through ranging.rover_io.GroveRangeIO."""
    clock = [NOW]
    fields = snapshot_to_rover_fields(_snap(rng=1.7), now_mono_s=NOW, max_range_m=3.5, this_host=HOST)
    fields["t"] = NOW - 0.05
    monkeypatch.setattr(rio.GroveRangeIO, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(rio.GroveRangeIO, "read_fields", lambda self: dict(fields))
    io = PiRobotIO(clock=lambda: clock[0], host=HOST)
    r = io.read_range()
    assert r.status == OK and r.range_m == pytest.approx(1.7) and r.seq == 7
    monkeypatch.setattr(rio.GroveRangeIO, "read_fields", lambda self: dict(fields, status="NO_ECHO", range_m=None,
                                                                          forward_motion_allowed=False))
    io2 = PiRobotIO(clock=lambda: clock[0], host=HOST)
    assert io2.read_range().status != OK


def test_from_rover_fields_rejects_other_clock_domain():
    f = snapshot_to_rover_fields(_snap(), now_mono_s=NOW, max_range_m=3.5, this_host=HOST)
    assert from_rover_fields(f, "time.monotonic@some-other-host").status != OK

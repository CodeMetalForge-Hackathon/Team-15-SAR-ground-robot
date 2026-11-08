"""Wheels-lifted bench mode against the executable firmware model. No hardware."""
import pytest

from rover.bench import PULSE_CAP_S, SPEED_CAP, Bench, BenchRefused
from rover.bridge import BridgeTransport
from rover.tests.bridge_model import BridgeFirmwareModel, LoopbackPort
from rover.tests.test_bridge import Clock


def rig(**kw):
    c = Clock()
    fw = BridgeFirmwareModel(c)
    port = LoopbackPort(fw)
    tr = BridgeTransport(port, c)
    seen = []

    def sleep(dt):
        end = c.t + dt
        while c.t < end - 1e-9:
            c.t = round(c.t + 0.005, 6)
            fw.loop()
            seen.append(tuple(fw.i2c.regs[i] for i in range(4)))

    args = dict(operator="op1", battery_v=3.95, min_battery_v=3.6, wheels_lifted=True)
    args.update(kw)
    return c, fw, port, Bench(tr, c, sleep, pump=fw.loop, **args), seen


def test_forward_pulse_is_bounded_and_ends_at_confirmed_zero():
    c, fw, port, b, seen = rig()
    r = b.pulse("forward")
    assert r["raw_y"] == 15 and r["registers"] == [15, 15, 15, 15]
    assert r["commanded_s"] <= PULSE_CAP_S + 0.06
    assert any(any(s) for s in seen)                       # wheels were commanded
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}         # and are zero afterwards
    assert r["after_stop"]["state"] in ("ARMED", "DISARMED")


def test_backward_pulse_uses_negative_raw_y():
    c, fw, port, b, seen = rig()
    assert b.pulse("backward")["registers"] == [-15, -15, -15, -15]
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


@pytest.mark.parametrize("kw,match", [
    ({"wheels_lifted": False}, "wheels-lifted"),
    ({"battery_v": None}, "battery"),
    ({"min_battery_v": None}, "battery"),
    ({"battery_v": 3.4}, "charge first"),
    ({"battery_v": 12.0}, "single Li-ion"),
    ({"operator": " "}, "named operator"),
])
def test_gate_refuses_without_every_precondition(kw, match):
    c, fw, port, b, seen = rig(**kw)
    with pytest.raises(BenchRefused, match=match):
        b.pulse("forward")
    assert not any(any(s) for s in seen) and fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


@pytest.mark.parametrize("speed,dur", [(SPEED_CAP + 1, 0.2), (0, 0.2), (10, 0.31), (10, 0.0)])
def test_speed_and_duration_hard_caps(speed, dur):
    c, fw, port, b, seen = rig()
    with pytest.raises(BenchRefused):
        b.pulse("forward", speed, dur)
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


def test_watchdog_check_passes_on_bridge_firmware():
    c, fw, port, b, seen = rig()
    r = b.watchdog()
    assert r["ok"] and r["state_after_silence"] == "WDSTOP" and r["wd_trips"] == [0, 1]
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


def test_estop_on_the_stickc_refuses_pulses():
    c, fw, port, b, seen = rig()
    fw.button_a()
    with pytest.raises(BenchRefused, match="ESTOP"):
        b.pulse("forward")
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


def test_unknown_firmware_never_acks_and_is_refused():
    c, fw, port, b, seen = rig()
    port.mute = True                                       # e.g. the installed non-bridge firmware
    with pytest.raises(BenchRefused, match="no ack"):
        b.status()
    with pytest.raises(BenchRefused, match="no ack"):
        b.pulse("forward")


def test_cable_pulled_mid_pulse_firmware_zeroes_on_its_own():
    c, fw, port, b, seen = rig()
    orig = b.tr.write_block
    n = {"k": 0}

    def flaky(*a):
        n["k"] += 1
        if n["k"] == 4:                                    # Z, then a couple of motion frames, then the cable goes
            port.cut()
        return orig(*a)
    b.tr.write_block = flaky
    with pytest.raises(Exception):
        b.pulse("forward")
    for _ in range(80):                                    # 400 ms of MCU time
        c.t = round(c.t + 0.005, 6)
        fw.loop()
    assert fw.state == "WDSTOP" and fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


def test_status_needs_no_motion_preconditions():
    c, fw, port, b, seen = rig(wheels_lifted=False, battery_v=None)
    assert b.status()["state"] == "DISARMED"

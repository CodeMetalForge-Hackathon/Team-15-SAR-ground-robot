"""USB-serial bridge: protocol, Pi transport, and the firmware model's watchdog. Mocked hardware only."""
import pytest

from rover.bridge import (ACK_TIMEOUT_S, WATCHDOG_MS, BridgeTransport, crc8, encode_motor, frame, open_serial,
                          parse)
from rover.hardware import RoverCAdapter
from rover.motion import Command, MotionLimits, SafetyStop, SafetySupervisor
from rover.protocol import HardwareVerification, WheelMapping, encode_motor_block
from rover.sensors import OK, Assessment, PowerReading, RangeReading
from rover.tests.bridge_model import BridgeFirmwareModel, FakeI2C, LoopbackPort


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def rig(arm=True):
    c = Clock()
    fw = BridgeFirmwareModel(c)
    port = LoopbackPort(fw)
    tr = BridgeTransport(port, c)
    if arm:
        tr.arm("bench-operator")
        tr.poll()
    return c, fw, port, tr


def advance(c, fw, dt, tr=None, step=0.01):
    end = c.t + dt
    while c.t < end - 1e-9:
        c.t = round(c.t + step, 6)
        fw.loop()


# --- protocol ---------------------------------------------------------------------------------
def test_crc_known_vector_and_roundtrip():
    assert crc8(b"123456789") == 0xF4  # CRC-8/SMBUS (poly 0x07) check value
    f = encode_motor(7, "0123abcd", (10, -10, 0, 100))
    assert parse(f) == ["M", "7", "0123abcd", "10", "-10", "0", "100"]


@pytest.mark.parametrize("line", [b"", b"garbage", b"M,1,0,0,0,0*00", b"M,1,0,0,0,0", b"\xff\xfe*AA",
                                  b"*", b"M,1,0,0,0,0*ZZ"])
def test_parse_rejects_bad_frames(line):
    assert parse(line) is None


@pytest.mark.parametrize("speeds", [(101, 0, 0, 0), (0, 0, 0, -101), (1, 2, 3), (True, 0, 0, 0), (1.0, 0, 0, 0)])
def test_encoder_refuses_out_of_range(speeds):
    with pytest.raises(ValueError):
        encode_motor(1, "0123abcd", speeds)


@pytest.mark.parametrize("session", ["", "0123ABCD", "0123abc", "0123abcde", "xyz12345", None])
def test_encoder_refuses_bad_session(session):
    with pytest.raises(ValueError):
        encode_motor(1, session, (0, 0, 0, 0))


def test_frame_refuses_injection():
    with pytest.raises(ValueError):
        frame("P,1*00\nM,2,100,100,100,100")


# --- firmware model: boot, arming, watchdog, e-stop ---------------------------------------------
def test_boot_is_zero_and_disarmed():
    c, fw, port, tr = rig(arm=False)
    assert fw.state == "DISARMED" and fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}
    assert fw.i2c.writes[0] == (0, 0, 0, 0)


def test_motor_frame_refused_until_armed():
    c, fw, port, tr = rig(arm=False)
    with pytest.raises(IOError, match="not-armed"):
        tr.write_block(0x38, 0x00, encode_motor_block((20, 20, 20, 20)))
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}
    assert tr.health() != ""  # any fault: no ack yet, refused, or DISARMED


def test_arm_needs_named_operator():
    c, fw, port, tr = rig(arm=False)
    for bad in ("", "x,y", "a*b", "name\nM,1,100,100,100,100"):
        with pytest.raises(PermissionError):
            tr.arm(bad)
    assert fw.state == "DISARMED"


def test_armed_motor_frame_applies_and_health_ok():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((20, -20, 5, -5)))
    assert fw.i2c.regs == {0: 20, 1: -20, 2: 5, 3: -5} and tr.health() == ""


def test_transport_only_carries_the_motor_block():
    c, fw, port, tr = rig()
    for addr, reg, data in [(0x38, 0x10, b"\x00\x00\x00\x00"), (0x39, 0x00, b"\x00" * 4),
                            (0x38, 0x00, b"\x00" * 3), (0x38, 0x20, b"\x5a")]:
        with pytest.raises(PermissionError):
            tr.write_block(addr, reg, data)


def test_out_of_range_byte_refused_before_sending():
    c, fw, port, tr = rig()
    with pytest.raises(ValueError):
        tr.write_block(0x38, 0x00, encode_motor_block((127, 0, 0, 0)))  # 127 > library clamp 100
    assert fw.i2c.regs[0] == 0


def test_firmware_watchdog_zeroes_within_300ms_of_last_frame():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    t_last = c.t
    while fw.state != "WDSTOP" and c.t - t_last < 1.0:
        advance(c, fw, 0.01)
    assert fw.state == "WDSTOP" and fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}
    assert (c.t - t_last) * 1000 <= 300 and (c.t - t_last) * 1000 > WATCHDOG_MS - 1
    assert fw.wd_trips == 1


def test_after_watchdog_motion_needs_rearm():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    advance(c, fw, 0.4)
    with pytest.raises(IOError, match="not-armed-WDSTOP"):
        tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    assert fw.i2c.regs[0] == 0
    tr.arm("bench-operator")
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    assert fw.i2c.regs[0] == 30


def test_corrupted_frames_ignored_and_do_not_feed_watchdog():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    t_last = c.t
    for _ in range(40):  # 0.4 s of corrupted frames
        port.corrupt_next = 1
        tr._send(encode_motor(tr._next(), tr.session, (90, 90, 90, 90)))
        advance(c, fw, 0.01)
    assert fw.state == "WDSTOP" and fw.i2c.regs[0] == 0 and 90 not in fw.i2c.regs.values()
    assert fw.wd_trips == 1


def test_button_estop_zeroes_and_disarms():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    fw.button_a()
    assert fw.state == "ESTOP" and fw.i2c.regs[0] == 0
    with pytest.raises(IOError):
        tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))


def test_i2c_error_reported_and_motion_refused():
    c, fw, port, tr = rig()
    fw.i2c.fail = True
    with pytest.raises(IOError, match="i2c"):
        tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    tr.ping()
    assert "I2CERR" in tr.health() or "refused" in tr.health()


def test_health_fails_when_acks_stop():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((0, 0, 0, 0)))
    assert tr.health() == ""
    port.connected = False  # cable pulled: no more acks
    c.t += ACK_TIMEOUT_S + 0.01
    assert "no ack" in tr.health()


def test_transport_refuses_slow_ack_timeout():
    with pytest.raises(ValueError):
        BridgeTransport(LoopbackPort(BridgeFirmwareModel(Clock())), Clock(), ack_timeout_s=0.5)


def test_open_serial_refuses_unstable_paths():
    for p in ("/dev/ttyACM0", "/dev/ttyUSB0", "COM3", "/tmp/x"):
        with pytest.raises(PermissionError):
            open_serial(p)


# --- end to end: supervisor + RoverCAdapter + bridge + firmware model --------------------------
VERIFIED_FIXTURE = HardwareVerification(
    controller_model="TEST", controller_firmware="TEST", roverc_revision="TEST", link="TEST bridge model",
    wiring_verified_by="TEST", power_verified_by="TEST", stop_on_link_loss_ms=WATCHDOG_MS,
    wheel_mapping=WheelMapping(1, 1, 1, evidence="TEST FIXTURE - not a real bench result"))


def stack(arm=True):
    c, fw, port, tr = rig(arm=arm)
    drv = RoverCAdapter(tr, VERIFIED_FIXTURE)
    sup = SafetySupervisor(drv, c, MotionLimits(min_voltage_v=3.3))
    return c, fw, port, tr, sup


def feed(c, sup):
    sup.heartbeat()
    sup.update_range(RangeReading(c.t, OK, 2.0, 3.5, "fake", forward_allowed=True), Assessment.CLEAR)
    sup.update_power(PowerReading(c.t, 4.0, "fake"))


def run(c, fw, sup, dt):
    end = c.t + dt
    while c.t < end - 1e-9:
        c.t = round(c.t + 0.05, 6)
        feed(c, sup)
        sup.tick()
        fw.loop()


def test_disarmed_bridge_blocks_the_supervisor():
    c, fw, port, tr, sup = stack(arm=False)
    sup.approve_motion("operator")
    feed(c, sup)
    r = sup.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "DISARMED" in r.reason and fw.i2c.regs[0] == 0


def test_end_to_end_motion_then_cable_pull_stops_both_sides():
    c, fw, port, tr, sup = stack()
    sup.approve_motion("operator")
    feed(c, sup)
    assert sup.command(Command.MOVE_FORWARD, 0.2, 1.0).accepted
    run(c, fw, sup, 0.3)
    assert any(fw.i2c.regs.values()) and fw.state == "ARMED"
    port.cut()
    t_cut = c.t
    run(c, fw, sup, 0.4)
    # firmware side: motors zero within the watchdog, independently of the Pi
    assert fw.state == "WDSTOP" and fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}
    # host side: driver fault latched, approval revoked, nothing restarts by itself
    assert sup.latched == SafetyStop.DRIVER_FAULT and sup.approved_by is None and sup.output.is_zero()
    assert c.t - t_cut <= 0.45


def test_supervisor_stop_sends_zero_frame():
    c, fw, port, tr, sup = stack()
    sup.approve_motion("operator")
    feed(c, sup)
    sup.command(Command.MOVE_FORWARD, 0.2, 1.0)
    run(c, fw, sup, 0.3)
    sup.command(Command.STOP)
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


def test_stopped_supervisor_keeps_the_firmware_watchdog_fed():
    c, fw, port, tr, sup = stack()
    run(c, fw, sup, 2.0)  # idle: tick() re-applies ZERO every cycle
    assert fw.state == "ARMED" and fw.wd_trips == 0


# --- no automatic re-arm: restart, second process, reconnect, firmware reboot -----------------------
def test_each_transport_has_its_own_session():
    c, fw, port, tr = rig()
    assert tr.session != BridgeTransport(port, c).session


def test_restarted_pi_process_cannot_drive_motors_armed_by_the_old_one():
    c, fw, port, old = rig()
    old.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    assert fw.i2c.regs[0] == 30
    new = BridgeTransport(port, c)             # crash + restart well inside the 250 ms watchdog window
    new.ping()
    assert "another session" in new.health()   # sees ARMED, but not by itself
    with pytest.raises(IOError, match="session"):
        new.write_block(0x38, 0x00, encode_motor_block((40, 40, 40, 40)))
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0} and fw.state == "DISARMED" and fw.session == "-"
    with pytest.raises(IOError):               # and the old session is disarmed too
        old.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))


def test_usb_reconnect_requires_rearm_even_inside_watchdog_window():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    port.connected = False
    with pytest.raises(OSError):
        tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    c.t += 0.05                                # re-plugged after 50 ms: firmware still ARMED (old session)
    port.connected = True
    assert fw.state == "ARMED"
    with pytest.raises(IOError, match="session"):
        tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    assert fw.i2c.regs[0] == 0 and fw.state == "DISARMED"
    tr.arm("bench-operator")                   # only an explicit ARM restores motion
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    assert fw.i2c.regs[0] == 30


def test_firmware_reboot_comes_up_zero_and_disarmed():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    fw2 = BridgeFirmwareModel(c, fw.i2c)       # brown-out / reset: same bus, fresh firmware
    port.fw = fw2
    assert fw2.state == "DISARMED" and fw2.i2c.regs[0] == 0
    with pytest.raises(IOError, match="not-armed-DISARMED"):
        tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    assert fw2.i2c.regs[0] == 0


def test_supervisor_restart_cannot_resume_without_operator():
    c, fw, port, tr, sup = stack()
    sup.approve_motion("operator")
    feed(c, sup)
    sup.command(Command.MOVE_FORWARD, 0.2, 1.0)
    run(c, fw, sup, 0.2)
    tr2 = BridgeTransport(port, c)             # Pi control process restarts: new transport + supervisor
    sup2 = SafetySupervisor(RoverCAdapter(tr2, VERIFIED_FIXTURE), c, MotionLimits(min_voltage_v=3.3))
    feed(c, sup2)
    r = sup2.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "approval" in r.reason
    sup2.approve_motion("operator")            # even approved, the bridge isn't ARMED for this session
    feed(c, sup2)
    r = sup2.command(Command.MOVE_FORWARD, 0.2, 0.5)
    assert not r.accepted and "driver" in r.reason
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


# --- I2C error handling --------------------------------------------------------------------------
def test_arm_refused_while_i2c_failing_then_recovers():
    c, fw, port, tr = rig(arm=False)
    fw.i2c.fail = True
    tr.arm("bench-operator")
    tr.poll()
    assert fw.state == "I2CERR" and "I2CERR" in tr.health()
    fw.i2c.fail = False
    tr.arm("bench-operator")
    tr.poll()
    assert fw.state == "ARMED" and tr.health() == ""


def test_failed_zero_is_retried_until_confirmed_and_watchdog_counts_once():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    fw.i2c.fail = True                         # bus fails exactly when the watchdog needs it
    advance(c, fw, 0.5)
    assert fw.wd_trips == 1 and fw.i2c.regs[0] == 30 and fw.state != "ARMED"  # still believed running
    n = fw.i2c_errs
    advance(c, fw, 0.1)
    assert fw.i2c_errs > n                     # retrying (every 20 ms)
    fw.i2c.fail = False
    advance(c, fw, 0.05)
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0} and fw.wd_trips == 1


# --- review fixes: reply matching, stale acks, hung firmware --------------------------------------------
def test_replies_are_matched_by_seq_and_late_nak_surfaces_on_next_write():
    c = Clock()
    fw = BridgeFirmwareModel(c)
    port = LoopbackPort(fw, reply_delay=1)      # every reply arrives one read later, like a real UART
    tr = BridgeTransport(port, c)
    tr.write_block(0x38, 0x00, encode_motor_block((0, 0, 0, 0)))        # reply still in flight
    tr.write_block(0x38, 0x00, encode_motor_block((20, 20, 20, 20)))    # refused (not armed), reply in flight
    with pytest.raises(IOError, match="not-armed"):                     # surfaces on the next write
        tr.write_block(0x38, 0x00, encode_motor_block((0, 0, 0, 0)))
    assert fw.i2c.regs[0] == 0


def test_stale_buffered_acks_do_not_look_fresh():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((0, 0, 0, 0)))
    assert tr.health() == ""
    for _ in range(3):                          # frames go out, but the Pi doesn't read replies (stalled)
        tr._send(frame(f"Z,{tr._next()}"))
    c.t += 0.5                                   # ...for half a second, then reads the backlog
    assert "no ack" in tr.health()               # acks answer frames SENT 0.5 s ago: not fresh


def test_foreign_replies_are_ignored():
    c, fw, port, tr = rig()
    fw.out += frame("K,999999,ARMED,deadbeef,0,0")   # a reply to a frame this transport never sent
    tr.poll()
    assert tr.last_ack.seq != 999999


def test_hung_firmware_latches_driver_fault_and_watchdog_holds():
    c, fw, port, tr, sup = stack()
    sup.approve_motion("operator")
    feed(c, sup)
    sup.command(Command.MOVE_FORWARD, 0.2, 1.0)
    run(c, fw, sup, 0.2)
    port.mute = True                             # writes still "succeed", nothing is processed or answered
    run(c, fw, sup, 0.5)
    assert sup.latched == SafetyStop.DRIVER_FAULT and sup.output.is_zero()
    assert fw.state == "WDSTOP" and fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


# --- review fixes: watchdog feeding ----------------------------------------------------------------------
def test_pings_do_not_feed_the_watchdog():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    for _ in range(40):                          # 0.4 s of pings only
        tr.ping()
        advance(c, fw, 0.01)
    assert fw.state == "WDSTOP" and fw.i2c.regs[0] == 0


def test_refused_and_unknown_frames_do_not_feed_the_watchdog():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    for i in range(40):
        tr._send(frame(f"X,{tr._next()}"))     # valid CRC, unknown kind
        advance(c, fw, 0.01)
    assert fw.state == "WDSTOP" and fw.i2c.regs[0] == 0


# --- review fixes: local e-stop can't be cleared remotely ---------------------------------------------
def test_remote_arm_cannot_clear_local_estop():
    c, fw, port, tr = rig()
    fw.button_a()
    tr.arm("bench-operator")
    tr.poll()
    assert fw.state == "ESTOP" and "estop-local-reset" in tr.health()
    fw.button_b_long()                           # local, deliberate clear -> DISARMED (never ARMED)
    assert fw.state == "DISARMED"
    tr.arm("bench-operator")
    tr.write_block(0x38, 0x00, encode_motor_block((10, 10, 10, 10)))
    assert fw.i2c.regs[0] == 10


# --- review fixes: I2C partial writes, boot failure ------------------------------------------------------
def test_partial_i2c_write_counts_as_unknown_output_and_zero_is_retried():
    c, fw, port, tr = rig()
    tr.write_block(0x38, 0x00, encode_motor_block((0, 0, 0, 0)))
    fw.i2c.fail, fw.i2c.partial = True, 1        # NACK after the first byte: motor 0 really changes
    with pytest.raises(IOError, match="i2c"):
        tr.write_block(0x38, 0x00, encode_motor_block((40, 40, 40, 40)))
    assert fw.i2c.regs[0] == 40 and fw.output_unknown and fw.state == "I2CERR"
    advance(c, fw, 0.1)
    assert fw.i2c_errs > 2                       # zero retried every 20 ms
    fw.i2c.fail = False
    advance(c, fw, 0.03)
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0} and not fw.output_unknown


def test_boot_with_failing_bus_is_i2cerr_and_keeps_retrying():
    c = Clock()
    bus = FakeI2C()
    bus.fail = True
    fw = BridgeFirmwareModel(c, bus)
    assert fw.state == "I2CERR" and fw.output_unknown
    bus.fail = False
    advance(c, fw, 0.05)
    assert not fw.output_unknown and fw.state == "I2CERR"   # zero confirmed; still needs an explicit ARM


# --- review fixes: model parsing parity with the .ino ---------------------------------------------------
@pytest.mark.parametrize("payload", ["M,5,,1,2,3,4", "M,5,{s},1_0,0,0,0", "M,5,{s},+1,0,0,0", "M,5,{s},12345,0,0,0",
                                     "M,5,{s}, 1,0,0,0", "M,,{s},1,0,0,0", "M,1234567890,{s},1,0,0,0"])
def test_malformed_motor_frames_never_move(payload):
    c, fw, port, tr = rig()
    fw.receive_line(frame(payload.format(s=tr.session)).rstrip(b"\n"))
    assert fw.i2c.regs == {0: 0, 1: 0, 2: 0, 3: 0}


def test_oversize_and_whitespace_lines_are_dropped():
    c, fw, port, tr = rig()
    good = encode_motor(tr._next(), tr.session, (10, 10, 10, 10)).rstrip(b"\n")
    fw.receive_line(good + b" ")                           # trailing space: CRC no longer matches
    fw.receive_line(b"M," + b"9" * 100 + good[2:])         # oversize
    assert fw.i2c.regs[0] == 0
    fw.receive_line(good)
    assert fw.i2c.regs[0] == 10


# --- review fixes: serial port opened without toggling DTR/RTS ------------------------------------------
def test_open_serial_deasserts_dtr_rts_before_open(monkeypatch):
    import sys
    import types
    calls = []

    class FakeSerial:
        def __init__(self):
            self.in_waiting = 0

        def __setattr__(self, k, v):
            calls.append(("set", k, v))
            object.__setattr__(self, k, v)

        def open(self):
            calls.append(("open",))

    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=FakeSerial))
    monkeypatch.setattr(sys, "platform", "linux")   # by-id path rule (Pi host); macOS rule tested in test_mac_host_e2e
    open_serial("/dev/serial/by-id/usb-TEST-if00-port0")
    i_open = calls.index(("open",))
    assert ("set", "dtr", False) in calls[:i_open] and ("set", "rts", False) in calls[:i_open]

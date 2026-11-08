"""End-to-end SIMULATION of the Mac-hosted loop. No hardware: synthetic detections and a firmware model.

camera_mapping pipeline (SYNTHETIC detections) -> rover.camera_gate -> CameraGatedController -> SafetySupervisor
-> RoverCAdapter -> BridgeTransport -> LoopbackPort -> BridgeFirmwareModel (executable model of the .ino).
"Wheels" are the firmware model's I2C motor registers. Nothing here is evidence of physical behaviour.
"""
import pytest

from camera_mapping.config import CALIBRATED, UNCALIBRATED
from camera_mapping.pipeline import PerceptionPipeline
from camera_mapping.tests.helpers import cfg, floor_box
from rover import camera_gate as G
from rover.bridge import WATCHDOG_MS, BridgeTransport, check_port_path
from rover.hardware import RoverCAdapter
from rover.mac_host import CameraGatedController
from rover.motion import Command, MotionLimits, SafetyStop, SafetySupervisor
from rover.sensors import OK, Assessment, PowerReading, RangeReading
from rover.sim import SimDriver
from rover.tests.bridge_model import BridgeFirmwareModel, LoopbackPort
from rover.tests.test_bridge import VERIFIED_FIXTURE, Clock

DT = 0.02


class World:
    def __init__(self, calibrated=True, require_live=False, source_mode="SYNTHETIC"):
        self.c = Clock()
        self.fw = BridgeFirmwareModel(self.c)
        self.port = LoopbackPort(self.fw)
        self.tr = BridgeTransport(self.port, self.c)
        self.tr.arm("sim-operator")
        self.tr.poll()
        self.sup = SafetySupervisor(RoverCAdapter(self.tr, VERIFIED_FIXTURE), self.c, MotionLimits(min_voltage_v=3.3))
        self.ctl = CameraGatedController(self.sup, self.c, camera_max_age_s=1.0, require_live_camera=require_live)
        self.pcfg = cfg(calibration_status=CALIBRATED if calibrated else UNCALIBRATED)
        self.pipe = PerceptionPipeline(self.pcfg, source_mode=source_mode)
        self.dets = []
        self.camera_on = True
        self.host_alive = True
        self.next_frame = self.c.t
        self.sup.approve_motion("sim-operator")

    def scene(self, *dets):
        self.dets = list(dets)
        self.run(0.8)      # >= 3 frames at 5 fps so tracks confirm

    def run(self, seconds):
        end = self.c.t + seconds
        while self.c.t < end - 1e-9:
            self.c.t = round(self.c.t + DT, 6)
            self.fw.loop()
            if self.camera_on and self.c.t >= self.next_frame - 1e-9:
                self.ctl.on_camera(self.pipe.process(self.c.t, self.dets))
                self.next_frame = self.c.t + 0.2
            if self.host_alive:
                self.sup.update_range(RangeReading(self.c.t, OK, 3.0, 4.0, "sim-ultrasonic", forward_allowed=True),
                                      Assessment.CLEAR, "SIM range")
                self.sup.update_power(PowerReading(self.c.t, 3.9, "SIM"))
                self.ctl.tick()

    @property
    def wheels(self):
        return tuple(self.fw.i2c.regs[i] for i in range(4))

    @property
    def spinning(self):
        return any(self.wheels)

    def fwd(self, speed=0.2, dur=1.0):
        return self.ctl.request(Command.MOVE_FORWARD, speed, dur)

    def chair(self, x, y=0.0):
        return floor_box(self.pcfg, "chair", x, y_m=y, w_m=0.3)


def test_01_clear_corridor_moves_then_stops_at_duration():
    w = World()
    w.scene()
    v = w.ctl.verdict()
    assert v.action == G.NO_OBJECTION and v.forward_ok, v.reason
    assert w.fwd(0.2, 0.6).accepted
    w.run(0.2)
    assert w.spinning
    w.run(0.6)
    assert not w.spinning and w.sup.last_stop_reason == "command duration elapsed"


def test_02_chair_directly_ahead_stops_and_asks_operator():
    w = World()
    w.scene(w.chair(1.0))
    v = w.ctl.verdict()
    assert v.action == G.STOP and not v.forward_ok
    assert v.operator == G.OPERATOR_INTERVENTION    # both swerves pass within body width of the chair
    d = w.fwd()
    assert not d.accepted and "camera STOP" in d.reason
    w.run(0.3)
    assert not w.spinning


def test_03_obstacle_appearing_while_moving_stops_within_one_frame():
    w = World()
    w.scene()
    assert w.fwd(0.2, 1.0).accepted
    w.run(0.2)
    assert w.spinning
    w.dets = [w.chair(1.0)]
    stopped_at = None
    for _ in range(60):
        w.run(DT)
        if not w.spinning:
            stopped_at = w.c.t
            break
    assert stopped_at is not None
    assert w.ctl.verdict().action in (G.STOP, G.HOLD)
    assert any(e["kind"] == "STOP" and "camera" in e["detail"] for e in w.ctl.events)


@pytest.mark.parametrize("side_y,free_side", [(0.35, "RIGHT"), (-0.35, "LEFT")])
def test_04_05_one_side_obstructed_suggests_the_other_for_operator_review(side_y, free_side):
    w = World()
    w.scene(w.chair(1.0, side_y))
    v = w.ctl.verdict()
    assert not v.forward_ok and v.action in (G.STOP, G.HOLD)
    assert v.operator == G.OPERATOR_REVIEW and v.suggestion == free_side
    st = {c["name"]: c["status"] for c in v.candidates}
    assert st[free_side] == "OBSERVED_CLEAR" and st["LEFT" if free_side == "RIGHT" else "RIGHT"] == "OBSTRUCTED"
    assert not w.fwd().accepted                     # a suggestion is never executed
    w.run(0.3)
    assert not w.spinning


def test_06_both_paths_obstructed_requires_operator_intervention():
    w = World()
    w.scene(w.chair(1.0), w.chair(1.1, 0.42), w.chair(1.1, -0.42))
    v = w.ctl.verdict()
    assert v.action == G.STOP and v.operator == G.OPERATOR_INTERVENTION and v.suggestion is None
    assert {c["name"]: c["status"] for c in v.candidates} == {
        "STRAIGHT": "OBSTRUCTED", "LEFT": "OBSTRUCTED", "RIGHT": "OBSTRUCTED"}


def test_07_person_ahead_stops():
    w = World()
    w.scene()
    assert w.fwd(0.2, 1.0).accepted
    w.run(0.1)
    w.dets = [floor_box(w.pcfg, "person", 1.5, h_m=1.7)]
    w.run(0.8)
    v = w.ctl.verdict()
    assert v.action == G.STOP and v.persons_ahead and "person ahead" in v.reason
    assert not w.spinning and not w.fwd().accepted


def test_08_missing_camera_frames_hold_and_block_all_motion():
    w = World()
    w.scene()
    assert w.fwd(0.2, 1.0).accepted
    w.run(0.2)
    assert w.spinning
    w.camera_on = False
    w.run(1.3)
    v = w.ctl.verdict()
    assert v.action == G.HOLD and "stale" in v.reason and not v.any_motion_ok
    assert not w.spinning
    assert not w.ctl.request(Command.TURN_LEFT, 0.2, 0.5).accepted     # stale camera: no motion of any kind


def test_09_uncalibrated_camera_never_clears_forward_motion():
    w = World(calibrated=False)
    w.scene()
    v = w.ctl.verdict()
    assert v.assessment == "CLEAR" and v.action == G.HOLD and "UNCALIBRATED" in v.reason
    assert not w.fwd().accepted
    st = w.pipe.last_state
    for o in st["objects"]:                         # and distances stay labelled estimates
        assert "VERIFIED" not in str((o.get("distance") or {}).get("label"))


def test_10_controller_disconnect_latches_and_firmware_zeroes_without_auto_restart():
    w = World()
    w.scene()
    assert w.fwd(0.2, 1.0).accepted
    w.run(0.2)
    assert w.spinning
    w.port.cut()
    w.run(0.1)
    assert w.sup.latched == SafetyStop.DRIVER_FAULT
    w.run(WATCHDOG_MS / 1000 + 0.1)                 # firmware watchdog holds the wheels at zero on its own
    assert w.fw.state == "WDSTOP" and not w.spinning
    w.port.connected = True                         # cable back: nothing restarts by itself
    w.run(0.3)
    assert not w.spinning and not w.fwd().accepted


def test_11_host_hang_trips_firmware_watchdog():
    w = World()
    w.scene()
    assert w.fwd(0.2, 1.0).accepted
    w.run(0.2)
    assert w.spinning
    w.host_alive = False                            # Mac process hangs: no more frames to the StickC
    w.run(WATCHDOG_MS / 1000 + 0.05)
    assert w.fw.state == "WDSTOP" and w.fw.wd_trips == 1 and not w.spinning


def test_12_emergency_stop_latches_until_named_reset():
    w = World()
    w.scene()
    assert w.fwd(0.2, 1.0).accepted
    w.run(0.2)
    assert w.ctl.request(Command.EMERGENCY_STOP, origin="dashboard").accepted   # anyone may stop
    w.run(DT)
    assert not w.spinning and w.sup.estop.tripped
    d = w.fwd()
    assert not d.accepted and "emergency stop" in d.reason
    w.fw.button_a()                                 # StickC local e-stop is independent of the Mac
    assert w.fw.state == "ESTOP"


# --- gate invariants ----------------------------------------------------------------------------
def test_autonomy_and_qwen_origins_are_refused():
    w = World()
    w.scene()
    for origin in ("autonomy", "qwen", "planner"):
        d = w.ctl.request(Command.MOVE_FORWARD, 0.2, 0.5, origin=origin)
        assert not d.accepted and "autonomous motion is disabled" in d.reason
    assert w.ctl.request(Command.STOP, origin="qwen").accepted                   # but stopping is never refused


def test_recorded_or_synthetic_camera_refused_when_live_required():
    w = World(require_live=True, source_mode="RECORDED")
    w.scene()
    v = w.ctl.verdict()
    assert v.action == G.HOLD and "not LIVE-HW" in v.reason and not v.any_motion_ok


def test_no_detections_is_not_clearance_without_observed_free_corridor():
    c = cfg(measured=False, calibration_status=CALIBRATED)     # nothing can be observed FREE
    p = PerceptionPipeline(c, source_mode="LIVE-HW")
    st = None
    for k in range(3):
        st = p.process(100 + k * 0.2, [])
    v = G.evaluate(st, 100.5)
    assert st["objects"] == [] and v.action == G.HOLD and not v.forward_ok


@pytest.mark.parametrize("bad", [None, {}, {"schema": "x"},
                                 {"schema": G.SCHEMA, "motion_authority": "FULL", "data_source": "CAMERA_ESTIMATE", "t": 1},
                                 {"schema": G.SCHEMA, "motion_authority": "NONE", "data_source": "CAMERA_ESTIMATE"}])
def test_malformed_states_hold(bad):
    v = G.evaluate(bad, 1.0, require_live=False)
    assert v.action == G.HOLD and not v.any_motion_ok


def test_status_labels_simulation_as_simulated():
    c = Clock()
    ctl = CameraGatedController(SafetySupervisor(SimDriver(), c), c)
    s = ctl.status()
    assert s["physical"] is False and s["label"].startswith("SIMULATED")
    assert s["autonomy"] == "DISABLED" and s["qwen_authority"].startswith("NONE")


# --- Mac serial path --------------------------------------------------------------------------
@pytest.mark.parametrize("path,serial,ok", [
    ("/dev/cu.usbserial-7D520E63EE0", "7D520E63EE", True),
    ("/dev/cu.usbserial-7D520E63EE1", "7D520E63EE", True),
    ("/dev/cu.usbserial-AAAA0", "7D520E63EE", False),        # some other FTDI device
    ("/dev/tty.usbserial-7D520E63EE0", "7D520E63EE", False),  # tty.* blocks on carrier detect
    ("/dev/cu.usbserial-7D520E63EE0", None, False),          # serial number must be named
    ("/dev/cu.Bluetooth-Incoming-Port", "7D520E63EE", False),
])
def test_mac_port_path_is_pinned_to_the_stickc_serial(path, serial, ok):
    if ok:
        check_port_path(path, serial, platform="darwin")
    else:
        with pytest.raises(PermissionError):
            check_port_path(path, serial, platform="darwin")


def test_linux_port_path_still_by_id_only():
    check_port_path("/dev/serial/by-id/usb-Hades2001_M5stack_7D520E63EE-if00-port0", "7D520E63EE", platform="linux")
    with pytest.raises(PermissionError):
        check_port_path("/dev/ttyUSB0", None, platform="linux")

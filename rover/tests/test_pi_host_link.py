"""Mac -> Pi -> (mocked) StickC path: signed link, Pi-side gates, fail-safe cases. No hardware, no serial port.

Perception states are SYNTHETIC detections labelled LIVE-HW only inside these tests, to exercise the live path.
"""
import json
import os
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from camera_mapping.config import UNCALIBRATED
from camera_mapping.pipeline import PerceptionPipeline
from camera_mapping.tests.helpers import cfg, floor_box
from rover import link
from rover.motion import SafetyStop
from rover.pi_host import PiHost, make_handler, mock_stack
from rover.remote import PiClient
from rover.tests.test_bridge import Clock

KEY = b"k" * 40


# --- link ---------------------------------------------------------------------------------------
def test_signed_request_verifies_and_replay_is_refused():
    c = Clock()
    s, v = link.Signer(KEY, c), link.Verifier(KEY, c)
    h = s.headers("POST", "/v1/command", b'{"cmd":"STOP"}')
    v.check("POST", "/v1/command", h, b'{"cmd":"STOP"}')
    with pytest.raises(link.AuthError, match="replay"):
        v.check("POST", "/v1/command", h, b'{"cmd":"STOP"}')


@pytest.mark.parametrize("mutate", ["body", "path", "key", "unsigned", "skew"])
def test_tampered_or_stale_requests_are_refused(mutate):
    c = Clock()
    s = link.Signer(b"x" * 40 if mutate == "key" else KEY, c)
    v = link.Verifier(KEY, c)
    h = s.headers("POST", "/v1/command", b"{}")
    body, path = b"{}", "/v1/command"
    if mutate == "body":
        body = b'{"cmd":"MOVE_FORWARD"}'
    if mutate == "path":
        path = "/v1/perception"
    if mutate == "unsigned":
        h = {}
    if mutate == "skew":
        c.t += 30
    with pytest.raises(link.AuthError):
        v.check("POST", path, h, body)


def test_key_file_must_be_private(tmp_path):
    k = tmp_path / "k"
    k.write_bytes(os.urandom(48).hex().encode())
    os.chmod(k, 0o644)
    with pytest.raises(link.AuthError, match="chmod 600"):
        link.load_key(str(k))
    os.chmod(k, 0o600)
    assert len(link.load_key(str(k))) >= 32


# --- Pi host over the mocked bridge -------------------------------------------------------------------
class Rig:
    def __init__(self):
        self.c = Clock()
        self.fw, self.tr, drv = mock_stack(self.c)
        self.host = PiHost(drv, self.tr, self.fw, clock=self.c, wall=self.c)
        self.pcfg = cfg(calibration_status=UNCALIBRATED)
        self.pipe = PerceptionPipeline(self.pcfg, source_mode="LIVE-HW")   # SYNTHETIC detections (test only)
        self.dets = []
        self.camera, self.mac = True, True
        self.next_frame = 0.0

    def run(self, s):
        end = self.c.t + s
        while self.c.t < end - 1e-9:
            self.c.t = round(self.c.t + 0.02, 6)
            if self.mac and self.c.t >= self.next_frame:
                st = self.pipe.process(self.c.t, self.dets) if self.camera else None
                if st is not None:
                    st = dict(st, age_s=0.05)            # what the dashboard view carries
                self.host.on_perception(st) if self.camera else self.host.on_mac()
                self.next_frame = self.c.t + 0.2
            self.host.tick()

    @property
    def wheels(self):
        return [self.fw.i2c.regs[i] for i in range(4)]

    def cmd(self, name, origin="operator", **kw):
        return self.host.command({"cmd": name, "origin": origin, "operator": "op1", **kw})


def ready():
    r = Rig()
    r.run(0.8)
    assert r.cmd("APPROVE")["accepted"]
    return r


def test_operator_turn_reaches_mocked_wheels_and_is_labelled_simulated():
    r = ready()
    d = r.cmd("TURN_LEFT", speed=0.15, duration_s=0.5)
    assert d["accepted"], d
    r.run(0.2)
    assert any(r.wheels)
    s = r.host.status()
    assert s["label"].startswith("SIMULATED MOTOR OUTPUT") and s["physical"] is False
    assert s["controller"]["kind"] == "FIRMWARE MODEL"
    r.run(0.5)
    assert not any(r.wheels)                         # bounded duration elapsed


def test_qwen_motion_requests_are_refused_but_qwen_stop_is_accepted():
    r = ready()
    for name in ("MOVE_FORWARD", "TURN_LEFT", "TURN_RIGHT", "MOVE_BACKWARD"):
        d = r.cmd(name, origin="qwen", speed=0.15, duration_s=0.3)
        assert not d["accepted"] and "autonomous motion is disabled" in d["reason"]
    assert r.cmd("STOP", origin="qwen")["accepted"]
    assert not r.cmd("APPROVE", origin="qwen")["accepted"]
    assert not any(r.wheels)


def test_forward_refused_while_corridor_unknown_and_person_ahead():
    r = ready()
    r.dets = [floor_box(r.pcfg, "person", 1.5, h_m=1.7)]
    r.run(0.8)
    d = r.cmd("MOVE_FORWARD", speed=0.2, duration_s=0.5)
    assert not d["accepted"] and "camera STOP" in d["reason"]


def test_backward_needs_operator_rear_clear():
    r = ready()
    assert not r.cmd("MOVE_BACKWARD", speed=0.15, duration_s=0.3)["accepted"]
    assert r.cmd("MOVE_BACKWARD", speed=0.15, duration_s=0.3, rear_clear=True)["accepted"]


def test_stale_camera_stops_motion():
    r = ready()
    assert r.cmd("TURN_LEFT", speed=0.15, duration_s=1.0)["accepted"]
    r.run(0.2)
    assert any(r.wheels)
    r.camera = False                                 # Mac still alive, camera path stalled
    r.run(1.3)
    assert not any(r.wheels)
    assert r.host.status()["camera_verdict"]["action"] == "HOLD"


def test_mac_link_loss_stops_latches_and_needs_operator_reset():
    r = ready()
    assert r.cmd("TURN_RIGHT", speed=0.15, duration_s=1.0)["accepted"]
    r.run(0.2)
    assert any(r.wheels)
    r.mac = False
    r.run(0.7)
    assert not any(r.wheels) and r.host.sup.latched == SafetyStop.COMMS_LOST and r.host.status()["link"] == "DOWN"
    r.mac = True
    r.run(0.5)
    assert not r.cmd("TURN_RIGHT", speed=0.15, duration_s=0.3)["accepted"]   # no auto-restart
    assert r.cmd("RESET_LATCH")["accepted"]
    assert not r.cmd("TURN_RIGHT", speed=0.15, duration_s=0.3)["accepted"]   # approval was revoked
    assert r.cmd("APPROVE")["accepted"] and r.cmd("TURN_RIGHT", speed=0.15, duration_s=0.3)["accepted"]


def test_pi_hang_trips_firmware_watchdog():
    r = ready()
    assert r.cmd("TURN_LEFT", speed=0.15, duration_s=1.0)["accepted"]
    r.run(0.2)
    for _ in range(20):                              # Pi host frozen: only the MCU loop runs
        r.c.t = round(r.c.t + 0.02, 6)
        r.fw.loop()
    assert r.fw.state == "WDSTOP" and not any(r.wheels)


def test_estop_cannot_be_reset_remotely():
    r = ready()
    assert r.cmd("TURN_LEFT", speed=0.15, duration_s=1.0)["accepted"]
    r.run(0.1)
    assert r.cmd("EMERGENCY_STOP")["accepted"]
    r.run(0.05)
    assert not any(r.wheels)
    d = r.cmd("RESET_LATCH")
    assert not d["accepted"] and "e-stop" in d["reason"]
    assert not r.cmd("TURN_LEFT", speed=0.15, duration_s=0.3)["accepted"]


def test_hardware_mode_never_gets_mock_sensor_data():
    class PhysicalDriver:
        name, physical = "phys", True

        def apply(self, v):
            raise AssertionError("must never be driven in this test")

        def stop(self):
            pass

        def health(self):
            return ""
    c = Clock()
    h = PiHost(PhysicalDriver(), None, None, clock=c, wall=c)
    assert h.mock_sensors is False
    h.on_mac()
    h.tick()
    assert h.sup.range is None and h.sup.power is None
    assert h.status()["label"] == "PHYSICAL" and h.status()["sensors"] == "real sensors only"


# --- real HTTP round trip (Mac client -> Pi handler) ---------------------------------------------
def test_http_round_trip_requires_signature():
    fw, tr, drv = mock_stack(time.monotonic)
    host = PiHost(drv, tr, fw)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(host, link.Verifier(KEY)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/v1/command", data=json.dumps({"cmd": "STOP"}).encode(), method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=2)
        assert e.value.code == 401
        cl = PiClient(base, KEY)
        assert cl.command("STOP")["accepted"] is True
        assert cl.command("TURN_LEFT", origin="qwen", speed=0.1, duration_s=0.2)["accepted"] is False
        st = cl.status()
        assert st["label"].startswith("SIMULATED") and st["link"] == "UP"
        assert PiClient(base, b"z" * 40).status().get("error") == "HTTP 401"
    finally:
        srv.shutdown()

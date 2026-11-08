"""Pi-side rover host: authenticated Mac link -> camera veto -> SafetySupervisor -> StickC bridge (USB on the Pi).

  python3 -m rover.pi_host --mock-motors --bind 100.97.93.118          # dry run: firmware MODEL, no serial port
  python3 -m rover.pi_host --serial /dev/serial/by-id/usb-Hades2001_M5stack_7D520E63EE-if00-port0 \\
      --usb-serial 7D520E63EE --verification ~/Team15_config/hardware_verification.json   # refuses until verified

The deterministic safety stack runs HERE, next to the serial port, so losing the Mac is handled locally:
  * Mac link: no authenticated message for `mac_timeout_s` (0.5 s) -> motion stopped and a COMMS_LOST latch that
    only a named operator can clear after the link is back. Commands are refused while the link is down.
  * Camera: the Mac forwards perception states; each is re-stamped on the Pi clock (rx - dashboard age), so a
    stalled camera or forwarder goes stale here and the veto stops motion (rover/camera_gate.py).
  * SafetySupervisor: approval, latches, e-stop, driver health (bridge acks), range + power gates, bounds, ramp.
  * StickC firmware: 250 ms watchdog and button-A e-stop, independent of this process and of the Mac.
Origins other than "operator" (qwen, autonomy, planner) can only stop. E-stop can be tripped remotely but only
reset at the Pi (`python3 -m rover.pi_host --reset-estop` is deliberately NOT provided: restart the host).

--mock-motors uses the executable firmware model (rover/tests/bridge_model.py) behind the real BridgeTransport
and RoverCAdapter. Its status is always "SIMULATED MOTOR OUTPUT", and ONLY in mock mode does the host feed
the supervisor simulated range and power readings. Hardware mode never fabricates sensor data.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from rover import link
from rover.mac_host import CameraGatedController
from rover.motion import Command, DirectionEvidence, MotionLimits, SafetyStop, SafetySupervisor
from rover.sensors import OK, Assessment, PowerReading, RangeReading

SCHEMA = "team15.mac_host_status/1"     # same display contract as the Mac host
CMDS = {"STOP": Command.STOP, "EMERGENCY_STOP": Command.EMERGENCY_STOP, "MOVE_FORWARD": Command.MOVE_FORWARD,
        "MOVE_BACKWARD": Command.MOVE_BACKWARD, "TURN_LEFT": Command.TURN_LEFT, "TURN_RIGHT": Command.TURN_RIGHT}


def mock_stack(clock: Callable[[], float]):
    """BridgeTransport + RoverCAdapter over the firmware MODEL. physical=False everywhere."""
    from rover.bridge import WATCHDOG_MS, BridgeTransport
    from rover.hardware import RoverCAdapter
    from rover.protocol import HardwareVerification, WheelMapping
    from rover.tests.bridge_model import BridgeFirmwareModel, LoopbackPort
    fw = BridgeFirmwareModel(clock)
    tr = BridgeTransport(LoopbackPort(fw), clock, physical=False)
    ver = HardwareVerification(
        controller_model="MOCK firmware model", controller_firmware="rover/tests/bridge_model.py",
        roverc_revision="MOCK", link="Pi -> LoopbackPort (no serial)", wiring_verified_by="MOCK",
        power_verified_by="MOCK", stop_on_link_loss_ms=WATCHDOG_MS,
        wheel_mapping=WheelMapping(1, 1, 1, evidence="MOCK - not a bench result"))
    tr.arm("pi-host-mock")
    tr.poll()
    return fw, tr, RoverCAdapter(tr, ver)


class PiHost:
    def __init__(self, driver, transport, fw=None, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time, mac_timeout_s: float = 0.5):
        self.physical = bool(getattr(driver, "physical", True))
        self.mock_sensors = not self.physical
        self.fw, self.tr, self.clock, self.wall = fw, transport, clock, wall
        lim = MotionLimits(min_voltage_v=3.3) if self.mock_sensors else MotionLimits()
        self.sup = SafetySupervisor(driver, clock, lim)
        self.ctl = CameraGatedController(self.sup, clock, camera_max_age_s=1.0, require_live_camera=True)
        self.mac_timeout_s = mac_timeout_s
        self.last_mac: Optional[float] = None
        self.link_ok = False
        self.lock = threading.RLock()
        self.decisions: list[dict] = []

    # --- authenticated inputs from the Mac ----------------------------------------------------------
    def on_mac(self) -> None:
        with self.lock:
            self.last_mac = self.clock()
            if not self.link_ok:
                self.link_ok = True
                self.ctl._event("LINK", "Mac link UP")

    def on_perception(self, state: Optional[dict]) -> None:
        with self.lock:
            self.on_mac()
            if isinstance(state, dict) and state.get("status") != "NO_DATA":
                st = dict(state)
                age = st.get("age_s") if isinstance(st.get("age_s"), (int, float)) else 1e9
                st["rx_time"] = self.clock() - max(0.0, float(age))   # Pi clock; no cross-machine clock trust
                self.ctl.on_camera(st)
            else:
                self.ctl.on_camera(None)

    def command(self, body: dict) -> dict:
        with self.lock:
            self.on_mac()
            name, origin = str(body.get("cmd", "")), str(body.get("origin") or "unknown")
            rec = {"t": round(self.wall(), 3), "cmd": name, "origin": origin, "operator": body.get("operator"),
                   "speed": body.get("speed"), "duration_s": body.get("duration_s"), "proposal": body.get("proposal")}
            try:
                if name == "APPROVE":
                    if origin != "operator":
                        raise PermissionError("only an operator can approve motion")
                    self.sup.approve_motion(str(body.get("operator") or ""))
                    rec.update(accepted=True, reason=f"approved by {body.get('operator')}")
                elif name == "RESET_LATCH":
                    if origin != "operator":
                        raise PermissionError("only an operator can reset a latch")
                    if self.sup.estop.tripped:
                        raise PermissionError("e-stop latched: reset only at the Pi (restart the host)")
                    if not self.link_ok:
                        raise PermissionError("Mac link down")
                    self.sup.reset_latch(str(body.get("operator") or ""))
                    rec.update(accepted=True, reason="latch reset; motion needs a fresh approval")
                elif name in CMDS:
                    cmd = CMDS[name]
                    ev = None
                    if cmd == Command.MOVE_BACKWARD and body.get("rear_clear") is True and origin == "operator":
                        ev = DirectionEvidence(cmd, self.clock(), f"{body.get('operator')} (rear-clear)")
                    d = self.ctl.request(cmd, float(body.get("speed") or 0.0), float(body.get("duration_s") or 0.0),
                                         ev, origin=origin)
                    rec.update(accepted=d.accepted, reason=d.reason)
                else:
                    rec.update(accepted=False, reason=f"unknown command {name!r}")
            except Exception as e:  # noqa: BLE001 - a refused command is a record, never a crash
                rec.update(accepted=False, reason=f"{type(e).__name__}: {e}")
            self.decisions.append(rec)
            del self.decisions[:-100]
            return rec

    # --- 20 Hz loop ---------------------------------------------------------------------------------
    def tick(self) -> None:
        with self.lock:
            now = self.clock()
            if self.fw is not None:
                self.fw.loop()
            if self.tr is not None:
                self.tr.poll()
            if self.link_ok and (self.last_mac is None or now - self.last_mac > self.mac_timeout_s):
                self.link_ok = False
                self.sup.trip_safety(SafetyStop.COMMS_LOST, f"Mac link silent > {self.mac_timeout_s:.1f} s")
                self.ctl._event("LINK", "Mac link LOST: motion stopped, COMMS_LOST latched")
            if self.mock_sensors:      # never in hardware mode
                self.sup.update_range(RangeReading(now, OK, 3.0, 4.0, "sim-ultrasonic (MOCK)", forward_allowed=True),
                                      Assessment.CLEAR, "MOCK range for the mocked motor chain")
                self.sup.update_power(PowerReading(now, 3.9, "MOCK"))
            self.ctl.tick()

    def status(self) -> dict:
        with self.lock:
            s = self.ctl.status()
            s["label"] = "SIMULATED MOTOR OUTPUT (firmware model, no wheels)" if not self.physical else "PHYSICAL"
            s["link"] = "UP" if self.link_ok else "DOWN"
            s["host"] = "pi"
            s["sensors"] = "MOCK range+power (mock mode only)" if self.mock_sensors else "real sensors only"
            if self.fw is not None:
                s["controller"] = {"kind": "FIRMWARE MODEL", "state": self.fw.state,
                                   "motor_registers": [self.fw.i2c.regs[i] for i in range(4)],
                                   "watchdog_trips": self.fw.wd_trips}
            elif self.tr is not None:
                a = self.tr.last_ack
                s["controller"] = {"kind": "StickC bridge", "state": a.state if a else "NO_ACK",
                                   "watchdog_trips": a.wd_trips if a else None, "health": self.tr.health()}
            s["decisions"] = self.decisions[-20:]
            return s


def make_handler(host: PiHost, verifier: link.Verifier):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            b = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _auth(self, body: bytes) -> bool:
            try:
                verifier.check(self.command, self.path, self.headers, body)
                return True
            except link.AuthError as e:
                self._send(401, {"error": str(e)})
                return False

        def do_GET(self):
            if not self._auth(b""):
                return
            if self.path == "/v1/status":
                host.on_mac()
                return self._send(200, host.status())
            self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                return self._send(413, {"error": "too large"})
            raw = self.rfile.read(n)
            if not self._auth(raw):
                return
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if self.path == "/v1/heartbeat":
                host.on_mac()
                return self._send(200, {"ok": True})
            if self.path == "/v1/perception":
                host.on_perception(body.get("state"))
                return self._send(200, {"ok": True})
            if self.path == "/v1/command":
                return self._send(200, host.command(body))
            self._send(404, {"error": "not found"})

        def log_message(self, *a):
            pass
    return H


def main(argv=None) -> int:  # pragma: no cover - process wiring; logic tested through PiHost + handler
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--bind", default="127.0.0.1", help="the Pi's Tailscale IP, never 0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--key", default=link.DEFAULT_KEY)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--mock-motors", action="store_true")
    g.add_argument("--serial", help="/dev/serial/by-id/... of the StickC")
    p.add_argument("--usb-serial")
    p.add_argument("--verification")
    p.add_argument("--hz", type=float, default=20.0)
    a = p.parse_args(argv)
    if a.bind in ("0.0.0.0", "::"):
        p.error("bind to the Tailscale IP or localhost only")
    key = link.load_key(a.key)
    fw = None
    if a.mock_motors:
        fw, tr, drv = mock_stack(time.monotonic)
    else:
        if not (a.usb_serial and a.verification):
            p.error("--serial needs --usb-serial and --verification")
        from rover.hardware import HardwareNotVerified
        from rover.mac_host import build_hardware
        try:
            tr, drv = build_hardware(a.serial, a.usb_serial, a.verification)
        except HardwareNotVerified as e:
            print(f"REFUSED: {e}", file=sys.stderr)
            return 3
    host = PiHost(drv, tr, fw)
    srv = ThreadingHTTPServer((a.bind, a.port), make_handler(host, link.Verifier(key)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"pi_host: {'MOCK MOTORS (firmware model)' if a.mock_motors else 'HARDWARE'} on http://{a.bind}:{a.port}",
          flush=True)
    try:
        while True:
            host.tick()
            time.sleep(1.0 / a.hz)
    except KeyboardInterrupt:
        pass
    finally:
        host.sup.stop("pi_host shutdown")
        srv.shutdown()
        print("pi_host stopped; output zero", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

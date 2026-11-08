"""Mac-hosted rover control: Pi camera perception (via the dashboard) -> camera veto -> SafetySupervisor -> driver.

Architecture: Raspberry Pi camera -> SSH/Tailscale -> Mac (Faster R-CNN, camera_mapping, dashboard) -> this
module -> USB serial -> M5StickC bridge firmware -> RoverC-Pro. Wheel commands never pass through the Pi.

Every motion request goes through two gates, in this order, and both must agree:
  1. the camera veto (rover/camera_gate.py): stale/missing/non-live camera -> no motion at all; person ahead,
     BLOCKED, CAUTION, UNKNOWN or an uncalibrated camera -> no forward motion. It can only say no.
  2. SafetySupervisor: operator approval, e-stop/latches, driver health (bridge acks), fresh range reading,
     measured power and undervoltage threshold, bounded speed/duration, ramping, heartbeat watchdog.
Every tick re-checks the camera veto and stops motion it no longer allows.

Not here, on purpose:
  * autonomous motion. Only origin="operator" may request motion; "autonomy" and "qwen" are refused until
    camera clearance and real movement have been validated and a reviewed change enables them.
  * any serial write outside BridgeTransport/RoverCAdapter. Hardware mode builds the existing adapter, which
    refuses to exist until HardwareVerification is complete.

Simulation (default) uses SimDriver (physical=False): its status is always labelled SIMULATED and no wheel moves.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import deque
from typing import Callable, Optional

from rover import camera_gate
from rover.motion import Command, Decision, DirectionEvidence, SafetySupervisor

SCHEMA = "team15.mac_host_status/1"
MOTION = {Command.MOVE_FORWARD, Command.MOVE_BACKWARD, Command.TURN_LEFT, Command.TURN_RIGHT,
          Command.STRAFE_LEFT, Command.STRAFE_RIGHT}


class CameraGatedController:
    def __init__(self, supervisor: SafetySupervisor, clock: Callable[[], float] = time.time,
                 camera_max_age_s: float = 1.0, require_live_camera: bool = True):
        self.sup = supervisor
        self.clock = clock
        self.camera_max_age_s = camera_max_age_s
        self.require_live = require_live_camera
        self.state: Optional[dict] = None
        self.events: deque = deque(maxlen=200)
        self._last_action: Optional[str] = None
        self.lock = threading.RLock()

    # --- inputs -------------------------------------------------------------------------------------
    def on_camera(self, state: Optional[dict]) -> None:
        with self.lock:
            self.state = state

    def verdict(self) -> camera_gate.CameraVerdict:
        with self.lock:
            return camera_gate.evaluate(self.state, self.clock(), self.camera_max_age_s, self.require_live)

    # --- the only motion entry point ----------------------------------------------------------------
    def request(self, cmd: Command, speed: float = 0.0, duration_s: float = 0.0,
                evidence: Optional[DirectionEvidence] = None, origin: str = "operator") -> Decision:
        with self.lock:
            if cmd == Command.EMERGENCY_STOP or cmd == Command.STOP:
                d = self.sup.command(cmd)                     # stopping is always allowed, from anyone
                self._event("COMMAND", f"{cmd.value} from {origin}: {d.reason}")
                return d
            if origin != "operator":
                return self._refuse(cmd, f"origin {origin!r}: autonomous motion is disabled until camera "
                                         "clearance and real movement are validated")
            if cmd in MOTION:
                v = self.verdict()
                if not v.any_motion_ok:
                    return self._refuse(cmd, f"camera {v.action}: {v.reason}")
                if cmd == Command.MOVE_FORWARD and not v.forward_ok:
                    return self._refuse(cmd, f"camera {v.action}: {v.reason}")
            d = self.sup.command(cmd, speed, duration_s, evidence)
            self._event("COMMAND" if d.accepted else "REFUSED", f"{cmd.value} {speed:.2f}x{duration_s:.2f}s: {d.reason}")
            return d

    def _refuse(self, cmd: Command, why: str) -> Decision:
        self._event("REFUSED", f"{cmd.value}: {why}")
        return Decision(False, why)

    # --- control loop -------------------------------------------------------------------------------
    def tick(self) -> camera_gate.CameraVerdict:
        with self.lock:
            v = self.verdict()
            if v.action != self._last_action:
                self._event("CAMERA_VERDICT", f"{self._last_action or '-'} -> {v.action}: {v.reason}")
                self._last_action = v.action
            moving = self.sup.active != Command.STOP or not self.sup.output.is_zero()
            if moving and not v.any_motion_ok:
                self.sup.stop(f"camera {v.action}: {v.reason}")
                self._event("STOP", f"camera {v.action}: {v.reason}")
            elif moving and self.sup.active == Command.MOVE_FORWARD and not v.forward_ok:
                self.sup.stop(f"camera {v.action}: {v.reason}")
                self._event("STOP", f"camera {v.action}: {v.reason}")
            self.sup.heartbeat()
            self.sup.tick()
            return v

    def _event(self, kind: str, detail: str) -> None:
        self.events.append({"t": round(self.clock(), 3), "kind": kind, "detail": detail})

    def status(self) -> dict:
        with self.lock:
            s = self.sup.status()
            v = self.verdict()
            physical = bool(s["driver"]["physical"])
            out = s["output"]
            return {
                "schema": SCHEMA, "t": round(self.clock(), 3),
                "physical": physical,
                "label": "PHYSICAL" if physical else "SIMULATED (no wheel moves)",
                "driver": s["driver"]["name"],
                "active_command": s["active_command"],
                "output": out,
                "moving": any(abs(out[k]) > 1e-9 for k in ("vx", "vy", "wz")),
                "estop": s["estop"], "safety_latch": s["safety_latch"],
                "motion_approved_by": s["motion_approved_by"], "last_stop_reason": s["last_stop_reason"],
                "camera_verdict": v.to_dict(),
                "autonomy": "DISABLED",
                "qwen_authority": "NONE (advisory only)",
                "events": list(self.events)[-30:],
            }


# --- CLI ---------------------------------------------------------------------------------------------
def _get(url: str, timeout: float = 0.5) -> Optional[dict]:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001 - a dead dashboard reads as "no camera data" (HOLD)
        return None


def _post(url: str, body: dict, timeout: float = 0.5) -> None:
    import urllib.request
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=timeout).read()
    except Exception:  # noqa: BLE001
        pass


def build_hardware(port: str, usb_serial: str, verification_path: str):  # pragma: no cover - real hardware
    """Bridge transport + RoverC adapter. Raises HardwareNotVerified until the record is complete."""
    from rover.bridge import BridgeTransport, open_serial
    from rover.hardware import RoverCAdapter
    from rover.protocol import HardwareVerification, WheelMapping
    rec = json.loads(open(verification_path, encoding="utf-8").read())
    wm = WheelMapping(**rec.pop("wheel_mapping", {}))
    ver = HardwareVerification(wheel_mapping=wm, **rec)
    missing = ver.missing()
    if missing:   # check BEFORE opening the port: opening can reset the StickC
        from rover.hardware import HardwareNotVerified
        raise HardwareNotVerified("RoverC-Pro hardware not verified; missing: " + ", ".join(missing))
    transport = BridgeTransport(open_serial(port, expected_usb_serial=usb_serial), time.monotonic)
    return transport, RoverCAdapter(transport, ver)


HELP = """operator commands (one per line):
  stop | estop | approve <name> | arm <name> (hardware only) | status
  fwd <speed> <seconds> | back <speed> <seconds> rear-clear | left <speed> <seconds> | right <speed> <seconds>
speeds are normalised (supervisor caps them, default 0.30); seconds are capped at 1.0 by the supervisor."""


def main(argv=None) -> int:  # pragma: no cover - interactive loop; logic is tested via CameraGatedController
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dashboard", default="http://127.0.0.1:8000")
    p.add_argument("--hardware", action="store_true", help="drive the real RoverC through the StickC bridge")
    p.add_argument("--port", help="Mac serial node, e.g. /dev/cu.usbserial-7D520E63EE0")
    p.add_argument("--usb-serial", help="StickC USB serial number the port must belong to, e.g. 7D520E63EE")
    p.add_argument("--verification", help="HardwareVerification JSON (filled in from the bench runbook)")
    p.add_argument("--camera-max-age-s", type=float, default=1.0)
    p.add_argument("--allow-recorded-camera", action="store_true",
                   help="SIMULATION ONLY: accept RECORDED/SYNTHETIC camera states (refused with --hardware)")
    p.add_argument("--hz", type=float, default=20.0)
    a = p.parse_args(argv)
    if a.hardware and a.allow_recorded_camera:
        p.error("--allow-recorded-camera is simulation-only")

    transport = None
    if a.hardware:
        if not (a.port and a.usb_serial and a.verification):
            p.error("--hardware needs --port, --usb-serial and --verification")
        from rover.hardware import HardwareNotVerified
        try:
            transport, driver = build_hardware(a.port, a.usb_serial, a.verification)
        except HardwareNotVerified as e:
            print(f"REFUSED: {e}", file=sys.stderr)
            return 3
    else:
        from rover.sim import SimDriver
        driver = SimDriver()
    sup = SafetySupervisor(driver, time.monotonic)
    ctl = CameraGatedController(sup, time.time, a.camera_max_age_s, require_live_camera=not a.allow_recorded_camera)
    print(f"mac_host: driver={'PHYSICAL ' + driver.name if a.hardware else 'SIMULATED'} dashboard={a.dashboard}")
    print(HELP)

    stop = threading.Event()

    def loop():
        n = 0
        while not stop.is_set():
            st = _get(a.dashboard + "/api/perception")
            ctl.on_camera(st if st and st.get("status") != "NO_DATA" else None)
            if transport is not None:
                transport.poll()
            ctl.tick()
            n += 1
            if n % max(1, int(a.hz / 5)) == 0:
                _post(a.dashboard + "/api/rover/state", ctl.status())
            time.sleep(1.0 / a.hz)

    th = threading.Thread(target=loop, daemon=True)
    th.start()
    cmds = {"fwd": Command.MOVE_FORWARD, "back": Command.MOVE_BACKWARD, "left": Command.TURN_LEFT,
            "right": Command.TURN_RIGHT}
    try:
        for line in sys.stdin:
            w = line.split()
            if not w:
                continue
            try:
                if w[0] == "stop":
                    print(ctl.request(Command.STOP))
                elif w[0] == "estop":
                    print(ctl.request(Command.EMERGENCY_STOP))
                elif w[0] == "approve" and len(w) == 2:
                    with ctl.lock:
                        sup.approve_motion(w[1])
                    print("approved by", w[1])
                elif w[0] == "arm" and len(w) == 2 and transport is not None:
                    with ctl.lock:
                        transport.arm(w[1])
                    print("ARM sent; firmware ack shows in status")
                elif w[0] == "status":
                    print(json.dumps(ctl.status(), indent=1)[:3000])
                elif w[0] in cmds and len(w) in (3, 4):
                    cmd = cmds[w[0]]
                    ev = None
                    if cmd == Command.MOVE_BACKWARD:   # no sensor faces backwards: the operator must attest it
                        if len(w) != 4 or w[3] != "rear-clear":
                            print("refused: add 'rear-clear' after looking behind the rover"); continue
                        ev = DirectionEvidence(cmd, time.monotonic(), "operator (typed rear-clear)")
                    print(ctl.request(cmd, float(w[1]), float(w[2]), ev))
                else:
                    print(HELP)
            except Exception as e:  # noqa: BLE001
                print("error:", e)
    except KeyboardInterrupt:
        pass
    finally:
        ctl.request(Command.STOP, origin="shutdown")
        stop.set()
        th.join(timeout=1)
        try:
            sup.stop("mac_host shutdown")
        except Exception:  # noqa: BLE001
            pass
        _post(a.dashboard + "/api/rover/state", ctl.status())
        print("mac_host stopped; output zero")
    return 0


if __name__ == "__main__":
    sys.exit(main())

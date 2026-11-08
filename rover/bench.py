"""WHEELS-LIFTED BENCH TEST MODE. A separate, explicitly selected configuration. NOT the production control path.

Why it exists: production (SafetySupervisor + RoverCAdapter) correctly refuses to move until the wheel mapping is
measured, a range reading exists and power is measured. The mapping can only be measured by spinning the wheels.
This mode does exactly that, wheels in the air, and nothing else. SafetySupervisor and pi_host are unchanged.

  python3 -m rover.bench --port /dev/serial/by-id/usb-Hades2001_M5stack_7D520E63EE-if00-port0 --usb-serial 7D520E63EE \\
      --operator NAME --battery-v 3.95 --min-battery-v 3.6 --wheels-lifted ACTION
  ACTION: status | stop | watchdog | forward | backward | record (no port: writes what the operator SAW)

Bench gate (every run, nothing is remembered between runs):
  * a named operator, the --wheels-lifted assertion, and a multimeter battery voltage >= --min-battery-v
    (measured by a person immediately before this run; there is no battery register on the RoverC);
  * the firmware must answer as the Team-15 bridge (K/N frames) and ACK ARMED for THIS session;
  * raw library speed y = +/-SPEED (default 15, hard cap 20 of 100), duration <= 0.30 s (hard cap);
  * motion frames are refreshed every 50 ms (firmware watchdog 250 ms); the pulse ends with Z and a confirmed
    zero; any NAK, missing ack or exception -> Z (and the firmware watchdog covers a dead host).
  * 'watchdog' sends ONE motion frame and then stays silent: the firmware must report WDSTOP with wd_trips+1.
Every run appends a JSON record to ~/Team15_evidence/wheel_tests/ (and latest.json only when the operator records
the observed wheel behaviour with --observed).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Callable, Optional

from rover.bridge import BridgeTransport
from rover.protocol import I2C_ADDRESS, REG_MOTOR, STOP_BLOCK, encode_motor_block, library_mix

SPEED_DEFAULT, SPEED_CAP = 15, 20
PULSE_CAP_S = 0.30
REFRESH_S = 0.05
ACK_WAIT_S = 0.30


class BenchRefused(RuntimeError):
    pass


class Bench:
    def __init__(self, transport: BridgeTransport, clock: Callable[[], float], sleep: Callable[[float], None],
                 operator: str, battery_v: Optional[float], min_battery_v: Optional[float], wheels_lifted: bool,
                 pump: Optional[Callable[[], None]] = None):
        self.tr, self.clock, self.sleep, self.pump = transport, clock, sleep, pump or (lambda: None)
        self.operator, self.battery_v, self.min_v, self.lifted = operator, battery_v, min_battery_v, wheels_lifted
        self.log: list[dict] = []

    # --- helpers ------------------------------------------------------------------------------------
    def _note(self, kind, **kw):
        self.log.append({"t": round(self.clock(), 3), "kind": kind, **kw})

    def _wait_ack(self, timeout=ACK_WAIT_S):
        """Poll until the latest sent frame is answered (K or N). Returns the Ack or raises."""
        end = self.clock() + timeout
        want = self.tr.seq
        while self.clock() < end:
            self.pump()
            self.tr.poll()
            if self.tr.last_nak:
                raise BenchRefused(f"firmware refused: {self.tr.last_nak}")
            a = self.tr.last_ack
            if a is not None and a.seq == want:
                return a
            self.sleep(0.005)
        raise BenchRefused("no ack from the StickC (is the Team-15 bridge firmware installed?)")

    def gate(self, motion: bool) -> None:
        if not self.operator or not self.operator.strip():
            raise BenchRefused("a named operator is required")
        if not motion:
            return
        if not self.lifted:
            raise BenchRefused("--wheels-lifted not asserted: all four wheels must be off the surface")
        if self.battery_v is None or self.min_v is None:
            raise BenchRefused("measured --battery-v and --min-battery-v are required")
        if not (3.0 <= self.min_v <= 4.2) or not (2.5 <= self.battery_v <= 4.35):
            raise BenchRefused("battery numbers outside a single Li-ion cell range: check the measurement")
        if self.battery_v < self.min_v:
            raise BenchRefused(f"battery {self.battery_v:.2f} V < threshold {self.min_v:.2f} V: charge first")

    def zero(self) -> dict:
        """Z frame (allowed in every firmware state) and a confirmed ack."""
        self.tr.write_block(I2C_ADDRESS, REG_MOTOR[0], STOP_BLOCK)
        a = self._wait_ack()
        self._note("ZERO", state=a.state, wd_trips=a.wd_trips, i2c_errs=a.i2c_errs)
        return {"state": a.state, "wd_trips": a.wd_trips, "i2c_errs": a.i2c_errs}

    # --- actions ------------------------------------------------------------------------------------
    def status(self) -> dict:
        self.gate(motion=False)
        self.tr.ping()
        a = self._wait_ack()
        self._note("STATUS", state=a.state, session=a.session, wd_trips=a.wd_trips, i2c_errs=a.i2c_errs)
        return {"state": a.state, "session": a.session, "wd_trips": a.wd_trips, "i2c_errs": a.i2c_errs}

    def _arm(self):
        self.tr.arm(self.operator.replace(" ", "_")[:32])
        a = self._wait_ack()
        if a.state != "ARMED" or a.session != self.tr.session:
            raise BenchRefused(f"firmware did not ARM this session (state {a.state})")
        self._note("ARMED", session=a.session)

    def pulse(self, direction: str, speed: int = SPEED_DEFAULT, duration_s: float = PULSE_CAP_S) -> dict:
        if direction not in ("forward", "backward"):
            raise BenchRefused("direction must be forward or backward")
        if not (1 <= speed <= SPEED_CAP):
            raise BenchRefused(f"speed must be 1..{SPEED_CAP} (raw, of 100)")
        if not (0 < duration_s <= PULSE_CAP_S):
            raise BenchRefused(f"duration must be in (0, {PULSE_CAP_S}] s")
        self.gate(motion=True)
        before = self.zero()
        if before["state"] in ("ESTOP", "I2CERR"):
            raise BenchRefused(f"firmware state {before['state']}: clear it locally first")
        self._arm()
        y = speed if direction == "forward" else -speed
        block = encode_motor_block(library_mix(0, y, 0))
        t0 = self.clock()
        sent = 0
        try:
            while self.clock() - t0 < duration_s:
                self.tr.write_block(I2C_ADDRESS, REG_MOTOR[0], block)   # refresh: firmware watchdog is 250 ms
                sent += 1
                self._wait_ack(timeout=0.1)
                self.sleep(REFRESH_S)
        finally:
            elapsed = self.clock() - t0
            after = self.zero()                                         # always: STOP and confirm
        self._note("PULSE", direction=direction, raw_y=y, registers=list(library_mix(0, y, 0)),
                   commanded_s=round(elapsed, 3), frames=sent, after=after)
        return {"direction": direction, "raw_y": y, "registers": list(library_mix(0, y, 0)),
                "commanded_s": round(elapsed, 3), "frames": sent, "after_stop": after}

    def watchdog(self, speed: int = 10) -> dict:
        """ONE motion frame, then silence: the firmware itself must zero and report WDSTOP."""
        self.gate(motion=True)
        before = self.zero()
        self._arm()
        trips0 = self.tr.last_ack.wd_trips
        self.tr.write_block(I2C_ADDRESS, REG_MOTOR[0], encode_motor_block(library_mix(0, min(speed, SPEED_CAP), 0)))
        t_last = self.clock()
        self._wait_ack(timeout=0.1)
        while self.clock() - t_last < 0.45:          # silence > 250 ms watchdog; pings never feed it
            self.sleep(0.01)
            self.pump()
        self.tr.ping()
        a = self._wait_ack()
        ok = a.state == "WDSTOP" and a.wd_trips == trips0 + 1
        after = self.zero()
        self._note("WATCHDOG", state_after_silence=a.state, wd_trips_before=trips0, wd_trips_after=a.wd_trips, ok=ok)
        if not ok:
            raise BenchRefused(f"WATCHDOG CHECK FAILED: state {a.state}, trips {trips0}->{a.wd_trips}")
        return {"ok": True, "state_after_silence": a.state, "wd_trips": [trips0, a.wd_trips], "before": before,
                "after_stop": after}


def main(argv=None) -> int:  # pragma: no cover - real serial port; logic tested with the firmware model
    p = argparse.ArgumentParser(description="WHEELS-LIFTED bench test (separate from production control)")
    p.add_argument("action", choices=("status", "stop", "watchdog", "forward", "backward", "record"))
    p.add_argument("--port", required=True)
    p.add_argument("--usb-serial", required=True)
    p.add_argument("--operator", required=True)
    p.add_argument("--battery-v", type=float)
    p.add_argument("--min-battery-v", type=float)
    p.add_argument("--wheels-lifted", action="store_true")
    p.add_argument("--speed", type=int, default=SPEED_DEFAULT)
    p.add_argument("--duration-s", type=float, default=PULSE_CAP_S)
    p.add_argument("--observed", help="record only: 'PASS: ...' or 'FAIL: ...' with what each wheel did and the stop")
    a = p.parse_args(argv)
    d = os.path.expanduser("~/Team15_evidence/wheel_tests")
    os.makedirs(d, exist_ok=True)
    if a.action == "record":       # never opens the port: the operator's observation of the last pulses
        if not a.observed or not a.operator.strip():
            p.error("record needs --operator and --observed")
        latest = {"operator": a.operator, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "result": "PASS" if a.observed.upper().startswith("PASS") else "FAIL",
                  "wheels_lifted": a.wheels_lifted, "observations": a.observed}
        with open(os.path.join(d, "latest.json"), "w") as f:
            json.dump(latest, f, indent=1)
        print(json.dumps(latest, indent=1))
        return 0
    from rover.bridge import open_serial
    tr = BridgeTransport(open_serial(a.port, expected_usb_serial=a.usb_serial), time.monotonic)
    b = Bench(tr, time.monotonic, time.sleep, a.operator, a.battery_v, a.min_battery_v, a.wheels_lifted)
    rec = {"t": time.time(), "action": a.action, "operator": a.operator, "battery_v": a.battery_v,
           "min_battery_v": a.min_battery_v, "wheels_lifted": a.wheels_lifted, "port": a.port}
    try:
        if a.action == "status":
            rec["result"] = b.status()
        elif a.action == "stop":
            rec["result"] = b.zero()
        elif a.action == "watchdog":
            rec["result"] = b.watchdog()
        else:
            rec["result"] = b.pulse(a.action, a.speed, a.duration_s)
        rec["ok"] = True
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error=f"{type(e).__name__}: {e}")
        try:
            b.zero()
        except Exception as e2:  # noqa: BLE001
            rec["zero_after_error"] = f"{type(e2).__name__}: {e2} (firmware watchdog zeroes within 250 ms)"
    rec["log"] = b.log
    path = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + f"_{a.action}.json")
    with open(path, "w") as f:
        json.dump(rec, f, indent=1, default=str)
    print(json.dumps(rec, indent=1, default=str))
    return 0 if rec["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())

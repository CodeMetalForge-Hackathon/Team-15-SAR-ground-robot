#!/usr/bin/env python3
"""Open-loop hop to the phone, for a Crazyflie with NO positioning deck.

The path is fixed for the demo table: spool up, rise about 5 in, tilt forward to cover
the distance (3 ft by default), tilt back to brake, settle, land. There is no position
or height sensing; the hop is a timed thrust/attitude profile, so tune it on the real
table:

  1. Find hover thrust with the lift test, and note the thrust when it lifts:
       python -m sar_sim.cf_lift --uri ble://Crazyflie
  2. Hop and adjust:
       python crazyflie/hop_to_phone.py --live-drone --hover-thrust 39000
     climbs too high -> lower --hover-thrust by 500; barely lifts -> raise it by 500
     stops short -> raise --pitch-deg by 1; overshoots -> lower it by 1
     goes backward -> add --reverse

The phone's identity comes from the ground scanner, as in fly_to_phone.py, and the
result goes to mission control as the crazyflie node.

Safety: typed confirmation; refuses if the drone is locked, not ready or under 3.7 V;
tilt past 35 degrees cuts the motors; thrust is capped; Ctrl+C or operator STOP ramps
the motors down at once; ends with 2.5 s of zero thrust (older firmware locks itself
if commands just stop).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "crazyflie")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fly_to_phone import GroundScanner, MissionControl, SimScanner, finite, log  # noqa: E402

G = 9.81
INCH, FOOT = 0.0254, 0.3048
CAP = 52000            # thrust ceiling, of 65535
TILT_CUT = 35.0
MIN_VBAT = 3.7
RATE_HZ = 50
TAIL_S = 2.5


def profile(hover, height_m, forward_m, pitch_deg, reverse=False):
    """Segments (name, seconds, pitch_deg, thrust_start, thrust_end) for one hop.

    Rise: 15% over hover for t_c then 15% under for t_c -> climbs 0.15 g t_c^2, ends level.
    Travel: tilt P for t_a then -P for t_a -> covers g tan(P) t_a^2, ends at rest.
    Thrust is raised by 1/cos(P) while tilted so lift stays the same.
    """
    t_c = math.sqrt(height_m / (0.15 * G))
    a = G * math.tan(math.radians(pitch_deg))
    t_a = math.sqrt(forward_m / a)
    tilt = hover / math.cos(math.radians(pitch_deg))
    p = -pitch_deg if reverse else pitch_deg
    segs = [("spool", 0.5, 0.0, 0.0, 0.9 * hover),
            ("rise", t_c, 0.0, 1.15 * hover, 1.15 * hover),
            ("level", t_c, 0.0, 0.85 * hover, 0.85 * hover),
            ("forward", t_a, p, tilt, tilt),
            ("brake", t_a, -p, tilt, tilt),
            ("settle", 0.3, 0.0, hover, hover),
            ("descend", 0.6, 0.0, 0.85 * hover, 0.85 * hover),
            ("touchdown", 0.4, 0.0, 0.85 * hover, 0.0)]
    return [(n, d, pt, min(CAP, a0), min(CAP, a1)) for n, d, pt, a0, a1 in segs]


def at(segs, t):
    """(segment name, pitch, thrust) at time t into the profile, or None when done."""
    for name, d, pitch, a0, a1 in segs:
        if t < d:
            return name, pitch, a0 + (a1 - a0) * (t / d)
        t -= d
    return None


def status(info):
    if info is None:
        return "?"
    return "LOCKED" if int(info) & 64 else ("ready" if int(info) & 8 else "not ready")


class Hop:
    def __init__(self, args, scanner=None, mc=None, live=False, ask=input):
        self.args, self.scanner, self.mc, self.live, self.ask = args, scanner, mc, live, ask
        self.lock = threading.Lock()
        self.phase, self.detail, self.outcome = "connecting", "", None
        self.trigger = self.finding = None
        self.vbat, self.events = None, []
        self.stop = threading.Event()

    def set_phase(self, phase, detail=""):
        with self.lock:
            self.phase, self.detail = phase, detail
            self.events.append(dict(t=round(time.time(), 2), phase=phase, detail=detail))
        log(f"[{phase}] {detail}")

    def summary_line(self):
        f = self.finding
        if self.outcome == "no_phone":
            return "Phone not detected by ground scanner; drone did not fly"
        if not f or not f.get("detected"):
            return ""
        rssi = f.get("rssi_dbm_median", f.get("rssi_dbm_latest"))
        kind = "verified" if f.get("verified") else "UNVERIFIED"
        return (f"Phone found: {f.get('label')} ({kind}, {f.get('mode_label')}), "
                f"{rssi} dBm over {f.get('samples')} packets, {f.get('sensed_by')}")

    def telemetry(self):
        with self.lock:
            a = self.args
            return dict(ready=True, source="LIVE" if self.live else "SIMULATED",
                        airborne=self.phase in ("spool", "rise", "level", "forward", "brake", "settle",
                                                "descend", "touchdown"),
                        position_m=None, position_frame="boot", position_source="none (open-loop hop)",
                        battery_v=round(self.vbat, 2) if finite(self.vbat) else None,
                        busy=False, agent_error="", last_action=f"{self.phase}: {self.detail}"[:300],
                        mission=dict(script="hop_to_phone", phase=self.phase, detail=self.detail,
                                     outcome=self.outcome, target_m=[round(a.forward_ft * FOOT, 3), 0.0,
                                                                     round(a.height_in * INCH, 3)],
                                     trigger=self.trigger, finding=self.finding,
                                     summary=self.summary_line()))

    def stopped(self):
        return self.stop.is_set() or (self.mc is not None and self.mc.stop_requested.is_set())

    def wait_for_phone(self):
        a = self.args
        if self.scanner is None or a.wait_for_phone <= 0:
            return True
        self.set_phase("waiting_for_phone", f"up to {a.wait_for_phone:.0f} s for the ground scanner")
        end = time.monotonic() + a.wait_for_phone
        while self.scanner.current() is None:
            if self.stopped() or time.monotonic() >= end:
                self.outcome = "no_phone" if not self.stopped() else "aborted"
                self.set_phase(self.outcome, "drone stays on the ground")
                return False
            time.sleep(0.2)
        self.trigger = self.scanner.current()
        log(f"  trigger: {self.trigger.get('label')} at {self.trigger.get('rssi')} dBm")
        return True

    def fly(self, cf, got):
        """Run the profile. got: latest log values (pm.vbat, supervisor.info, stabilizer.roll/pitch)."""
        a = self.args
        segs = profile(a.hover_thrust, a.height_in * INCH, a.forward_ft * FOOT, a.pitch_deg, a.reverse)
        total = sum(s[1] for s in segs)
        for _ in range(6):                       # zero thrust first: unlocks thrust protection
            cf.commander.send_setpoint(0, 0, 0, 0)
            time.sleep(0.05)
        t0, phase, thrust, since = time.monotonic(), None, 0.0, time.monotonic()
        try:
            while True:
                t = time.monotonic() - t0
                step = at(segs, t)
                if step is None:
                    self.outcome = "completed"
                    break
                name, pitch, thrust = step
                if name != phase:
                    phase = name
                    self.set_phase(name, f"pitch {pitch:+.0f} deg, thrust {int(thrust)}")
                    if name == "settle":
                        since = time.monotonic()
                tilt = max(abs(got.get("stabilizer.roll", 0.0)), abs(got.get("stabilizer.pitch", 0.0)))
                if tilt > TILT_CUT:
                    self.outcome = "aborted"
                    self.set_phase("aborted", f"tilted {tilt:.0f} deg: motors cut")
                    thrust = 0.0
                    break
                if self.stopped():
                    self.outcome = "aborted"
                    self.set_phase("aborted", self.mc.stop_reason if self.mc and self.mc.stop_requested.is_set()
                                   else "stop requested: motors ramping down")
                    break
                cf.commander.send_setpoint(0.0, pitch, 0.0, int(thrust))
                self.vbat = got.get("pm.vbat", self.vbat)
                time.sleep(1.0 / RATE_HZ)
        except KeyboardInterrupt:
            self.outcome = "aborted"
            self.set_phase("aborted", "Ctrl+C: motors ramping down")
        finally:
            t1, start = time.monotonic(), thrust      # quick ramp down instead of a dead drop
            while start > 0 and time.monotonic() - t1 < 0.4:
                cf.commander.send_setpoint(0, 0, 0, int(start * (1 - (time.monotonic() - t1) / 0.4)))
                time.sleep(0.02)
            end = time.monotonic() + TAIL_S
            while time.monotonic() < end:
                cf.commander.send_setpoint(0, 0, 0, 0)
                time.sleep(0.05)
            cf.commander.send_notify_setpoint_stop()
        if self.scanner is not None:
            with self.lock:
                self.finding = self.scanner.summary(since=since)
        log(f"  hop profile was {total:.1f} s")

    def report(self):
        a = self.args
        with self.lock:
            return dict(script="hop_to_phone", mode="LIVE" if self.live else "SIMULATED", outcome=self.outcome,
                        summary=self.summary_line(), hover_thrust=a.hover_thrust, pitch_deg=a.pitch_deg,
                        height_in=a.height_in, forward_ft=a.forward_ft, reverse=a.reverse,
                        trigger=self.trigger, finding=self.finding, events=list(self.events),
                        note="Open-loop hop: no position or height sensing. Identity from the ground scanner.")


def connect_and_fly(hop, uri):
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.log import LogConfig
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

    cache = os.path.join(tempfile.gettempdir(), "t15-cflib-cache")
    os.makedirs(cache, exist_ok=True)
    cflib.crtp.init_drivers()
    if uri.startswith("ble://"):
        from sar_sim import ble_link
        ble_link.register()
        log("connecting over Bluetooth (15-30 s)")
    cf = Crazyflie(rw_cache=cache)
    scf = SyncCrazyflie(uri, cf=cf)
    scf.open_link()
    got = {}
    try:
        toc = getattr(cf.log.toc, "toc", {})
        for i, names in enumerate([("pm.vbat", "supervisor.info"), ("stabilizer.roll", "stabilizer.pitch")]):
            names = [n for n in names if n.split(".")[1] in toc.get(n.split(".")[0], {})]
            if names:
                lc = LogConfig(name=f"t15hop{i}", period_in_ms=50)
                for n in names:
                    lc.add_variable(n)
                lc.data_received_cb.add_callback(lambda _t, d, _l: got.update(d))
                cf.log.add_config(lc)
                lc.start()
        end = time.monotonic() + 5.0
        while time.monotonic() < end and "pm.vbat" not in got:
            time.sleep(0.1)
        time.sleep(0.5)
        hop.vbat = got.get("pm.vbat")
        st, vb = status(got.get("supervisor.info")), float(got.get("pm.vbat", 0.0))
        hop.set_phase("connected", f"battery {vb:.2f} V, drone {st}")
        if st == "LOCKED":
            hop.outcome = "error"
            hop.set_phase("error", "drone LOCKED: turn it off and on, keep it still, rerun")
            return
        if st == "not ready":
            hop.outcome = "error"
            hop.set_phase("error", "drone not ready: keep it flat and still a few seconds, rerun")
            return
        if vb < MIN_VBAT:
            hop.outcome = "error"
            hop.set_phase("error", f"battery {vb:.2f} V is under {MIN_VBAT} V")
            return
        if not hop.wait_for_phone():
            return
        if hop.ask('Type "hop" and press Enter to fly (anything else cancels): ').strip().lower() != "hop":
            hop.outcome = "cancelled"
            hop.set_phase("cancelled", "nothing was spun")
            return
        hop.fly(cf, got)
    finally:
        scf.close_link()


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live-drone", action="store_true", help="fly the real drone (default: print the profile)")
    p.add_argument("--uri", default="ble://Crazyflie")
    p.add_argument("--hover-thrust", type=int, help="thrust at which it lifts in cf_lift (required live)")
    p.add_argument("--height-in", type=float, default=5.0)
    p.add_argument("--forward-ft", type=float, default=3.0)
    p.add_argument("--pitch-deg", type=float, default=8.0, help="forward tilt; more = farther")
    p.add_argument("--reverse", action="store_true", help="flip the pitch sign if it hops backward")
    p.add_argument("--discovery-url")
    p.add_argument("--alias", type=int)
    p.add_argument("--wait-for-phone", type=float, default=0.0)
    p.add_argument("--coordinator")
    p.add_argument("--credentials", type=Path)
    p.add_argument("--linger-s", type=float, default=30.0)
    p.add_argument("--report", type=Path)
    return p


def main(argv=None, ask=input):
    p = build_parser()
    a = p.parse_args(argv)
    if a.live_drone and a.hover_thrust is None:
        p.error("--live-drone needs --hover-thrust (run: python -m sar_sim.cf_lift --uri ble://Crazyflie)")
    if a.hover_thrust is None:
        a.hover_thrust = 38000
    for name, lo, hi in (("hover_thrust", 25000, 45000), ("height_in", 2, 24), ("forward_ft", 0.5, 6),
                         ("pitch_deg", 3, 15)):
        v = getattr(a, name)
        if not finite(v) or not lo <= v <= hi:
            p.error(f"--{name.replace('_', '-')} must be between {lo} and {hi}")
    segs = profile(a.hover_thrust, a.height_in * INCH, a.forward_ft * FOOT, a.pitch_deg, a.reverse)
    log(f"hop: {a.height_in:g} in up, {a.forward_ft:g} ft {'backward' if a.reverse else 'forward'} at "
        f"{a.pitch_deg:g} deg, hover thrust {a.hover_thrust}; open-loop, {sum(s[1] for s in segs):.1f} s")
    for n, d, pt, t0, t1 in segs:
        log(f"  {n:<9} {d:4.2f} s  pitch {pt:+5.1f}  thrust {int(t0):5d} -> {int(t1):5d}")
    if not a.live_drone:
        log("profile only; add --live-drone --hover-thrust N to fly")
        return 0

    scanner = None
    if a.discovery_url:
        scanner = GroundScanner(a.discovery_url, alias=a.alias).start()
    hop = Hop(a, scanner=scanner, live=True, ask=ask)
    mc = None
    if a.coordinator:
        from mission_control.agent import load_token
        from mission_control.protocol import DEFAULT_CREDENTIALS
        try:
            token = load_token(a.credentials or DEFAULT_CREDENTIALS, "crazyflie")
            mc = MissionControl(a.coordinator, token, "LIVE", hop.telemetry)
            hop.mc = mc
            mc.start()
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            p.error(f"mission control: {exc}")
    try:
        connect_and_fly(hop, a.uri)
    except Exception as exc:
        hop.outcome = hop.outcome or "error"
        hop.set_phase("error", str(exc)[:300])
    finally:
        hop.outcome = hop.outcome or "error"
        hop.set_phase("on_ground", hop.summary_line())
        rep = hop.report()
        path = a.report or Path(f"/tmp/t15-hop-{time.strftime('%Y%m%dT%H%M%S')}.json")
        try:
            path.write_text(json.dumps(rep, indent=2))
            log(f"report: {path}")
        except OSError as exc:
            log(f"report not written ({exc})")
        if scanner is not None:
            scanner.stop()
        if mc is not None:
            mc.close(a.linger_s)
    log(f"outcome: {rep['outcome']}  {rep['summary']}")
    return 0 if rep["outcome"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())

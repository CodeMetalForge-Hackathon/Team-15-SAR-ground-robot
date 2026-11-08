#!/usr/bin/env python3
"""Fly the Crazyflie to the phone, hover over it, come back, and report to mission control.

Minimum demo for Team-15 (Code Metal Forge):
  1. (optional) wait until the ground BLE scanner sees the target phone: the trigger
  2. take off to about 5 inches
  3. fly 5 feet forward along the drone's boot heading (point the drone at the phone)
  4. hover over the phone and record its identity from the ground scanner
  5. fly back over the takeoff spot and land
  6. publish phase, pose, battery and the finding to mission control as the
     'crazyflie' node, and write a JSON report

The Crazyflie carries no Bluetooth receiver in this mode. Identity and RSSI come
from the stationary ESP32 scanner read by discovery.server (next to the Jetson).
The drone flies to where the phone is; it does not steer by signal strength.

Dry run (no hardware; real time, so the operator view can watch it):
    python3 crazyflie/fly_to_phone.py
    python3 crazyflie/fly_to_phone.py --coordinator http://127.0.0.1:8080
Live (see crazyflie/FLY_TO_PHONE.md for the full checklist):
    python3 -m sar_sim.cf_bridge --uri radio://0/80/2M/E7E7E7E7E7 --fence 2.0   # optional
    python3 crazyflie/fly_to_phone.py --live-drone --preflight-confirmed \\
        --discovery-url http://127.0.0.1:8765 --alias 1 --wait-for-phone 30 \\
        --coordinator http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import statistics
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INCH, FOOT = 0.0254, 0.3048
SCANNER_FRESH_S = 5.0     # unverified discovery signals go stale after 5 s on the server


DEFAULT_CAL = (3.28, -59.0, 2.2)   # 1 m reference, typical phone; calibrate at the venue instead


def distance_ft(rssi, cal):
    """Log-distance path loss: d = d_ref * 10^((rssi_ref - rssi) / (10 n))."""
    d_ref, r_ref, n = cal
    return d_ref * 10 ** ((r_ref - rssi) / (10 * n))


def parse_cal_point(text):
    ft, _, dbm = text.partition(":")
    try:
        ft, dbm = float(ft), float(dbm)
    except ValueError:
        raise ValueError(f"calibration point {text!r} must look like 3:-60 (feet:dBm)")
    if not (0.5 <= ft <= 30 and -120 <= dbm <= 0):
        raise ValueError(f"calibration point {text!r} is out of range")
    return ft, dbm


def make_cal(points):
    """Fit (d_ref, rssi_ref, n) through two (feet, dBm) readings."""
    (d1, r1), (d2, r2) = sorted(points)
    if d2 / d1 < 1.5:
        raise ValueError("take the two calibration readings at least 1.5x apart in distance (e.g. 2 ft and 6 ft)")
    n = (r1 - r2) / (10 * math.log10(d2 / d1))
    if not 1.2 <= n <= 5.0:
        raise ValueError(f"those readings give a path-loss exponent of {n:.2f} (expected 1.2-5; the closer "
                         "reading must be clearly stronger). Retake both with the phone held the same way.")
    return (d1, r1, n)


class Abort(Exception):
    """Stop the mission; leaving the link's context lands the drone where it is."""


def finite(*values):
    return all(type(v) in (int, float) and math.isfinite(v) for v in values)


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


# ---------------------------------------------------------------- simulation ----
class SimLink:
    """CrazyflieLink stand-in. Interpolates commanded motion on a virtual clock."""

    def __init__(self, speedup=1.0, vbat=4.05, drain_v_per_s=0.004):
        self.now, self.speedup = 0.0, speedup
        self.vbat0, self.drain = vbat, drain_v_per_s
        self.start, self.seg = (0.0, 0.0, 0.0), None
        self.flying, self.commands = False, []
        self.vbat_override = None
        self.pose_offset = (0.0, 0.0, 0.0)

    def clock(self):
        return self.now

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        if self.flying:
            x, y, _ = self._pos()
            self.commands.append(("land",))
            self._move((x, y, 0.0), 2.5)
            self.wait(3.1)
            self.flying = False
        return False

    @property
    def vbat(self):
        return self.vbat_override if self.vbat_override is not None else self.vbat0 - self.drain * self.now

    def _pos(self):
        if not self.seg:
            return self.start
        t0, a, b, d = self.seg
        f = min(1.0, (self.now - t0) / d)
        return tuple(a[i] + (b[i] - a[i]) * f for i in range(3))

    def _move(self, target, duration):
        self.start = self._pos()
        self.seg = (self.now, self.start, tuple(target), max(duration, 1e-6))

    def takeoff(self, height, duration):
        self.flying = True
        self.commands.append(("takeoff", height, duration))
        x, y, _ = self._pos()
        self._move((x, y, height), duration)

    def go_to(self, x, y, z, yaw, duration):
        self.commands.append(("go_to", x, y, z, yaw, duration))
        self._move((x, y, z), duration)

    def wait(self, seconds):
        seconds = max(0.0, seconds)
        self.now += seconds
        if math.isfinite(self.speedup) and self.speedup > 0:
            time.sleep(seconds / self.speedup)

    def pose(self):
        p = self._pos()
        return (p[0] + self.pose_offset[0], p[1] + self.pose_offset[1], p[2] + self.pose_offset[2], 0.0)


class SimScanner:
    """Stands in for the ground scanner in dry runs."""

    def __init__(self, present=True):
        self.present, self.n = present, 0

    def start(self):
        return self

    def stop(self):
        pass

    def current(self):
        if not self.present:
            return None
        self.n += 1
        return dict(verified=True, mode_label="SIMULATED", label="Enrolled beacon 001", alias=1,
                    rssi=-62 + (self.n * 7) % 5 - 2, age_s=0.3)

    def rssis(self, since=None):
        return [-62 + (i * 7) % 5 - 2 for i in range(12)] if self.present else []

    def summary(self, since=None):
        cur = self.current()
        return _summary(cur, [cur["rssi"]] * 8 if cur else [], "SIMULATED ground scanner")


# ------------------------------------------------------------ ground scanner ----
def _summary(latest, rssis, sensed_by):
    out = dict(sensed_by=sensed_by, detected=latest is not None, samples=len(rssis))
    if latest:
        out.update({k: latest[k] for k in ("verified", "label", "alias", "id", "classification",
                                            "mode_label", "age_s") if k in latest})
        out["rssi_dbm_latest"] = latest["rssi"]
    if rssis:
        out["rssi_dbm_median"] = statistics.median(rssis)
    return out


class GroundScanner:
    """Polls the existing discovery server (stationary ESP32) for the target phone.

    --alias N        an authenticated, enrolled beacon from /api/beacons (identity proven)
    --signal-id ID   an unverified advertisement from /api/discovery (identity NOT proven)
    neither          the freshest authenticated sighting, if any
    """

    def __init__(self, url, alias=None, signal_id=None, period=0.25):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.path not in ("", "/"):
            raise ValueError("--discovery-url must be http(s)://HOST:PORT")
        self.url, self.alias, self.signal_id, self.period = url.rstrip("/"), alias, signal_id, period
        self.lock, self.stop_event = threading.Lock(), threading.Event()
        self.latest, self.error, self.samples = None, None, []
        self._last_age, self._keys = None, set()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _get(self, path):
        with urlopen(self.url + path, timeout=0.5) as r:
            data = json.loads(r.read(1024 * 1024))
        if not isinstance(data, dict):
            raise ValueError("bad snapshot")
        return data

    def read_once(self):
        if self.signal_id is not None:
            d = self._get("/api/discovery")
            s = next((s for s in d.get("signals", []) if s.get("id") == self.signal_id), None)
            if not s or s.get("stale") or not finite(s.get("rssi"), s.get("age_s")) or s["age_s"] > SCANNER_FRESH_S:
                return None
            return dict(verified=False, id=s["id"], label=s.get("label"), classification=s.get("classification"),
                        rssi=s["rssi"], age_s=s["age_s"], mode_label="UNVERIFIED ADVERTISEMENT")
        b = self._get("/api/beacons")
        found = [s for s in b.get("sightings", []) if not s.get("stale") and finite(s.get("rssi"))
                 and (self.alias is None or s.get("alias") == self.alias)]
        if not found:
            return None
        s = min(found, key=lambda s: s.get("last_verified_age_s", 1e9))
        # A verified sighting refreshes once per 30 s token window. Within the window the phone
        # keeps sending the same token; the verifier logs those as "replay": same signature check,
        # same phone, fresh RSSI. Use them (and the verified ones) as signal readings.
        now = time.monotonic()
        samples = [(now - e["age_s"], e["rssi"]) for e in b.get("events", [])
                   if e.get("alias") == s["alias"] and e.get("kind") in ("verified", "replay")
                   and finite(e.get("rssi"), e.get("age_s"))]
        return dict(verified=True, alias=s["alias"], label=s.get("label"), rssi=s["rssi"],
                    age_s=s.get("last_verified_age_s"), mode_label=b.get("mode_label"),
                    samples=samples)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                cur, err = self.read_once(), None
            except Exception as exc:          # network, JSON, server restarting
                cur, err = None, f"{type(exc).__name__}: {exc}"[:150]
            with self.lock:
                samples = cur.pop("samples", None) if cur else None
                if samples:
                    cur["rssi"] = max(samples)[1]            # newest authenticated reading
                self.latest, self.error = cur, err
                if samples:
                    for t, r in samples:
                        key = round(t, 1)                     # events carry age to 0.1 s
                        if key not in self._keys:
                            self._keys.add(key)
                            self.samples.append((t, r))
                    if len(self._keys) > 5000:
                        self._keys = {round(t, 1) for t, _ in self.samples[-500:]}
                    del self.samples[:-2000]
                elif cur is not None and finite(cur.get("age_s")):
                    if self._last_age is None or cur["age_s"] < self._last_age - 0.01:
                        self.samples.append((time.monotonic(), cur["rssi"]))   # a new packet arrived
                        del self.samples[:-2000]
                    self._last_age = cur["age_s"]
            self.stop_event.wait(self.period)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()

    def current(self):
        with self.lock:
            return dict(self.latest) if self.latest else None

    def rssis(self, since=None):
        with self.lock:
            return [r for t, r in self.samples if since is None or t >= since]

    def summary(self, since=None):
        with self.lock:
            rssis = [r for t, r in self.samples if since is None or t >= since]
            latest = dict(self.latest) if self.latest else None
            err = self.error
        out = _summary(latest, rssis, "ground scanner (stationary ESP32 via discovery.server)")
        if err:
            out["scanner_error"] = err
        return out


# ----------------------------------------------------------- mission control ----
class MissionControl:
    """Reports as the 'crazyflie' node over the same sync API mission_control.agent uses.

    Operator STOP/pause (any safety command after the first sync) lands the drone.
    Manual flight commands are refused while this script flies. If no sync
    succeeds for `lost_s` while airborne, the mission aborts and lands.
    """

    def __init__(self, url, token, mode, telemetry, period=0.25):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.path not in ("", "/"):
            raise ValueError("--coordinator must be http(s)://HOST:PORT")
        self.url = url.rstrip("/") + "/api/nodes/crazyflie/sync"
        self.token, self.mode, self.telemetry, self.period = token, mode, telemetry, period
        self.boot = secrets.token_hex(16)
        self.stop_requested = threading.Event()
        self.stop_reason = ""
        self.result, self.error = None, None
        self.last_ok = time.monotonic()
        self.halt = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def sync_once(self, first=False):
        body = json.dumps(dict(boot=self.boot, mode=self.mode, telemetry=self.telemetry(),
                               result=self.result), allow_nan=False).encode()
        req = Request(self.url, body, {"Authorization": "Bearer " + self.token,
                                       "Content-Type": "application/json"})
        with urlopen(req, timeout=0.8) as r:
            reply = json.load(r)
        self.result, self.last_ok, self.error = None, time.monotonic(), None
        cmd = reply.get("command")
        if cmd and cmd.get("safety"):
            if not first:          # the first reply carries the "node connected" landing request
                self.stop_reason = "Operator STOP/pause from mission control"
                self.stop_requested.set()
        elif cmd:
            self.result = dict(id=cmd["id"], ok=False,
                               detail="fly_to_phone.py is flying autonomously; manual commands refused")
            self.stop_reason = "Manual command arrived while flying autonomously"
            self.stop_requested.set()

    def start(self):
        try:
            self.sync_once(first=True)
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            hint = " (is mission_control.agent --node crazyflie still running? stop it first)" \
                if exc.code == 409 else ""
            raise RuntimeError(f"mission control refused the crazyflie node: {exc.code} {detail}{hint}")
        self.thread.start()
        return self

    def _loop(self):
        while not self.halt.wait(self.period):
            try:
                self.sync_once()
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:150]

    def close(self, linger_s=0.0):
        end = time.monotonic() + max(0.0, linger_s)
        try:
            while time.monotonic() < end:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        self.halt.set()
        self.thread.join(timeout=1.5)
        try:
            self.sync_once()
        except Exception:
            pass


# ------------------------------------------------------------------ mission ----
class Mission:
    def __init__(self, link, cfg, scanner=None, mc=None, live=False):
        self.link, self.cfg, self.scanner, self.mc, self.live = link, cfg, scanner, mc, live
        self.clock = getattr(link, "clock", time.monotonic)
        self.lock = threading.Lock()
        self.snap = dict(pose=None, vbat=None, t=time.monotonic())
        self.phase, self.detail, self.outcome = "connecting", "", None
        self.airborne, self.t_air = False, None
        self.trigger, self.finding, self.events = None, None, []
        self.home = (0.0, 0.0)
        self.forward_m, self.estimate = cfg.forward_m, None
        self.bad_vbat_since = self.bad_pose_since = None

    # ---- shared state -------------------------------------------------------
    def set_phase(self, phase, detail=""):
        with self.lock:
            self.phase, self.detail = phase, detail
            self.events.append(dict(t=round(time.time(), 2), phase=phase, detail=detail))
        log(f"[{phase}] {detail}")

    def _sample(self):
        pose, vbat = self.link.pose(), self.link.vbat
        with self.lock:
            self.snap = dict(pose=tuple(pose[:3]) if pose and finite(*pose[:3]) else None,
                             vbat=vbat if finite(vbat) else None, t=time.monotonic())
        return self.snap

    def telemetry(self):
        with self.lock:
            s, phase, detail = dict(self.snap), self.phase, self.detail
            finding, trigger, outcome = self.finding, self.trigger, self.outcome
            estimate, fwd = self.estimate, self.forward_m
            airborne = self.airborne
        c = self.cfg
        t = dict(ready=True, source="LIVE" if self.live else "SIMULATED", airborne=airborne,
                 position_frame="boot",
                 position_source="onboard estimator" if self.live else "SIMULATED",
                 battery_v=round(s["vbat"], 2) if s["vbat"] is not None else None,
                 busy=airborne, agent_error="",
                 last_action=f"{phase}: {detail}"[:300],
                 mission=dict(script="fly_to_phone", phase=phase, detail=detail, outcome=outcome,
                              target_m=[round(fwd, 3), 0.0, round(c.height_m, 3)],
                              distance_estimate=estimate,
                              elapsed_s=None if self.t_air is None else round(self.clock() - self.t_air, 1),
                              trigger=trigger, finding=finding,
                              summary=self.summary_line()))
        if s["pose"] is not None:
            t["position_m"] = [round(v, 3) for v in s["pose"]]
            t["position_age_s"] = round(min(2.0, max(0.0, time.monotonic() - s["t"])), 3)
        else:
            t["position_m"] = None
        return t

    def summary_line(self):
        e = self.estimate
        pre = ""
        if e and e.get("used") == "signal":
            pre = (f"Signal put the phone at ~{e['estimate_ft']} ft (noise spread {e['spread_ft'][0]}-"
                   f"{e['spread_ft'][1]} ft{'' if e['calibrated'] else ', UNCALIBRATED'}); flew {e['forward_ft']} ft. ")
        elif e:
            pre = f"Signal too sparse ({e['reason']}); flew the fixed {e['forward_ft']} ft. "
        return pre + self._finding_line()

    def _finding_line(self):
        f = self.finding
        if self.outcome == "no_phone":
            return "Phone not detected by ground scanner; drone did not fly"
        if not f:
            return ""
        if not f.get("detected"):
            return "No fresh reading of the phone while hovering over it"
        rssi = f.get("rssi_dbm_median", f.get("rssi_dbm_latest"))
        kind = "verified" if f.get("verified") else "UNVERIFIED"
        return (f"Phone found: {f.get('label')} ({kind}, {f.get('mode_label')}), "
                f"{rssi} dBm over {f.get('samples')} packets, {f.get('sensed_by')}")

    # ---- safety ---------------------------------------------------------------
    def _check(self):
        c, now, wall = self.cfg, self.clock(), time.monotonic()
        if self.mc is not None:
            if self.mc.stop_requested.is_set():
                raise Abort(self.mc.stop_reason or "Operator STOP")
            if self.airborne and wall - self.mc.last_ok > c.mc_lost_s:
                raise Abort(f"Mission control unreachable for {c.mc_lost_s:.0f} s (no operator STOP path)")
        if not self.airborne:
            return
        s = self.snap
        if now - self.t_air > c.max_flight_s:
            raise Abort(f"Flight time limit {c.max_flight_s:.0f} s reached")
        v = s["vbat"]
        if v is None or v < c.vbat_min:
            self.bad_vbat_since = self.bad_vbat_since if self.bad_vbat_since is not None else now
            if now - self.bad_vbat_since > (1.0 if v is None else 0.5):
                raise Abort("Battery unavailable" if v is None else f"Battery {v:.2f} V below {c.vbat_min} V")
        else:
            self.bad_vbat_since = None
        p = s["pose"]
        if p is None:
            self.bad_pose_since = self.bad_pose_since if self.bad_pose_since is not None else now
            if now - self.bad_pose_since > 0.5:
                raise Abort("Position estimate lost")
            return
        self.bad_pose_since = None
        hx, hy = self.home
        if not (hx - c.corridor_m <= p[0] <= hx + self.forward_m + c.corridor_m
                and abs(p[1] - hy) <= c.corridor_m + 0.1 and p[2] <= c.height_m + 0.35):
            raise Abort(f"Left the flight corridor at ({p[0]:+.2f}, {p[1]:+.2f}, {p[2]:.2f}) m")

    def hold(self, seconds):
        end = self.clock() + seconds
        while self.clock() < end:
            self.link.wait(min(0.1, max(0.0, end - self.clock())))
            self._sample()
            self._check()

    def estimate_distance(self):
        c = self.cfg
        if self.scanner is None:
            raise Abort("--distance-from-signal needs the ground scanner (--discovery-url)")
        self.set_phase("measuring_signal", f"{c.signal_window_s:.0f} s of phone readings before launch")
        since, end = time.monotonic(), self.clock() + c.signal_window_s
        while self.clock() < end:
            self._check()
            self.link.wait(0.2)
            self._sample()
        rs = sorted(self.scanner.rssis(since))
        d_ref, r_ref, n = c.cal
        est = dict(samples=len(rs), calibrated=c.cal_ok,
                   model=dict(ref_ft=round(d_ref, 2), ref_dbm=r_ref, exponent=round(n, 2)))
        if len(rs) < c.min_signal_samples:
            est.update(used="fixed", forward_ft=round(self.forward_m / FOOT, 2),
                       reason=f"{len(rs)} readings in {c.signal_window_s:.0f} s, need {c.min_signal_samples}")
        else:
            med = statistics.median(rs)
            weak, strong = rs[len(rs) // 4], rs[(3 * len(rs)) // 4]
            d = distance_ft(med, c.cal)
            hop = min(max(d, c.min_forward_ft), c.max_forward_ft)
            est.update(used="signal", rssi_dbm_median=med, rssi_dbm_iqr=[weak, strong],
                       estimate_ft=round(d, 1),
                       spread_ft=[round(distance_ft(strong, c.cal), 1), round(distance_ft(weak, c.cal), 1)],
                       forward_ft=round(hop, 2), clamped=abs(hop - d) > 1e-9)
            self.forward_m = hop * FOOT
        with self.lock:
            self.estimate = est
        self.set_phase("distance_estimated", self.summary_line().split(". ")[0])

    def arrived(self, target, name, tol_xy, tol_z):
        p = self.snap["pose"]
        if p is None:
            raise Abort(f"{name}: no position estimate")
        exy, ez = math.hypot(p[0] - target[0], p[1] - target[1]), abs(p[2] - target[2])
        if exy > tol_xy or ez > tol_z:
            raise Abort(f"{name}: {exy:.2f} m off horizontally, {ez:.2f} m off vertically "
                        "(position hold is not good enough; check Flow deck, floor texture, light)")
        log(f"  {name}: within {exy:.2f} m / {ez:.2f} m of target")

    # ---- the flight -----------------------------------------------------------
    def run(self):
        c, L = self.cfg, self.link
        try:
            self._sample()
            if self.scanner is not None and c.wait_for_phone > 0:
                self.set_phase("waiting_for_phone", f"up to {c.wait_for_phone:.0f} s for the ground scanner")
                end = self.clock() + c.wait_for_phone
                while self.scanner.current() is None:
                    self._check()
                    if self.clock() >= end:
                        self.outcome = "no_phone"
                        self.set_phase("no_phone", "phone not detected; drone stays on the ground")
                        return self.outcome
                    L.wait(0.2)
                    self._sample()
            if self.scanner is not None:
                self.trigger = self.scanner.current()
                if self.trigger:
                    log(f"  trigger: {self.trigger.get('label')} at {self.trigger.get('rssi')} dBm "
                        f"({'verified' if self.trigger.get('verified') else 'UNVERIFIED'})")

            if c.distance_from_signal:
                self.estimate_distance()

            s = self._sample()
            if s["vbat"] is None or s["vbat"] < c.takeoff_vbat:
                raise Abort(f"Battery {s['vbat']} V is below the {c.takeoff_vbat} V takeoff minimum")
            if s["pose"] is None:
                raise Abort("No position estimate before takeoff (positioning deck attached and settled?)")
            self.home = s["pose"][:2]
            hx, hy, h, d = self.home[0], self.home[1], c.height_m, self.forward_m

            self.set_phase("takeoff", f"to {h / INCH:.1f} in")
            self.t_air, self.airborne = self.clock(), True
            L.takeoff(h, c.takeoff_s)
            self.hold(c.takeoff_s + 0.8)
            self.arrived((hx, hy, h), "takeoff", 0.25, 0.08)

            leg = max(1.0, d / c.speed)
            self.set_phase("outbound", f"{d / FOOT:.1f} ft forward at {c.speed:.2f} m/s")
            L.go_to(hx + d, hy, h, 0.0, leg)
            self.hold(leg + 1.0)
            self.arrived((hx + d, hy, h), "at phone", 0.30, 0.10)

            self.set_phase("at_phone", f"hovering {c.hover_s:.0f} s over the phone")
            since = time.monotonic()
            self.hold(c.hover_s)
            if self.scanner is not None:
                with self.lock:
                    self.finding = self.scanner.summary(since=since)
                log("  " + self.summary_line())

            self.set_phase("returning", "back over the takeoff spot")
            L.go_to(hx, hy, h, 0.0, leg)
            self.hold(leg + 1.0)
            self.set_phase("landing", "")
            self.outcome = "completed"
        except Abort as exc:
            self.outcome = "aborted"
            self.set_phase("aborted", f"{exc}; landing in place")
        except RuntimeError as exc:               # the bridge or radio refused something
            msg = str(exc)
            if "fence" in msg:
                msg += "  -> restart the bridge with --fence 2.0 (5 ft is 1.52 m; default fence is 1.5 m)"
            self.outcome = "aborted"
            self.set_phase("aborted", f"{msg}; landing in place")
        return self.outcome

    def finish(self, outcome):
        with self.lock:
            self.outcome = self.outcome or outcome
            was_airborne, self.airborne = self.airborne, False
        try:
            self._sample()
        except Exception:
            pass
        if self.scanner is not None and self.finding is None and self.outcome != "no_phone":
            with self.lock:
                self.finding = self.scanner.summary()
        self.set_phase("on_ground", "landing requested and link closed" if was_airborne else "did not take off")

    def report(self):
        with self.lock:
            return dict(script="fly_to_phone", mode="LIVE" if self.live else "SIMULATED",
                        outcome=self.outcome, summary=self.summary_line(),
                        height_in=round(self.cfg.height_m / INCH, 1), forward_ft=round(self.cfg.forward_m / FOOT, 2),
                        flown_forward_ft=round(self.forward_m / FOOT, 2), distance_estimate=self.estimate,
                        trigger=self.trigger, finding=self.finding, events=list(self.events),
                        note="Identity/RSSI come from the stationary ground scanner, not from the drone.")


# --------------------------------------------------------------------- main ----
def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live-drone", action="store_true", help="fly the real Crazyflie (default: dry run)")
    p.add_argument("--preflight-confirmed", action="store_true",
                   help="required with --live-drone: Flow deck on, area clear, drone facing the phone")
    p.add_argument("--uri", default="radio://0/80/2M/E7E7E7E7E7")
    p.add_argument("--height-in", type=float, default=5.0, help="hover height, inches (default 5)")
    p.add_argument("--forward-ft", type=float, default=5.0, help="distance to the phone, feet (default 5)")
    p.add_argument("--speed", type=float, default=0.25, help="horizontal speed, m/s (0.1-0.4)")
    p.add_argument("--hover-s", type=float, default=4.0, help="seconds hovering over the phone")
    p.add_argument("--takeoff-s", type=float, default=2.0)
    p.add_argument("--max-flight-s", type=float, default=45.0)
    p.add_argument("--vbat-min", type=float, default=3.3, help="land below this in flight (V)")
    p.add_argument("--takeoff-vbat", type=float, default=3.6, help="refuse takeoff below this (V)")
    p.add_argument("--discovery-url", help="ground scanner, e.g. http://127.0.0.1:8765")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--alias", type=int, help="enrolled, authenticated beacon alias to look for")
    g.add_argument("--signal-id", help="unverified discovery signal id to look for")
    p.add_argument("--wait-for-phone", type=float, default=0.0,
                   help="seconds to wait for the phone before taking off; 0 = fly immediately")
    p.add_argument("--distance-from-signal", action="store_true",
                   help="set the hop from the phone's signal strength (scanner beside the drone's takeoff spot)")
    p.add_argument("--rssi-cal", nargs=2, metavar="FT:DBM",
                   help="two venue readings from --calibrate-at, e.g. --rssi-cal 2:-52 6:-64")
    p.add_argument("--calibrate-at", type=float, metavar="FT",
                   help="no flight: print the phone's median signal with it FT feet from the scanner")
    p.add_argument("--signal-window-s", type=float, default=5.0, help="seconds of readings to average")
    p.add_argument("--min-signal-samples", type=int, default=5)
    p.add_argument("--min-forward-ft", type=float, default=1.0)
    p.add_argument("--max-forward-ft", type=float, default=6.0)
    p.add_argument("--coordinator", help="mission control, e.g. http://127.0.0.1:8080")
    p.add_argument("--credentials", type=Path, help="role file with the 'crazyflie' token "
                   "(default ~/.config/team15/network.json)")
    p.add_argument("--linger-s", type=float, default=30.0,
                   help="keep the result visible in mission control this long after landing")
    p.add_argument("--report", type=Path, help="JSON report path (default /tmp/t15-fly-to-phone-<time>.json)")
    p.add_argument("--fast", action="store_true", help="dry run without real-time waits")
    p.add_argument("--sim-no-phone", action="store_true", help="dry run: the scanner never sees the phone")
    return p


def validate(args, p):
    if args.live_drone and not args.preflight_confirmed:
        p.error("--live-drone needs --preflight-confirmed (Flow deck on, area clear, drone facing the phone)")
    if args.live_drone and args.fast:
        p.error("--fast is dry-run only")
    for name, lo, hi in (("height_in", 4, 40), ("forward_ft", 0.5, 6.0), ("speed", 0.1, 0.4),
                         ("hover_s", 0, 15), ("max_flight_s", 15, 90), ("wait_for_phone", 0, 600)):
        v = getattr(args, name)
        if not finite(v) or not lo <= v <= hi:
            p.error(f"--{name.replace('_', '-')} must be between {lo} and {hi}")
    for name, lo, hi in (("signal_window_s", 1, 30), ("min_forward_ft", 0.5, 6.0), ("max_forward_ft", 0.5, 6.0)):
        v = getattr(args, name)
        if not finite(v) or not lo <= v <= hi:
            p.error(f"--{name.replace('_', '-')} must be between {lo} and {hi}")
    if args.min_forward_ft > args.max_forward_ft:
        p.error("--min-forward-ft is above --max-forward-ft")
    try:
        args.cal = make_cal([parse_cal_point(t) for t in args.rssi_cal]) if args.rssi_cal else DEFAULT_CAL
    except ValueError as exc:
        p.error(str(exc))
    args.cal_ok = bool(args.rssi_cal)
    args.height_m, args.forward_m = args.height_in * INCH, args.forward_ft * FOOT
    args.corridor_m, args.mc_lost_s = 0.45, 2.0
    longest = max(args.forward_m, args.max_forward_ft * FOOT if args.distance_from_signal else 0)
    need = args.takeoff_s + 0.8 + 2 * (max(1.0, longest / args.speed) + 1.0) + args.hover_s + 3
    if need > args.max_flight_s:
        p.error(f"this flight needs about {need:.0f} s; raise --max-flight-s or --speed")


def calibrate(args, scanner):
    if scanner is None:
        log("--calibrate-at needs --discovery-url (the ground scanner)")
        return 2
    window = max(8.0, args.signal_window_s)
    log(f"hold the phone {args.calibrate_at:g} ft from the scanner, in front of it, as it will be in the demo; "
        f"measuring for {window:.0f} s")
    scanner.start()
    since = time.monotonic()
    try:
        if not args.fast:
            time.sleep(window)
    finally:
        rs = scanner.rssis(since)
        scanner.stop()
    if len(rs) < args.min_signal_samples:
        log(f"only {len(rs)} readings; is the phone advertising and the right --alias/--signal-id set?")
        return 1
    med = statistics.median(rs)
    log(f"{len(rs)} readings, median {med:g} dBm (min {min(rs)}, max {max(rs)})")
    print(f"{args.calibrate_at:g}:{med:g}")
    return 0


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    validate(args, p)
    live = args.live_drone
    if args.height_in < 8:
        log(f"note: {args.height_in:.0f} in is inside ground effect; if the hover bounces, try --height-in 12")

    if live:
        from sar_sim.backends.crazyflie_backend import CrazyflieLink
        link = CrazyflieLink(args.uri)
    else:
        link = SimLink(speedup=math.inf if args.fast else 1.0)

    if args.discovery_url:
        scanner = GroundScanner(args.discovery_url, alias=args.alias, signal_id=args.signal_id)
    elif not live:
        scanner = SimScanner(present=not args.sim_no_phone)
    else:
        scanner = None
        log("note: no --discovery-url; the drone will fly but report no phone identity")

    if args.calibrate_at is not None:
        return calibrate(args, scanner)
    if args.distance_from_signal and not args.cal_ok:
        log("note: --distance-from-signal without --rssi-cal uses a generic phone model; expect large errors")

    mission = Mission(link, args, scanner=scanner, live=live)
    mc = None
    if args.coordinator:
        from mission_control.agent import load_token
        from mission_control.protocol import DEFAULT_CREDENTIALS
        try:
            token = load_token(args.credentials or DEFAULT_CREDENTIALS, "crazyflie")
        except (OSError, ValueError, KeyError) as exc:
            p.error(f"crazyflie credentials: {exc} (create with: python3 -m mission_control.server --init)")
        mc = MissionControl(args.coordinator, token, "LIVE" if live else "SIMULATED", mission.telemetry)
        mission.mc = mc
        try:
            mc.start()
        except (OSError, RuntimeError) as exc:
            p.error(f"mission control: {exc}")
        log(f"reporting to mission control at {args.coordinator} as the crazyflie node")

    if scanner is not None:
        scanner.start()
    outcome = "error"
    try:
        with link:                 # live: connects and settles the estimator; leaving ALWAYS lands
            mission.set_phase("connected", f"{'LIVE ' + args.uri if live else 'dry run'}")
            outcome = mission.run()
    except KeyboardInterrupt:
        mission.outcome = "aborted"
        mission.set_phase("aborted", "Ctrl+C; landing requested")
        outcome = "aborted"
    except Exception as exc:       # could not connect, estimator did not settle, no deck
        mission.outcome = "error"
        mission.set_phase("error", str(exc)[:300])
    finally:
        mission.finish(outcome)
        rep = mission.report()
        path = args.report or Path(f"/tmp/t15-fly-to-phone-{time.strftime('%Y%m%dT%H%M%S')}.json")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "w") as f:
                json.dump(rep, f, indent=2)
            log(f"report: {path}")
        except OSError as exc:
            log(f"report not written ({exc})")
        if scanner is not None:
            scanner.stop()
        if mc is not None:
            if args.linger_s > 0:
                log(f"result stays live in mission control for {args.linger_s:.0f} s (Ctrl+C to quit)")
            mc.close(args.linger_s)
    log(f"outcome: {rep['outcome']}  {rep['summary']}")
    return 0 if rep["outcome"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())

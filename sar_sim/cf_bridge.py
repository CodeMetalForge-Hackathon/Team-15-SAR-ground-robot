"""Team-15 Crazyflie bridge: the one program that owns the Crazyradio.

Start it first, on the Jetson or laptop with the Crazyradio plugged in:
    python3 -m sar_sim.cf_bridge --uri radio://0/80/2M/E7E7E7E7E7

It does three jobs.
  1. Scanner lines. The drone app's packets become the scanner's own text
     lines on a pseudo-serial port, /tmp/t15-scanner-<id>. Mabelle's
     discovery server reads it unchanged:
         python3 -m discovery.server --serial /tmp/t15-scanner-1
  2. Commands. Programs fly the drone over a local socket (127.0.0.1:8770),
     one JSON object per line. CrazyflieLink (her demo and keyboard
     control) and the homebase planner both use it.
  3. Safety. The bridge lands a flying drone when the program flying it
     disconnects or goes quiet for 2 s, when pose stops arriving, when the
     battery reads below --vbat-min, or on Ctrl-C. The drone app lands it
     too if this bridge goes quiet. Commands outside the fence are refused.
"""
from __future__ import annotations

import argparse
import fcntl
import itertools
import json
import math
import os
import queue
import socketserver
import struct
import termios
import threading
import time
import tty

from sar_sim import scanner_codec
from sar_sim.cf_core import CfDrone

PORT = 8770
LAND_S = 2.5
SCANNER_PARAMS = ("minRssi", "advHz", "capPps", "wdMs")


class ScannerPort:
    """A pseudo-serial port that carries one drone's scanner lines."""

    def __init__(self, path):
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)                       # no echo, no line editing
        flags = fcntl.fcntl(self.master, fcntl.F_GETFL)
        fcntl.fcntl(self.master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.path, self.dropped, self.lines = path, 0, 0
        if os.path.islink(path) or os.path.exists(path):
            os.unlink(path)
        os.symlink(os.ttyname(self.slave), path)

    def write_line(self, line):
        try:
            waiting = struct.unpack("i", fcntl.ioctl(self.slave, termios.FIONREAD, b"\0" * 4))[0]
            if waiting > 2048:                       # nobody is reading: don't keep stale lines
                termios.tcflush(self.slave, termios.TCIFLUSH)
            os.write(self.master, line.encode() + b"\n")
            self.lines += 1
        except OSError:
            self.dropped += 1
        try:
            while os.read(self.master, 4096):        # the reader never writes; drain just in case
                pass
        except OSError:
            pass

    def close(self):
        try:
            if os.path.islink(self.path) and os.readlink(self.path) == os.ttyname(self.slave):
                os.unlink(self.path)
        except OSError:
            pass
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass


class Slot:
    """One drone, its scanner port, and who is flying it."""

    def __init__(self, idx, uri, port_path, log):
        self.id, self.uri, self.log = idx, uri, log
        self.port = ScannerPort(port_path) if port_path else None
        self.drone = CfDrone(uri, on_app_packet=self._packet, log=log)
        self.lock = threading.RLock()
        self.pilot = None
        self.pilot_seen = 0.0
        self.landing_until = None
        self.subscribers: set[queue.Queue] = set()
        self.drone_stats = {}
        self.last_keep = 0.0

    def _packet(self, pkt):
        stats = scanner_codec.drone_stats(pkt)
        if stats:
            self.drone_stats = stats
        line = scanner_codec.decode(pkt)
        if line is None:
            return
        if self.port:
            self.port.write_line(line)
        for q in list(self.subscribers):
            try:
                q.put_nowait(line)
            except queue.Full:
                pass


class Bridge:
    def __init__(self, uris, host="127.0.0.1", port=PORT, scanner_dir="/tmp", fence_xy=1.5,
                 z_min=0.1, z_max=1.5, vbat_min=3.0, takeoff_vbat=3.5, pilot_timeout=2.0,
                 scanner_params=None, land_s=LAND_S, log=print):
        self.log = log
        self.slots = {}
        for i, uri in enumerate(uris, start=1):
            path = os.path.join(scanner_dir, f"t15-scanner-{i}") if scanner_dir else None
            self.slots[i] = Slot(i, uri, path, log)
        self.host, self.port = host, port
        self.fence_xy, self.z_min, self.z_max = fence_xy, z_min, z_max
        self.vbat_min, self.takeoff_vbat, self.pilot_timeout = vbat_min, takeoff_vbat, pilot_timeout
        self.scanner_params = scanner_params or {}
        self.land_s = land_s
        self.sessions = itertools.count(1)
        self.stop_event = threading.Event()
        self.server = None

    # ---- lifecycle --------------------------------------------------------
    def start(self):
        for s in self.slots.values():
            self.log(f"connecting drone {s.id}: {s.uri}")
            s.drone.connect()
            if s.drone.has_app:
                for name, value in self.scanner_params.items():
                    s.drone.set_param(f"t15scan.{name}", value)
            if s.port:
                self.log(f"  drone {s.id} scanner lines on {s.port.path}")
        bridge = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                bridge._serve(self)

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer((self.host, self.port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self._safety_loop, daemon=True).start()
        self.log(f"bridge ready on {self.host}:{self.port}")
        return self

    def close(self):
        self.stop_event.set()
        flying = [s for s in self.slots.values() if s.drone.flying]
        for s in flying:
            self._land(s, "bridge shutting down")
        if flying:
            time.sleep(self.land_s + 0.5)
        for s in self.slots.values():
            if s.drone.flying:
                s.drone.stop()
            s.drone.close()
            if s.port:
                s.port.close()
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    # ---- safety -----------------------------------------------------------
    def _land(self, s, reason):
        with s.lock:
            if s.landing_until is not None:
                return
            self.log(f"drone {s.id}: LANDING ({reason})")
            try:
                s.drone.land(self.land_s)
            except Exception as exc:          # link gone: the drone app's watchdog lands it
                self.log(f"drone {s.id}: land command failed: {exc}")
            s.landing_until = time.monotonic() + self.land_s + 0.5

    def _safety_loop(self):
        while not self.stop_event.wait(0.1):
            now = time.monotonic()
            for s in self.slots.values():
                if s.drone.connected and now - s.last_keep >= 0.5:
                    s.last_keep = now
                    try:
                        s.drone.send_app(scanner_codec.KEEPALIVE)
                    except Exception:
                        pass
                with s.lock:
                    if s.landing_until is not None:
                        if now >= s.landing_until:
                            s.drone.stop()
                            s.landing_until, s.pilot = None, None
                            self.log(f"drone {s.id}: landed, motors off")
                        continue
                    if not s.drone.flying:
                        continue
                    st = s.drone.state()
                    if st["age"] > 1.0:
                        self._land(s, f"no pose for {st['age']:.1f} s")
                    elif st["vbat"] is not None and st["vbat"] < self.vbat_min:
                        self._land(s, f"battery {st['vbat']:.2f} V")
                    elif s.pilot is None or now - s.pilot_seen > self.pilot_timeout:
                        self._land(s, "the program flying it went quiet")

    # ---- requests ---------------------------------------------------------
    def _serve(self, h):
        session = next(self.sessions)
        try:
            for raw in h.rfile:
                try:
                    msg = json.loads(raw)
                    if msg.get("op") == "subscribe":
                        return self._stream(h, self._slot(msg))
                    reply = self.handle(session, msg)
                except Exception as exc:
                    reply = dict(ok=False, error=str(exc))
                self._touch(session)                # quiet time counts from the end of each request
                h.wfile.write((json.dumps(reply) + "\n").encode())
                h.wfile.flush()
        except OSError:
            pass
        finally:
            for s in self.slots.values():
                with s.lock:
                    if s.pilot == session:
                        s.pilot = None              # the safety loop lands it if still flying

    def _stream(self, h, s):
        q = queue.Queue(maxsize=1000)
        s.subscribers.add(q)
        try:
            while not self.stop_event.is_set():
                try:
                    line = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                h.wfile.write((json.dumps(dict(scan=s.id, line=line)) + "\n").encode())
                h.wfile.flush()
        except OSError:
            pass
        finally:
            s.subscribers.discard(q)

    def _slot(self, msg):
        s = self.slots.get(int(msg.get("id", 1)))
        if s is None:
            raise ValueError(f"no drone {msg.get('id')}; have {sorted(self.slots)}")
        return s

    def _fly(self, s, session):
        if s.pilot not in (None, session) and s.drone.flying:
            raise RuntimeError(f"drone {s.id} is being flown by another program")
        if s.landing_until is not None:
            raise RuntimeError(f"drone {s.id} is landing")
        s.pilot, s.pilot_seen = session, time.monotonic()

    def _check_point(self, x, y, z):
        vals = (x, y, z)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
            raise ValueError("waypoint must be finite numbers")
        if abs(x) > self.fence_xy or abs(y) > self.fence_xy or not self.z_min <= z <= self.z_max:
            raise ValueError(f"({x:.2f}, {y:.2f}, {z:.2f}) is outside the fence "
                             f"(±{self.fence_xy} m, {self.z_min}-{self.z_max} m up)")

    def handle(self, session, msg):
        op = msg.get("op")
        now = time.monotonic()
        for s in self.slots.values():
            if s.pilot == session:
                s.pilot_seen = now
        if op == "hello":
            return dict(ok=True, drones=[dict(id=s.id, uri=s.uri, app=s.drone.has_app,
                                              decks=s.drone.decks,
                                              scanner=s.port.path if s.port else None)
                                         for s in self.slots.values()])
        if op == "ping":
            return dict(ok=True)
        s = self._slot(msg)
        with s.lock:
            if op == "state":
                st = s.drone.state()
                return dict(ok=True, id=s.id, landing=s.landing_until is not None,
                            pilot=s.pilot == session, scanner=s.drone_stats,
                            **{k: (None if isinstance(v, float) and math.isnan(v) else v)
                               for k, v in st.items()})
            if op == "takeoff":
                h, d = float(msg["h"]), float(msg.get("d", 2.0))
                st = s.drone.state()
                self._check_point(0.0, 0.0, h)
                if st["vbat"] is None or (not s.drone.flying and st["vbat"] < self.takeoff_vbat):
                    raise RuntimeError(f"battery {st['vbat']} V too low for takeoff "
                                       f"(need {self.takeoff_vbat} V)")
                if math.isnan(st["x"]):
                    raise RuntimeError("no fresh pose; not taking off")
                self._fly(s, session)
                s.drone.takeoff(h, max(1.0, d))
                self.log(f"drone {s.id}: takeoff to {h:.2f} m")
                return dict(ok=True)
            if op == "go_to":
                x, y, z = float(msg["x"]), float(msg["y"]), float(msg["z"])
                self._check_point(x, y, z)
                if not s.drone.flying:
                    raise RuntimeError("take off first")
                self._fly(s, session)
                s.drone.go_to(x, y, z, float(msg.get("yaw", 0.0)), max(0.2, float(msg.get("d", 2.0))))
                return dict(ok=True)
            if op == "land":
                if s.drone.flying and s.landing_until is None:
                    self._fly(s, session)
                    self._land(s, "requested")
                return dict(ok=True)                 # already landing or on the ground: fine
            if op == "focus":
                a, b = scanner_codec.focus_params(msg.get("address"))
                s.drone.set_param("t15scan.focusA", a)
                s.drone.set_param("t15scan.focusB", b)
                return dict(ok=True)
            if op == "scanner_param":
                if msg.get("name") not in SCANNER_PARAMS:
                    raise ValueError(f"scanner_param name must be one of {SCANNER_PARAMS}")
                s.drone.set_param(f"t15scan.{msg['name']}", int(msg["value"]))
                return dict(ok=True)
        raise ValueError(f"unknown op {op!r}")

    def _touch(self, session):
        now = time.monotonic()
        for s in self.slots.values():
            if s.pilot == session:
                s.pilot_seen = now


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", action="append", required=True,
                    help="Crazyflie radio URI; repeat for more drones (ids 1, 2, ...)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--scanner-dir", default="/tmp", help="where t15-scanner-<id> ports go; '' = none")
    ap.add_argument("--fence", type=float, default=1.5, help="max |x| and |y| from takeoff (m)")
    ap.add_argument("--z-max", type=float, default=1.5)
    ap.add_argument("--vbat-min", type=float, default=3.0, help="land below this in flight (V)")
    ap.add_argument("--takeoff-vbat", type=float, default=3.5, help="refuse takeoff below this (V)")
    ap.add_argument("--min-rssi", type=int, help="drone app: drop adverts weaker than this (dBm)")
    ap.add_argument("--adv-hz", type=int, help="drone app: adverts per second per address")
    args = ap.parse_args(argv)
    params = {k: v for k, v in (("minRssi", args.min_rssi), ("advHz", args.adv_hz)) if v is not None}
    bridge = Bridge(args.uri, port=args.port, scanner_dir=args.scanner_dir or None,
                    fence_xy=args.fence, z_max=args.z_max, vbat_min=args.vbat_min,
                    takeoff_vbat=args.takeoff_vbat, scanner_params=params)
    try:
        bridge.start()
        while True:
            time.sleep(5)
            for s in bridge.slots.values():
                st = s.drone.state()
                v = "--" if st["vbat"] is None else f"{st['vbat']:.2f} V"
                pos = "no pose" if st["x"] is None or math.isnan(st["x"]) else \
                    f"({st['x']:+.2f}, {st['y']:+.2f}, {st['z']:.2f}) m"
                scan = s.drone_stats or {}
                bridge.log(f"  drone {s.id}: {pos}, {v}, {'flying' if st['flying'] else 'landed'}, "
                           f"scanner lines {scan.get('lines', 0)} dropped {scan.get('dropped', 0)}")
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()


if __name__ == "__main__":
    main()

"""CrazyflieLink: the flight backend crazyflie/demo_mission.py and keyboard_control.py load.

It keeps the contract those scripts expect:
    with CrazyflieLink(uri) as link:      # connects; leaving ALWAYS lands and disconnects
        link.vbat                         # volts, or None if not fresh
        link.pose()                       # (x, y, z, yaw) m / rad in the drone's boot frame; NaN if stale
        link.takeoff(height, duration)    # non-blocking, like the simulated FakeLink
        link.go_to(x, y, z, yaw, duration)
        link.wait(seconds)

If the bridge (python3 -m sar_sim.cf_bridge ...) is running, CrazyflieLink flies
through it. That is the only way to get the drone's scanner lines into the
discovery server at the same time. With no bridge, it opens the radio itself.
Set T15_CF_BRIDGE=host:port to use a bridge somewhere other than 127.0.0.1:8770.
"""
from __future__ import annotations

import json
import math
import os
import socket
import threading
import time

NAN4 = (math.nan,) * 4
LAND_S = 2.5


class CrazyflieLink:
    def __init__(self, uri="radio://0/80/2M/E7E7E7E7E7", bridge=None, land_s=LAND_S):
        self.uri, self.land_s = uri, land_s
        self.bridge = bridge or os.environ.get("T15_CF_BRIDGE", "127.0.0.1:8770")
        self.sock = self.rfile = self.drone = None
        self.id = None
        self.lock = threading.Lock()
        self.state, self.t_state = {}, -1e9
        self.flying = False
        self.last_keep = 0.0

    # ---- context ------------------------------------------------------------
    def __enter__(self):
        host, _, port = self.bridge.rpartition(":")
        try:
            self.sock = socket.create_connection((host or "127.0.0.1", int(port)), timeout=1.0)
        except OSError:
            self.sock = None
        if self.sock is not None:
            self.sock.settimeout(3.0)
            self.rfile = self.sock.makefile("rb")
            drones = self._call("hello")["drones"]
            match = [d for d in drones if d["uri"] == self.uri]
            if not match:
                self.close()
                raise RuntimeError(f"bridge has no drone {self.uri}; it has "
                                   f"{[d['uri'] for d in drones]}")
            self.id = match[0]["id"]
            print(f"CrazyflieLink: flying {self.uri} through the bridge at {self.bridge}", flush=True)
        else:
            from sar_sim.cf_core import CfDrone
            print(f"CrazyflieLink: no bridge at {self.bridge}; opening the radio directly "
                  "(no scanner lines in this mode)", flush=True)
            self.drone = CfDrone(self.uri).connect()
        self._refresh(force=True)
        return self

    def __exit__(self, *_exc):
        try:
            if self.flying:
                if self.drone is not None:
                    self.drone.land(self.land_s)
                else:
                    self._call("land", d=self.land_s)
                self.wait(self.land_s + 0.6)
                if self.drone is not None:
                    self.drone.stop()            # the bridge stops the motors itself
                self.flying = False
        finally:
            self.close()
        return False

    def close(self):
        if self.drone is not None:
            self.drone.close()
            self.drone = None
        if self.sock is not None:
            for thing in (self.rfile, self.sock):
                try:
                    thing.close()
                except (OSError, AttributeError):
                    pass
            self.sock = self.rfile = None

    # ---- the demo contract ----------------------------------------------------
    @property
    def vbat(self):
        try:
            self._refresh()
        except (OSError, RuntimeError, ValueError):
            return None
        return self.state.get("vbat")

    def pose(self):
        try:
            self._refresh(max_age=0.1)
        except (OSError, RuntimeError, ValueError):
            return NAN4
        st = self.state
        return tuple(math.nan if st.get(k) is None else float(st[k]) for k in ("x", "y", "z", "yaw"))

    def takeoff(self, height, duration):
        if self.drone is not None:
            self.drone.takeoff(height, duration)
        else:
            self._call("takeoff", h=height, d=duration)
        self.flying = True

    def go_to(self, x, y, z, yaw, duration):
        if self.drone is not None:
            self.drone.go_to(x, y, z, yaw, duration)
        else:
            self._call("go_to", x=x, y=y, z=z, yaw=yaw, d=duration)

    def wait(self, seconds):
        end = time.monotonic() + max(0.0, seconds)
        while True:
            left = end - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(0.1, left))
            try:
                self._refresh(max_age=0.25)      # also tells the bridge we are still here
            except (OSError, RuntimeError, ValueError):
                pass

    # ---- plumbing -------------------------------------------------------------
    def _refresh(self, force=False, max_age=0.2):
        now = time.monotonic()
        if not force and now - self.t_state < max_age:
            return
        if self.drone is not None:
            self.state = self.drone.state()
            if now - self.last_keep >= 0.5:      # arm the drone app's quiet-host landing
                self.last_keep = now
                from sar_sim.scanner_codec import KEEPALIVE
                self.drone.send_app(KEEPALIVE)
        else:
            self.state = self._call("state")
        self.t_state = now

    def _call(self, op, **kw):
        if self.sock is None:
            raise RuntimeError("not connected to the bridge")
        msg = dict(op=op, **kw)
        if self.id is not None:
            msg.setdefault("id", self.id)
        with self.lock:
            self.sock.sendall((json.dumps(msg) + "\n").encode())
            line = self.rfile.readline()
        if not line:
            raise RuntimeError("bridge closed the connection")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise RuntimeError(f"bridge refused {op}: {reply.get('error')}")
        return reply

"""fleet/web.py — the live command-centre dashboard.

A tiny web server (Python standard library only, so it runs on the Jetson
without installs). The browser page draws a real satellite map. The homebase
pushes its state to it a few times a second over Server-Sent Events.

    homebase.py --sim --web            -> open http://localhost:8080
    homebase.py --port /dev/ttyACM0 --web

Endpoints:  /         the dashboard page (fleet/web/index.html)
            /stream   live state, one JSON message per update
            /control  POST {"cmd": "pause" | "play" | "speed" | "jam" | "restart", ...}
"""
from __future__ import annotations

import json
import math
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "web", "index.html")


class Dashboard:
    def __init__(self, port=8080, host="0.0.0.0"):
        self.port, self.host = port, host
        self._cond = threading.Condition()
        self._snap = b"{}"
        self._version = 0
        self.commands = []                       # pending commands from the browser
        self._cmd_lock = threading.Lock()
        self.server = None

    # ------------------------------------------------------------ app side
    def publish(self, snap: dict):
        data = json.dumps(snap, separators=(",", ":")).encode()
        with self._cond:
            self._snap = data
            self._version += 1
            self._cond.notify_all()

    def take_commands(self):
        with self._cmd_lock:
            cmds, self.commands = self.commands, []
        return cmds

    # ---------------------------------------------------------- web side
    def _wait(self, last, timeout=1.0):
        with self._cond:
            if self._version == last:
                self._cond.wait(timeout)
            return self._snap, self._version

    def start(self):
        dash = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):           # keep the terminal clean
                pass

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    with open(PAGE, "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    last = -1
                    try:
                        while True:
                            snap, ver = dash._wait(last)
                            if ver != last:
                                self.wfile.write(b"data: " + snap + b"\n\n")
                                last = ver
                            else:
                                self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                elif self.path.startswith("/leaflet/"):
                    rel = os.path.normpath(self.path.split("?")[0].lstrip("/"))
                    full = os.path.join(HERE, "web", rel)
                    if not full.startswith(os.path.join(HERE, "web") + os.sep) or not os.path.isfile(full):
                        self.send_error(404)
                        return
                    ctype = {".js": "application/javascript", ".css": "text/css",
                             ".png": "image/png"}.get(os.path.splitext(full)[1], "application/octet-stream")
                    with open(full, "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/control":
                    self.send_error(404)
                    return
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    cmd = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    cmd = {}
                with dash._cmd_lock:
                    dash.commands.append(cmd)
                self.send_response(204)
                self.end_headers()

        class QuietServer(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass                              # a closed/reloaded tab is not an error

        self.server = QuietServer((self.host, self.port), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()


def _u8(a):
    return [int(v) for v in np.clip(np.nan_to_num(a) * 255.0, 0, 255).round().astype(int).ravel()]


def snapshot(hub, t, mission_id, origin, mode="live", paused=False, speed=1.0,
             people=None, sim_drones=None, gw=None, done_at=None, events_tail=50):
    """Everything the page needs, as plain JSON. Positions are local metres;
    the page converts them to latitude/longitude around `origin`."""
    w, g = hub.world, hub.grid
    prior = np.maximum(w.belief, 1e-15)
    ratio = np.where(w.obstacles, 1.0, hub.mass / prior)             # 1 = never searched
    m = np.where(w.obstacles, 0.0, hub.mass)
    prob = m / m.max() if m.max() > 0 else m
    drones = []
    for d in hub.drones.values():
        if d.target is not None:
            tx, ty = d.target_xy if d.target_xy is not None else g.to_xy(d.target)
        else:
            tx = ty = None
        drones.append(dict(
            id=d.id, name=hub.names.get(d.id, f"D{d.id}"), role=hub.roles.get(d.id, "search"),
            x=round(d.x, 2), y=round(d.y, 2), z=round(d.z, 1), sigma=round(d.sigma, 2),
            task="LOST" if d.lost else d.task, state=d.state,
            battery=None if d.battery == 255 else d.battery,
            time_left=None if d.state == 0 else round(hub.time_left(d, t), 0),
            sensors=d.sensors, rssi=d.rssi, tx=tx, ty=ty, cmd=d.cmd,
            confirm=d.confirm_track, seen=round(t - d.last_seen, 1) if d.last_seen > -1e8 else None,
            trail=[[x, y] for _, x, y in hub.trails.get(d.id, [])[-150:]]))
    snap = dict(
        mission=mission_id, mode=mode, t=round(t, 1), paused=paused, speed=speed,
        military=hub.cfg.military, signed=bool(hub.key), done_at=done_at, recalled=hub.recalled,
        grid=dict(n=w.n, cell=w.cell_m, home=list(g.home), origin=list(origin),
                  walls=[] if getattr(w, "scenario", None) is not None else
                  [[int(i), int(j)] for i, j in zip(*np.nonzero(w.obstacles))]),
        searched=_u8(1.0 - ratio), prob=_u8(prob),
        pos=round(100 * hub.pos(), 1),
        drones=drones,
        tracks=[tr.as_dict() for tr in hub.casualties()],
        signals=[a.as_dict() for a in hub.signals],
        names={str(k): v for k, v in hub.names.items()},
        events=[e for e in hub.events if not e.get("q")][-events_tail:],
        stats=dict(rx=hub.stats["rx"], tx=hub.stats["tx"], bad=hub.stats["rx_bad"],
                   replay=hub.stats["rx_replay"], rtb=hub.stats["rtb"]),
    )
    sc = getattr(w, "scenario", None)
    if sc is not None:
        assessed_at = {}
        for e in hub.events:
            if e["ev"] == "vitals" and e.get("track") not in assessed_at:
                assessed_at[e["track"]] = e["t"]
        reports = []
        for tr in hub.casualties():
            if tr.confirmed and tr.assessed:
                facts = sc.describe(tr.x, tr.y, w.cell_m, g.home)
                reports.append(dict(track=tr.id, t=assessed_at.get(tr.id, t), x=round(tr.x, 1), y=round(tr.y, 1),
                                    status=tr.status, hr=tr.hr, br=tr.br, ally=tr.ally,
                                    tag=hex(tr.tag_id) if tr.tag_id else None,
                                    seen_by=sorted(tr.drones), **facts))
        snap["scenario"] = dict(
            name=sc.name, brief=sc.brief, source=sc.source, minutes_ago=sc.minutes_ago,
            lkp=[round(sc.lkp[0], 1), round(sc.lkp[1], 1)],
            threats=[[round(x, 1), round(y, 1), round(r, 1)] for x, y, r in sc.threats],
            regions=sc.regions(hub.mass), reports=reports,
            canopy=round(100 * float((sc.vis < 0.5).mean())))
    if gw is not None:
        sent = max(1, gw.stats["up_sent"])
        snap["radio"] = dict(loss=round(100 * gw.stats["up_lost"] / sent, 1),
                             jam=bool(gw.jam and gw.jam[0] <= t < gw.jam[1]),
                             jam_until=round(gw.jam[1], 1) if gw.jam else None)
    if people is not None:
        snap["truth"] = [dict(x=round(p.x, 1), y=round(p.y, 1), status=p.status, hr=p.hr, br=p.br,
                              seen=p.first_detected is not None) for p in people]
    if sim_drones is not None:
        snap["truth_drones"] = [dict(id=d.id, x=round(float(d.true[0]), 2), y=round(float(d.true[1]), 2),
                                     dead=d.dead) for d in sim_drones]
    return snap


def parse_origin(text):
    lat, lon = (float(v) for v in text.split(","))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or math.isnan(lat + lon):
        raise ValueError("origin must be lat,lon")
    return lat, lon

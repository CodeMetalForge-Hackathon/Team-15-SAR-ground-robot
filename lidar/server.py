"""SIMULATED replay server (stdlib http.server), so the dashboard works without a LiDAR.

    python -m lidar replay --scenario 08_obstacle_approaching --serve --port 8775

    GET /                 polar/top-down view (static/lidar_panel.html)
    GET /api/lidar        team15.lidar_panel/1        (?frame=N to pin a frame)
    GET /api/range        team15.range_snapshot/1     FRONT-sector compatibility snapshot (display only)
    GET /api/advisory     team15.lidar_advisory_context/1 (optional Qwen context field)
    GET /api/scenarios    scenario names

Binds 127.0.0.1 by default. Port 8775 avoids 8765 (ranging), 8770 (robot API), 8792 (camera test)
and the dashboard's own port. Serves only SIMULATED replays: it has no hardware code path.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import adapters
from .config import DEFAULT_SIM_PORT
from .panel import ReplaySource

STATIC = Path(__file__).with_name("static") / "lidar_panel.html"


class ReplayApp:
    def __init__(self, scenario: str, seed: int = 15):
        self.lock = threading.Lock()
        self.scenario, self.seed = scenario, seed
        self.src = ReplaySource(scenario, seed)

    def select(self, scenario: str) -> None:
        with self.lock:
            if scenario != self.scenario:
                self.src = ReplaySource(scenario, self.seed)
                self.scenario = scenario

    def panel(self, frame=None) -> dict:
        with self.lock:
            return self.src.view(frame)

    def range_snapshot(self) -> dict:
        with self.lock:
            self.src.view()
            return adapters.to_range_snapshot(self.src.last_assessment)

    def advisory(self) -> dict:
        with self.lock:
            self.src.view()
            return adapters.to_advisory_context(self.src.last_assessment)


def make_server(app: ReplayApp, host: str = "127.0.0.1", port: int = DEFAULT_SIM_PORT) -> ThreadingHTTPServer:
    from .simulation import BYTE_LEVEL_SCENARIOS, SCENARIOS

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if "scenario" in q:
                name = q["scenario"][0]
                if name not in SCENARIOS and name not in BYTE_LEVEL_SCENARIOS:
                    return self._send(404, {"error": f"unknown scenario {name!r}"})
                app.select(name)
            frame = int(q["frame"][0]) if "frame" in q and q["frame"][0].isdigit() else None
            if u.path == "/":
                return self._send(200, STATIC.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/lidar":
                return self._send(200, app.panel(frame))
            if u.path == "/api/range":
                return self._send(200, app.range_snapshot())
            if u.path == "/api/advisory":
                return self._send(200, app.advisory())
            if u.path == "/api/scenarios":
                return self._send(200, {"scenarios": sorted(SCENARIOS) + sorted(BYTE_LEVEL_SCENARIOS),
                                        "current": app.scenario, "label": "SIMULATED"})
            return self._send(404, {"error": "not found"})

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), H)

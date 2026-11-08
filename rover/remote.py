"""Mac-side client for the Pi rover host (rover/pi_host.py). Signs every request; holds no motor objects.

The Mac can only ASK: every command is re-evaluated on the Pi by the camera veto and the safety supervisor.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from rover import link


class PiClient:
    def __init__(self, base_url: str, key: bytes, timeout_s: float = 0.6):
        self.base = base_url.rstrip("/")
        self.signer = link.Signer(key)
        self.timeout_s = timeout_s

    def _req(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        raw = b"" if body is None else json.dumps(body, separators=(",", ":"), default=str).encode()
        hdr = self.signer.headers(method, path, raw)
        if body is not None:
            hdr["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=raw if body is not None else None, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}", "detail": e.read()[:200].decode(errors="replace")}
        except Exception as e:  # noqa: BLE001 - an unreachable Pi is reported, and the Pi stops on its own
            return {"error": type(e).__name__, "detail": str(e)[:200]}

    def status(self) -> dict:
        return self._req("GET", "/v1/status")

    def heartbeat(self) -> dict:
        return self._req("POST", "/v1/heartbeat", {})

    def perception(self, state: Optional[dict]) -> dict:
        return self._req("POST", "/v1/perception", {"state": state})

    def command(self, cmd: str, origin: str = "operator", operator: Optional[str] = None, speed: float = 0.0,
                duration_s: float = 0.0, rear_clear: bool = False, proposal: Optional[dict] = None) -> dict:
        return self._req("POST", "/v1/command", {"cmd": cmd, "origin": origin, "operator": operator, "speed": speed,
                                                 "duration_s": duration_s, "rear_clear": rear_clear,
                                                 "proposal": proposal})

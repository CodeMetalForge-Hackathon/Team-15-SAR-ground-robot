"""Latest status posted by the Mac rover host (rover/mac_host.py). Display only: memory, no motor path.

The host posts team15.mac_host_status/1. Validation keeps simulation from ever reading as physical motion:
``physical`` must be a bool, and a non-physical status must be labelled SIMULATED. The dashboard has no
route back to the host: it cannot command, arm or approve anything.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

SCHEMA = "team15.mac_host_status/1"


class InvalidRoverState(ValueError):
    pass


class RoverStateStore:
    def __init__(self, clock: Callable[[], float] = time.time, stale_after_s: float = 2.0):
        self.clock, self.stale_after_s = clock, stale_after_s
        self.lock = threading.Lock()
        self.state: Optional[dict] = None
        self.received_at: Optional[float] = None

    def post(self, st: dict) -> dict:
        if not isinstance(st, dict) or st.get("schema") != SCHEMA:
            raise InvalidRoverState("unknown schema")
        if not isinstance(st.get("physical"), bool):
            raise InvalidRoverState("physical must be true or false")
        if not st["physical"] and not str(st.get("label", "")).startswith("SIMULATED"):
            raise InvalidRoverState("a non-physical driver must be labelled SIMULATED")
        if st.get("autonomy") != "DISABLED":
            raise InvalidRoverState("autonomy must be DISABLED in this build")
        with self.lock:
            self.state, self.received_at = dict(st), self.clock()
        return {"ok": True}

    def view(self) -> dict:
        with self.lock:
            if self.state is None:
                return {"status": "NOT_RUNNING", "label": "no rover host connected",
                        "text": "no rover host is running: no motor command can be sent"}
            age = round(self.clock() - self.received_at, 2)
            v = dict(self.state, age_s=age)
            v["status"] = "LIVE" if age <= self.stale_after_s else "STALE"
            if v["status"] == "STALE":
                v["text"] = (f"rover host silent for {age:.1f} s: last state shown; the StickC watchdog "
                             "zeroes the motors 250 ms after frames stop")
            return v

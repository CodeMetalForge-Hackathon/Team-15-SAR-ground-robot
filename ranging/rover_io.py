"""Adapter for the Rover navigation worker (feature/rover-navigation, rover/sensors.py).

Navigation expects ``RangeReading(t, status, range_m, max_range_m, source, seq)``:
status is OK | NO_ECHO | ERROR, and t is on the controller clock. This module
produces exactly those fields from a range snapshot. It does not import ``rover``
(a separate branch).

    from ranging.rover_io import GroveRangeIO
    from rover.sensors import RangeReading
    io = GroveRangeIO()
    f = io.read_fields()                  # dict, never raises
    reading = RangeReading(**{k: f[k] for k in ("t", "status", "range_m", "max_range_m", "source", "seq")})
    if not f["forward_motion_allowed"]:   # REQUIRED: our BLOCKED/UNKNOWN verdict
        stop_forward()

Clock: ``t`` is ``time.monotonic()`` seconds on the Pi, taken from the reading's own
monotonic timestamp. Navigation's ``clock()`` must also be ``time.monotonic``, on the
same Pi. A snapshot from another host cannot be placed on that clock, so it gives ERROR.

Status mapping (every non-OK value is UNKNOWN in rover.sensors.assess, so the robot stops):
    VALID, our status CLEAR/CAUTION/BLOCKED   -> OK, range_m = our decision range
    VALID, but our status UNKNOWN             -> ERROR  (e.g. filter window not yet full)
    NO_ECHO, OUT_OF_RANGE                     -> NO_ECHO
    anything else, stale, unreachable         -> ERROR
"""
from __future__ import annotations

import socket
import time
from typing import Optional

from .config import SensorConfig
from .service import RangeClient

ROVER_SOURCE = "grove-ultrasonic"
_NO_ECHO = {"NO_ECHO", "OUT_OF_RANGE"}


def snapshot_to_rover_fields(snap: dict, now_mono_s: float, max_range_m: float,
                             this_host: Optional[str] = None) -> dict:
    """Map a freshness-checked snapshot to rover RangeReading fields plus our verdict."""
    latest = snap.get("latest") or {}
    same_host = (snap.get("provenance") or {}).get("host") == (this_host or socket.gethostname())
    t = latest["mono_ns"] / 1e9 if (same_host and latest.get("mono_ns") is not None) else now_mono_s
    obst = snap.get("obstacle_status", "UNKNOWN")
    stale = (snap.get("freshness") or {}).get("stale", True)
    ms = latest.get("measurement_status")
    reason = snap.get("error") or (snap.get("assessment") or {}).get("reason")
    if not same_host:
        status, rng, reason = "ERROR", None, "snapshot not from this host: cannot use controller clock"
    elif stale or not latest:
        status, rng = "ERROR", None
    elif ms == "VALID" and obst in ("CLEAR", "CAUTION", "BLOCKED") and snap.get("range_m") is not None:
        status, rng = "OK", float(snap["range_m"])
    elif ms in _NO_ECHO:
        status, rng = "NO_ECHO", None
    else:
        status, rng = "ERROR", None
    allowed = bool(snap.get("forward_motion_allowed")) and status == "OK" and same_host and not stale
    return {"t": t, "status": status, "range_m": rng, "max_range_m": max_range_m, "source": ROVER_SOURCE,
            "seq": int(latest.get("seq") or 0),
            # Extra fields (not in rover RangeReading). Navigation must AND with forward_motion_allowed.
            "forward_motion_allowed": allowed, "obstacle_status": obst if not stale else "UNKNOWN",
            "measurement_status": ms, "reason": reason,
            "blocked_threshold_m": ((snap.get("assessment") or {}).get("thresholds") or {}).get("blocked_m"),
            "diagnosis": ((snap.get("health") or {}).get("diagnosis") or {}).get("code"),
            "source_mode": (snap.get("provenance") or {}).get("source_mode")}


class GroveRangeIO:
    """read_range()/clock() source for the navigator, backed by RangeClient (no GPIO here)."""

    def __init__(self, client: Optional[RangeClient] = None, max_range_m: Optional[float] = None):
        self.client = client or RangeClient()
        self.max_range_m = max_range_m if max_range_m is not None else SensorConfig().max_range_m

    @staticmethod
    def clock() -> float:
        return time.monotonic()

    def read_fields(self) -> dict:
        return snapshot_to_rover_fields(self.client.get(), self.clock(), self.max_range_m)

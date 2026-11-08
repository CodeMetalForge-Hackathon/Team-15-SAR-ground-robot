"""Navigator IO for the real Pi 5. It reports only what is actually verified, and that is very little.

    io = PiRobotIO()        # consumes PR #7 ranging.rover_io.GroveRangeIO on the same Pi

- clock: ``time.monotonic`` on this Pi. The clock domain string is ``time.monotonic@<hostname>``,
  and range fields from any other domain are rejected (``rover.sensors.from_rover_fields``).
- range: PR #7's versioned ``team15.rover_range_fields/1`` (``GroveRangeIO.read_fields()``), validated
  for schema, clock domain and contradictions. ``forward_motion_allowed`` is ANDed into every
  assessment, and NO_ECHO is always UNKNOWN.
  If the ranging package won't import, or the service is missing, crashed or stale, the result is
  an ERROR reading with t = -inf. That is never fresh, so motion is refused or stopped.
- heading: None. There is no verified, calibrated heading source, so rotation scanning is refused.
- power: None. There is no verified battery telemetry, so the supervisor refuses all physical motion.
- camera: []. The perception stream is not wired into the navigator yet.
- pose: UNKNOWN. With no localization, the navigator can only offer operator-assisted waypoints.
- traveled: UNKNOWN. There is no odometry.
This module issues no motor commands. It has no driver.
"""
from __future__ import annotations

import socket
import time
from typing import Callable, Optional

from rover.navigator import UNKNOWN, Pose
from rover.sensors import CameraDetection, HeadingReading, PowerReading, RangeReading, from_rover_fields


def clock_domain(host: Optional[str] = None) -> str:
    return "time.monotonic@" + (host or socket.gethostname())


def _default_grove_reader() -> Callable[[], dict]:
    try:
        from ranging.rover_io import ROVER_FIELDS_SCHEMA, GroveRangeIO  # PR #7
    except Exception as e:  # missing or broken dependency: fail safe, do not crash the control loop
        err = f"ranging.rover_io unavailable: {type(e).__name__}: {e}"
        return lambda: {"error": err}
    if ROVER_FIELDS_SCHEMA != "team15.rover_range_fields/1":
        return lambda: {"error": f"unsupported ranging interface {ROVER_FIELDS_SCHEMA}"}
    return GroveRangeIO().read_fields


class PiRobotIO:
    physical = True

    def __init__(self, range_fields: Optional[Callable[[], dict]] = None,
                 clock: Callable[[], float] = time.monotonic, host: Optional[str] = None):
        self._range_fields = range_fields if range_fields is not None else _default_grove_reader()
        self._clock = clock
        self.clock_domain = clock_domain(host)
        self.last_fields: Optional[dict] = None

    def clock(self) -> float:
        return self._clock()

    def read_range(self) -> Optional[RangeReading]:
        try:
            f = self._range_fields()
        except Exception as e:  # a reader failure must look like no data, never like clear space
            f = {"error": f"{type(e).__name__}: {e}"}
        self.last_fields = f
        return from_rover_fields(f, self.clock_domain)

    def read_heading(self) -> Optional[HeadingReading]:
        return None

    def read_power(self) -> Optional[PowerReading]:
        return None

    def read_camera(self) -> list[CameraDetection]:
        return []

    def pose(self) -> Pose:
        return Pose(UNKNOWN, self._clock())

    def bearing(self, a: str, b: str) -> Optional[float]:
        return None

    def traveled(self) -> dict:
        return {"value_m": None, "kind": "UNKNOWN"}

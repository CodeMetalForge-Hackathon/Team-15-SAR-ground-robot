"""Navigator IO for the real Pi 5. It reports only what is actually verified, and that is very little.

    from ranging.rover_io import GroveRangeIO          # PR #7, runs on the same Pi
    io = PiRobotIO(GroveRangeIO().read_fields)

- clock: ``time.monotonic`` on the Pi. This is the same clock as PR #7's ``t`` (taken from ``mono_ns``).
- range: PR #7's rover_io fields go through ``rover.sensors.from_rover_fields``. NO_ECHO is always
  UNKNOWN, and ``forward_motion_allowed`` is ANDed into every assessment.
- heading: None. There is no verified, calibrated heading source, so rotation scanning is refused.
- power: None. There is no verified battery telemetry, so the supervisor refuses all physical motion.
- camera: []. The perception stream is not wired into the navigator yet.
- pose: UNKNOWN. With no localization, the navigator can only offer operator-assisted waypoints.
- traveled: UNKNOWN. There is no odometry.
This module issues no motor commands. It has no driver.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from rover.navigator import UNKNOWN, Pose
from rover.sensors import CameraDetection, HeadingReading, PowerReading, RangeReading, from_rover_fields


class PiRobotIO:
    physical = True

    def __init__(self, range_fields: Callable[[], dict], clock: Callable[[], float] = time.monotonic):
        self._range_fields = range_fields
        self._clock = clock
        self.last_fields: Optional[dict] = None

    def clock(self) -> float:
        return self._clock()

    def read_range(self) -> Optional[RangeReading]:
        try:
            f = self._range_fields()
        except Exception as e:  # a reader failure must look like no data, never like clear space
            f = {"error": str(e)}
        self.last_fields = f
        return from_rover_fields(f)

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

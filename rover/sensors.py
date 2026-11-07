"""Sensor reading types and the conservative obstacle assessment.

The Grove ultrasonic worker produces ``RangeReading``. See contracts/ROVER_NAV_CONTRACT.md section 2.
Every reading carries its own capture time. A reading's age is (now - t). Nothing is ever back-dated.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Optional

OK = "OK"
NO_ECHO = "NO_ECHO"   # nothing returned within range. Ambiguous: soft or angled objects absorb sound.
ERROR = "ERROR"


class Assessment(str, enum.Enum):
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class NoEchoPolicy(str, enum.Enum):
    UNKNOWN = "UNKNOWN"            # default: no echo is not evidence of clear space
    CLEAR_TO_MAX = "CLEAR_TO_MAX"  # only after a bench calibration shows reliable echoes; the sim labels this


@dataclass(frozen=True)
class RangeReading:
    t: float                     # capture time, in seconds on the controller clock
    status: str                  # OK | NO_ECHO | ERROR
    range_m: Optional[float]     # set when status == OK
    max_range_m: float
    source: str                  # "grove-ultrasonic" | "sim-ultrasonic" | "fake"
    seq: int = 0

    def to_dict(self) -> dict:
        return {"t": self.t, "status": self.status, "range_m": self.range_m,
                "max_range_m": self.max_range_m, "source": self.source, "seq": self.seq}


@dataclass(frozen=True)
class HeadingReading:
    t: float
    heading_deg: float           # counter-clockwise, in the frame of the heading source
    source: str                  # "sim-truth" | "imu-calibrated" (no hardware source exists yet)


@dataclass(frozen=True)
class PowerReading:
    t: float
    voltage_v: Optional[float]
    source: str


@dataclass(frozen=True)
class CameraDetection:
    """A camera detection relative to the robot. It is never a global coordinate (no localization)."""
    t: float
    label: str
    score: float
    relative_bearing_deg: float
    source: str


def age(reading_t: Optional[float], now: float) -> float:
    return math.inf if reading_t is None else now - reading_t


def assess(reading: Optional[RangeReading], now: float, required_clear_m: float,
           max_age_s: float, no_echo_policy: NoEchoPolicy = NoEchoPolicy.UNKNOWN) -> tuple[Assessment, str]:
    """Is there ``required_clear_m`` of free space along the beam? Anything doubtful is UNKNOWN.

    A reading from the future (now < t by more than 50 ms) is a clock fault, so it is UNKNOWN too.
    """
    if reading is None:
        return Assessment.UNKNOWN, "no range reading"
    a = now - reading.t
    if a < -0.05:
        return Assessment.UNKNOWN, f"range reading timestamp {-a:.3f}s in the future (clock fault)"
    if a > max_age_s:
        return Assessment.UNKNOWN, f"range reading stale ({a:.3f}s > {max_age_s:.3f}s)"
    if required_clear_m < 0:
        return Assessment.UNKNOWN, "negative required clearance"
    if reading.status == OK and reading.range_m is not None and reading.range_m >= 0:
        if reading.range_m < required_clear_m:
            return Assessment.BLOCKED, f"obstacle at {reading.range_m:.2f} m < {required_clear_m:.2f} m"
        return Assessment.CLEAR, f"clear {reading.range_m:.2f} m >= {required_clear_m:.2f} m"
    if reading.status == NO_ECHO:
        if no_echo_policy == NoEchoPolicy.CLEAR_TO_MAX and required_clear_m <= reading.max_range_m:
            return Assessment.CLEAR, f"no echo within {reading.max_range_m:.2f} m (policy CLEAR_TO_MAX)"
        return Assessment.UNKNOWN, "no echo (not treated as clear)"
    return Assessment.UNKNOWN, f"range sensor status {reading.status}"


def combine(assessments: list[Assessment]) -> Assessment:
    """Worst case wins: UNKNOWN beats BLOCKED, and BLOCKED beats CLEAR. An empty list is UNKNOWN."""
    if not assessments or Assessment.UNKNOWN in assessments:
        return Assessment.UNKNOWN
    if Assessment.BLOCKED in assessments:
        return Assessment.BLOCKED
    return Assessment.CLEAR


def ang_diff(a_deg: float, b_deg: float) -> float:
    """Signed smallest difference a - b, in (-180, 180]."""
    d = (a_deg - b_deg + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def norm_deg(a: float) -> float:
    return a % 360.0

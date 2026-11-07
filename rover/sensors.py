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
    t: float                     # capture time on the controller's MONOTONIC clock (hardware: time.monotonic on the Pi)
    status: str                  # OK | NO_ECHO | ERROR
    range_m: Optional[float]     # set when status == OK
    max_range_m: float
    source: str                  # "grove-ultrasonic" | "sim-ultrasonic" | "fake"
    seq: int = 0
    # From the ranging service (PR #7 ranging/rover_io.py). None means the source gives no verdict (sim).
    forward_allowed: Optional[bool] = None     # the service's forward_motion_allowed, ANDed into every check
    blocked_threshold_m: Optional[float] = None  # required clearance is never below this
    hardware: bool = False       # real sensor: NO_ECHO is always UNKNOWN, whatever the policy

    def to_dict(self) -> dict:
        return {"t": self.t, "status": self.status, "range_m": self.range_m,
                "max_range_m": self.max_range_m, "source": self.source, "seq": self.seq,
                "forward_allowed": self.forward_allowed, "blocked_threshold_m": self.blocked_threshold_m,
                "hardware": self.hardware}


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


GROVE_FIELDS = ("t", "status", "range_m", "max_range_m", "source", "seq", "forward_motion_allowed")
GROVE_SOURCE = "grove-ultrasonic"  # PR #7 ranging/rover_io.py ROVER_SOURCE


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def from_rover_fields(f: dict) -> RangeReading:
    """Adopt PR #7 ``ranging.rover_io.snapshot_to_rover_fields()`` output as a RangeReading.

    The dict's ``t`` is ``time.monotonic()`` on the Pi (taken from the reading's own ``mono_ns``), so
    the navigator's clock must be ``time.monotonic`` on that same Pi. Anything malformed becomes an
    ERROR reading that is stamped -inf, so it is always stale. It never raises and never guesses
    "clear".
    """
    try:
        missing = [k for k in GROVE_FIELDS if k not in f]
        if missing:
            raise ValueError(f"missing {missing}")
        status = f["status"]
        if status not in (OK, NO_ECHO, ERROR):
            raise ValueError(f"status {status!r}")
        if not _finite(f["t"]) or not _finite(f["max_range_m"]):
            raise ValueError("non-finite t/max_range_m")
        rng = f["range_m"]
        if status == OK and not (_finite(rng) and rng >= 0):
            raise ValueError("OK without a usable range_m")
        if status != OK:
            rng = None
        thr = f.get("blocked_threshold_m")
        return RangeReading(
            t=float(f["t"]), status=status, range_m=None if rng is None else float(rng),
            max_range_m=float(f["max_range_m"]), source=str(f["source"]), seq=int(f["seq"] or 0),
            forward_allowed=f["forward_motion_allowed"] is True,
            blocked_threshold_m=float(thr) if _finite(thr) else None,
            hardware=f.get("source_mode") != "SIMULATED")
    except (ValueError, TypeError, KeyError) as e:
        return RangeReading(-math.inf, ERROR, None, 0.0, f"{GROVE_SOURCE}:malformed({e})", 0,
                            forward_allowed=False, hardware=True)


def age(reading_t: Optional[float], now: float) -> float:
    return math.inf if reading_t is None else now - reading_t


def assess(reading: Optional[RangeReading], now: float, required_clear_m: float,
           max_age_s: float, no_echo_policy: NoEchoPolicy = NoEchoPolicy.UNKNOWN) -> tuple[Assessment, str]:
    """Is there ``required_clear_m`` of free space along the beam? Anything doubtful is UNKNOWN.

    - ``now`` and ``reading.t`` must be on the same monotonic clock. A reading from the future
      (more than 50 ms ahead), or a non-finite time, is a clock fault and gives UNKNOWN.
    - A hardware NO_ECHO is always UNKNOWN. ``CLEAR_TO_MAX`` applies only to simulated sources.
    - The ranging service's ``forward_allowed=False`` can never be overruled to CLEAR.
    - The required clearance is never below the service's ``blocked_threshold_m``.
    """
    if reading is None:
        return Assessment.UNKNOWN, "no range reading"
    if not _finite(reading.t) or not _finite(now):
        return Assessment.UNKNOWN, "range reading has no valid timestamp"
    a = now - reading.t
    if a < -0.05:
        return Assessment.UNKNOWN, f"range reading timestamp {-a:.3f}s in the future (clock fault)"
    if a > max_age_s:
        return Assessment.UNKNOWN, f"range reading stale ({a:.3f}s > {max_age_s:.3f}s)"
    if not _finite(required_clear_m) or required_clear_m < 0:
        return Assessment.UNKNOWN, "invalid required clearance"
    if reading.blocked_threshold_m is not None:
        required_clear_m = max(required_clear_m, reading.blocked_threshold_m)
    if reading.status == OK and _finite(reading.range_m) and reading.range_m >= 0:
        if reading.range_m < required_clear_m:
            return Assessment.BLOCKED, f"obstacle at {reading.range_m:.2f} m < {required_clear_m:.2f} m"
        if reading.forward_allowed is False:
            return Assessment.UNKNOWN, "ranging service forward_motion_allowed=false"
        return Assessment.CLEAR, f"clear {reading.range_m:.2f} m >= {required_clear_m:.2f} m"
    if reading.status == NO_ECHO:
        if reading.hardware:
            return Assessment.UNKNOWN, "no echo from real sensor (always UNKNOWN)"
        if (no_echo_policy == NoEchoPolicy.CLEAR_TO_MAX and required_clear_m <= reading.max_range_m
                and reading.forward_allowed is not False):
            return Assessment.CLEAR, f"no echo within {reading.max_range_m:.2f} m (SIMULATED policy CLEAR_TO_MAX)"
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

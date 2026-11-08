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
    service_status: Optional[str] = None  # ranging service obstacle_status: CLEAR|CAUTION|BLOCKED|UNKNOWN
    reason: str = ""

    def __post_init__(self):
        # Issue #9: forward_allowed is a strict tri-state, and a real sensor must always state a verdict.
        if self.forward_allowed is not None and not isinstance(self.forward_allowed, bool):
            raise ValueError(f"forward_allowed must be True, False or None, not {self.forward_allowed!r}")
        if self.hardware and self.forward_allowed is None:
            raise ValueError("a hardware range reading must carry an explicit forward_allowed verdict")

    def to_dict(self) -> dict:
        return {"t": self.t, "status": self.status, "range_m": self.range_m,
                "max_range_m": self.max_range_m, "source": self.source, "seq": self.seq,
                "forward_allowed": self.forward_allowed, "blocked_threshold_m": self.blocked_threshold_m,
                "hardware": self.hardware, "service_status": self.service_status, "reason": self.reason}


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


ROVER_FIELDS_SCHEMA = "team15.rover_range_fields/1"  # PR #7 ranging/rover_io.py (versioned interface)
GROVE_FIELDS = ("schema", "clock", "t", "status", "range_m", "max_range_m", "source", "seq",
                "forward_motion_allowed", "obstacle_status", "measurement_status")
GROVE_SOURCE = "grove-ultrasonic"  # PR #7 ROVER_SOURCE
_SERVICE_STATUSES = ("CLEAR", "CAUTION", "BLOCKED", "UNKNOWN")
_NO_ECHO_MS = ("NO_ECHO", "OUT_OF_RANGE")


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _error(why: str, seq: int = 0) -> RangeReading:
    # t = -inf: an ERROR is not fresh sensor data, so it can never satisfy a freshness check
    return RangeReading(-math.inf, ERROR, None, 0.0, GROVE_SOURCE, seq, forward_allowed=False, hardware=True,
                        service_status="UNKNOWN", reason=why)


def from_rover_fields(f, expected_clock: str) -> RangeReading:
    """Validate PR #7 ``team15.rover_range_fields/1`` (``GroveRangeIO.read_fields()``) into a RangeReading.

    ``expected_clock`` is the navigator's own clock domain, ``"time.monotonic@<this host>"``. A reading
    from any other clock domain (another host, or wall clock) is rejected as ERROR.
    Every problem gives an ERROR reading, never an exception and never "clear":
      - a wrong schema, a missing key, a non-finite number or an unknown status;
      - a contradiction between the numbers and the verdict, such as forward_motion_allowed=true
        while status/obstacle_status is not OK/CLEAR|CAUTION, a range below the blocked threshold
        while motion is allowed, a range on a non-OK status, or a measurement_status that
        disagrees with status.
    BLOCKED at a large range is allowed. PR #7 reports its honest decision range, so the verdict
    decides and we treat it as BLOCKED.
    An ERROR reading gets t = -inf, so service loss and malformed input always read as stale.
    """
    try:
        if not isinstance(f, dict):
            return _error("fields are not a dict")
        missing = [k for k in GROVE_FIELDS if k not in f]
        if missing:
            return _error(f"missing fields {missing}")
        if f["schema"] != ROVER_FIELDS_SCHEMA:
            return _error(f"schema {f['schema']!r} != {ROVER_FIELDS_SCHEMA}")
        if f["clock"] != expected_clock:
            return _error(f"clock domain {f['clock']!r} != {expected_clock!r}")
        if f["source"] != GROVE_SOURCE:
            return _error(f"source {f['source']!r}")
        status, rng, ms, obst = f["status"], f["range_m"], f["measurement_status"], f["obstacle_status"]
        allowed = f["forward_motion_allowed"]
        seq = f["seq"]
        if not _finite(f["t"]):
            return _error("non-finite t")
        if not (_finite(f["max_range_m"]) and f["max_range_m"] > 0):
            return _error("bad max_range_m")
        if not (isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0):
            return _error(f"bad seq {seq!r}")
        if status not in (OK, NO_ECHO, ERROR):
            return _error(f"status {status!r}")
        if obst not in _SERVICE_STATUSES:
            return _error(f"obstacle_status {obst!r}")
        if not isinstance(allowed, bool):
            return _error("forward_motion_allowed is not a bool")
        thr = f.get("blocked_threshold_m")
        if thr is not None and not (_finite(thr) and thr >= 0):
            return _error("bad blocked_threshold_m")
        # numerical / status contradictions
        if status == OK:
            if not (_finite(rng) and 0 <= rng <= f["max_range_m"] * 1.05):
                return _error(f"OK with unusable range_m {rng!r}")
            if ms != "VALID":
                return _error(f"status OK but measurement_status {ms!r}")
            if obst == "UNKNOWN":
                return _error("status OK but obstacle_status UNKNOWN")
        else:
            if rng is not None:
                return _error(f"status {status} carries range_m {rng!r}")
            if status == NO_ECHO and ms not in _NO_ECHO_MS:
                return _error(f"status NO_ECHO but measurement_status {ms!r}")
        if allowed and (status != OK or obst not in ("CLEAR", "CAUTION")):
            return _error(f"forward_motion_allowed with status {status}/{obst}")
        if allowed and thr is not None and rng < thr:
            return _error(f"forward_motion_allowed with range {rng} < blocked threshold {thr}")
        if status == ERROR:
            return _error(f"service: {f.get('reason')}", seq=seq)
        return RangeReading(
            t=float(f["t"]), status=status, range_m=None if rng is None else float(rng),
            max_range_m=float(f["max_range_m"]), source=GROVE_SOURCE, seq=seq,
            forward_allowed=allowed, blocked_threshold_m=None if thr is None else float(thr),
            hardware=f.get("source_mode") != "SIMULATED", service_status=obst,
            reason=str(f.get("reason") or ""))
    except Exception as e:  # never let a malformed reading escape as anything but ERROR
        return _error(f"malformed: {type(e).__name__}: {e}")


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
        why = f"range reading stale (no valid timestamp{': ' + reading.reason if reading.reason else ''})"
        return Assessment.UNKNOWN, why
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
            if reading.service_status == "BLOCKED":
                return Assessment.BLOCKED, f"ranging service BLOCKED at {reading.range_m:.2f} m"
            return Assessment.UNKNOWN, f"ranging service forward_motion_allowed=false ({reading.service_status})"
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

"""Range reading record (one ping of the Grove Ultrasonic Ranger).

A reading is either VALID with a distance, or invalid with ``distance_m = None``
and a status saying why. Nothing in this package ever turns a missing echo,
timeout or fault into a number.
"""
from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

SCHEMA = "team15.range_reading/1"
SENSOR_TYPE = "GROVE_ULTRASONIC"
MEASUREMENT_TYPE = "FORWARD_OBSTACLE_RANGE"


class MeasurementStatus(str, Enum):
    VALID = "VALID"
    NO_ECHO = "NO_ECHO"                    # echo never started (no target, absorbed, disconnected)
    ECHO_TIMEOUT = "ECHO_TIMEOUT"          # echo started but never ended in time
    MISSED_ECHO_START = "MISSED_ECHO_START"  # saw the end of an echo, not its start
    OUT_OF_RANGE = "OUT_OF_RANGE"          # echo longer than the max rated range
    BELOW_MIN_RANGE = "BELOW_MIN_RANGE"    # echo shorter than the min rated range
    LINE_STUCK_HIGH = "LINE_STUCK_HIGH"    # SIG high before trigger: wiring / contention fault
    DRIVER_ERROR = "DRIVER_ERROR"          # GPIO open/request/read failed
    NOT_STARTED = "NOT_STARTED"            # no reading taken yet


def utc_iso(epoch_s: float) -> str:
    return _dt.datetime.fromtimestamp(epoch_s, tz=_dt.timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class RangeReading:
    status: MeasurementStatus
    distance_m: Optional[float]
    wall_time: float                 # epoch s at trigger (for humans / cross-host)
    mono_ns: int                     # time.monotonic_ns() at trigger (for age checks on this host)
    echo_us: Optional[float] = None  # measured echo high time
    seq: int = 0
    source: str = "SIMULATED"
    sensor_mount: str = "FRONT"
    sensor_id: str = "grove-us-front"
    driver: str = "simulated"
    detail: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status is MeasurementStatus.VALID:
            if self.distance_m is None:
                raise ValueError("VALID reading needs a distance")
        elif self.distance_m is not None:
            raise ValueError(f"{self.status.value} reading must not carry a distance")

    @property
    def valid(self) -> bool:
        return self.status is MeasurementStatus.VALID

    def age_s(self, now_mono_ns: Optional[int] = None) -> float:
        now = time.monotonic_ns() if now_mono_ns is None else now_mono_ns
        return max(0.0, (now - self.mono_ns) / 1e9)

    def to_dict(self) -> dict:
        d = {
            "schema": SCHEMA,
            "sensor_type": SENSOR_TYPE,
            "measurement_type": MEASUREMENT_TYPE,
            "sensor_id": self.sensor_id,
            "distance_m": None if self.distance_m is None else round(self.distance_m, 4),
            "valid": self.valid,
            "timestamp": utc_iso(self.wall_time),
            "obs_time": round(self.wall_time, 6),
            "mono_ns": self.mono_ns,
            "seq": self.seq,
            "sensor_mount": self.sensor_mount,
            "measurement_status": self.status.value,
            "echo_us": None if self.echo_us is None else round(self.echo_us, 1),
            "source": self.source,
            "driver": self.driver,
            "detail": self.detail,
        }
        if self.extra:
            d["extra"] = dict(self.extra)
        return d

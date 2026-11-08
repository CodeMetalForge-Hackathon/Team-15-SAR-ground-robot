"""Structured 360-degree scan (``team15.lidar_scan/1``).

A ``Scan`` is one revolution in the SENSOR frame. Every sample keeps its raw
distance and quality, plus the validity verdict and its reason. A zero distance
means the sensor had no usable return. That is ``NO_RETURN``, never "free space".

Timestamps: ``capture_start_mono_ns`` is the arrival of the revolution's first
node on this host. It is the conservative capture time: the oldest sample in the
scan is about that old. Every age check uses it, never the completion time.
"""
from __future__ import annotations

import datetime as _dt
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .config import MODEL_LABEL, MODEL_NAME, ProcessingConfig

SCHEMA = "team15.lidar_scan/1"


class SourceMode(str, Enum):
    SIMULATED = "SIMULATED"
    HARDWARE_UNVERIFIED = "HARDWARE_UNVERIFIED"   # real device, stage C calibration not yet passed
    HARDWARE_VERIFIED = "HARDWARE_VERIFIED"       # reserved: only after a reviewed stage-C sign-off; nothing sets it


class SampleStatus(str, Enum):
    VALID = "VALID"
    NO_RETURN = "NO_RETURN"              # distance 0: nothing measured (absorbing, glass, out of range)
    BELOW_MIN_RANGE = "BELOW_MIN_RANGE"
    BEYOND_MAX_RANGE = "BEYOND_MAX_RANGE"
    LOW_QUALITY = "LOW_QUALITY"
    NON_FINITE = "NON_FINITE"
    SELF_OCCLUDED = "SELF_OCCLUDED"      # inside a recorded robot-body window


class ScanCompletion(str, Enum):
    COMPLETE = "COMPLETE"                # start flag to next start flag, enough points and coverage
    PARTIAL = "PARTIAL"                  # revolution ended early or too few points/coverage
    INTERRUPTED = "INTERRUPTED"          # device error / disconnect mid-revolution


def utc_iso(epoch_s: float) -> str:
    return _dt.datetime.fromtimestamp(epoch_s, tz=_dt.timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class Sample:
    angle_deg: float          # sensor frame, clockwise
    distance_m: float         # raw (0.0 = no return)
    quality: int
    status: SampleStatus

    @property
    def valid(self) -> bool:
        return self.status is SampleStatus.VALID

    @property
    def range_m(self) -> Optional[float]:
        return self.distance_m if self.valid else None

    def xy_sensor(self) -> Optional[tuple[float, float]]:
        """Sensor-frame Cartesian (x along sensor 0 mark, y 90 deg COUNTER-clockwise), for display only."""
        if not self.valid:
            return None
        th = math.radians(-self.angle_deg)   # protocol angle is clockwise
        return (self.distance_m * math.cos(th), self.distance_m * math.sin(th))


def classify_sample(angle_deg: float, distance_m: float, quality: int, cfg: ProcessingConfig,
                    occluded: bool = False) -> SampleStatus:
    if not (isinstance(angle_deg, (int, float)) and math.isfinite(angle_deg)
            and isinstance(distance_m, (int, float)) and math.isfinite(distance_m)):
        return SampleStatus.NON_FINITE
    if occluded:
        return SampleStatus.SELF_OCCLUDED
    if distance_m <= 0.0:
        return SampleStatus.NO_RETURN
    if quality < cfg.min_quality:
        return SampleStatus.LOW_QUALITY
    if distance_m < cfg.min_range_m:
        return SampleStatus.BELOW_MIN_RANGE
    if distance_m > cfg.max_range_m:
        return SampleStatus.BEYOND_MAX_RANGE
    return SampleStatus.VALID


@dataclass
class Scan:
    sensor_id: str
    frame_id: str
    seq: int
    capture_start_mono_ns: int
    capture_end_mono_ns: int
    capture_start_wall: float
    samples: list[Sample]
    completion: ScanCompletion
    source_mode: SourceMode
    provenance: dict = field(default_factory=dict)   # driver, device, fixture name, host...
    model: str = MODEL_NAME
    model_label: str = MODEL_LABEL
    bin_deg: float = 1.0
    detail: Optional[str] = None

    @property
    def simulated(self) -> bool:
        return self.source_mode is SourceMode.SIMULATED

    @property
    def valid_samples(self) -> list[Sample]:
        return [s for s in self.samples if s.valid]

    def coverage_bins(self) -> set[int]:
        n = int(round(360.0 / self.bin_deg))
        return {int((s.angle_deg % 360.0) // self.bin_deg) % n for s in self.samples if s.valid}

    @property
    def valid_coverage(self) -> float:
        n = int(round(360.0 / self.bin_deg))
        return len(self.coverage_bins()) / n

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.capture_end_mono_ns - self.capture_start_mono_ns) / 1e9)

    def age_s(self, now_mono_ns: Optional[int] = None) -> float:
        now = time.monotonic_ns() if now_mono_ns is None else now_mono_ns
        return (now - self.capture_start_mono_ns) / 1e9

    def status_counts(self) -> dict:
        out: dict = {}
        for s in self.samples:
            out[s.status.value] = out.get(s.status.value, 0) + 1
        return out

    def to_dict(self, include_samples: bool = True) -> dict:
        d = {
            "schema": SCHEMA,
            "sensor_id": self.sensor_id, "model": self.model, "model_label": self.model_label,
            "frame_id": self.frame_id, "frame": "SENSOR (angle clockwise from the sensor 0 mark; not robot, not world)",
            "seq": self.seq,
            "capture_timestamp": utc_iso(self.capture_start_wall),
            "capture_start_wall": round(self.capture_start_wall, 6),
            "capture_start_mono_ns": self.capture_start_mono_ns,
            "capture_end_mono_ns": self.capture_end_mono_ns,
            "duration_s": round(self.duration_s, 4),
            "completion": self.completion.value,
            "point_count": len(self.samples),
            "valid_count": len(self.valid_samples),
            "valid_coverage": round(self.valid_coverage, 4),
            "status_counts": self.status_counts(),
            "source_mode": self.source_mode.value,
            "simulated": self.simulated,
            "provenance": dict(self.provenance),
            "detail": self.detail,
        }
        if include_samples:
            d["samples"] = [{"bearing_deg": round(s.angle_deg, 3),
                             "range_m": None if s.range_m is None else round(s.range_m, 4),
                             "raw_distance_m": round(s.distance_m, 4), "quality": s.quality,
                             "valid": s.valid, "status": s.status.value} for s in self.samples]
        return d


def build_scan(points, *, sensor_id: str, frame_id: str, seq: int, start_mono_ns: int, end_mono_ns: int,
               start_wall: float, cfg: ProcessingConfig, source_mode: SourceMode, provenance: dict,
               interrupted: bool = False, occluded=None, detail: Optional[str] = None) -> Scan:
    """points: iterable of (angle_deg, distance_m, quality) in the sensor frame."""
    samples = []
    for a, d, q in points:
        occ = bool(occluded(a)) if (occluded is not None and isinstance(a, (int, float)) and math.isfinite(a)) else False
        st = classify_sample(a, d, q, cfg, occ)
        samples.append(Sample(float(a) % 360.0 if st is not SampleStatus.NON_FINITE else 0.0,
                              float(d) if st is not SampleStatus.NON_FINITE else 0.0, int(q), st))
    scan = Scan(sensor_id=sensor_id, frame_id=frame_id, seq=seq, capture_start_mono_ns=start_mono_ns,
                capture_end_mono_ns=end_mono_ns, capture_start_wall=start_wall, samples=samples,
                completion=ScanCompletion.COMPLETE, source_mode=source_mode, provenance=dict(provenance),
                bin_deg=cfg.bin_deg, detail=detail)
    if interrupted:
        scan.completion = ScanCompletion.INTERRUPTED
    elif len(samples) < cfg.min_points or _angular_span(samples) < 300.0:
        # Completion is about the revolution being swept, valid or not. Low VALID coverage
        # (e.g. an open room) is judged separately by the assessor and reads UNKNOWN there.
        scan.completion = ScanCompletion.PARTIAL
    return scan


def _angular_span(samples: list[Sample]) -> float:
    """Angular extent swept by the samples (valid or not), from sorted gaps."""
    if not samples:
        return 0.0
    angs = sorted(s.angle_deg for s in samples)
    gaps = [b - a for a, b in zip(angs, angs[1:])] + [angs[0] + 360.0 - angs[-1]]
    return 360.0 - max(gaps)

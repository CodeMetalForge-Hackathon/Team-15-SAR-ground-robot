"""Sector analysis and the fail-closed LiDAR assessment (``team15.lidar_sectors/1``).

Eight 45-degree sectors in the ROBOT frame (0 = robot forward, counter-clockwise positive):

    FRONT 0, FRONT_LEFT 45, LEFT 90, REAR_LEFT 135, REAR 180, REAR_RIGHT 225, RIGHT 270, FRONT_RIGHT 315

Per sector, in order:
  1. A valid return at or inside ``blocked_m``                    -> BLOCKED
  2. Fewer than ``min_sector_coverage`` of the sector's bins hold
     a valid return (no return, glass, absorbing, occluded)      -> UNKNOWN
  3. The nearest valid return at or inside ``caution_m``          -> CAUTION
  4. Otherwise                                                   -> CLEAR

Then the downgrades, applied to every sector. CLEAR or CAUTION becomes UNKNOWN when:
  * the mount alignment is not verified (we do not know which way is forward), in which case
    BLOCKED also becomes UNKNOWN and an orientation-free ``any_return_within_blocked`` is raised;
  * the scan is not COMPLETE;
  * the scan is older than ``display_max_age_s`` (STALE), or the timestamp is in the future;
  * the connection is not SCANNING, or the device health is not GOOD.

In addition, the footprint corridor (lidar/footprint.py) must be CLEAR or CAUTION, and the orientation
monitor must be OK. Weak returns (< clearance_min_quality) never count as clear-space evidence.

``forward_motion_allowed`` is True only if ALL of the following hold:
  * the scan is fresh (no older than 0.20 s, measured from the capture START);
  * FRONT is CLEAR or CAUTION;
  * FRONT_LEFT and FRONT_RIGHT are neither BLOCKED nor UNKNOWN;
  * the scan rate is known and inside its window;
  * ``clear_confirm_scans`` consecutive scans agree;
  * the source is SIMULATED. In this PR a real device is HARDWARE_UNVERIFIED, which never allows motion.
This is an input to the rover's deterministic safety layer. It authorizes nothing by itself
(Issue #9), and the rover adapter is rejected by today's rover anyway (LIDAR_C1_DATA_CONTRACT.md section 5).

The ranges are distances to reflecting surfaces in the scan plane. They are never the
distance to a detected person, and never a robot position.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .config import LidarConfig
from .footprint import ORIENTATION_FAILED, ORIENTATION_OK, CorridorResult, assess_corridor
from .scan import Scan, ScanCompletion, SourceMode

SCHEMA = "team15.lidar_sectors/1"
RANGE_SEMANTICS = ("nearest valid LiDAR return in the sensor's horizontal scan plane, per robot-frame sector; "
                   "NOT a distance to a person or camera detection, NOT a robot position")

SECTORS = (("FRONT", 0.0), ("FRONT_LEFT", 45.0), ("LEFT", 90.0), ("REAR_LEFT", 135.0),
           ("REAR", 180.0), ("REAR_RIGHT", 225.0), ("RIGHT", 270.0), ("FRONT_RIGHT", 315.0))
SECTOR_WIDTH_DEG = 45.0


class SectorStatus(str, Enum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class Connection(str, Enum):
    GATE_LOCKED = "GATE_LOCKED"        # hardware checklist incomplete: port never opened
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    SCANNING = "SCANNING"
    TIMEOUT = "TIMEOUT"
    HEALTH_ERROR = "HEALTH_ERROR"


@dataclass
class SectorResult:
    name: str
    center_deg: float
    status: SectorStatus
    min_range_m: Optional[float]
    min_bearing_robot_deg: Optional[float]
    coverage: float
    valid_count: int
    reason: str

    def to_dict(self) -> dict:
        return {"name": self.name, "center_deg": self.center_deg, "width_deg": SECTOR_WIDTH_DEG,
                "status": self.status.value,
                "min_range_m": None if self.min_range_m is None else round(self.min_range_m, 4),
                "min_bearing_robot_deg": None if self.min_bearing_robot_deg is None
                else round(self.min_bearing_robot_deg, 2),
                "coverage": round(self.coverage, 3), "valid_count": self.valid_count, "reason": self.reason}


def sector_of(robot_bearing_deg: float) -> str:
    i = int(((robot_bearing_deg + SECTOR_WIDTH_DEG / 2) % 360.0) // SECTOR_WIDTH_DEG)
    return SECTORS[i][0]


def analyze_sectors(scan: Scan, cfg: LidarConfig) -> list[SectorResult]:
    """Raw per-sector status (rules 1-4). Requires a configured forward offset."""
    p, m = cfg.processing, cfg.mount
    bins_per_sector = int(round(SECTOR_WIDTH_DEG / p.bin_deg))
    acc = {name: {"bins": set(), "min": None, "brg": None, "n": 0} for name, _ in SECTORS}
    for s in scan.samples:
        if not s.valid or m.occluded(s.angle_deg):    # re-apply the CURRENT signed-off windows
            continue
        rb = m.robot_bearing(s.angle_deg)
        if rb is None:
            continue
        name = sector_of(rb)
        a = acc[name]
        a["n"] += 1
        if s.quality >= p.clearance_min_quality:   # weak returns are obstacles, never clear-space evidence
            a["bins"].add(int(((rb + SECTOR_WIDTH_DEG / 2) % 360.0) // p.bin_deg))
        if a["min"] is None or s.distance_m < a["min"]:
            a["min"], a["brg"] = s.distance_m, rb
    out = []
    for name, c in SECTORS:
        a = acc[name]
        cov = min(1.0, len(a["bins"]) / bins_per_sector)
        mn = a["min"]
        if mn is not None and mn <= p.blocked_m:
            st, why = SectorStatus.BLOCKED, f"valid return at {mn:.2f} m <= {p.blocked_m:.2f} m"
        elif cov < p.min_sector_coverage:
            st, why = SectorStatus.UNKNOWN, (f"valid returns in {cov:.0%} of sector < {p.min_sector_coverage:.0%} "
                                             "(no return is not clear space)")
        elif mn <= p.caution_m:
            st, why = SectorStatus.CAUTION, f"nearest {mn:.2f} m <= {p.caution_m:.2f} m"
        else:
            st, why = SectorStatus.CLEAR, f"nearest {mn:.2f} m, coverage {cov:.0%}"
        out.append(SectorResult(name, c, st, mn, a["brg"], cov, a["n"], why))
    return out


@dataclass
class LidarAssessment:
    connection: Connection
    sectors: list[SectorResult]
    forward_motion_allowed: bool
    forward_status: SectorStatus
    reason: str
    scan_seq: Optional[int]
    scan_age_s: Optional[float]
    stale_for_motion: bool
    stale_for_display: bool
    completion: Optional[str]
    valid_coverage: Optional[float]
    scan_rate_hz: Optional[float]
    alignment_verified: bool
    source_mode: str
    closest: Optional[dict]
    any_return_within_blocked: bool
    last_valid_scan_wall: Optional[float]
    sensor_id: str
    frame_id: str
    thresholds: dict
    health: Optional[dict] = None
    scan_wall: Optional[float] = None
    scan_mono_ns: Optional[int] = None
    provenance: dict = field(default_factory=dict)
    mount: dict = field(default_factory=dict)
    corridor: Optional[CorridorResult] = None
    orientation: str = "NOT_CONFIGURED"

    def sector(self, name: str) -> SectorResult:
        return next(s for s in self.sectors if s.name == name)

    @property
    def simulated(self) -> bool:
        return self.source_mode == SourceMode.SIMULATED.value

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "sensor_id": self.sensor_id, "sensor_type": "RPLIDAR_C1",
            "frame_id": self.frame_id,
            "frames": {"sector_bearings": "ROBOT (0 = forward axis as configured, CCW positive)",
                       "closest.sensor_bearing_deg": "SENSOR (clockwise from sensor 0 mark)",
                       "world": "NONE: a 2D scan gives no position or heading"},
            "connection": self.connection.value, "source_mode": self.source_mode, "simulated": self.simulated,
            "forward_motion_allowed": self.forward_motion_allowed, "forward_status": self.forward_status.value,
            "motion_authority": "NONE: input to the rover's deterministic safety layer only (Issue #9)",
            "reason": self.reason, "scan_seq": self.scan_seq,
            "scan_capture_start_wall": self.scan_wall, "scan_capture_start_mono_ns": self.scan_mono_ns,
            "mount": dict(self.mount),
            "forward_corridor": None if self.corridor is None else self.corridor.to_dict(),
            "orientation_monitor": self.orientation,
            "scan_age_s": None if self.scan_age_s is None else round(self.scan_age_s, 4),
            "stale_for_motion": self.stale_for_motion, "stale_for_display": self.stale_for_display,
            "completion": self.completion,
            "valid_coverage": None if self.valid_coverage is None else round(self.valid_coverage, 4),
            "scan_rate_hz": None if self.scan_rate_hz is None else round(self.scan_rate_hz, 2),
            "alignment_verified": self.alignment_verified, "closest": self.closest,
            "any_return_within_blocked": self.any_return_within_blocked,
            "last_valid_scan_wall": self.last_valid_scan_wall,
            "sectors": [s.to_dict() for s in self.sectors], "thresholds": self.thresholds,
            "health": self.health, "provenance": dict(self.provenance),
            "range_semantics": RANGE_SEMANTICS,
            "person_distance_m": None,
        }


def _unknown_sectors(reason: str) -> list[SectorResult]:
    return [SectorResult(n, c, SectorStatus.UNKNOWN, None, None, 0.0, 0, reason) for n, c in SECTORS]


class LidarAssessor:
    """Stateful: scan-rate estimate and BLOCKED/UNKNOWN -> CLEAR confirmation across scans."""

    def __init__(self, cfg: LidarConfig, clock_ns=time.monotonic_ns):
        self.cfg = cfg.validate() if cfg.mode == "simulated" else cfg
        self.clock_ns = clock_ns
        self._starts: deque = deque(maxlen=6)
        self._confirm = 0
        self._last_scan: Optional[Scan] = None
        self._last_valid_wall: Optional[float] = None
        self._prev_forward_ok = False

    def thresholds(self) -> dict:
        p = self.cfg.processing
        return {"blocked_m": p.blocked_m, "caution_m": p.caution_m, "min_sector_coverage": p.min_sector_coverage,
                "motion_max_age_s": p.motion_max_age_s, "display_max_age_s": p.display_max_age_s,
                "min_quality": p.min_quality, "min_range_m": p.min_range_m, "max_range_m": p.max_range_m,
                "scan_hz_window": [p.scan_hz_min, p.scan_hz_max], "clear_confirm_scans": p.clear_confirm_scans,
                "placeholders": "blocked/caution/quality/coverage/rate are PLACEHOLDERS until stage-C calibration"}

    def scan_rate_hz(self) -> Optional[float]:
        if len(self._starts) < 2:
            return None
        span = (self._starts[-1] - self._starts[0]) / 1e9
        return (len(self._starts) - 1) / span if span > 0 else None

    def update(self, scan: Scan, now_mono_ns: Optional[int] = None, connection: Connection = Connection.SCANNING,
               health: Optional[dict] = None) -> LidarAssessment:
        if self._starts and scan.capture_start_mono_ns <= self._starts[-1]:
            self._starts.clear()   # time went backwards or a replayed scan: restart the estimate
        self._starts.append(scan.capture_start_mono_ns)
        self._last_scan = scan
        if scan.completion is ScanCompletion.COMPLETE and scan.valid_samples:
            self._last_valid_wall = scan.capture_start_wall
        return self._assess(now_mono_ns, connection, health, new_scan=True)

    def status(self, connection: Connection, reason: str = "", now_mono_ns: Optional[int] = None,
               health: Optional[dict] = None) -> LidarAssessment:
        """Re-assess without a new scan (watchdog, disconnect, timeout)."""
        if connection is not Connection.SCANNING:
            self._confirm = 0
            self._starts.clear()
        return self._assess(now_mono_ns, connection, health, new_scan=False, extra_reason=reason)

    def _assess(self, now_mono_ns, connection: Connection, health, new_scan: bool,
                extra_reason: str = "") -> LidarAssessment:
        cfg, p = self.cfg, self.cfg.processing
        now = self.clock_ns() if now_mono_ns is None else now_mono_ns
        scan = self._last_scan
        reasons = []
        base = dict(sensor_id=cfg.sensor_id, frame_id=cfg.frame_id, thresholds=self.thresholds(),
                    mount={"sensor_rotation": cfg.mount.sensor_rotation, "sign": cfg.mount.sign,
                           "forward_offset_deg": cfg.mount.forward_offset_deg,
                           "alignment_verified": cfg.mount.aligned},
                    alignment_verified=cfg.mount.aligned, health=health,
                    last_valid_scan_wall=self._last_valid_wall, scan_rate_hz=self.scan_rate_hz())
        if scan is None:
            self._confirm = 0
            why = extra_reason or "no scan yet"
            return LidarAssessment(connection=connection, sectors=_unknown_sectors(why),
                                   forward_motion_allowed=False, forward_status=SectorStatus.UNKNOWN, reason=why,
                                   scan_seq=None, scan_age_s=None, stale_for_motion=True, stale_for_display=True,
                                   completion=None, valid_coverage=None, source_mode=SourceMode.SIMULATED.value
                                   if cfg.mode == "simulated" else SourceMode.HARDWARE_UNVERIFIED.value,
                                   closest=None, any_return_within_blocked=False, **base)
        age = scan.age_s(now)
        clock_fault = age < -p.max_future_skew_s or not math.isfinite(age)
        stale_motion = clock_fault or age > p.motion_max_age_s
        stale_display = clock_fault or age > p.display_max_age_s

        # Closest valid return: always reported in the SENSOR frame (orientation-free).
        closest = None
        vs = scan.valid_samples
        if vs and not stale_display:
            c = min(vs, key=lambda s: s.distance_m)
            rb = cfg.mount.robot_bearing(c.angle_deg) if cfg.mount.aligned else None
            closest = {"range_m": round(c.distance_m, 4), "sensor_bearing_deg": round(c.angle_deg, 2),
                       "robot_bearing_deg": None if rb is None else round(rb, 2),
                       "robot_sector": None if rb is None else sector_of(rb),
                       "quality": c.quality, "is_person": None,
                       "note": "nearest reflecting surface; not associated with any camera detection"}
        any_blocked = bool(vs) and not stale_display and min(s.distance_m for s in vs) <= p.blocked_m

        corridor = assess_corridor(scan, cfg)
        orientation = corridor.orientation
        if cfg.mount.aligned and orientation != ORIENTATION_FAILED:
            sectors = analyze_sectors(scan, cfg)
        elif cfg.mount.aligned:
            sectors = _unknown_sectors(corridor.reason)
            reasons.append("orientation monitor FAILED")
        else:
            sectors = _unknown_sectors("sensor-to-robot alignment not verified: forward direction unknown")
            reasons.append("alignment not verified")
        if orientation != ORIENTATION_OK:
            reasons.append(f"orientation monitor {orientation}")

        degrade = []
        if clock_fault:
            degrade.append(f"scan timestamp {-age:.3f} s in the future (clock fault)")
        elif stale_display:
            degrade.append(f"scan stale ({age:.3f} s > {p.display_max_age_s} s)")
        if scan.completion is not ScanCompletion.COMPLETE:
            degrade.append(f"scan {scan.completion.value}" + (f": {scan.detail}" if scan.detail else ""))
        if connection is not Connection.SCANNING:
            degrade.append(f"connection {connection.value}")
        if health is not None and health.get("status") != "GOOD":
            degrade.append(f"device health {health.get('status')}")
        if degrade and corridor.status in ("CLEAR", "CAUTION") or \
                ((clock_fault or stale_display) and corridor.status == "BLOCKED"):
            corridor = CorridorResult("UNKNOWN", None, None, None, None, None, corridor.near_zone_m,
                                      corridor.half_width_m, corridor.lookahead_m, orientation, "; ".join(degrade))
        for s in sectors:
            if degrade and s.status in (SectorStatus.CLEAR, SectorStatus.CAUTION):
                s.status, s.reason = SectorStatus.UNKNOWN, "; ".join(degrade)
            elif (clock_fault or stale_display) and s.status is SectorStatus.BLOCKED:
                s.status, s.reason = SectorStatus.UNKNOWN, "; ".join(degrade)
        reasons += degrade

        front = next(s for s in sectors if s.name == "FRONT")
        fl = next(s for s in sectors if s.name == "FRONT_LEFT")
        fr = next(s for s in sectors if s.name == "FRONT_RIGHT")
        rate = self.scan_rate_hz()
        geom_ok = (front.status in (SectorStatus.CLEAR, SectorStatus.CAUTION)
                   and fl.status not in (SectorStatus.BLOCKED, SectorStatus.UNKNOWN)
                   and fr.status not in (SectorStatus.BLOCKED, SectorStatus.UNKNOWN))
        if stale_motion and not stale_display:
            reasons.append(f"scan too old for motion ({age:.3f} s > {p.motion_max_age_s} s)")
        if rate is None:
            reasons.append("scan rate unknown (need >= 2 scans)")
        elif not (p.scan_hz_min <= rate <= p.scan_hz_max):
            reasons.append(f"scan rate {rate:.1f} Hz outside [{p.scan_hz_min}, {p.scan_hz_max}] Hz")
        if scan.source_mode is not SourceMode.SIMULATED:
            reasons.append("hardware source not stage-C verified: motion never allowed in this PR")
        if not geom_ok:
            reasons.append(f"forward sectors FRONT={front.status.value} FRONT_LEFT={fl.status.value} "
                           f"FRONT_RIGHT={fr.status.value}")
        corridor_ok = corridor.status in ("CLEAR", "CAUTION")
        if not corridor_ok:
            reasons.append(f"forward corridor {corridor.status}: {corridor.reason}")
        candidate = (geom_ok and corridor_ok and orientation == ORIENTATION_OK and not stale_motion and rate is not None and p.scan_hz_min <= rate <= p.scan_hz_max
                     and scan.source_mode is SourceMode.SIMULATED and connection is Connection.SCANNING
                     and cfg.mount.aligned and scan.completion is ScanCompletion.COMPLETE)
        if candidate:
            if new_scan:
                self._confirm += 1
            allowed = self._confirm >= p.clear_confirm_scans or self._prev_forward_ok
            if not allowed:
                reasons.append(f"confirming clearance {self._confirm}/{p.clear_confirm_scans} scans")
        else:
            self._confirm = 0
            allowed = False
        self._prev_forward_ok = allowed
        if extra_reason:
            reasons.insert(0, extra_reason)
        return LidarAssessment(
            connection=connection, sectors=sectors, forward_motion_allowed=allowed,
            forward_status=front.status, reason="; ".join(reasons) or front.reason,
            scan_seq=scan.seq, scan_age_s=age, stale_for_motion=stale_motion, stale_for_display=stale_display,
            completion=scan.completion.value, valid_coverage=scan.valid_coverage,
            source_mode=scan.source_mode.value, closest=closest, any_return_within_blocked=any_blocked,
            scan_wall=scan.capture_start_wall, scan_mono_ns=scan.capture_start_mono_ns,
            provenance=dict(scan.provenance), corridor=corridor, orientation=orientation, **base)

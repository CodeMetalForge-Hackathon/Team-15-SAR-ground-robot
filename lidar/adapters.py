"""Compatibility adapters: LiDAR assessment -> existing Team-15 contracts.

1. ``to_range_snapshot``: ``team15.range_snapshot/1`` built from the FRONT sector, so
   the existing dashboard "Forward obstacle range" card (core/range_view.py) can show
   LiDAR data with NO dashboard code change. Display only:
     * ``forward_motion_allowed`` is ALWAYS False in this snapshot. A Grove consumer
       (ranging.rover_io.GroveRangeIO / RangeClient) pointed at it by mistake would
       relabel it "grove-ultrasonic" (rover_io.ROVER_SOURCE). With motion always denied,
       that mistake can stop the robot but never move it.
     * ``provenance.driver`` is "rplidar-c1", never "gpiod". range_view.hardware_verified
       requires gpiod, so the card shows SIMULATED for LiDAR data until the dashboard owner
       adds a reviewed LiDAR rule (LIDAR_DASHBOARD_INTERFACE_REQUEST in GROVE_TO_LIDAR_MIGRATION.md).
     * It refuses to write to ranging's default snapshot path (/dev/shm/team15_range.json).
2. ``to_rover_fields``: ``team15.rover_range_fields/1`` with ``source = "rplidar-c1"``.
   Today's rover/sensors.py:from_rover_fields accepts only "grove-ultrasonic", so these
   fields read ERROR -> UNKNOWN -> no motion. That is the intended Stage B behaviour: the
   rover owner must allowlist the source in a reviewed change (Stage D, after Issue #9).
   We do NOT impersonate the Grove source.
3. ``to_advisory_context``: optional ``lidar`` field for the Qwen advisory request context.
"""
from __future__ import annotations

import socket
import time
from typing import Optional

from .processing import LidarAssessment, SectorStatus
from .scan import utc_iso

RANGE_SNAPSHOT_SCHEMA = "team15.range_snapshot/1"
ROVER_FIELDS_SCHEMA = "team15.rover_range_fields/1"
ROVER_SOURCE = "rplidar-c1"
ADVISORY_SCHEMA = "team15.lidar_advisory_context/1"
GROVE_SNAPSHOT_PATHS = ("/dev/shm/team15_range.json",)


def _front_measurement_status(a: LidarAssessment) -> str:
    f = a.sector("FRONT")
    if a.connection.value != "SCANNING" and a.scan_seq is None:
        return "DRIVER_ERROR"
    if a.stale_for_display:
        return "NOT_STARTED" if a.scan_seq is None else "DRIVER_ERROR"
    if f.min_range_m is not None and f.status is not SectorStatus.UNKNOWN:
        return "VALID"
    if f.status is SectorStatus.UNKNOWN and f.min_range_m is None:
        return "NO_ECHO"          # range_view shows "unknown (no echo)": never clear
    return "DRIVER_ERROR"


def to_range_snapshot(a: LidarAssessment, *, now_wall: Optional[float] = None,
                      now_mono_ns: Optional[int] = None) -> dict:
    now_wall = time.time() if now_wall is None else now_wall
    now_mono_ns = time.monotonic_ns() if now_mono_ns is None else now_mono_ns
    f = a.sector("FRONT")
    ms = _front_measurement_status(a)
    valid = ms == "VALID"
    status = f.status.value if not a.stale_for_display else "UNKNOWN"
    wall = a.scan_wall
    latest = None
    if a.scan_seq is not None:
        latest = {"schema": "team15.range_reading/1", "sensor_type": "RPLIDAR_C1",
                  "measurement_type": "FORWARD_SECTOR_MIN_RANGE", "sensor_id": a.sensor_id,
                  "distance_m": round(f.min_range_m, 4) if (valid and f.min_range_m is not None) else None,
                  "valid": valid, "timestamp": utc_iso(wall) if wall else None,
                  "obs_time": None if wall is None else round(wall, 6), "mono_ns": a.scan_mono_ns,
                  "seq": a.scan_seq, "sensor_mount": "TOP_360", "measurement_status": ms,
                  "echo_us": None, "source": a.source_mode, "driver": "rplidar-c1", "detail": f.reason}
    reason = (f"LiDAR FRONT sector ({f.center_deg:g}±22.5°): {f.reason}; display only, "
              "forward_motion_allowed is never set by this compatibility snapshot")
    return {
        "schema": RANGE_SNAPSHOT_SCHEMA, "sensor_id": a.sensor_id, "sensor_type": "RPLIDAR_C1",
        "measurement_type": "FORWARD_SECTOR_MIN_RANGE", "sensor_mount": "TOP_360",
        "published_at": utc_iso(now_wall), "published_time": round(now_wall, 6), "published_mono_ns": now_mono_ns,
        "obstacle_status": status,
        "forward_motion_allowed": False,
        "range_m": round(f.min_range_m, 4) if (valid and f.min_range_m is not None) else None,
        "valid": valid, "obs_time": None if wall is None else round(wall, 6),
        "stale_after_s": a.thresholds["display_max_age_s"],
        "latest": latest,
        "assessment": {"status": status, "forward_motion_allowed": False, "reason": reason,
                       "thresholds": {"blocked_m": a.thresholds["blocked_m"], "caution_m": a.thresholds["caution_m"]},
                       "range_semantics": "nearest LiDAR return in the FRONT 45° sector; NOT a person distance"},
        "health": {"state": "OK" if a.connection.value == "SCANNING" else "FAULT", "connection": a.connection.value},
        "provenance": {"source_mode": "SIMULATED" if a.simulated else a.source_mode, "platform": "SIM" if a.simulated
                       else "BENCH", "source": "rplidar-c1", "driver": "rplidar-c1", "host": socket.gethostname(),
                       "wiring_verified_by": None, "service_boot_id": None},
        "lidar": {"schema": "team15.lidar_sectors/1", "connection": a.connection.value,
                  "alignment_verified": a.alignment_verified},
    }


def write_range_snapshot(path: str, snap: dict) -> None:
    """Atomic write, refusing the Grove service's own snapshot path (no source confusion)."""
    import json
    import os
    if os.path.abspath(path) in GROVE_SNAPSHOT_PATHS:
        raise ValueError(f"refusing to write LiDAR data to the Grove ranging path {path}")
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(snap, fh)
    os.replace(tmp, path)


def to_rover_fields(a: LidarAssessment, now_mono_s: float, this_host: Optional[str] = None,
                    max_range_m: Optional[float] = None) -> dict:
    """``team15.rover_range_fields/1`` from the FRONT sector. Honest source, so today's rover rejects it."""
    host = this_host or socket.gethostname()
    f = a.sector("FRONT")
    same_host = (a.provenance or {}).get("host") in (None, host)
    t = a.scan_mono_ns / 1e9 if (a.scan_mono_ns is not None and same_host) else now_mono_s
    if a.scan_seq is None or a.stale_for_motion or not same_host:
        status, rng = "ERROR", None
    elif f.status in (SectorStatus.CLEAR, SectorStatus.CAUTION, SectorStatus.BLOCKED) and f.min_range_m is not None:
        status, rng = "OK", float(f.min_range_m)
    elif f.status is SectorStatus.UNKNOWN and f.min_range_m is None and a.connection.value == "SCANNING":
        status, rng = "NO_ECHO", None
    else:
        status, rng = "ERROR", None
    allowed = bool(a.forward_motion_allowed) and status == "OK" and f.status in (SectorStatus.CLEAR,
                                                                                 SectorStatus.CAUTION)
    ms = {"OK": "VALID", "NO_ECHO": "NO_ECHO"}.get(status, "DRIVER_ERROR")
    return {"schema": ROVER_FIELDS_SCHEMA, "clock": "time.monotonic@" + host, "t": t, "status": status,
            "range_m": rng, "max_range_m": max_range_m or a.thresholds["max_range_m"], "source": ROVER_SOURCE,
            "seq": int(a.scan_seq or 0), "forward_motion_allowed": allowed,
            "obstacle_status": f.status.value if status != "ERROR" else "UNKNOWN", "measurement_status": ms,
            "reason": a.reason, "blocked_threshold_m": a.thresholds["blocked_m"], "diagnosis": a.connection.value,
            "source_mode": "SIMULATED" if a.simulated else a.source_mode}


def to_advisory_context(a: LidarAssessment) -> dict:
    """Optional ``lidar`` key for the Qwen advisory request ``context``. Validated, structured, non-authoritative."""
    usable = not a.stale_for_display and a.connection.value == "SCANNING"
    return {
        "schema": ADVISORY_SCHEMA,
        "sensor_id": a.sensor_id, "sensor_type": "RPLIDAR_C1",
        "source_mode": "SIMULATED" if a.simulated else a.source_mode,
        "connection": a.connection.value,
        "obs_time": a.scan_wall, "scan_seq": a.scan_seq, "stale": a.stale_for_display,
        "alignment_verified": a.alignment_verified,
        "frame": "ROBOT sectors (0 = forward, CCW+), no world coordinates",
        "sectors": [{"facing": s.name, "status": s.status.value if usable else "UNKNOWN",
                     "min_range_cm": None if (s.min_range_m is None or not usable) else round(s.min_range_m * 100, 1),
                     "coverage": round(s.coverage, 3)} for s in a.sectors],
        "closest_cm": None if not (usable and a.closest) else round(a.closest["range_m"] * 100, 1),
        "association": "NOT_ESTABLISHED",
        "person_distance_cm": None,
        "localization": "NONE",
        "may_authorize_motion": False,
        "may_authorize_release": False,
        "note": ("LiDAR returns are reflecting surfaces, not people. No camera-LiDAR calibration exists; "
                 "do not claim a person distance, a world position, an injury, or a clear path."),
    }

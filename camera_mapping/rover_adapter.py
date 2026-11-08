"""Camera perception -> rover interfaces, advisory only.

What this adapter does:
  * ``camera_detections(state)`` -> ``rover.sensors.CameraDetection`` (bearing only),
    the interface the navigator already uses for camera hits.
  * ``log_observations(state, log)`` -> UNCONFIRMED observations in
    ``rover.observations.ObservationLog``. UNCONFIRMED never blocks routing and
    never clears an edge; a human must confirm.

What it refuses to do:
  * produce a ``RangeReading`` (the Grove-specific forward-motion gate, PR #7/#14),
  * use the Grove source name, or claim ``hardware=True`` range data,
  * send anything to the motor controller or StickC bridge (PR #15).
Camera distances stay ``CAMERA_ESTIMATE`` in ``detail`` for display and simulation.
"""
from __future__ import annotations

from typing import List

CAMERA_SOURCE = "pi5-imx708-camera-estimate"
OBS_KIND = "camera_obstacle_estimate"


class NotARangeSensor(RuntimeError):
    pass


def camera_detections(state: dict):
    from rover.sensors import CameraDetection
    out = []
    for r in state.get("objects") or []:
        if r.get("validity") != "VALID":
            continue
        out.append(CameraDetection(t=float(r["timestamp"]), label=r["object_class"],
                                   score=float(r["detection_confidence"]),
                                   relative_bearing_deg=float((r.get("distance") or {}).get("bearing_deg", 0.0)),
                                   source=CAMERA_SOURCE))
    return out


def log_observations(state: dict, log) -> List:
    from rover.observations import UNCONFIRMED
    added = []
    for r in state.get("objects") or []:
        if r.get("validity") != "VALID":
            continue
        fd = r.get("filtered_distance")
        added.append(log.add(OBS_KIND, CAMERA_SOURCE, UNCONFIRMED, dynamic=True, edge=None,
                             t=float(r["timestamp"]),
                             detail={"label": r["object_class"], "track_id": r["track_id"],
                                     "estimate_m": fd["distance_m"] if fd else None,
                                     "sigma_m": fd["sigma_m"] if fd else None,
                                     "corridor_position": r["corridor_position"],
                                     "assessment": (state.get("assessment") or {}).get("status"),
                                     "data_source": "CAMERA_ESTIMATE", "source_mode": state.get("source_mode"),
                                     "motion_authority": "NONE"}))
    return added


def as_range_reading(state: dict):
    """Deliberately unsupported: a camera estimate must never feed the range gate."""
    raise NotARangeSensor("camera estimates are not range-sensor readings; the Grove forward-motion "
                          "gate is unchanged and still requires its own sensor")

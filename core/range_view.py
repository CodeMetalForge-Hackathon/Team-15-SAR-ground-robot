"""Turn a forward-range reading into what the dashboard's range card shows.

Inputs are the ranging service's ``team15.range_snapshot/1`` (PR #7) and,
optionally, the robot API's ``team15.robot_status/1`` (``forward_range`` and
``claims``). The output is ``team15.range_panel/1``: display-ready, with every
safety rule applied here so the browser only renders it.

Rules (agreed with the robotics session, issue: Grove range panel):
- The reading is the nearest reflecting surface in a ~15° forward cone. It is
  never the distance to the detected person, so nothing here refers to tracks.
- "HARDWARE" only when every allowlisted check passes; everything else is
  SIMULATED. Today nothing passes.
- Stale uses the snapshot's own ``stale_after_s`` (0.5 s). Live data: the age is
  recomputed from ``published_time``; skew beyond -1 s also counts as stale.
  Fixture data: the fixture's own ``freshness`` is used as-is.
- Stale, invalid, NO_ECHO, warm-up, inconsistent or missing data reads UNKNOWN
  or DISCONNECTED and is greyed out. NO_ECHO is never "clear".
- Forward motion is only ever shown when it is NOT allowed (BLOCKED/UNKNOWN);
  the panel never says "motion allowed".
"""
from __future__ import annotations

from datetime import datetime, timezone

TITLE = "Forward obstacle range"
QUALIFICATION = ("nearest reflecting surface in a ~15° forward cone; "
                 "not the distance to the detected person")
DEFAULT_STALE_AFTER_S = 0.5
MAX_FUTURE_SKEW_S = 1.0
USABLE = ("CLEAR", "CAUTION", "BLOCKED")
NO_ECHO = ("NO_ECHO", "OUT_OF_RANGE")


def _utc_hms(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%H:%M:%SZ")


def _epoch(iso: str | None) -> float | None:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt.timestamp() if dt.tzinfo else None


def hardware_verified(snapshot: dict | None, robot: dict | None) -> bool:
    """Allowlist: True only if every hardware check passes."""
    if snapshot is not None:
        prov = snapshot.get("provenance") or {}
        if not (prov.get("source_mode") == "LIVE-HW" and prov.get("wiring_verified_by")
                and prov.get("driver") == "gpiod"):
            return False
    if robot is not None:
        claims = robot.get("claims") or {}
        if robot.get("mode") == "SIMULATION" or claims.get("hardware_validated") is not True:
            return False
        if snapshot is None:
            fr = robot.get("forward_range") or {}
            if fr.get("sensor_source") != "LIVE-HW":
                return False
    return snapshot is not None or robot is not None


def _freshness(published: float | None, stale_after: float, fixture: bool,
               given: dict | None, now: float) -> tuple[bool, float | None]:
    if fixture:
        given = given or {}
        stale = given.get("stale")
        return (stale is not False), given.get("age_s")
    if published is None:
        return True, None
    age = now - float(published)
    stale = age > stale_after or age < -MAX_FUTURE_SKEW_S or bool((given or {}).get("stale"))
    return stale, round(age, 3)


def _base(source: str, hw: bool) -> dict:
    return {
        "schema": "team15.range_panel/1", "title": TITLE, "qualification": QUALIFICATION,
        "source": source, "hardware": hw, "simulated": not hw,
        "badge": "HARDWARE" if hw else "SIMULATED",
        "status": "DISCONNECTED", "usable": False, "status_text": "",
        "stale": True, "age_s": None, "stale_after_s": DEFAULT_STALE_AFTER_S,
        "measurement_status": None, "distance_cm": None, "sensor_time": None,
        "value_text": None, "motion_text": "UNKNOWN", "reason": None,
        "thresholds_m": None, "sensor_id": None, "provenance": None,
        "robot_mode": None, "frame": None,
    }


def _classify(view: dict, *, valid: bool, mstatus: str | None, obstacle: str | None,
              motion_allowed, stale: bool, stale_after: float, age) -> None:
    """Fill status/usable/status_text/motion_text from the reading."""
    if stale:
        age_txt = f"{age:.1f} s old" if isinstance(age, (int, float)) else "age unknown"
        status, text = "UNKNOWN", f"stale ({age_txt}, limit {stale_after:g} s)"
    elif mstatus in NO_ECHO:
        status, text = "UNKNOWN", "unknown (no echo)"
    elif not valid or mstatus != "VALID" or view["distance_cm"] is None:
        status, text = "UNKNOWN", f"unknown ({mstatus or 'invalid reading'})"
    elif obstacle not in USABLE:
        status, text = "UNKNOWN", f"unknown ({(view['reason'] or obstacle or 'no assessment')})"
    elif motion_allowed is not True and obstacle != "BLOCKED":
        status, text = "UNKNOWN", "unknown (forward motion not allowed by ranging)"
    else:
        status, text = obstacle, obstacle.lower()
    view["status"], view["status_text"] = status, text
    view["usable"] = status in USABLE
    view["motion_text"] = "BLOCKED" if status == "BLOCKED" else (
        None if (status in ("CLEAR", "CAUTION") and motion_allowed is True) else "UNKNOWN")


def from_snapshot(snapshot: dict, *, now: float, fixture: bool,
                  robot: dict | None = None) -> dict:
    view = _base("FIXTURE" if fixture else "LIVE", hardware_verified(snapshot, robot))
    latest = snapshot.get("latest") or {}
    assess = snapshot.get("assessment") or {}
    stale_after = float(snapshot.get("stale_after_s") or DEFAULT_STALE_AFTER_S)
    stale, age = _freshness(snapshot.get("published_time"), stale_after, fixture,
                            snapshot.get("freshness"), now)
    dist = latest.get("distance_m")
    valid = latest.get("valid") is True and snapshot.get("valid") is not False
    cm = round(float(dist) * 100, 1) if (dist is not None and valid) else None
    hms = _utc_hms(latest.get("timestamp"))
    prov = snapshot.get("provenance") or {}
    view.update({
        "stale": stale, "age_s": age, "stale_after_s": stale_after,
        "measurement_status": latest.get("measurement_status"),
        "distance_cm": cm, "sensor_time": latest.get("timestamp"),
        "value_text": f"{cm:.0f} cm @ {hms}" if (cm is not None and hms) else None,
        "reason": assess.get("reason"),
        "thresholds_m": assess.get("thresholds") or (
            {"blocked_m": (snapshot.get("geometry") or {}).get("blocked_threshold_m"),
             "caution_m": (snapshot.get("geometry") or {}).get("caution_threshold_m")}
            if snapshot.get("geometry") else None),
        "sensor_id": snapshot.get("sensor_id"),
        "provenance": {k: prov.get(k) for k in ("source_mode", "platform", "driver",
                                                "wiring_verified_by", "service_boot_id")},
        "robot_mode": (robot or {}).get("mode"),
    })
    _classify(view, valid=valid, mstatus=latest.get("measurement_status"),
              obstacle=snapshot.get("obstacle_status"),
              motion_allowed=snapshot.get("forward_motion_allowed"),
              stale=stale, stale_after=stale_after, age=age)
    return view


def from_robot_status(robot: dict, *, now: float, fixture: bool) -> dict:
    """Fallback when only the robot API's ``forward_range`` is available.

    It has no obstacle assessment, so the best it can read is UNKNOWN with the
    value shown (greyed); it never reads CLEAR.
    """
    fr = robot.get("forward_range") or {}
    view = _base("FIXTURE" if fixture else "LIVE", hardware_verified(None, robot))
    ts = fr.get("sensor_timestamp")
    if fixture:
        stale, age = bool(fr.get("stale", True)), fr.get("age_s")
    else:
        stale, age = _freshness(_epoch(ts), DEFAULT_STALE_AFTER_S, False,
                                {"stale": fr.get("stale")}, now)
    cm = fr.get("distance_cm") if fr.get("validity") == "VALID" else None
    hms = _utc_hms(ts)
    view.update({
        "stale": stale, "age_s": age, "measurement_status": fr.get("validity"),
        "distance_cm": cm, "sensor_time": ts, "sensor_id": fr.get("sensor_id"),
        "value_text": f"{float(cm):.0f} cm @ {hms}" if (cm is not None and hms) else None,
        "reason": "robot API reading only (no obstacle assessment)",
        "provenance": {"source_mode": fr.get("sensor_source")},
        "robot_mode": robot.get("mode"),
    })
    _classify(view, valid=fr.get("validity") == "VALID", mstatus=fr.get("validity"),
              obstacle=None, motion_allowed=None, stale=stale,
              stale_after=DEFAULT_STALE_AFTER_S, age=age)
    return view


def disconnected(reason: str, *, source: str = "LIVE") -> dict:
    view = _base(source, False)
    view["status_text"] = f"disconnected ({reason})"
    view["reason"] = reason
    return view

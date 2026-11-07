"""Normalise an incoming observation to the §8.2 contract.

The bench camera (PR #3, perception/live_camera.py) prints observations without
``boot_id``, ``seq``, ``rx_time`` and ``stale_after_s``. Ingest fills them in:
``boot_id``/``seq`` are parsed from ``obs_id`` (``{drone}-{boot}-{seq:06d}``),
``rx_time`` is the base-station receive time, and the stale TTL comes from
the sensor (RGB 300 s, §9.6).
"""
from __future__ import annotations

import datetime as _dt
import re
import time

from contracts.camera_provenance import (CAPTURE_TIME_TOLERANCE_S, LOCAL, LOCAL_CLOCKS,
                                        LOCAL_TRANSPORTS, PI, PI_CLOCKS, PI_TRANSPORTS,
                                        camera_kind)

REQUIRED = ("obs_id", "drone_id", "source_mode", "sensor", "kind", "how", "cell", "obs_time")
SOURCE_MODES = {"SIMULATED", "RECORDED-IMAGERY", "LIVE-HW"}
PLATFORMS = {"SIM", "BENCH", "AIRCRAFT"}
HOWS = {"SECTOR_ONLY", "BEARING_ONLY", "GROUND_PLANE", "MULTI_VIEW"}
STALE_AFTER_S = {"rgb": 300.0, "ble": 120.0, "thermal": 300.0}
OBS_ID_RE = re.compile(r"^(?P<drone>[A-Za-z0-9]+)-(?P<boot>[A-Za-z0-9]+)-(?P<seq>\d{6})$")


COORDINATE_FIELDS = ("xy_m", "lat", "lon", "alt_m", "bearing_deg")


class InvalidObservation(ValueError):
    pass


def _check_camera(obs: dict, obs_time: float) -> None:
    """evidence.camera is optional; when present it must follow
    contracts/camera_provenance.py. Pi sightings are always bench, sector-only,
    operator-assigned, timed by the Pi, and obs_time IS the Pi capture time."""
    cam = (obs.get("evidence") or {}).get("camera")
    if cam is None:
        return
    if not isinstance(cam, dict):
        raise InvalidObservation("evidence.camera must be an object")
    kind = camera_kind(cam)
    if kind == LOCAL:
        if cam.get("transport") not in LOCAL_TRANSPORTS:
            raise InvalidObservation(f"local camera transport {cam.get('transport')!r}")
        if cam.get("capture_clock") not in LOCAL_CLOCKS:
            raise InvalidObservation(f"local camera capture_clock {cam.get('capture_clock')!r}")
        return
    if kind != PI:
        raise InvalidObservation(f"unknown evidence.camera.source {cam.get('source')!r}")
    need = {"source_mode": "LIVE-HW", "platform": "BENCH", "how": "SECTOR_ONLY",
            "cell_source": "OPERATOR_ASSIGNED"}
    bad = [f"{k}={obs.get(k)!r}" for k, v in need.items() if obs.get(k) != v]
    if cam.get("transport") not in PI_TRANSPORTS:
        bad.append(f"transport={cam.get('transport')!r}")
    if cam.get("capture_clock") not in PI_CLOCKS:
        bad.append(f"capture_clock={cam.get('capture_clock')!r} (must be the Pi's clock)")
    ct = cam.get("capture_time")
    try:
        ct = None if ct is None else float(ct)
    except (TypeError, ValueError):
        raise InvalidObservation("evidence.camera.capture_time must be a number") from None
    if ct is not None and abs(ct - obs_time) > CAPTURE_TIME_TOLERANCE_S:
        bad.append("obs_time is not the Pi capture time (evidence.camera.capture_time)")
    if bad:
        raise InvalidObservation("Pi camera sighting must be LIVE-HW/BENCH/SECTOR_ONLY/"
                                 "OPERATOR_ASSIGNED, timed by the Pi; got " + ", ".join(bad))


def normalise(obs: dict, *, known_cells, rx_time: float | None = None) -> dict:
    if not isinstance(obs, dict):
        raise InvalidObservation("observation must be a JSON object")
    missing = [k for k in REQUIRED if obs.get(k) in (None, "")]
    if missing:
        raise InvalidObservation("missing field(s): " + ", ".join(missing))
    m = OBS_ID_RE.match(str(obs["obs_id"]))
    if not m:
        raise InvalidObservation(f"obs_id {obs['obs_id']!r} is not {{drone}}-{{boot}}-{{seq:06d}}")
    if m["drone"] != obs["drone_id"]:
        raise InvalidObservation("obs_id drone does not match drone_id")
    if obs["source_mode"] not in SOURCE_MODES:
        raise InvalidObservation(f"unknown source_mode {obs['source_mode']!r}")
    if obs.get("platform") is not None and obs["platform"] not in PLATFORMS:
        raise InvalidObservation(f"unknown platform {obs['platform']!r}")
    if obs["how"] not in HOWS:
        raise InvalidObservation(f"unknown how {obs['how']!r}")
    if obs["cell"] not in set(known_cells):
        raise InvalidObservation(f"cell {obs['cell']!r} is not a sector cell on the trail map")
    try:
        obs_time = float(obs["obs_time"])
    except (TypeError, ValueError):
        raise InvalidObservation("obs_time must be a number (epoch seconds)") from None

    if obs.get("boot_id") is not None and obs["boot_id"] != m["boot"]:
        raise InvalidObservation("boot_id does not match obs_id")
    if obs.get("seq") is not None and obs["seq"] != int(m["seq"]):
        raise InvalidObservation("seq does not match obs_id")
    if obs.get("evidence") is not None and not isinstance(obs["evidence"], dict):
        raise InvalidObservation("evidence must be an object")

    if obs["how"] == "SECTOR_ONLY":
        coords = [k for k in COORDINATE_FIELDS if obs.get(k) is not None]
        if coords:
            raise InvalidObservation("SECTOR_ONLY sighting must not carry coordinates: "
                                     + ", ".join(coords))
    iso = obs.get("obs_time_iso")
    if iso is not None:
        try:
            iso_t = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
        except ValueError:
            raise InvalidObservation(f"obs_time_iso {iso!r} is not ISO-8601") from None
        if abs(iso_t - obs_time) > 1.0:
            raise InvalidObservation("obs_time_iso disagrees with obs_time")
    _check_camera(obs, obs_time)

    out = dict(obs)
    out["obs_time"] = obs_time
    out["boot_id"] = m["boot"]
    out["seq"] = int(m["seq"])
    out["rx_time"] = float(rx_time if rx_time is not None else time.time())
    out.setdefault("stale_after_s", STALE_AFTER_S.get(obs["sensor"], 300.0))
    return out

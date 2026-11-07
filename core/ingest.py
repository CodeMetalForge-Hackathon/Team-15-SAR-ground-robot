"""Normalise an incoming observation to the §8.2 contract.

The bench camera (PR #3, perception/live_camera.py) prints observations without
``boot_id``, ``seq``, ``rx_time`` and ``stale_after_s``. Ingest fills them in:
``boot_id``/``seq`` are parsed from ``obs_id`` (``{drone}-{boot}-{seq:06d}``),
``rx_time`` is the base-station receive time, and the stale TTL comes from
the sensor (RGB 300 s, §9.6).
"""
from __future__ import annotations

import re
import time

REQUIRED = ("obs_id", "drone_id", "source_mode", "sensor", "kind", "how", "cell", "obs_time")
SOURCE_MODES = {"SIMULATED", "RECORDED-IMAGERY", "LIVE-HW"}
PLATFORMS = {"SIM", "BENCH", "AIRCRAFT"}
HOWS = {"SECTOR_ONLY", "BEARING_ONLY", "GROUND_PLANE", "MULTI_VIEW"}
STALE_AFTER_S = {"rgb": 300.0, "ble": 120.0, "thermal": 300.0}
OBS_ID_RE = re.compile(r"^(?P<drone>[A-Za-z0-9]+)-(?P<boot>[A-Za-z0-9]+)-(?P<seq>\d{6})$")


class InvalidObservation(ValueError):
    pass


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

    out = dict(obs)
    out["obs_time"] = obs_time
    out.setdefault("boot_id", m["boot"])
    out.setdefault("seq", int(m["seq"]))
    out["rx_time"] = float(rx_time if rx_time is not None else time.time())
    out.setdefault("stale_after_s", STALE_AFTER_S.get(obs["sensor"], 300.0))
    return out

"""``evidence.camera``: which camera produced a sighting, and how it was timed.

This matches what perception/ emits since PR #3 ``4d3093d``
(``perception/pi_source.py`` ``PiCameraSource.camera_info()`` and
``perception/live_camera.py`` ``local_camera_info()``). The Pi stream's wire
format is private to ``perception/pi_source.py`` (sender and receiver live in
one file), so it is not part of this contract.

Kinds (decided from ``source``):
    PI     ``source`` starts with "pi"  e.g. "pi5-imx708" (board + sensor as the
           Pi reported them at connect time; "pi-unknown" if it didn't say)
    LOCAL  ``source == "local"``       the Mac's own camera (``device`` says which index)

Capture clocks:
    sensor                 Pi: picamera2 SensorTimestamp mapped to the Pi's NTP wall clock
    pi_wall_at_request     Pi: fallback when the sensor timestamp was missing/implausible
    receiver_wall_at_read  local: Mac clock when the frame was read

Rules the dashboard enforces (core/ingest.py):
- ``evidence.camera`` is optional (older sightings have none).
- PI sightings: LIVE-HW / BENCH / SECTOR_ONLY / OPERATOR_ASSIGNED, transport
  ``ssh-jpeg``, a Pi capture clock (never the receiver's), and when
  ``camera.capture_time`` is present it must equal ``obs_time`` (the sighting
  time IS the Pi capture time, not the Mac arrival time).
- LOCAL sightings: transport ``local``, clock ``receiver_wall_at_read``.
"""
from __future__ import annotations

PI, LOCAL = "PI", "LOCAL"
PI_TRANSPORTS = {"ssh-jpeg"}
LOCAL_TRANSPORTS = {"local"}
PI_CLOCKS = {"sensor": "Pi sensor timestamp (NTP-synced Pi clock)",
             "pi_wall_at_request": "Pi clock at frame request (sensor timestamp unavailable)"}
LOCAL_CLOCKS = {"receiver_wall_at_read": "Mac clock when the frame was read"}
CAPTURE_TIME_TOLERANCE_S = 0.002

KNOWN_PI_LABELS = {"pi5-imx708": "Raspberry Pi 5 IMX708 camera"}


def camera_kind(cam: dict | None) -> str | None:
    if not cam:
        return None
    src = str(cam.get("source") or "")
    if src == "local":
        return LOCAL
    if src.startswith("pi"):
        return PI
    return "UNKNOWN"


def camera_label(cam: dict | None) -> str:
    kind = camera_kind(cam)
    if kind is None:
        return "camera not reported"
    if kind == LOCAL:
        return "MacBook camera"
    if kind == PI:
        return KNOWN_PI_LABELS.get(cam["source"], f"Raspberry Pi camera ({cam['source']})")
    return f"unknown camera ({cam.get('source')})"


def clock_label(clock: str | None) -> str:
    return PI_CLOCKS.get(clock) or LOCAL_CLOCKS.get(clock) or "not reported"

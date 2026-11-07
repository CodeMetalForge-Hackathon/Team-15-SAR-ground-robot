"""Pi camera frame stream: wire format + camera provenance contract (T2-owned).

Standard library only, so it can be imported by perception/ (Mac side), by the
dashboard, and by tests. The Pi-side sender runs as a single script piped over
``ssh … python3 -`` and cannot import this module, so it must write exactly the
bytes described here; ``tests/e2e`` checks a reference sender against it.

Wire format (one record per frame, on the ssh stdout byte stream)
-----------------------------------------------------------------
    b"T15F" | uint32 big-endian H | H bytes header JSON (UTF-8) | uint32 big-endian J | J bytes JPEG

Header JSON fields:
    seq           int    0, 1, 2 … per stream (strictly increasing)
    capture_time  float  Unix epoch seconds of exposure, Pi wall clock mapped
                         from libcamera SensorTimestamp (CLOCK_BOOTTIME)
    sensor_ts_ns  int|null  raw SensorTimestamp
    sent_time     float  Pi wall clock just before the record was written
    w, h          int    size of the JPEG *after* rotation (1280 × 720)
    rotation      int    0 or 180; rotation was applied ON THE PI, so the JPEG
                         is already upright
    optional:     exposure_us, lux, host

Camera provenance: ``observation["evidence"]["camera"]``
--------------------------------------------------------
See ``camera_provenance()``. ``obs_time`` of a Pi sighting MUST be the
header ``capture_time`` of the evidence frame, never the Mac receive time.
"""
from __future__ import annotations

import json
import struct

MAGIC = b"T15F"
MAX_HEADER = 64 * 1024
MAX_JPEG = 16 * 1024 * 1024

PI5_IMX708 = "PI5_IMX708"
MAC_LOCAL = "MAC_LOCAL"
CAMERA_SOURCES = {
    PI5_IMX708: "Raspberry Pi 5 IMX708 camera",
    MAC_LOCAL: "MacBook camera",
}
TRANSPORTS = {"JPEG_OVER_SSH_TAILSCALE", "LOCAL"}
CAPTURE_CLOCKS = {"PI_SENSOR_TIMESTAMP_NTP", "MAC_WALL_CLOCK_AT_READ"}
REQUIRED_HEADER = ("seq", "capture_time", "w", "h", "rotation")


class StreamError(ValueError):
    pass


def encode_record(header: dict, jpeg: bytes) -> bytes:
    missing = [k for k in REQUIRED_HEADER if k not in header]
    if missing:
        raise StreamError("header missing " + ", ".join(missing))
    h = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return MAGIC + struct.pack(">I", len(h)) + h + struct.pack(">I", len(jpeg)) + jpeg


def _read_exact(stream, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return bytes(buf)


def read_record(stream) -> tuple[dict, bytes]:
    """Read one record from a binary stream. Raises EOFError at clean end."""
    magic = stream.read(4)
    if not magic:
        raise EOFError
    if len(magic) < 4:
        magic += _read_exact(stream, 4 - len(magic))
    if magic != MAGIC:
        raise StreamError(f"bad magic {magic!r}: stream out of sync")
    hlen = struct.unpack(">I", _read_exact(stream, 4))[0]
    if hlen > MAX_HEADER:
        raise StreamError(f"header too large ({hlen} bytes)")
    header = json.loads(_read_exact(stream, hlen))
    missing = [k for k in REQUIRED_HEADER if k not in header]
    if missing:
        raise StreamError("header missing " + ", ".join(missing))
    jlen = struct.unpack(">I", _read_exact(stream, 4))[0]
    if jlen > MAX_JPEG:
        raise StreamError(f"jpeg too large ({jlen} bytes)")
    return header, _read_exact(stream, jlen)


def camera_provenance(*, source: str, frame_size, rotation_deg: int = 0,
                      host: str | None = None, frame_seq: int | None = None,
                      capture_to_rx_s: float | None = None,
                      jpeg_quality: int | None = None) -> dict:
    """The ``evidence.camera`` object the camera puts in every sighting."""
    if source not in CAMERA_SOURCES:
        raise ValueError(f"unknown camera source {source!r}")
    pi = source == PI5_IMX708
    return {
        "source": source,
        "label": CAMERA_SOURCES[source],
        "device": "imx708" if pi else "cv2.VideoCapture",
        "host": host,
        "transport": "JPEG_OVER_SSH_TAILSCALE" if pi else "LOCAL",
        "capture_clock": "PI_SENSOR_TIMESTAMP_NTP" if pi else "MAC_WALL_CLOCK_AT_READ",
        "rotation_deg": int(rotation_deg),
        "frame_size": [int(frame_size[0]), int(frame_size[1])],
        "jpeg_quality": jpeg_quality,
        "frame_seq": frame_seq,
        "capture_to_rx_s": capture_to_rx_s,
    }

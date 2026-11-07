"""link/protocol.py — the exact bytes that fly between drones and the homebase.

    drone ESP32  --ESP-NOW-->  ESP32-S3 gateway  --USB serial-->  Jetson homebase
                 <--ESP-NOW--                    <--USB serial--  (waypoints back)

This file and firmware/t15_protocol.h describe the same format. If you change
one, change the other, then run `python tests/test_link.py` (it compiles the C
header and checks both sides agree byte for byte).

Packet (all little-endian):
    header   14 B  magic, version, type, flags, src, dst, seq(u32), t_ms(u32)
    payload   N B  depends on type (see the structs below)
    auth tag  8 B  only if flags & FLAG_AUTH: HMAC-SHA256(key, header+payload)[:8]
    crc16     2 B  CRC-16/CCITT-FALSE over everything before it

Serial framing between the S3 gateway and the Jetson:
    gateway -> Jetson : COBS(rssi_i8 + packet) + 0x00
    Jetson -> gateway : COBS(packet) + 0x00     (gateway broadcasts it over ESP-NOW)

Coordinates are metres in a local frame. The origin (0, 0) is the homebase,
where the AprilTag / UWB anchor lives. x = east, y = north, z = up.
"""
from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass
from typing import Optional, Union

MAGIC = 0xA5
VERSION = 1
HOME_ID = 0
BROADCAST = 0xFF

# message types
TELEMETRY = 1
DETECTION = 2
WAYPOINT = 3

FLAG_AUTH = 0x01
TAG_LEN = 8

# sensor ids (DETECTION.sensor) and capability bits (TELEMETRY.sensing)
SENSOR_IDS = {"thermal": 1, "cv": 2, "mmwave": 3, "ble": 4, "acoustic": 5}
SENSOR_NAMES = {v: k for k, v in SENSOR_IDS.items()}


def sensor_bit(name: str) -> int:
    return 1 << (SENSOR_IDS[name] - 1)


def mask_to_sensors(mask: int) -> list:
    return [n for n, i in SENSOR_IDS.items() if mask & (1 << (i - 1))]


# person status (DETECTION.status)
STATUS = {0: "unknown", 1: "ok", 2: "injured", 3: "critical"}
STATUS_IDS = {v: k for k, v in STATUS.items()}

# drone state (TELEMETRY.state)
STATE = {0: "landed", 1: "flying", 2: "holding", 3: "rtb", 4: "link_lost"}

# waypoint commands (WAYPOINT.cmd)
CMD_GOTO, CMD_HOLD, CMD_RTB, CMD_LAND = 0, 1, 2, 3
CMD = {0: "goto", 1: "hold", 2: "rtb", 3: "land"}

HDR = struct.Struct("<BBBBBBII")      # magic ver type flags src dst seq t_ms   = 14
TELEM = struct.Struct("<fffffBBBI")   # x y z yaw sigma batt state sensing wp_ack = 27
DET = struct.Struct("<ffBBBBBBHI")    # x y sensor conf status hr br range_dm det_id tag_id = 20
WP = struct.Struct("<ffffBBHI")       # x y z yaw cmd tx_period_ds det_ack wp_seq = 24

PAYLOAD = {TELEMETRY: TELEM, DETECTION: DET, WAYPOINT: WP}


@dataclass
class Telemetry:
    x: float
    y: float
    z: float
    yaw: float = 0.0
    sigma: float = 0.0          # 1-sigma position uncertainty, metres (VIO drift)
    battery: int = 255          # percent, 255 = unknown
    state: int = 1              # see STATE
    sensing: int = 0            # bitmask of sensors that were ON (for no-detection updates)
    wp_ack: int = 0             # wp_seq the drone is executing

    def pack(self) -> bytes:
        return TELEM.pack(self.x, self.y, self.z, self.yaw, self.sigma,
                          self.battery, self.state, self.sensing, self.wp_ack)


@dataclass
class Detection:
    x: float                    # estimated target position, metres
    y: float
    sensor: int                 # see SENSOR_IDS
    conf: int = 200             # 0..255  (255 = certain)
    status: int = 0             # see STATUS
    hr: int = 0                 # heart rate bpm, 0 = unknown
    br: int = 0                 # breaths per minute, 0 = unknown
    range_dm: int = 0           # range from drone in decimetres, 0 = unknown
    det_id: int = 0             # per-drone id for store-and-forward acks (1, 2, 3 ...)
    tag_id: int = 0             # ID beacon / ally tag, 0 = none

    def pack(self) -> bytes:
        return DET.pack(self.x, self.y, self.sensor, self.conf, self.status, self.hr,
                        self.br, self.range_dm, self.det_id, self.tag_id)


@dataclass
class Waypoint:
    x: float
    y: float
    z: float
    yaw: float = float("nan")   # NaN = keep current heading
    cmd: int = CMD_GOTO
    tx_period_ds: int = 5       # telemetry period in 0.1 s (5 = 2 Hz). EMCON knob.
    det_ack: int = 0            # highest contiguous det_id received from this drone
    wp_seq: int = 0             # changes only when the target changes

    def pack(self) -> bytes:
        return WP.pack(self.x, self.y, self.z, self.yaw, self.cmd,
                       self.tx_period_ds, self.det_ack, self.wp_seq)


Body = Union[Telemetry, Detection, Waypoint]
TYPE_OF = {Telemetry: TELEMETRY, Detection: DETECTION, Waypoint: WAYPOINT}
CLASS_OF = {TELEMETRY: Telemetry, DETECTION: Detection, WAYPOINT: Waypoint}


@dataclass
class Packet:
    type: int
    src: int
    dst: int
    seq: int
    t_ms: int
    flags: int
    body: Body


class PacketError(ValueError):
    pass


# ------------------------------------------------------------------ crc16
def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _tag(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()[:TAG_LEN]


# ------------------------------------------------------------- encode/decode
def encode(body: Body, src: int, dst: int, seq: int, t_ms: int = 0,
           key: Optional[bytes] = None) -> bytes:
    flags = FLAG_AUTH if key else 0
    mtype = TYPE_OF[type(body)]
    raw = HDR.pack(MAGIC, VERSION, mtype, flags, src, dst,
                   seq & 0xFFFFFFFF, t_ms & 0xFFFFFFFF) + body.pack()
    if key:
        raw += _tag(key, raw)
    return raw + struct.pack("<H", crc16(raw))


def decode(buf: bytes, key: Optional[bytes] = None, require_auth: bool = False) -> Packet:
    """Parse and check one packet. Raises PacketError on anything wrong.
    If `key` is given, a packet carrying a tag must verify. If `require_auth`,
    an untagged packet is rejected too (military mode)."""
    if len(buf) < HDR.size + 2:
        raise PacketError("short packet")
    body_and_hdr, crc_rx = buf[:-2], struct.unpack("<H", buf[-2:])[0]
    if crc16(body_and_hdr) != crc_rx:
        raise PacketError("bad crc")
    magic, ver, mtype, flags, src, dst, seq, t_ms = HDR.unpack_from(buf, 0)
    if magic != MAGIC or ver != VERSION:
        raise PacketError("bad magic/version")
    if mtype not in PAYLOAD:
        raise PacketError(f"unknown type {mtype}")
    st = PAYLOAD[mtype]
    want = HDR.size + st.size + (TAG_LEN if flags & FLAG_AUTH else 0) + 2
    if len(buf) != want:
        raise PacketError(f"length {len(buf)} != {want}")
    if flags & FLAG_AUTH:
        if key is None:
            if require_auth:
                raise PacketError("auth required but no key")
        else:
            signed = buf[:HDR.size + st.size]
            tag = buf[HDR.size + st.size:HDR.size + st.size + TAG_LEN]
            if not hmac.compare_digest(_tag(key, signed), tag):
                raise PacketError("bad auth tag")
    elif require_auth:
        raise PacketError("unauthenticated packet")
    body = CLASS_OF[mtype](*st.unpack_from(buf, HDR.size))
    return Packet(mtype, src, dst, seq, t_ms, flags, body)


class ReplayGuard:
    """Rejects packets whose seq is not newer than the last one from that sender.
    Drones persist their counter in flash, so it survives reboots."""

    def __init__(self):
        self.last = {}

    def ok(self, src: int, seq: int) -> bool:
        prev = self.last.get(src)
        if prev is not None and seq <= prev:
            return False
        self.last[src] = seq
        return True


# --------------------------------------------------------------------- COBS
def cobs_encode(data: bytes) -> bytes:
    """Standard COBS. Output never contains 0x00, so 0x00 can end a frame."""
    out = bytearray([0])
    code_idx, code = 0, 1
    for b in data:
        if b == 0:
            out[code_idx] = code
            code_idx, code = len(out), 1
            out.append(0)
        else:
            out.append(b)
            code += 1
            if code == 0xFF:
                out[code_idx] = code
                code_idx, code = len(out), 1
                out.append(0)
    out[code_idx] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    out = bytearray()
    idx = 0
    n = len(data)
    while idx < n:
        code = data[idx]
        if code == 0:
            raise PacketError("zero in COBS data")
        idx += 1
        end = idx + code - 1
        if end > n:
            raise PacketError("COBS overrun")
        out += data[idx:end]
        idx = end
        if code < 0xFF and idx < n:
            out.append(0)
    return bytes(out)


class FrameReader:
    """Feed raw serial bytes in, get whole COBS-decoded frames out."""

    def __init__(self, max_len: int = 512):
        self.buf = bytearray()
        self.max_len = max_len
        self.bad = 0

    def feed(self, data: bytes) -> list:
        frames = []
        for b in data:
            if b == 0:
                if self.buf:
                    try:
                        frames.append(cobs_decode(bytes(self.buf)))
                    except PacketError:
                        self.bad += 1
                self.buf.clear()
            else:
                self.buf.append(b)
                if len(self.buf) > self.max_len:
                    self.buf.clear()
                    self.bad += 1
        return frames


def frame(data: bytes) -> bytes:
    return cobs_encode(data) + b"\x00"


def load_key(path_or_text: Optional[str]) -> Optional[bytes]:
    """Key file holds the shared team secret as plain text (one line).
    The same text goes in firmware as T15_KEY."""
    if not path_or_text:
        return None
    try:
        with open(path_or_text, "rb") as f:
            return f.read().strip()
    except OSError:
        return path_or_text.encode()

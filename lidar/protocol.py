"""RPLIDAR serial protocol: request packets, response descriptors, measurement nodes.

Pure functions, no I/O. Source: SLAMTEC "RPLIDAR Interface Protocol and Application
Notes" and the BSD-2-Clause rplidar_sdk (sdk/include/sl_lidar_cmd.h). Only the legacy
commands are implemented:

    STOP 0x25, RESET 0x40, SCAN 0x20, GET_INFO 0x50, GET_HEALTH 0x52

UNVERIFIED ON OUR UNIT: the official SDK drives the C1 with its own scan modes. Whether
our C1M1-R2 answers the legacy SCAN (0x20) with standard 5-byte nodes at 460800 baud
must be confirmed at hardware stage C (LIDAR_C1_DRIVER.md section 5). Until then, every
hardware-mode claim in this package is "proposed", and the decoder is exercised only
against synthetic byte streams.

Standard measurement node (5 bytes):
    b0: quality(6) << 2 | !S << 1 | S     S = 1 on the first node of a new 360 deg revolution
    b1: angle_q6[6:0] << 1 | C           C (check bit) is always 1
    b2: angle_q6[14:7]                   angle_deg = angle_q6 / 64, clockwise seen from above
    b3,b4: distance_q2 (little endian)   distance_mm = distance_q2 / 4; 0 = no valid return
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

SYNC1 = 0xA5
SYNC2 = 0x5A

CMD_STOP = 0x25
CMD_RESET = 0x40
CMD_SCAN = 0x20
CMD_GET_INFO = 0x50
CMD_GET_HEALTH = 0x52

ANS_TYPE_MEASUREMENT = 0x81
ANS_TYPE_DEVINFO = 0x04
ANS_TYPE_DEVHEALTH = 0x06

NODE_LEN = 5
DESCRIPTOR_LEN = 7
INFO_LEN = 20
HEALTH_LEN = 3

HEALTH_GOOD, HEALTH_WARNING, HEALTH_ERROR = 0, 1, 2
HEALTH_NAMES = {HEALTH_GOOD: "GOOD", HEALTH_WARNING: "WARNING", HEALTH_ERROR: "ERROR"}


class ProtocolError(ValueError):
    """Bytes from the device did not match the protocol (corruption, wrong device, wrong baud)."""


def request(cmd: int) -> bytes:
    """Legacy commands carry no payload: A5 <cmd>."""
    if cmd not in (CMD_STOP, CMD_RESET, CMD_SCAN, CMD_GET_INFO, CMD_GET_HEALTH):
        raise ValueError(f"unsupported command 0x{cmd:02X}")
    return bytes((SYNC1, cmd))


@dataclass(frozen=True)
class Descriptor:
    length: int
    mode: int        # 0 = single response, 1 = multiple (streaming)
    data_type: int


def parse_descriptor(b: bytes) -> Descriptor:
    if len(b) != DESCRIPTOR_LEN:
        raise ProtocolError(f"descriptor needs {DESCRIPTOR_LEN} bytes, got {len(b)}")
    if b[0] != SYNC1 or b[1] != SYNC2:
        raise ProtocolError(f"bad descriptor sync {b[0]:02X} {b[1]:02X}")
    word = struct.unpack("<I", b[2:6])[0]
    return Descriptor(length=word & 0x3FFFFFFF, mode=word >> 30, data_type=b[6])


def build_descriptor(length: int, mode: int, data_type: int) -> bytes:
    """Encoder for tests and the mock serial device."""
    return bytes((SYNC1, SYNC2)) + struct.pack("<I", (length & 0x3FFFFFFF) | (mode << 30)) + bytes((data_type,))


@dataclass(frozen=True)
class Node:
    start_flag: bool     # first node of a new revolution
    quality: int         # 0-63 (6 bits)
    angle_deg: float     # sensor frame, clockwise from the sensor's own 0 mark
    distance_m: float    # 0.0 = no valid return (NOT "nothing there")


def decode_node(b: bytes) -> Node:
    """Decode one 5-byte node. Raises ProtocolError if the check bits are wrong."""
    if len(b) != NODE_LEN:
        raise ProtocolError(f"node needs {NODE_LEN} bytes, got {len(b)}")
    s = b[0] & 0x1
    not_s = (b[0] >> 1) & 0x1
    if s == not_s:
        raise ProtocolError("start-flag check failed (S == !S)")
    if (b[1] & 0x1) != 1:
        raise ProtocolError("check bit C is not 1")
    quality = b[0] >> 2
    angle_q6 = ((b[2] << 7) | (b[1] >> 1))
    dist_q2 = b[3] | (b[4] << 8)
    angle = angle_q6 / 64.0
    if angle >= 360.0:
        raise ProtocolError(f"angle {angle:.2f} deg out of range")
    return Node(start_flag=bool(s), quality=quality, angle_deg=angle, distance_m=dist_q2 / 4.0 / 1000.0)


def encode_node(angle_deg: float, distance_m: float, quality: int, start: bool) -> bytes:
    """Encoder for tests, fixtures and the mock device (never sent to hardware)."""
    q = max(0, min(63, int(quality)))
    a = int(round((angle_deg % 360.0) * 64.0)) & 0x7FFF
    if a >= 360 * 64:
        a = 0
    d = max(0, min(0xFFFF, int(round(distance_m * 1000.0 * 4.0))))
    s = 1 if start else 0
    return bytes(((q << 2) | ((1 - s) << 1) | s, ((a & 0x7F) << 1) | 1, a >> 7, d & 0xFF, d >> 8))


@dataclass(frozen=True)
class DeviceInfo:
    model: int
    firmware: str
    hardware: int
    serial_hex: str

    def to_dict(self) -> dict:
        return {"model": self.model, "firmware": self.firmware, "hardware": self.hardware,
                "serial": self.serial_hex}


def parse_info(b: bytes) -> DeviceInfo:
    if len(b) != INFO_LEN:
        raise ProtocolError(f"info needs {INFO_LEN} bytes, got {len(b)}")
    return DeviceInfo(model=b[0], firmware=f"{b[2]}.{b[1]:02d}", hardware=b[3], serial_hex=b[4:20].hex().upper())


@dataclass(frozen=True)
class Health:
    status: int
    error_code: int

    @property
    def name(self) -> str:
        return HEALTH_NAMES.get(self.status, f"UNKNOWN({self.status})")

    @property
    def good(self) -> bool:
        return self.status == HEALTH_GOOD

    def to_dict(self) -> dict:
        return {"status": self.name, "error_code": self.error_code}


def parse_health(b: bytes) -> Health:
    if len(b) != HEALTH_LEN:
        raise ProtocolError(f"health needs {HEALTH_LEN} bytes, got {len(b)}")
    return Health(status=b[0], error_code=b[1] | (b[2] << 8))


def find_node_alignment(buf: bytes) -> Optional[int]:
    """Offset (0..4) where two consecutive nodes decode cleanly, for resync after corruption."""
    for off in range(NODE_LEN):
        try:
            decode_node(buf[off:off + NODE_LEN])
            decode_node(buf[off + NODE_LEN:off + 2 * NODE_LEN])
            return off
        except ProtocolError:
            continue
    return None

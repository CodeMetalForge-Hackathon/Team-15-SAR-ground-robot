"""Turn the drone app's packets back into the scanner's own text lines.

firmware/crazyflie_scanner_app packs each scanner line into one app-channel
packet of at most 30 bytes. decode() rebuilds the line that Mabelle's
discovery server and BLE-ID checker already read, so neither needs a change.

What the drone keeps, and what it drops:
  heartbeat   kept as is (flags + millis)
  scan event  "#SCAN_END,..." / "#SCAN_ERROR,..." text, first 29 bytes
  token row   rssi + full 16-byte UUID; name cut to 11 bytes
  advert      rssi, address, type, name (cut to 19 bytes) and the Apple
              0x004C flag. Other advertising fields are not sent, because
              the discovery server only reads the name and that flag.
  #RAW, #CONFIG and other diagnostics stay on the drone.
"""
from __future__ import annotations

import struct

HEART, EVENT, TOKEN, ADVERT = ord("H"), ord("E"), ord("U"), ord("B")
KEEPALIVE = b"K"


def decode(pkt: bytes) -> str | None:
    """One app-channel packet -> one scanner line (no newline), or None."""
    if not pkt:
        return None
    kind = pkt[0]
    if kind == HEART and len(pkt) >= 10:
        flags = pkt[1]
        millis, = struct.unpack_from("<I", pkt, 2)
        line = f"#HEARTBEAT,scanning={flags & 1},millis={millis}"
        if flags & 2:
            line += ",passive=1"
        if flags & 4:
            line += ",discovery=1"
        return line
    if kind == EVENT and len(pkt) >= 2:
        return pkt[1:].decode("ascii", "replace")
    if kind == TOKEN and len(pkt) >= 19:
        rssi, = struct.unpack_from("b", pkt, 1)
        flags, n = pkt[18] & 0xE0, pkt[18] & 0x1F
        name = pkt[19:19 + n].decode("ascii", "replace")
        h = pkt[2:18].hex()
        uuid = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
        if flags & 0x20:
            uuid = uuid.upper()
        return f"{rssi},{name},{uuid}"
    if kind == ADVERT and len(pkt) >= 11:
        rssi, = struct.unpack_from("b", pkt, 1)
        address = ":".join(f"{b:02x}" for b in pkt[2:8])
        atype, flags, n = pkt[8], pkt[9], pkt[10]
        name = pkt[11:11 + n]
        payload = b""
        if name:
            payload += bytes([len(name) + 1, 8 if flags & 4 else 9]) + name
        if flags & 1:
            payload += b"\x03\xff\x4c\x00"
        return f"#BLE,{rssi},{address},{atype},{payload.hex().upper()}"
    return None


def drone_stats(pkt: bytes) -> dict | None:
    """Counters the drone sends with each heartbeat."""
    if len(pkt) >= 10 and pkt[0] == HEART:
        dropped, lines = struct.unpack_from("<HH", pkt, 6)
        return dict(dropped=dropped, lines=lines)
    return None


def focus_params(address: str | None) -> tuple[int, int]:
    """'aa:bb:cc:dd:ee:ff' -> (t15scan.focusA, t15scan.focusB); None clears focus."""
    if not address:
        return 0, 0
    b = bytes.fromhex(address.replace(":", ""))
    if len(b) != 6:
        raise ValueError("address must have 6 bytes")
    return int.from_bytes(b[:4], "big"), int.from_bytes(b[4:], "big")

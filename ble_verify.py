"""Pure verifier for OLF BLE-ID wire format v1 (SENSOR_ID_SPEC.md).

No I/O, no clock reads, no in-place mutation. ``verify`` returns a Decision and
the proposed next replay state; the caller persists that state (ble_state.py)
BEFORE emitting a verified observation.

Classification order (base spec, with the accepted alias-0 and reason labels):
  1. drop     not bytes, wrong length, unsupported version, reserved alias 0
  2. unknown  well-formed v1 payload whose alias is not enrolled
  3. forged   enrolled alias, HMAC tag does not match (regardless of time)
  4. replay   valid tag, counter outside the current window +/- 1: stale / future
  5. replay   counter <= that alias's high-water mark: duplicate / not_newer
     verified otherwise; only this outcome advances state
RSSI validation is the adapter's job (C3); this module never sees RSSI.
"""
from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

VERSION = 0x01
DOMAIN = b"OLF/BLE-ID/v1"
WINDOW_S = 30
PAYLOAD_LEN = 16
HEADER_LEN = 6
TAG_LEN = 10
KEY_LEN = 32
MAX_COUNTER = 0xFFFFFFFF

VERIFIED, REPLAY, FORGED, UNKNOWN, DROP = "verified", "replay", "forged", "unknown", "drop"


@dataclass(frozen=True)
class Decision:
    kind: str                      # verified | replay | forged | unknown | drop
    reason: str                    # diagnostic label, never a new kind
    alias: Optional[int] = None    # set only when the tag authenticated
    counter: Optional[int] = None  # set only when the tag authenticated


def counter_at(now: float) -> int:
    """Window counter for Unix time ``now`` (seconds). Raises on bad clocks."""
    if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
        raise ValueError("now must be a finite number of Unix seconds")
    if now < 0:
        raise ValueError("now is before the Unix epoch")
    c = math.floor(now / WINDOW_S)
    if c > MAX_COUNTER:
        raise OverflowError("counter does not fit in 32 bits")
    return c


def _check_key(alias: int, key: bytes) -> None:
    if not isinstance(alias, int) or isinstance(alias, bool) or not 1 <= alias <= 255:
        raise ValueError(f"enrolled alias must be 1..255, got {alias!r}")
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_LEN:
        raise ValueError(f"key for alias {alias} must be {KEY_LEN} bytes")


def _tag(key: bytes, header: bytes) -> bytes:
    return hmac.new(bytes(key), DOMAIN + header, hashlib.sha256).digest()[:TAG_LEN]


def make_token(key: bytes, counter: int, *, alias: int) -> bytes:
    """The 16-byte payload for ``alias`` at window ``counter``."""
    _check_key(alias, key)
    if not isinstance(counter, int) or isinstance(counter, bool) or not 0 <= counter <= MAX_COUNTER:
        raise OverflowError("counter must fit in an unsigned 32-bit integer")
    header = bytes([VERSION, alias]) + counter.to_bytes(4, "big")
    return header + _tag(key, header)


def _check_state(seen: Mapping[int, int]) -> None:
    for a, c in seen.items():
        if not isinstance(a, int) or isinstance(a, bool) or not 1 <= a <= 255:
            raise ValueError(f"replay state has invalid alias {a!r}")
        if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= MAX_COUNTER:
            raise ValueError(f"replay state has invalid counter for alias {a}")


def verify(payload, keys: Mapping[int, bytes], seen: Mapping[int, int], *,
           now: float) -> Tuple[Decision, Mapping[int, int]]:
    """Classify one received payload.

    Returns ``(decision, next_seen)``. ``next_seen`` is ``seen`` itself unless
    the decision is verified, in which case it is a new read-only mapping with
    that alias's high-water mark advanced. Bad configuration (keys, state, or
    clock) raises; bad input from the air never raises.
    """
    for a, k in keys.items():
        _check_key(a, k)
    _check_state(seen)
    current = counter_at(now)

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        return Decision(DROP, "type"), seen
    p = bytes(payload)
    if len(p) != PAYLOAD_LEN:
        return Decision(DROP, "length"), seen
    if p[0] != VERSION:
        return Decision(DROP, "unsupported_version"), seen
    alias = p[1]
    if alias == 0:
        return Decision(DROP, "reserved_alias"), seen
    key = keys.get(alias)
    if key is None:
        return Decision(UNKNOWN, "unenrolled_alias"), seen
    header, tag = p[:HEADER_LEN], p[HEADER_LEN:]
    if not hmac.compare_digest(_tag(key, header), tag):
        return Decision(FORGED, "bad_tag"), seen

    counter = int.from_bytes(header[2:6], "big")
    if counter < current - 1:
        return Decision(REPLAY, "stale", alias, counter), seen
    if counter > current + 1:
        return Decision(REPLAY, "future", alias, counter), seen
    high = seen.get(alias)
    if high is not None and counter <= high:
        reason = "duplicate" if counter == high else "not_newer"
        return Decision(REPLAY, reason, alias, counter), seen
    nxt = dict(seen)
    nxt[alias] = counter
    return Decision(VERIFIED, "fresh", alias, counter), MappingProxyType(nxt)

"""BLE status v2: signed SOS bit, 27-bit window and 4-bit update sequence.

Six header bytes + the unchanged 80-bit HMAC fit one 128-bit service UUID.
Replay state stores (window << 4) | sequence, separately from v1 state.
"""
from dataclasses import dataclass
import hashlib
import hmac
from types import MappingProxyType

from ble_verify import counter_at

DOMAIN = b'OLF/BLE-STATUS/v2'
MAX_WINDOW = (1 << 27)-1
MAX_ORDER = (1 << 31)-1


@dataclass(frozen=True)
class StatusDecision:
    kind: str
    reason: str
    alias: int | None = None
    counter: int | None = None
    revision: int | None = None
    sos: bool | None = None

    @property
    def order(self):
        return (self.counter << 4) | self.revision if self.counter is not None else None


def check_key(alias, key):
    if type(alias) is not int or not 1 <= alias <= 255 or not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise ValueError('Status keys require aliases 1..255 and 32-byte keys')


def make_status_token(key, counter, *, alias, revision, sos):
    check_key(alias, key)
    if type(counter) is not int or not 0 <= counter <= MAX_WINDOW or type(revision) is not int or not 0 <= revision <= 15 or type(sos) is not bool:
        raise ValueError('Invalid status window, revision or SOS bit')
    word = (counter << 5) | (revision << 1) | int(sos)
    header = bytes([2, alias]) + word.to_bytes(4, 'big')
    return header + hmac.new(bytes(key), DOMAIN+header, hashlib.sha256).digest()[:10]


def verify_status(payload, keys, seen, *, now):
    for alias, key in keys.items():
        check_key(alias, key)
    for alias, order in seen.items():
        if type(alias) is not int or not 1 <= alias <= 255 or type(order) is not int or not 0 <= order <= MAX_ORDER:
            raise ValueError('Invalid v2 replay state')
    current = counter_at(now)
    if current > MAX_WINDOW:
        raise ValueError('Status v2 time window overflow')
    if not isinstance(payload, (bytes, bytearray)) or len(payload) != 16:
        return StatusDecision('drop', 'length'), seen
    payload = bytes(payload)
    if payload[0] != 2:
        return StatusDecision('drop', 'unsupported_version'), seen
    alias = payload[1]
    if alias == 0:
        return StatusDecision('drop', 'reserved_alias'), seen
    if alias not in keys:
        return StatusDecision('unknown', 'unenrolled_alias'), seen
    tag = hmac.new(bytes(keys[alias]), DOMAIN+payload[:6], hashlib.sha256).digest()[:10]
    if not hmac.compare_digest(payload[6:], tag):
        return StatusDecision('forged', 'bad_tag'), seen
    word = int.from_bytes(payload[2:6], 'big')
    window, revision, sos = word >> 5, (word >> 1) & 15, bool(word & 1)
    fields = dict(alias=alias, counter=window, revision=revision, sos=sos)
    order = (window << 4) | revision
    if window < current-1:
        return StatusDecision('replay', 'stale', **fields), seen
    if window > current+1:
        return StatusDecision('replay', 'future', **fields), seen
    high = seen.get(alias)
    if high is not None and order <= high:
        return StatusDecision('replay', 'duplicate' if order == high else 'not_newer', **fields), seen
    next_seen = dict(seen)
    next_seen[alias] = order
    return StatusDecision('verified', 'fresh', **fields), MappingProxyType(next_seen)

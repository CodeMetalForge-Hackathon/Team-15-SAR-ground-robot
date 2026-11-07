"""C2: tampering, state poisoning, purity, and configuration errors."""
import builtins
import time
from types import MappingProxyType

import pytest

import ble_verify as bv
from ble_verify import counter_at, make_token, verify

NOW = 1794077187.0
N = counter_at(NOW)


def test_every_tag_bit_flip_is_forged_and_changes_nothing(keys):
    good = make_token(keys[1], N, alias=1)
    seen = MappingProxyType({1: N - 1})
    for i in range(6, 16):
        for bit in range(8):
            p = bytearray(good); p[i] ^= 1 << bit
            d, nxt = verify(bytes(p), keys, seen, now=NOW)
            assert (d.kind, d.reason, d.alias) == ("forged", "bad_tag", None)
            assert nxt is seen


def test_every_header_bit_flip_never_verifies(keys):
    good = make_token(keys[1], N, alias=1)
    for i in range(6):
        for bit in range(8):
            p = bytearray(good); p[i] ^= 1 << bit
            d, nxt = verify(bytes(p), keys, {}, now=NOW)
            assert d.kind in ("drop", "unknown", "forged"), (i, bit, d)
            assert nxt == {}


def test_negative_control_bypass_would_be_caught(keys, monkeypatch):
    """If tag checking were bypassed, a forged token would verify; prove the test notices."""
    forged = make_token(b"\xa5" * 32, N, alias=1)
    assert verify(forged, keys, {}, now=NOW)[0].kind == "forged"
    monkeypatch.setattr(bv.hmac, "compare_digest", lambda a, b: True)
    assert verify(forged, keys, {}, now=NOW)[0].kind == "verified"


def test_tag_comparison_uses_compare_digest(keys, monkeypatch):
    calls = []
    real = bv.hmac.compare_digest
    monkeypatch.setattr(bv.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    verify(make_token(keys[1], N, alias=1), keys, {}, now=NOW)
    assert calls == [1]


@pytest.mark.parametrize("make", [
    lambda k: make_token(b"\xa5" * 32, N + 1, alias=1),          # forged, high counter
    lambda k: make_token(b"\xa5" * 32, N + 1, alias=7),          # unknown alias
    lambda k: make_token(k[1], N + 1, alias=1)[:15],             # truncated
    lambda k: make_token(k[1], N + 2, alias=1),                  # authentic but future
    lambda k: make_token(k[1], N - 2, alias=1),                  # authentic but stale
])
def test_rejected_input_cannot_poison_state(make, keys):
    seen = {}
    d, nxt = verify(make(keys), keys, seen, now=NOW)
    assert d.kind != "verified" and nxt is seen and seen == {}
    d2, _ = verify(make_token(keys[1], N, alias=1), keys, nxt, now=NOW)
    assert d2.kind == "verified", "the genuine current token must still be accepted"


def test_aliases_are_isolated(keys):
    _, s = verify(make_token(keys[1], N + 1, alias=1), keys, {}, now=NOW)
    d, s = verify(make_token(keys[2], N, alias=2), keys, s, now=NOW)
    assert d.kind == "verified" and dict(s) == {1: N + 1, 2: N}


def test_state_is_shared_across_zones_in_one_process(keys):
    tok = make_token(keys[1], N, alias=1)
    _, shared = verify(tok, keys, {}, now=NOW)              # heard by the zone A receiver
    d, _ = verify(tok, keys, shared, now=NOW + 1)            # same token heard in zone B
    assert (d.kind, d.reason) == ("replay", "duplicate")


def test_verify_is_pure(keys, monkeypatch):
    seen = {1: N - 1}
    before = dict(seen)
    for name in ("time", "monotonic", "perf_counter"):
        monkeypatch.setattr(time, name, lambda: pytest.fail("verify read a clock"))
    monkeypatch.setattr(builtins, "open", lambda *a, **k: pytest.fail("verify did I/O"))
    d, nxt = verify(make_token(keys[1], N, alias=1), keys, seen, now=NOW)
    assert d.kind == "verified" and seen == before and nxt is not seen
    with pytest.raises(TypeError):
        nxt[1] = 0                                           # proposed state is read-only


@pytest.mark.parametrize("payload,reason", [
    (None, "type"), ("01010390", "type"), (12345, "type"), ([1] * 16, "type"),
    (b"", "length"), (b"\x01" * 15, "length"), (b"\x01" * 17, "length"),
])
def test_malformed_air_input_drops_without_raising(payload, reason, keys):
    d, nxt = verify(payload, keys, {}, now=NOW)
    assert (d.kind, d.reason) == ("drop", reason) and nxt == {}


def test_bytearray_and_memoryview_are_accepted(keys):
    tok = make_token(keys[1], N, alias=1)
    for p in (bytearray(tok), memoryview(tok)):
        assert verify(p, keys, {}, now=NOW)[0].kind == "verified"


@pytest.mark.parametrize("now", [float("nan"), float("inf"), -1.0, True, "1794077187"])
def test_bad_verifier_clock_fails_closed(now, keys):
    with pytest.raises(ValueError):
        verify(make_token(keys[1], N, alias=1), keys, {}, now=now)


@pytest.mark.parametrize("bad_keys", [{1: b"short"}, {0: b"\x00" * 32}, {256: b"\x00" * 32}])
def test_bad_key_configuration_raises(bad_keys, keys):
    with pytest.raises(ValueError):
        verify(make_token(keys[1], N, alias=1), bad_keys, {}, now=NOW)


@pytest.mark.parametrize("bad_seen", [{1: -1}, {1: 2 ** 32}, {0: 5}, {1: True}, {1: 1.0}])
def test_bad_state_raises(bad_seen, keys):
    with pytest.raises(ValueError):
        verify(make_token(keys[1], N, alias=1), keys, bad_seen, now=NOW)

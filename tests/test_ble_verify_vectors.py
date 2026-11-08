"""C2: the pure verifier against the fixed, independently generated C0 vectors."""
import hashlib

import pytest

from ble_verify import MAX_COUNTER, counter_at, make_token, verify
from conftest import VECTORS, VECTORS_SHA256, expected


def _load():
    import json
    return json.loads(VECTORS.read_bytes())


V = _load()


def test_reference_vector_file_is_unchanged():
    assert hashlib.sha256(VECTORS.read_bytes()).hexdigest() == VECTORS_SHA256


def _check(d, nxt, seen, label):
    kind, reason = expected(label)
    assert d.kind == kind, label
    if reason:
        assert d.reason == reason, label
    if kind == "verified":
        assert nxt[d.alias] == d.counter and nxt is not seen
    else:
        assert nxt is seen, "a non-verified decision must not propose new state"


@pytest.mark.parametrize("v", V["auth"], ids=[v["id"] for v in V["auth"]])
def test_authentication_vectors(v, keys):
    seen = {}
    d, nxt = verify(bytes.fromhex(v["payload_hex"]), keys, seen, now=V["now_unix_s"])
    _check(d, nxt, seen, v["expected"])


@pytest.mark.parametrize("v", V["freshness"], ids=[v["id"] for v in V["freshness"]])
def test_freshness_vectors(v, keys):
    seen = {}
    d, nxt = verify(bytes.fromhex(v["payload_hex"]), keys, seen, now=v["now_unix_s"])
    _check(d, nxt, seen, v["expected"])
    if d.kind in ("verified", "replay"):
        assert d.counter == v["counter"] and d.alias == 1


@pytest.mark.parametrize("s", V["sequences"], ids=[s["id"] for s in V["sequences"]])
def test_state_sequences(s, keys):
    seen = {}
    for step in s["steps"]:
        d, nxt = verify(bytes.fromhex(step["payload_hex"]), keys, seen, now=step["now_unix_s"])
        _check(d, nxt, seen, step["expected"])
        seen = nxt


def test_make_token_reproduces_every_authentic_vector(keys):
    authentic = [(1, v["counter"], v["payload_hex"]) for v in V["freshness"]]
    for s in V["sequences"]:
        authentic += [(st["alias"], st["counter"], st["payload_hex"]) for st in s["steps"]
                      if expected(st["expected"])[0] in ("verified", "replay")]
    assert len(authentic) >= 15
    for alias, counter, hexp in authentic:
        assert make_token(keys[alias], counter, alias=alias).hex() == hexp


def test_max_counter_vector_and_overflow(keys):
    assert make_token(keys[1], MAX_COUNTER, alias=1).hex() == V["boundary"]["max_counter"]["payload_hex"]
    with pytest.raises(OverflowError):
        make_token(keys[1], MAX_COUNTER + 1, alias=1)
    with pytest.raises(OverflowError):
        counter_at(V["boundary"]["make_token_at_unix_s"])


N = V["N"]


@pytest.mark.parametrize("now,offset,kind", [
    (30.0 * N, -1, "verified"),                 # first instant of window N
    (30.0 * N, -2, "replay"),
    (30.0 * N - 1e-3, -2, "verified"),          # last instant of window N-1
    (30.0 * (N + 1) - 1e-3, -1, "verified"),    # token about 59.999 s old: accepted
    (30.0 * (N + 1), -1, "replay"),             # same token at 60.000 s: stale
    (30.0 * N, +1, "verified"),
    (30.0 * N, +2, "replay"),
    (30.0 * (N + 1) - 1e-3, +2, "replay"),
    (30.0 * (N + 1), +2, "verified"),           # clock moved into window N+1
])
def test_window_edges(now, offset, kind, keys):
    d, _ = verify(make_token(keys[1], N + offset, alias=1), keys, {}, now=now)
    assert d.kind == kind


def test_freshness_is_not_an_exact_30_second_guarantee(keys):
    t0 = 30.0 * (N - 1)                         # token window N-1 starts here
    d, _ = verify(make_token(keys[1], N - 1, alias=1), keys, {}, now=30.0 * (N + 1) - 1e-3)
    assert d.kind == "verified" and (30.0 * (N + 1) - 1e-3) - t0 > 59.99


@pytest.mark.parametrize("jump,kind,reason", [
    (-300.0, "replay", "future"),               # verifier clock 5 min behind the phone
    (+300.0, "replay", "stale"),                # verifier clock 5 min ahead
    (-29.0, "verified", "fresh"),
])
def test_clock_skew_between_phone_and_verifier(jump, kind, reason, keys):
    d, _ = verify(make_token(keys[1], N, alias=1), keys, {}, now=30.0 * N + 15 + jump)
    assert (d.kind, d.reason) == (kind, reason)

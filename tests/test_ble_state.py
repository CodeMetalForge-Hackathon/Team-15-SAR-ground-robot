"""C2: durable replay state: restarts, corruption, atomicity (fails closed)."""
import json
import os
import stat

import pytest

import ble_state
from ble_state import StateError, init_state, load_state, save_state
from ble_verify import counter_at, make_token, verify

NOW = 1794077187.0
N = counter_at(NOW)
SCOPE = "mission-synthetic-test"


@pytest.fixture
def path(tmp_path):
    return tmp_path / "replay_state.json"


def test_first_use_requires_explicit_init(path):
    with pytest.raises(StateError, match="missing"):
        load_state(path, scope=SCOPE)
    assert dict(init_state(path, scope=SCOPE)) == {}
    assert dict(load_state(path, scope=SCOPE)) == {}
    with pytest.raises(StateError, match="already exists"):
        init_state(path, scope=SCOPE)                      # never silently reset


def test_round_trip_and_permissions(path):
    save_state(path, {1: N, 255: 7}, scope=SCOPE)
    assert dict(load_state(path, scope=SCOPE)) == {1: N, 255: 7}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_restart_keeps_replay_protection(path, keys):
    tok = make_token(keys[1], N, alias=1)
    seen = init_state(path, scope=SCOPE)
    d, nxt = verify(tok, keys, seen, now=NOW)
    assert d.kind == "verified"
    save_state(path, nxt, scope=SCOPE)                     # persist BEFORE emitting
    # --- verifier process restarts ---
    seen = load_state(path, scope=SCOPE)
    d, _ = verify(tok, keys, seen, now=NOW + 5)
    assert (d.kind, d.reason) == ("replay", "duplicate")
    d, _ = verify(make_token(keys[1], N + 1, alias=1), keys, seen, now=NOW + 30)
    assert d.kind == "verified"


def test_crash_before_persist_reaccepts_but_nothing_was_emitted(path, keys):
    """Persist-before-emit: a crash between verify and save emitted nothing, so the
    token being accepted again after restart cannot produce a double observation."""
    tok = make_token(keys[1], N, alias=1)
    seen = init_state(path, scope=SCOPE)
    verify(tok, keys, seen, now=NOW)                       # crash: state never saved
    d, _ = verify(tok, keys, load_state(path, scope=SCOPE), now=NOW)
    assert d.kind == "verified"


def test_failed_write_leaves_old_state_and_no_temp_files(path, monkeypatch):
    save_state(path, {1: N}, scope=SCOPE)
    monkeypatch.setattr(ble_state.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        save_state(path, {1: N + 5}, scope=SCOPE)
    assert dict(load_state(path, scope=SCOPE)) == {1: N}
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_leftover_temp_file_is_ignored(path):
    save_state(path, {1: N}, scope=SCOPE)
    (path.parent / f".{path.name}.abc.tmp").write_text("{partial")
    assert dict(load_state(path, scope=SCOPE)) == {1: N}


def test_wrong_scope_fails_closed(path):
    save_state(path, {1: N}, scope=SCOPE)
    with pytest.raises(StateError, match="scope"):
        load_state(path, scope="another-mission")


def _doc(path):
    return json.loads(path.read_text())


def _rewrite(path, edit):
    d = _doc(path); edit(d); path.write_text(json.dumps(d))


CORRUPTIONS = {
    "empty file": lambda p: p.write_bytes(b""),
    "truncated": lambda p: p.write_bytes(p.read_bytes()[:-20]),
    "not json": lambda p: p.write_bytes(b"\x00\xff garbage"),
    "json list": lambda p: p.write_text("[]"),
    "missing checksum": lambda p: _rewrite(p, lambda d: d.pop("sha256")),
    "checksum mismatch": lambda p: _rewrite(p, lambda d: d.update(sha256="0" * 64)),
    "edited counter, stale checksum": lambda p: _rewrite(p, lambda d: d["body"]["high_water"].update({"1": 1})),
    "extra field": lambda p: _rewrite(p, lambda d: d.update(note="x")),
    "wrong schema": lambda p: _rewrite(p, lambda d: d["body"].update(schema="v0")),
    "alias zero": lambda p: _rewrite(p, lambda d: d["body"]["high_water"].update({"0": 1})),
    "alias 256": lambda p: _rewrite(p, lambda d: d["body"]["high_water"].update({"256": 1})),
    "alias leading zero": lambda p: _rewrite(p, lambda d: d["body"]["high_water"].update({"01": 1})),
    "negative counter": lambda p: _rewrite(p, lambda d: d["body"]["high_water"].update({"2": -1})),
    "counter overflow": lambda p: _rewrite(p, lambda d: d["body"]["high_water"].update({"2": 2 ** 32})),
    "boolean counter": lambda p: _rewrite(p, lambda d: d["body"]["high_water"].update({"2": True})),
    "float counter": lambda p: _rewrite(p, lambda d: d["body"]["high_water"].update({"2": 1.0})),
    "high_water not object": lambda p: _rewrite(p, lambda d: d["body"].update(high_water=[1])),
    "oversized": lambda p: p.write_bytes(b" " * (ble_state.MAX_BYTES + 1)),
    "deleted": lambda p: p.unlink(),
}


@pytest.mark.parametrize("name", sorted(CORRUPTIONS))
def test_corrupt_or_lost_state_fails_closed(name, path):
    save_state(path, {1: N}, scope=SCOPE)
    CORRUPTIONS[name](path)
    with pytest.raises(StateError):
        load_state(path, scope=SCOPE)


@pytest.mark.parametrize("bad", [{0: 1}, {1: -1}, {1: 2 ** 32}, {1: True}])
def test_invalid_state_is_never_written(bad, path):
    with pytest.raises(StateError):
        save_state(path, bad, scope=SCOPE)
    assert not path.exists()

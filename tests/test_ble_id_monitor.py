"""C3 (SIMULATED inputs): adapter rules with injected clocks and no hardware."""
import json

import pytest

import ble_id
from ble_id import STALE_S, BeaconMonitor, OwnerError
from ble_keys import TEST_KEYS
from ble_sim import row
from ble_state import StateError, init_state, load_state
from ble_verify import counter_at, make_token

WALL0 = 1794077187.0
N = counter_at(WALL0)
SCOPE = "TESTKEY-unit"


class Clock:
    def __init__(self):
        self.wall, self.mono, self.ready = WALL0, 1000.0, True

    def tick(self, s):
        self.wall += s
        self.mono += s


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "state.json"
    init_state(path, scope=SCOPE)
    c = Clock()
    m = BeaconMonitor(TEST_KEYS, str(path), scope=SCOPE, mode="test-keys", source="SIMULATED",
                      receiver_ready=lambda: c.ready, wall=lambda: c.wall, mono=lambda: c.mono)
    return m, c, path


def tok(counter=N, alias=1, key=None, rssi=-60):
    return row(rssi, make_token(key or TEST_KEYS[alias], counter, alias=alias))


def test_verified_is_persisted_then_shown(env):
    m, c, path = env
    m.ingest(tok())
    assert dict(load_state(path, scope=SCOPE)) == {1: N}
    [s] = m.snapshot()["sightings"]
    assert (s["alias"], s["counter"], s["rssi"], s["verified_tokens"]) == (1, N, -60, 1)


def test_duplicates_neither_erase_nor_refresh_freshness(env):
    m, c, _ = env
    m.ingest(tok())
    c.tick(20)
    for _ in range(5):
        m.ingest(tok(rssi=-40))
    snap = m.snapshot()
    [s] = snap["sightings"]
    assert s["last_verified_age_s"] == 20.0 and s["rssi"] == -60 and s["verified_tokens"] == 1
    assert snap["counts"]["replay:duplicate"] == 5
    c.tick(STALE_S)
    assert m.snapshot()["sightings"][0]["stale"] is True        # kept, marked stale


@pytest.mark.parametrize("line,key", [
    (tok(key=b"\xa5" * 32), "forged:bad_tag"), (tok(alias=9, key=b"\xa5" * 32), "unknown:unenrolled_alias"),
    (tok(N - 2), "replay:stale"), (tok(N + 2), "replay:future"),
    ("garbage", "drop:framing"), (tok().upper(), "drop:framing"), (tok() + ",x", "drop:framing"),
    ("-500" + tok()[3:], "drop:rssi_out_of_range"), ("nan,," + tok()[5:], "drop:framing"),
    ("-60,NAME" + tok()[4:], "drop:name_present"), (tok()[:-1], "drop:framing"), ("-60,," + "0" * 36, "drop:framing"),
    ("x" * 300, "drop:framing"),
])
def test_rejected_input_stays_in_diagnostics(line, key, env):
    m, c, path = env
    m.ingest(line)
    snap = m.snapshot()
    assert snap["sightings"] == [] and snap["counts"] == {key: 1}
    assert dict(load_state(path, scope=SCOPE)) == {}
    m.ingest(tok())                                              # genuine token still accepted
    assert len(m.snapshot()["sightings"]) == 1


def test_unrelated_uuids_are_counted_not_listed(env):
    m, c, _ = env
    m.ingest("-70,,0000fe9f-0000-1000-8000-00805f9b34fb")
    snap = m.snapshot()
    assert snap["counts"] == {"drop:unsupported_version": 1} and snap["events"] == []


def test_comment_channels_ignored_and_receiver_gate(env):
    m, c, _ = env
    m.ingest("#BLE,-58,aa:bb:cc:dd:ee:ff,1,0201")
    c.ready = False
    m.ingest(tok())
    snap = m.snapshot()
    assert snap["counts"] == {"ignored:receiver_not_ready": 1} and snap["status"] == "receiver_unavailable"


def test_persistence_failure_withholds_result_and_halts(env, monkeypatch):
    m, c, path = env
    monkeypatch.setattr(ble_id, "save_state", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    m.ingest(tok())
    snap = m.snapshot()
    assert snap["sightings"] == [] and snap["status"] == "halted" and "withheld" in snap["detail"]
    m.ingest(tok(N + 1))
    assert m.snapshot()["counts"]["not_processed:halted"] == 1
    assert dict(load_state(path, scope=SCOPE)) == {}


@pytest.mark.parametrize("bad", [float("nan"), 0.0, 1_000_000_000.0, float("inf")])
def test_invalid_host_clock_halts(bad, env):
    m, c, _ = env
    c.wall = bad
    m.ingest(tok())
    assert m.snapshot()["status"] == "halted" and m.snapshot()["sightings"] == []


def test_restart_rejects_replay_and_lock_enforces_one_owner(env):
    m, c, path = env
    m.ingest(tok())
    with pytest.raises(OwnerError):
        BeaconMonitor(TEST_KEYS, str(path), scope=SCOPE, mode="test-keys", source="x", receiver_ready=lambda: True)
    import os
    os.close(m.owner)                                            # process exits
    m2 = BeaconMonitor(TEST_KEYS, str(path), scope=SCOPE, mode="test-keys", source="SIMULATED",
                       receiver_ready=lambda: True, wall=lambda: c.wall, mono=lambda: c.mono)
    m2.ingest(tok())
    assert m2.snapshot()["counts"] == {"replay:duplicate": 1} and m2.snapshot()["sightings"] == []


def test_missing_or_corrupt_state_fails_closed(tmp_path):
    p = tmp_path / "state.json"
    kw = dict(scope=SCOPE, mode="test-keys", source="x", receiver_ready=lambda: True)
    with pytest.raises(StateError, match="missing"):
        BeaconMonitor(TEST_KEYS, str(p), **kw)
    p.write_text("{corrupt")
    with pytest.raises(StateError, match="corrupt"):
        BeaconMonitor(TEST_KEYS, str(p), **kw)               # same process: lock was released
    init_state(tmp_path / "other.json", scope="TESTKEY-other")
    with pytest.raises(StateError, match="scope"):
        BeaconMonitor(TEST_KEYS, str(tmp_path / "other.json"), **kw)


def test_snapshot_exposes_no_key_material_or_addresses(env):
    m, c, _ = env
    m.ingest("#BLE,-58,aa:bb:cc:dd:ee:ff,1,0201")
    m.ingest(tok())
    text = json.dumps(m.snapshot())
    assert TEST_KEYS[1].hex() not in text and "aa:bb:cc" not in text

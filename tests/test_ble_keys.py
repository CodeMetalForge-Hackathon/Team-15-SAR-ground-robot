"""C3 (SIMULATED inputs): explicit key loading and test-key restrictions."""
import json
import os

import pytest

from ble_keys import (PUBLIC_SYNTHETIC, SIM_KEYS, TEST_KEYS, KeyConfigError, check_scope,
                      keys_for, load_production_keys)

SCOPE = "MISSION-ALPHA"
REAL = {"3": "7f" * 32, "4": "1e" * 31 + "20"}   # stand-ins for real random keys (not published)


def write(tmp_path, doc, mode=0o600):
    p = tmp_path / "keys.json"
    p.write_text(json.dumps(doc))
    os.chmod(p, mode)
    return p


def good(**over):
    return {"format": "olf-ble-id-keys/1", "scope": SCOPE, "keys": dict(REAL), **over}


def test_production_loads_explicit_file(tmp_path):
    keys = keys_for("production", scope=SCOPE, path=str(write(tmp_path, good())))
    assert sorted(keys) == [3, 4] and keys[3] == bytes.fromhex(REAL["3"])


def test_test_keys_match_the_published_c0_vectors(vec):
    assert TEST_KEYS[1].hex() == vec["keys_hex"]["1"] and TEST_KEYS[2].hex() == vec["keys_hex"]["2"]
    assert bytes.fromhex(vec["keys_hex"]["wrong"]) in PUBLIC_SYNTHETIC


@pytest.mark.parametrize("key", sorted(k.hex() for k in PUBLIC_SYNTHETIC))
def test_every_published_synthetic_key_is_refused_in_production(key, tmp_path):
    with pytest.raises(KeyConfigError, match="synthetic") as exc:
        load_production_keys(write(tmp_path, good(keys={"5": key})), scope=SCOPE)
    assert key not in str(exc.value)                      # never echo key material


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
def test_keys_file_must_be_owner_only(mode, tmp_path):
    with pytest.raises(KeyConfigError, match="chmod 600"):
        load_production_keys(write(tmp_path, good(), mode), scope=SCOPE)


@pytest.mark.parametrize("doc,match", [
    (good(scope="MISSION-OTHER"), "different"),
    (good(format="v0"), "format"),
    (good(keys={}), "no enrolled"),
    (good(keys={"0": REAL["3"]}), "invalid alias"),
    (good(keys={"256": REAL["3"]}), "invalid alias"),
    (good(keys={"03": REAL["3"]}), "invalid alias"),
    (good(keys={"3": REAL["3"].upper()}), "64 lowercase hex"),
    (good(keys={"3": REAL["3"][:-2]}), "64 lowercase hex"),
    (good(keys={"3": REAL["3"], "4": REAL["3"]}), "duplicates"),
    ({**good(), "note": "x"}, "exactly"),
    ([], "exactly"),
])
def test_bad_keys_files_are_refused(doc, match, tmp_path):
    with pytest.raises(KeyConfigError, match=match):
        load_production_keys(write(tmp_path, doc), scope=SCOPE)


def test_missing_or_non_json_keys_file(tmp_path):
    with pytest.raises(KeyConfigError, match="not found"):
        keys_for("production", scope=SCOPE, path=str(tmp_path / "nope.json"))
    p = tmp_path / "keys.json"
    p.write_text("{not json")
    os.chmod(p, 0o600)
    with pytest.raises(KeyConfigError, match="JSON"):
        keys_for("production", scope=SCOPE, path=str(p))


def test_production_never_falls_back_to_test_keys():
    with pytest.raises(KeyConfigError, match="requires --keys"):
        keys_for("production", scope=SCOPE)


@pytest.mark.parametrize("mode,scope,ok", [
    ("test-keys", "TESTKEY-bench", True), ("test-keys", "MISSION-ALPHA", False),
    ("simulated", "SIMULATED-x", True), ("simulated", "TESTKEY-x", False),
    ("production", "TESTKEY-x", False), ("production", "SIMULATED-x", False),
    ("production", "MISSION-ALPHA", True), ("demo", "MISSION-ALPHA", False), ("production", "", False),
])
def test_modes_and_scopes_cannot_mix(mode, scope, ok):
    if ok:
        check_scope(mode, scope)
    else:
        with pytest.raises(KeyConfigError):
            check_scope(mode, scope)


def test_test_and_sim_modes_use_built_in_keys_only(tmp_path):
    assert keys_for("test-keys", scope="TESTKEY-b") is TEST_KEYS
    assert keys_for("simulated", scope="SIMULATED-b") is SIM_KEYS
    assert set(SIM_KEYS.values()).isdisjoint(TEST_KEYS.values())
    with pytest.raises(KeyConfigError, match="do not pass --keys"):
        keys_for("test-keys", scope="TESTKEY-b", path=str(write(tmp_path, good())))

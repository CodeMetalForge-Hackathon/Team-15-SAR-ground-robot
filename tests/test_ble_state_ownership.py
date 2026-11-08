"""Regression: one owner per replay-state FILE, however its path is spelled.

Two separate OS processes. The first owns the state through its real path; the
second reaches the same file through a symlink (or another alias) and must be
refused before it processes a single token. SIMULATED input, no hardware.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ble_id import BeaconMonitor, OwnerError
from ble_keys import TEST_KEYS
from ble_sim import row
from ble_state import init_state, load_state
from ble_verify import counter_at, make_token

ROOT = Path(__file__).resolve().parents[1]
SCOPE = "TESTKEY-ownership"
COMMON = ("import sys, time; sys.path.insert(0, sys.argv[1])\n"
          "from ble_id import BeaconMonitor, OwnerError\nfrom ble_keys import TEST_KEYS\n"
          "kw = dict(scope=sys.argv[3], mode='test-keys', source='SIMULATED', receiver_ready=lambda: True)\n")
HOLDER = COMMON + ("m = BeaconMonitor(TEST_KEYS, sys.argv[2], **kw)\n"
                   "print('OWNED', flush=True)\nsys.stdin.read()\n")      # hold until stdin closes
SECOND = COMMON + ("from ble_sim import row\nfrom ble_verify import counter_at, make_token\n"
                   "try:\n    m = BeaconMonitor(TEST_KEYS, sys.argv[2], **kw)\n"
                   "except OwnerError as e:\n    print('REFUSED', e, flush=True); sys.exit(3)\n"
                   "m.ingest(row(-60, make_token(TEST_KEYS[1], counter_at(time.time()), alias=1)))\n"
                   "print('PROCESSED', m.snapshot()['counts'], flush=True)\n")


def second_process(path):
    return subprocess.run([sys.executable, "-c", SECOND, str(ROOT), str(path), SCOPE],
                          capture_output=True, text=True, timeout=60)


def start_holder(real):
    p = subprocess.Popen([sys.executable, "-c", HOLDER, str(ROOT), str(real), SCOPE],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "OWNED", p.stderr.read()
    return p


def stop_holder(p):
    p.stdin.close()
    assert p.wait(timeout=10) == 0


@pytest.fixture
def owned(tmp_path):
    real = tmp_path / "real" / "state.json"
    real.parent.mkdir()
    init_state(real, scope=SCOPE)
    p = start_holder(real)
    yield real
    stop_holder(p)


def alias(kind, real, tmp_path):
    if kind == "file symlink":
        (tmp_path / "link.json").symlink_to(real)
        return tmp_path / "link.json"
    if kind == "directory symlink":
        (tmp_path / "linkdir").symlink_to(real.parent, target_is_directory=True)
        return tmp_path / "linkdir" / "state.json"
    if kind == "dot-dot path":
        return real.parent / ".." / "real" / "state.json"
    return real                                            # identical spelling


@pytest.mark.parametrize("kind", ["file symlink", "directory symlink", "dot-dot path", "same path"])
def test_second_process_refused_before_processing_any_token(kind, owned, tmp_path):
    r = second_process(alias(kind, owned, tmp_path))
    assert r.returncode == 3 and r.stdout.startswith("REFUSED"), r.stdout + r.stderr
    assert "PROCESSED" not in r.stdout
    assert dict(load_state(owned, scope=SCOPE)) == {}      # nothing processed or saved


def test_lock_is_released_for_every_alias_when_the_owner_exits(tmp_path):
    real = tmp_path / "state.json"
    init_state(real, scope=SCOPE)
    link = alias("file symlink", real, tmp_path)
    holder = start_holder(real)
    assert second_process(link).returncode == 3
    stop_holder(holder)                                    # first owner exits
    r = second_process(link)
    assert r.returncode == 0 and r.stdout.startswith("PROCESSED"), r.stdout + r.stderr
    assert 1 in dict(load_state(real, scope=SCOPE))       # saved into the real file


def test_saving_through_a_symlink_updates_the_real_file_and_keeps_the_link(tmp_path):
    real = tmp_path / "state.json"
    init_state(real, scope=SCOPE)
    link = tmp_path / "link.json"
    link.symlink_to(real)
    m = BeaconMonitor(TEST_KEYS, str(link), scope=SCOPE, mode="test-keys", source="SIMULATED",
                      receiver_ready=lambda: True)
    n = counter_at(1794077187.0)
    m.wall = lambda: 1794077187.0
    m.ingest(row(-60, make_token(TEST_KEYS[1], n, alias=1)))
    assert dict(load_state(real, scope=SCOPE)) == {1: n}
    assert link.is_symlink() and m.path == os.path.realpath(real)
    os.close(m.owner)


def test_symlinked_lock_file_is_refused(tmp_path):
    real = tmp_path / "state.json"
    init_state(real, scope=SCOPE)
    (tmp_path / "elsewhere").write_text("")
    (tmp_path / "state.json.lock").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OwnerError, match="lock file"):
        BeaconMonitor(TEST_KEYS, str(real), scope=SCOPE, mode="test-keys", source="x", receiver_ready=lambda: True)


def test_hard_linked_state_is_rejected(tmp_path):
    real = tmp_path / "state.json"
    init_state(real, scope=SCOPE)
    os.link(real, tmp_path / "hard.json")
    for p in (real, tmp_path / "hard.json"):
        with pytest.raises(OwnerError, match="hard link"):
            BeaconMonitor(TEST_KEYS, str(p), scope=SCOPE, mode="test-keys", source="x", receiver_ready=lambda: True)

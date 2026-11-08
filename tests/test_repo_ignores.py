"""Repository hygiene: local secret-key files and replay state are ignored by Git,
while tracked evidence and code are not. Skips outside a Git checkout."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(),
                                reason="needs a Git checkout")


def ignored(path):
    return subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT).returncode == 0


@pytest.mark.parametrize("path", ["keys.json", "ble/keys.json", "olf-keys.json", "mission_keys.json",
                                  "prod.keys.json", "secrets/key.bin", "state.json.lock",
                                  "replay_state.simulated.json", "olf-MISSION-state.json"])
def test_local_secrets_and_state_are_ignored(path):
    assert ignored(path)


@pytest.mark.parametrize("path", ["evidence/c0-20261107T1914Z/protocol_vectors_v1.json",
                                  "ble_keys.py", "tests/test_ble_keys.py", "discovery/static/beacons.js"])
def test_tracked_evidence_and_code_are_not_ignored(path):
    assert not ignored(path)


def test_no_tracked_file_is_matched_by_ignore_rules():
    out = subprocess.run(["git", "ls-files", "-ci", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    assert out == ""

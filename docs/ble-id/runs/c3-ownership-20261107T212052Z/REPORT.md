# C3 review fix: replay-state ownership across symlinks and secret-key ignore rules

Run: `c3-ownership-20261107T212052Z` · November 7, 2026 · tested commits `acbb102`, `e3b5905`, `1c09ce5`
Kind of evidence: **SIMULATED / software regression only.**

| Gate | Status |
| --- | --- |
| C3 review finding: symlink / path-alias replay-state lock bypass fixed | **PASSED** (`acbb102`) |
| Two-process regression test with file symlink, directory symlink, `..` path, and hard links | **PASSED** (`tests/test_ble_state_ownership.py`, 8/8 passed; failed 4/7 pre-fix) |
| `.gitignore` rules for local secret-key files and replay state / locks | **PASSED** (`e3b5905`, `tests/test_repo_ignores.py`, 14/14 passed) |
| Full C1–C3 regression test suite | **PASSED** (`208 passed` in 8.95 s) |

## 1. What changed, and what can the user now observe?

A reviewer reproduced a replay-state ownership bypass in C3 (`f104439` / `4f63f0e`):
`acquire_owner()` locked `<supplied_path>.lock` before canonicalizing the state file path, so two separate processes opening the same replay-state file via its real path and a symlink acquired two different lock files and both accepted the same token as `verified:fresh`. In addition, `save_state()` replaced the symlink itself rather than updating the target file.

- **`ble_owner.py`** (46 lines) resolves the state path once with `os.path.realpath` (`canonical_state_path`), rejects hard-linked state files (`st_nlink > 1`), and opens `<canonical_path>.lock` with `O_NOFOLLOW` before taking an exclusive non-blocking `flock`.
- **`ble_id.py`** (135 lines) canonicalizes `state_path` at the start of `BeaconMonitor.__init__` and `init-state` so locking, loading, and saving all use the exact same canonical path, and closes the lock file descriptor if `load_state` raises.
- **`.gitignore`** ignores local production key files (`keys.json`, `*keys.json`, `*.keys.json`, `olf-keys*`, `secrets/`) and local runtime state (`*.json.lock`, `*replay_state*.json`, `olf-*-state.json`) without ignoring tracked code or evidence.

## 2. What did we actually try? (SIMULATED)

| Check | Commit | Command | Result |
| --- | --- | --- | --- |
| New ownership regression test on unfixed code (`4f63f0e`) | `4f63f0e` | `python -B -m pytest -v -p no:cacheprovider tests/test_ble_state_ownership.py` | **4 failed**, 3 passed (`prefix_regression_expected_fail.log`) |
| Ownership regression test after fix (`acbb102`) | `acbb102` | `python -B -m pytest -v -p no:cacheprovider tests/test_ble_state_ownership.py` | **8 passed**, exit 0 (`postfix_ownership_tests.log`) |
| Each commit on its own (`acbb102`, `e3b5905`, `1c09ce5`) | per-commit | `python -B -m pytest -q -p no:cacheprovider tests` | 194 passed → 208 passed → 208 passed (`per_commit_tests.log`) |
| Full suite verbose | `1c09ce5` | `python -B -m pytest -v -p no:cacheprovider tests` | **208 passed**, exit 0 (`postfix_full_suite_vm_py310.log`) |

## 3. Expected vs observed

| Test case | Expected | Observed pre-fix (`4f63f0e`) | Observed post-fix (`acbb102`) | Pass |
| --- | --- | --- | --- | --- |
| Second OS process opens state via file symlink | Refused (`OwnerError`, exit 3), 0 tokens processed | **Bypassed**: processed token (`verified:fresh: 1`) | Refused (`OwnerError`, exit 3), 0 tokens processed | PASS |
| Second OS process opens state via directory symlink | Refused (`OwnerError`, exit 3) | Refused | Refused | PASS |
| Second OS process opens state via `..` relative path | Refused (`OwnerError`, exit 3) | Refused | Refused | PASS |
| Second OS process opens state via identical path | Refused (`OwnerError`, exit 3) | Refused | Refused | PASS |
| First owner exits, then symlink process opens state | Lock released; second process succeeds and saves to real file | Failed | Lock released; real file updated | PASS |
| Saving through a symlink | Updates target file and preserves symlink | Replaced symlink with regular file | Target updated (`{1: 59802572}`), symlink preserved | PASS |
| Symlinked `.lock` file | Refused (`OwnerError`) | Not checked | Refused (`OwnerError`) | PASS |
| Hard-linked state file (`st_nlink > 1`) | Refused (`OwnerError`) | Accepted | Refused (`OwnerError`) | PASS |
| `.gitignore` check on 9 secret/state patterns & 4 tracked paths | All 9 ignored; 0 tracked files ignored | Not ignored | All 9 ignored; 0 tracked files ignored | PASS |

## 4. Where is the proof?

- [Pre-fix failure reproduction log](prefix_regression_expected_fail.log)
- [Post-fix ownership test log](postfix_ownership_tests.log)
- [Full 208-test suite log](postfix_full_suite_vm_py310.log)
- [Per-commit test log](per_commit_tests.log)
- [Commands and exit codes](commands.log), [environment](environment.txt), [SHA-256 manifest](MANIFEST.sha256)

## 5. What this establishes and what remains

- **Established (software):** Replay-state single-owner locking cannot be bypassed via file symlinks, directory symlinks, `..` traversal, symlinked `.lock` files, or hard links within the same filesystem mount. Local secret keys and replay state files are ignored by Git.
- **Out of scope:** The same file accessed across distinct filesystem mounts (bind mounts or network shares).

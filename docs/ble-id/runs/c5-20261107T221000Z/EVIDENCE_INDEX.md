# Evidence Index: Team-15 Authenticated BLE Sensor Module (C0–C5)

Branch: `culubo/sensor-id-specs` · Repository: `/Users/culubo/Team-15`

## 1. Description of Each C Checkpoint and Run Variant

- **C0 (`c0-20261107T1914Z`) — Baseline Inspection, Spec Amendment & Reference Vectors:**
  Inspected the actual repository and remote branches before implementation; documented that the base spec's assumed `forge/` and `Reading` types do not exist (`SENSOR_ID_SPEC_AMENDMENT_1.md`); wrote the hardware/software experiment plan (`EXPERIMENT_PLAN.md`); and generated 19 fixed authentication/freshness vectors plus 6 stateful sequences (`protocol_vectors_v1.json`, cross-checked with Python `hmac` and OpenSSL CLI).
- **C1 — Minimal Foreground iPhone-to-Passive-ESP32 Carrier Feasibility:**
  - **`c1-review-20261107T201136Z` (Hardware Build, Flash & Scanner Smoke Run):** Compiled and flashed passive NimBLE scanner firmware (`esp32:esp32:esp32c5:CDCOnBoot=cdc`) onto the ESP32-C5 rev 1.0, compiled and installed `ios/BeaconC1` (**OLF C1**) onto the iPhone 14 Pro (iOS 26.0), verified Swift CryptoKit vector A1 agreement, and captured a 5-second scanner heartbeat smoke test before iOS developer-profile trust was enabled.
  - **`c1-capture-20261107T202438Z` (Over-the-Air Radio Captures — Stopped, Static & Rotating):**
    - **Stage A (`capture_A_stopped.tsv`, 30 s):** Phone app stopped control (`29` heartbeats, `0` test-beacon rows).
    - **Stage B (`capture_B_static.tsv`, 60 s):** Phone advertising static vector A1 (`1,665` exact UUID rows and `1,665` matching `#RAW` advertisement byte rows).
    - **Stage C Attempt 1 (`attempt1_capture_C_rotating.tsv`, 120 s, FAILED & preserved):** Phone advertising 30 s rotating tokens; received `3,284` rows across 5 consecutive counters (`59802778`..`59802782`), but included 2 buffered static A1 rows and 2 fragments within `<0.5 ms` of serial open before the startup drain fix.
    - **Stage C Retry (`capture_C_rotating.tsv`, 120 s, PASSED at `1582429`):** Added a 2 s startup drain (`capture_C_rotating.tsv.warmup.txt`) and line alignment; received `3,273` valid rows across 5 consecutive counters (`59802784`..`59802788`) with `0` rejected rows.
- **C2 (`c2-20261107T204259Z`) — Pure Verifier & Atomic Replay State:**
  Implemented `ble_verify.py` (pure HMAC-SHA256 verification, ±1 window freshness, and per-alias high-water replay classification) and `ble_state.py` (atomic temp-file + fsync + `os.replace` persistence with SHA-256 integrity check and fail-closed loading). Verified with 104 tests across Linux VM and cloud environments, 10/10 deliberate bug mutations (`mutation_check.py`), and 1,200 deterministic E0 trials (`e0_experiment.py`).
- **C3 — Serial Adapter, Key Modes, Single-Owner Locking & Local Discovery/Verification Dashboard:**
  - **`c3-20261107T205707Z` (Simulated Serial-to-Browser Integration & Video Proof):** Added `ble_keys.py`, `ble_id.py`, `ble_sim.py`, and `discovery/beacons.py` + `beacons.js` so one serial reader serves both unverified discovery and authenticated beacon cards. Verified by 186 tests, 50-trial pty-to-API latency probes, and a 57.28 s headless Chrome video (`_media/c3/c3-software-proof-SIMULATED.mp4`).
  - **`c3-ownership-20261107T212052Z` (Symlink Lock-Bypass Fix & Secret Ignore Rules):** Fixed the C3 review finding where opening the same replay state via a symlink bypassed `<path>.lock`. Added `ble_owner.py` (`os.path.realpath` canonicalization, `O_NOFOLLOW`, hard-link rejection), 8 two-process ownership regression tests (`tests/test_ble_state_ownership.py`), and `.gitignore` rules for secret keys and replay state (`tests/test_repo_ignores.py`).
  - **`c3-native-20261107T212551Z`, `c3-native-20261107T212627Z`, `c3-native-20261107T212950Z` (Preserved Native Runner Setup Failures):** Documented and retained initial native macOS runner failures (Homebrew Python 3.15 missing `pip`, busy serial port `/dev/cu.usbmodem2101`, and macOS 26.1 `libexpat` incompatibility with Homebrew Python 3.13 `pyexpat`/`ensurepip`) before switching to SHA-256-verified pure-Python wheels (`fe7042a`).
  - **`c3-native-20261107T215002Z` & `c3-completion-20261107T215441Z` (Native macOS Test Suite & Live ESP32-C5 USB Scan):** Passed all `208` `pytest` tests and `8` `unittest` discovery tests natively on macOS 26.1 (Apple M4 Pro, Python 3.13.13), proved live symlink second-owner refusal against a running `discovery.server`, and recorded 120 s (`3,068` BLE advertisements) from `/dev/cu.usbmodem2101` (`sightings=[]` because the iPhone app was not broadcasting in Rotating mode during that window).
- **C4 (`c4-20261107T220500Z`) — Verifier Replay on C1 Hardware Captures, Aging/Recovery Verification & Live Hardware Runner:**
  Added `tools/c4/c4_analyze.py`, `tools/c4/run_c4.py`, and `tests/test_c4_analyze.py`. Replayed the real C1 hardware captures through `Discovery` + `BeaconMonitor` + `ble_state` (`c1_verifier_replay.json`: `0` rows in Stopped; `1,645 replay:stale` in Static A1 with state `{}`; `5 verified:fresh` and `3,240 replay:duplicate` in Rotating retry with `high_water={"1": 59802788}`), verified 70 s card staleness (`STALE_S = 70 s`) and receiver disconnect/reconnect recovery (`aging_and_recovery.json`), and prepared the interactive live runner for E2 (20 trials at 1 m without state resets), E3 (1 m, 3 m, 5 m, obstruction), and E4 (`foreground`, `background`, `locked`, `force_quit`).
- **C5 (`c5-20261107T221000Z`) — Clean-Checkout Reproduction, Video Decode Verification & Final Audit:**
  Added the zero-dependency standard-library audit runner `tools/c5/reproduce_c5.py` (`149` lines), verified all software tests, C1 pass/fail grading, C2 mutation and E0 experiments, C4 replay, `ffmpeg` full decode of `_media/c3/c3-software-proof-SIMULATED.mp4`, SHA-256 manifests, `<150`-line source bounds, and relative markdown links from a clean clone, and published [`README.md`](../../../../README.md) and [`REPORT.md`](REPORT.md).

## 2. Checkpoint Runs, Tested Commits, and Primary Artifacts

| Checkpoint / Run ID | Evidence Kind | Tested Commit | Directory / Primary Report | Key Artifacts & SHA-256 Manifests |
| --- | --- | --- | --- | --- |
| **C0** `c0-20261107T1914Z` | Baseline & Protocol Vectors | `4f181ae` | [`evidence/c0-20261107T1914Z/REPORT.md`](../../../../evidence/c0-20261107T1914Z/REPORT.md) | `protocol_vectors_v1.json` (`558467fdd4c0ee16e1f99d0a21b5c2bcecac2c9b63da075b68379b4dd6703899`), `EXPERIMENT_PLAN.md`, `OWNER_QUESTIONS.md` |
| **C1 Build** `c1-review-20261107T201136Z` | Build + Real Hardware Flash | `8c514f9` | [`docs/ble-id/runs/c1-review-20261107T201136Z/REPORT.md`](../c1-review-20261107T201136Z/REPORT.md) | [`manifest.json`](../c1-review-20261107T201136Z/manifest.json), `firmware-build-c5.log`, `firmware-upload.log`, `ios-build-final.log`, `ios-install-final.log`, `scanner-smoke.tsv` |
| **C1 Capture** `c1-capture-20261107T202438Z` | **REAL HARDWARE** Radio Captures | `8c514f9` (A/B & C attempt 1), `1582429` (C retry) | [`docs/ble-id/runs/c1-capture-20261107T202438Z/REPORT.md`](../c1-capture-20261107T202438Z/REPORT.md) | [`manifest.json`](../c1-capture-20261107T202438Z/manifest.json), `capture_A_stopped.tsv`, `capture_B_static.tsv`, `capture_C_rotating.tsv`, `attempt1_capture_C_rotating.tsv`, `c1_analysis.json`, `metrics.json` |
| **C2** `c2-20261107T204259Z` | SIMULATED / Software Verifier & State | `ec19d1a` | [`docs/ble-id/runs/c2-20261107T204259Z/REPORT.md`](../c2-20261107T204259Z/REPORT.md) | [`MANIFEST.sha256`](../c2-20261107T204259Z/MANIFEST.sha256), `pytest_vm_py310.log`, `pytest_cloud_py313.log`, `mutation_check.log`, `e0/e0_metrics.json` |
| **C3 Sim** `c3-20261107T205707Z` | SIMULATED Serial → Verifier → Browser + Video | `f104439` | [`docs/ble-id/runs/c3-20261107T205707Z/REPORT.md`](../c3-20261107T205707Z/REPORT.md) | [`MANIFEST.sha256`](../c3-20261107T205707Z/MANIFEST.sha256), `browser/browser_checks.json`, `latency/latency_vm_py310.json`, `_media/c3/c3-software-proof-SIMULATED.mp4` |
| **C3 Fix** `c3-ownership-20261107T212052Z` | Symlink Lock Bypass Fix & Ignore Rules | `acbb102`, `e3b5905`, `1c09ce5` | [`docs/ble-id/runs/c3-ownership-20261107T212052Z/REPORT.md`](../c3-ownership-20261107T212052Z/REPORT.md) | [`MANIFEST.sha256`](../c3-ownership-20261107T212052Z/MANIFEST.sha256), `prefix_regression_expected_fail.log`, `postfix_ownership_tests.log`, `postfix_full_suite_vm_py310.log` |
| **C3 Native Setup** `c3-native-212551Z` / `212627Z` / `212950Z` | Preserved Native Runner Setup Failures | `1c09ce5`, `2b7aca8` | [`c3-native-20261107T212551Z/`](../c3-native-20261107T212551Z/), [`212627Z/`](../c3-native-20261107T212627Z/), [`212950Z/`](../c3-native-20261107T212950Z/) | [`MANIFEST.sha256`](../c3-native-20261107T212551Z/MANIFEST.sha256), [`MANIFEST.sha256`](../c3-native-20261107T212627Z/MANIFEST.sha256), [`MANIFEST.sha256`](../c3-native-20261107T212950Z/MANIFEST.sha256), `pip.log`, `ensurepip.log`, `receiver.txt` |
| **C3 Native** `c3-native-20261107T215002Z` & `c3-completion-215441Z` | Native macOS 26.1 Suite + Live ESP32 USB Scan | `aadbdc7` | [`docs/ble-id/runs/c3-native-20261107T215002Z/REPORT.md`](../c3-native-20261107T215002Z/REPORT.md) | [`MANIFEST.sha256`](../c3-native-20261107T215002Z/MANIFEST.sha256), [`c3-completion MANIFEST.sha256`](../c3-completion-20261107T215441Z/MANIFEST.sha256), `pytest_native_macos.log` (208 passed), `second_owner_via_symlink.log`, `api_snapshots.jsonl`, `summary.txt` |
| **C4** `c4-20261107T220500Z` | C1 Hardware TSV Verifier Replay + Aging/Recovery + Live Runner | `ad4d419` | [`docs/ble-id/runs/c4-20261107T220500Z/REPORT.md`](../c4-20261107T220500Z/REPORT.md) | [`MANIFEST.sha256`](../c4-20261107T220500Z/MANIFEST.sha256), `c1_verifier_replay.json`, `aging_and_recovery.json`, `c4_analysis.json`, `pytest_sandbox_macos.log` |
| **C5** `c5-20261107T221000Z` | Clean-Checkout Reproduction & Final Audit | `10d6080` / `6ae87f7` | [`docs/ble-id/runs/c5-20261107T221000Z/REPORT.md`](REPORT.md) | [`MANIFEST.sha256`](MANIFEST.sha256), `c5_audit.json`, `pytest_clean_clone.log`, `c1_unittest_clean_clone.log`, `c2_mutation_clean_clone.log`, `c2_e0_clean_clone.log`, `video_check.txt`, `line_counts.txt` |

## 3. External Media Artifacts (Kept Outside Git per Spec)

| File Path | Kind | Format & Duration | SHA-256 Checksum | Status |
| --- | --- | --- | --- | --- |
| `_media/c3/c3-software-proof-SIMULATED.mp4` | SIMULATED Browser Proof (C3) | H.264 MP4, 1440×900, 57.28 s (1,135,313 bytes) | `6f4a2c1785d1ec3b0aea8311ae5c2193ba928ddbeef694a2d0f24b6e545f13aa` | **VERIFIED PLAYABLE (`ffmpeg` 0 decode errors)** |
| Filming phone camera roll (not yet copied to Mac) | Physical C1 Proof Video | N/A | N/A | **PENDING** (storage-constrained; not transferred/reviewed) |
| C2 standalone software screen clip | SIMULATED Screen Clip | N/A | N/A | **PENDING** |
| C4 physical experiments video | Physical C4 Proof Video | N/A | N/A | **UNTESTED / PENDING** |

## 4. Exact Reproduction Commands & Exit Codes

```sh
# 0. One-command zero-dependency C5 clean-checkout reproduction & audit (stdlib only):
/opt/homebrew/bin/python3.13 -B tools/c5/reproduce_c5.py
# Exit code: 0 (all_reproducible_checks_pass: true)

# 1. Native macOS full pytest suite (214 tests when run with ~/.olf-c3-pytest-python3.13):
PYTHONPATH="$HOME/.olf-c3-pytest-python3.13" /opt/homebrew/bin/python3.13 -B -m pytest -v -p no:cacheprovider tests
# Exit code: 0

# 2. Discovery unit tests (8 tests including pty and HTTP):
/opt/homebrew/bin/python3.13 -B -m unittest discover -s tests -p test_discovery.py -v
# Exit code: 0

# 3. C1 analyzer & serial capture unit tests (12 tests) and C1 hardware capture grading:
/opt/homebrew/bin/python3.13 -B -m unittest discover -s tools/c1 -p 'test_*.py' -v
/opt/homebrew/bin/python3.13 -B tools/c1/analyze_c1.py docs/ble-id/runs/c1-capture-20261107T202438Z
# Exit code: 0

# 4. C2 mutation check (10 deliberate bugs) and E0 software experiment (1,200 trials):
PYTHONPATH="$HOME/.olf-c3-pytest-python3.13" /opt/homebrew/bin/python3.13 -B tools/c2/mutation_check.py . /tmp/c2mut
/opt/homebrew/bin/python3.13 -I -B tools/c2/e0_experiment.py . /tmp/c2e0 100
# Exit code: 0

# 5. C3 live native macOS + iPhone-to-browser integration check:
bash tools/c3/native_macos_check.sh /dev/cu.usbmodem2101
# Exit code: 0 when iPhone OLF C1 app is running in foreground Rotating mode; 1 if no sightings arrive

# 6. C4 baseline verifier replay & interactive live hardware runner:
/opt/homebrew/bin/python3.13 -B tools/c4/run_c4.py baseline /tmp/c4-repro
/opt/homebrew/bin/python3.13 -B tools/c4/run_c4.py live --serial /dev/cu.usbmodem2101 --out docs/ble-id/runs/c4-live-$(date -u +%Y%m%dT%H%M%SZ)
```

# Evidence Index: Team-15 Authenticated BLE Sensor Module (C0–C5)

Branch: `culubo/sensor-id-specs` · Repository: `/Users/culubo/Team-15`

## 1. Checkpoint Runs, Tested Commits, and Primary Artifacts

| Checkpoint / Run ID | Evidence Kind | Tested Commit | Directory / Primary Report | Key Artifacts & SHA-256 Manifests |
| --- | --- | --- | --- | --- |
| **C0** `c0-20261107T1914Z` | Baseline & Protocol Vectors | `4f181ae` | [`evidence/c0-20261107T1914Z/REPORT.md`](../../../../evidence/c0-20261107T1914Z/REPORT.md) | `protocol_vectors_v1.json` (`27a27820be4f1983d82770bd794ff7bf7aa86dc8fc8d39278a472df5c8e35ef7`), `EXPERIMENT_PLAN.md`, `OWNER_QUESTIONS.md` |
| **C1 Build** `c1-review-20261107T201136Z` | Build + Real Hardware Flash | `8c514f9` | [`docs/ble-id/runs/c1-review-20261107T201136Z/REPORT.md`](../c1-review-20261107T201136Z/REPORT.md) | [`manifest.json`](../c1-review-20261107T201136Z/manifest.json), `firmware-build-c5.log`, `firmware-upload.log`, `ios-build-final.log`, `ios-install-final.log`, `scanner-smoke.tsv` |
| **C1 Capture** `c1-capture-20261107T202438Z` | **REAL HARDWARE** Radio Captures | `8c514f9` (A/B & C attempt 1), `1582429` (C retry) | [`docs/ble-id/runs/c1-capture-20261107T202438Z/REPORT.md`](../c1-capture-20261107T202438Z/REPORT.md) | [`manifest.json`](../c1-capture-20261107T202438Z/manifest.json), `capture_A_stopped.tsv`, `capture_B_static.tsv`, `capture_C_rotating.tsv`, `attempt1_capture_C_rotating.tsv`, `c1_analysis.json`, `metrics.json` |
| **C2** `c2-20261107T204259Z` | SIMULATED / Software Verifier & State | `ec19d1a` | [`docs/ble-id/runs/c2-20261107T204259Z/REPORT.md`](../c2-20261107T204259Z/REPORT.md) | [`MANIFEST.sha256`](../c2-20261107T204259Z/MANIFEST.sha256), `pytest_vm_py310.log`, `pytest_cloud_py313.log`, `mutation_check.log`, `e0/e0_metrics.json` |
| **C3 Sim** `c3-20261107T205707Z` | SIMULATED Serial → Verifier → Browser + Video | `f104439` | [`docs/ble-id/runs/c3-20261107T205707Z/REPORT.md`](../c3-20261107T205707Z/REPORT.md) | [`MANIFEST.sha256`](../c3-20261107T205707Z/MANIFEST.sha256), `browser/browser_checks.json`, `latency/latency_vm_py310.json`, `_media/c3/c3-software-proof-SIMULATED.mp4` |
| **C3 Fix** `c3-ownership-20261107T212052Z` | Symlink Lock Bypass Fix & Ignore Rules | `acbb102`, `e3b5905`, `1c09ce5` | [`docs/ble-id/runs/c3-ownership-20261107T212052Z/REPORT.md`](../c3-ownership-20261107T212052Z/REPORT.md) | [`MANIFEST.sha256`](../c3-ownership-20261107T212052Z/MANIFEST.sha256), `prefix_regression_expected_fail.log`, `postfix_ownership_tests.log`, `postfix_full_suite_vm_py310.log` |
| **C3 Native** `c3-native-20261107T215002Z` | Native macOS 26.1 Suite + Live ESP32 USB Scan | `aadbdc7` | [`docs/ble-id/runs/c3-native-20261107T215002Z/REPORT.md`](../c3-native-20261107T215002Z/REPORT.md) | [`MANIFEST.sha256`](../c3-native-20261107T215002Z/MANIFEST.sha256), `pytest_native_macos.log` (208 passed), `second_owner_via_symlink.log`, `api_snapshots.jsonl`, `summary.txt` |
| **C4** `c4-20261107T220500Z` | C1 Hardware TSV Verifier Replay + Aging/Recovery + Live Runner | `ad4d419` | [`docs/ble-id/runs/c4-20261107T220500Z/REPORT.md`](../c4-20261107T220500Z/REPORT.md) | [`MANIFEST.sha256`](../c4-20261107T220500Z/MANIFEST.sha256), `c1_verifier_replay.json`, `aging_and_recovery.json`, `c4_analysis.json`, `pytest_sandbox_macos.log` |
| **C5** `c5-20261107T221000Z` | Clean-Checkout Reproduction & Final Audit | `2584e60` | [`docs/ble-id/runs/c5-20261107T221000Z/REPORT.md`](REPORT.md) | [`MANIFEST.sha256`](MANIFEST.sha256), `pytest_clean_clone.log`, `c1_unittest_clean_clone.log`, `c2_mutation_clean_clone.log`, `c2_e0_clean_clone.log`, `line_counts.txt` |

## 2. External Media Artifacts (Kept Outside Git per Spec)

| File Path | Kind | Format & Duration | SHA-256 Checksum | Status |
| --- | --- | --- | --- | --- |
| `_media/c3/c3-software-proof-SIMULATED.mp4` | SIMULATED Browser Proof (C3) | H.264 MP4, 1440×900, 57.3 s (1,135,313 bytes) | `6f4a2c1785d1ec3b0aea8311ae5c2193ba928ddbeef694a2d0f24b6e545f13aa` | **VERIFIED PLAYABLE** |
| Filming phone camera roll (not yet copied to Mac) | Physical C1 Proof Video | N/A | N/A | **PENDING** (storage-constrained; not transferred/reviewed) |
| C2 standalone software screen clip | SIMULATED Screen Clip | N/A | N/A | **PENDING** |
| C4 physical experiments video | Physical C4 Proof Video | N/A | N/A | **UNTESTED / PENDING** |

## 3. Exact Reproduction Commands & Exit Codes

```sh
# 1. Native macOS full pytest suite (208 tests + 6 C4 grading tests = 214 tests when run with ~/.olf-c3-pytest-python3.13):
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

# C5 report: clean-checkout reproduction, operator handoff, and audit of all C0–C5 gates

Run: `c5-20261107T221000Z` · November 7, 2026 · MacBook Pro (Apple M4 Pro, macOS 26.1 Build 25B78)
Tested commit (isolated clean clone): `2584e60cbf777817e993b79ed60c4dc60be2361c` (`docs(ble-id): add root operator guide and update discovery README`)

## 1. Executive Gate Audit (PASSED / FAILED / UNTESTED / BLOCKED / UNSUPPORTED / STUB)

**This module is NOT fully complete and NOT production-ready.** While software verification, C1 foreground hardware transport, C3 symlink-ownership hardening, and native macOS test execution pass, physical phone-to-browser sighting in C3, physical C4 range/discovery/lifecycle experiments, physical video review, Keychain provisioning, and shared mission-dashboard posting remain incomplete or blocked.

| Gate | Status | Provenance (Software vs Physical) | Tested Commit & Run ID | Key Evidence & Honest Summary |
| --- | --- | --- | --- | --- |
| **1. Software Verifier, Replay State & Ownership** | **PASSED** | SIMULATED / Software (Linux VM, Cloud, Native macOS 26.1) | `2584e60` (`c5-20261107T221000Z`), `aadbdc7` (`c3-native-20261107T215002Z`), `ec19d1a` (`c2-20261107T204259Z`) | 208/208 `pytest` tests + 6/6 C4 grading tests + 12/12 C1 tests pass; 10/10 deliberate bugs caught; 1,200/1,200 E0 trials match expected decisions with 0 invalid verified events; `ble_owner.py` prevents symlink/hard-link lock bypasses across separate OS processes |
| **2. Exact ESP32-C5 & iOS Builds + Upload** | **PASSED** | BUILD + REAL HARDWARE | `8c514f9` (`c1-review-20261107T201136Z`) | `esp32:esp32:esp32c5:CDCOnBoot=cdc` compiled (751,965 B) & flashed to ESP32-C5 rev 1.0 (8 MB flash, ESP32 core 3.3.11, NimBLE-Arduino 2.5.1); `ios/BeaconC1` compiled & installed as **OLF C1** on iPhone 14 Pro (iOS 26.0) |
| **3. C1 Foreground Hardware Transport** | **PASSED** (attempt 1 **FAILED** & retained) | **REAL HARDWARE** (iPhone 14 Pro → passive ESP32-C5 over USB) | `1582429` (`c1-capture-20261107T202438Z`), re-verified through C3 `BeaconMonitor` at `ad4d419` (`c4-20261107T220500Z`) | Stopped: 0 rows in 30.005 s; Static A1: 1,665 exact rows in 60.001 s (`replay:stale` in C3 verifier, state unpoisoned); Rotating retry: 3,273 rows in 120.001 s across 5 consecutive 30 s counters (`59802784`..`59802788`), yielding 5 `verified:fresh` and 3,240 `replay:duplicate`. First rotating attempt failed due to 2 buffered static rows + 2 startup fragments before the 2 s startup drain fix and is retained |
| **4. C3 Local Dashboard Integration (Simulated & Live Receiver)** | **PASSED (SIMULATED)** · **INCOMPLETE (LIVE PHONE-TO-BROWSER)** | SIMULATED (`c3-20261107T205707Z`) + **REAL HARDWARE** USB scan (`c3-native-20261107T215002Z`) | `f104439` (`c3-20261107T205707Z`), `aadbdc7` (`c3-native-20261107T215002Z`), `351c4c4` (footer fix) | Single serial reader serves both discovery and verification. Simulated Chrome run passed 9/9 checks. Live native macOS run scanned 3,068 BLE advertisements from `/dev/cu.usbmodem2101` and refused a live second owner via symlink, **but** iPhone app was off so `/api/beacons` recorded `sightings=[]` |
| **5. Shared Mission Dashboard (`POST /observations`)** | **BLOCKED** | Spec / Teammate Contract | `4f181ae` (`evidence/c0-20261107T1914Z/REPORT.md`), [`SENSOR_ID_SPEC_AMENDMENT_1.md`](../../../SENSOR_ID_SPEC_AMENDMENT_1.md) | Base spec's `forge/` does not exist; `SENSOR_ID_SPEC_AMENDMENT_1.md` is still **PROPOSED** and blocked on Teammate T2 request R1 (`core/store.py` labels any posted observation as a person candidate and retargets routes) |
| **6. C4 Physical Radio, Distance, Discovery & Lifecycle Measurements** | **INCOMPLETE / UNTESTED** (software aging/recovery & C1 replay **PASSED**) | SIMULATED aging/recovery + C1 hardware TSV replay (`c4-20261107T220500Z`); physical E2/E3/E4 **UNTESTED** | `ad4d419` (`c4-20261107T220500Z`) | Verified-card aging (`STALE_S = 70 s`), duplicate non-refresh, and receiver disconnect/reconnect recovery verified in software; C4 runner (`tools/c4/run_c4.py`) and grader (`tools/c4/c4_analyze.py`) ready, but physical 20-trial E2 (1 m), E3 (1/3/5 m + obstruction), and E4 (lifecycle) captures have not been run |
| **7. Proof Videos** | **PARTIAL / INCOMPLETE** | Playable C3 software clip delivered; C1/C2/C4 clips **PENDING / UNTESTED** | `f104439` (`_media/c3/c3-software-proof-SIMULATED.mp4`) | Playable 57.3 s H.264 clip (`SHA-256: 6f4a2c17...`) proves simulated C3 flow (packet-loss phase covered by unit test rather than visual window change). C1 physical video remains on filming phone; C2 screen clip and C4 physical video are unrecorded |
| **8. Production Key Provisioning (iOS Keychain)** | **UNSUPPORTED / STUB** | Out of C1 App Scope | `ios/BeaconC1/BeaconC1/Token.swift` | Host `ble_keys.py` enforces production `keys.json` (`chmod 600`, rejects all 15 synthetic keys), but iPhone app hardcodes synthetic alias-1 test key and has no Keychain provisioning |
| **9. Background / Locked-Screen Advertising** | **UNSUPPORTED** | Platform & App Design | `ios/BeaconC1/BeaconC1/BeaconC1App.swift` | Baseline is foreground-only; `BeaconC1App.swift` calls `adv.stop()` on `.background`, and iOS moves background service UUIDs to the overflow area |

## 2. What Changed in C3–C5 and What We Reproduced From a Clean Checkout

From an isolated clean clone of `2584e60cbf777817e993b79ed60c4dc60be2361c`:

| Check | Command | Observed Result | Exit Code |
| --- | --- | --- | --- |
| Clean checkout status | `git status --short` | Empty (`''`) | `0` |
| Handwritten file line-count audit (`< 150` lines) | `wc -l ble_*.py discovery/beacons.py discovery/static/*.js firmware/esp32_scanner/*.ino ios/BeaconC1/BeaconC1/*.swift tools/c4/*.py tests/*.py` | Every handwritten BLE-ID module, script, Swift/ino file, and test file is **≤ 149 lines** (`line_counts.txt`) | `0` |
| Full non-socket test suite (C2 + C3 + C4) | `python3.13 -B -m pytest tests/test_ble_id_monitor.py tests/test_ble_keys.py tests/test_ble_state.py tests/test_ble_state_ownership.py tests/test_ble_verify_properties.py tests/test_ble_verify_vectors.py tests/test_repo_ignores.py tests/test_c4_analyze.py` | **201 passed, 0 failed** (`pytest_clean_clone.log`; full 208-test suite including 7 socket tests verified in [`c3-native-20261107T215002Z/pytest_native_macos.log`](../c3-native-20261107T215002Z/pytest_native_macos.log) & [`c3-completion-20261107T215441Z/pytest_native_macos.log`](../c3-completion-20261107T215441Z/pytest_native_macos.log)) | `0` |
| C1 analyzer & serial capture tests | `python3.13 -B -m unittest discover -s tools/c1 -p 'test_*.py' -v` | **12 passed** (`c1_unittest_clean_clone.log`) | `0` |
| C2 mutation check (10 deliberate bugs) | `python3.13 -B tools/c2/mutation_check.py . <tmp>` | **10/10 mutants caught** (`c2_mutation_clean_clone.log`) | `0` |
| C2 E0 deterministic software experiment | `python3.13 -I -B tools/c2/e0_experiment.py . <tmp> 100` | **1,200/1,200 classified as expected; 0 invalid verified**; `verify()` latency p50 = **2.8 µs**, p95 = **3.2 µs** on Apple M4 Pro (`c2_e0_clean_clone.log`) | `0` |
| JS & shell syntax checks | `node --check discovery/static/app.js && node --check discovery/static/beacons.js && bash -n tools/c1/run_c1.sh tools/c1/capture_serial.sh tools/c3/native_macos_check.sh` | All syntax checks OK | `0` |
| C3 software proof video integrity | `shasum -a 256 _media/c3/c3-software-proof-SIMULATED.mp4` | `6f4a2c1785d1ec3b0aea8311ae5c2193ba928ddbeef694a2d0f24b6e545f13aa` (matches C3 manifest) | `0` |

## 3. Genuine Measurements in Ordinary Language

1. **How fast does the verifier check a token in software? (`E0`, SIMULATED)**
   - Boundary: a single Python call to `verify(payload, keys, seen, now=...)` using `time.perf_counter_ns()`, excluding 10 warmup calls, USB serial reading, disk writes, and radio propagation.
   - Result: **2.8 µs median (p50)** and **3.2 µs 95th percentile (p95)** across 1,300 calls on the MacBook Pro (Apple M4 Pro, Python 3.13.13), and **3.2 µs p50 / 5.1 µs p95** on the Linux VM (Python 3.10.12). All 1,200 deterministic trials across 12 valid, replay, forged, unknown, and malformed classes produced the exact expected decision with zero false verifications.
2. **How fast does a serial line become visible on the local HTTP API? (`C3`, SIMULATED)**
   - Boundary: writing one authenticated CSV line into a pseudo-terminal (`os.write`) → `serial_worker` line framing → `Discovery.ingest` → `BeaconMonitor.ingest` → `verify()` → atomic `save_state()` with `fsync` → `/api/beacons` HTTP JSON response (polled every 5 ms; excludes radio, ESP32, physical USB, and the browser's 1-second poll timer).
   - Result: **50/50 trials succeeded**; **7.9 ms p50**, **13.7 ms p95**, **17.6 ms max** on the Mac Linux VM (`c3-20261107T205707Z/latency/latency_vm_py310.json`), and **3.0 ms p50**, **4.8 ms p95**, **9.1 ms max** on the cloud host.
3. **What happened over the air with the real iPhone 14 Pro and passive ESP32-C5? (`C1` + `C3` + `C4`, REAL HARDWARE)**
   - **Stopped control (`30.005 s`):** 29 scanner heartbeats, **0** test-beacon rows received (`rssi_dbm: null`).
   - **Static vector A1 (`60.001 s`):** **1,665** exact UUID receptions (`01010390-83cc-c438-cfa7-043609b9d1c4`) and 1,665 matching `#RAW` advertisement byte rows (`c4d1b909...030101`). Replayed through `BeaconMonitor`, all 1,645 post-heartbeat rows authenticated with alias 1's key and were rejected as `replay:stale` (because static counter `59802572` was ~106 minutes old), leaving replay state `{}` unpoisoned. RSSI: **min -99 dBm, p10 -84 dBm, median -80 dBm, p90 -78 dBm, max -76 dBm**.
   - **Rotating token stage (`120.001 s`, retry after 2 s startup drain fix):** **3,273** authenticated receptions across **5 consecutive 30-second counters** (`59802784`..`59802788`) with 0 invalid HMAC tags. Replayed through `BeaconMonitor`, the first post-heartbeat reception in each of the 5 windows was accepted as **`verified:fresh` (5 total)** and saved to disk (`high_water = {1: 59802788}`), while the remaining **3,240** repeated advertisements in those windows were classified as **`replay:duplicate`** without refreshing card age. RSSI: **min -99 dBm, p10 -88 dBm, median -86 dBm, p90 -83 dBm, max -74 dBm** (unmeasured bench distance; RSSI is not a distance measurement).
   - **Live ESP32-C5 USB discovery + symlink lock check (`120 s`, `c3-native-20261107T215002Z`):** Over 60 two-second `/api/beacons` snapshots on native macOS 26.1, the passive ESP32-C5 on `/dev/cu.usbmodem2101` processed **3,068** ambient BLE advertisements (`malformed = 0`), refused a live second server process attempting to open the active replay state through a symlink (`exit=1`), and reported `sightings = []` because the iPhone app was not broadcasting in Rotating mode during that window.

## 4. Proof & Evidence Index

- See [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) in this directory for the complete index of all C0–C5 runs, commands, exit codes, tested commits, and artifact SHA-256 checksums.
- Local files in this C5 run:
  - [`environment.txt`](environment.txt), [`commands.log`](commands.log), [`line_counts.txt`](line_counts.txt)
  - [`pytest_clean_clone.log`](pytest_clean_clone.log), [`c1_unittest_clean_clone.log`](c1_unittest_clean_clone.log)
  - [`c2_mutation_clean_clone.log`](c2_mutation_clean_clone.log), [`c2_e0_clean_clone.log`](c2_e0_clean_clone.log)
  - [`video_check.txt`](video_check.txt), [`MANIFEST.sha256`](MANIFEST.sha256)

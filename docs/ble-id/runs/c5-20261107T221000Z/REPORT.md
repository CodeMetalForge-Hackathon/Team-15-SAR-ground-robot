# C5 report: clean-checkout reproduction, operator handoff, and audit of all C0–C5 gates

Run: `c5-20261107T221000Z` · November 7, 2026 · MacBook Pro (Apple M4 Pro, macOS 26.1 Build 25B78)
Tested commit (isolated clean clone): `10d6080925a3f18d9f887390dc2a282f94ba207d` (`feat(ble-id): add zero-dependency C5 clean-checkout reproduction and audit tool`)

**Overall Completion Status: INCOMPLETE (Software, Builds, and C1 Foreground Transport PASSED; Live Phone-to-Browser Sighting, Physical C4 Distance/Discovery/Lifecycle Runs, Shared Mission Integration, and Physical Proof Videos PENDING/BLOCKED).**

| Completion Gate (`SENSOR_ID_SPEC.md`) | Status | Evidence Kind | Tested Commit & Run ID | Key Evidence & Honest Summary |
| --- | --- | --- | --- | --- |
| **(1) Software verified** | **PASSED** | SIMULATED / Software (Linux VM, Cloud, Native macOS 26.1) | [`c2-20261107T204259Z/REPORT.md`](../c2-20261107T204259Z/REPORT.md) (`ec19d1a`), [`c3-ownership-20261107T212052Z/REPORT.md`](../c3-ownership-20261107T212052Z/REPORT.md) (`1c09ce5`), this run (`10d6080`) | 214/214 tests pass (211 in zero-dependency clean-clone runner + 3 loopback HTTP socket tests verified in [`c3-native-20261107T215002Z/pytest_native_macos.log`](../c3-native-20261107T215002Z/pytest_native_macos.log)); 10/10 deliberate bugs caught; 1,200/1,200 E0 trials (`verify()` p50 `2.8 µs` M4 Pro / `3.2 µs` VM); `ble_owner.py` prevents symlink/hard-link lock bypasses |
| **(2) Exact ESP32 and iOS builds verified** | **PASSED** | BUILD + REAL HARDWARE | [`c1-review-20261107T201136Z/REPORT.md`](../c1-review-20261107T201136Z/REPORT.md) (`8c514f9`) | `esp32:esp32:esp32c5:CDCOnBoot=cdc` compiled (751,965 B) & flashed to ESP32-C5 rev 1.0 (8 MB flash, ESP32 core 3.3.11, NimBLE-Arduino 2.5.1); `ios/BeaconC1` compiled & installed as **OLF C1** on iPhone 14 Pro (iOS 26.0) |
| **(3) Foreground hardware verified** | **PASSED** (attempt 1 **FAILED** & retained) | **REAL HARDWARE** (iPhone 14 Pro → passive ESP32-C5 over USB) | [`c1-capture-20261107T202438Z/REPORT.md`](../c1-capture-20261107T202438Z/REPORT.md) (`1582429`), [`c4-20261107T220500Z/REPORT.md`](../c4-20261107T220500Z/REPORT.md) (`ad4d419`) | Stopped: 0 rows in 30.005 s; Static A1: 1,665 exact rows in 60.001 s (`replay:stale` in C3 verifier, state unpoisoned); Rotating retry: 3,273 rows in 120.001 s across 5 consecutive 30 s counters (`59802784`..`59802788`), yielding 5 `verified:fresh` and 3,240 `replay:duplicate`. First rotating attempt failed due to 2 buffered static rows + 2 startup fragments before the 2 s startup drain fix and is retained |
| **(4) Integration verified** | **PARTIAL**: Local dashboard **PASSED (SIMULATED)** & **LIVE USB SCAN PASSED**; Live iPhone-to-browser sighting **UNTESTED**; Shared mission dashboard **BLOCKED** | SIMULATED (`c3-20261107T205707Z`) + **REAL HARDWARE** USB (`c3-native-20261107T215002Z`) | [`c3-20261107T205707Z/REPORT.md`](../c3-20261107T205707Z/REPORT.md) (`f104439`), [`c3-native-20261107T215002Z/REPORT.md`](../c3-native-20261107T215002Z/REPORT.md) (`aadbdc7`), [`SENSOR_ID_SPEC_AMENDMENT_1.md`](../../../../SENSOR_ID_SPEC_AMENDMENT_1.md) | Single serial reader serves both discovery and verification. Simulated Chrome run passed 9/9 checks. Live native macOS run scanned 3,068 BLE advertisements from `/dev/cu.usbmodem2101` and refused a live second owner via symlink, **but** iPhone app was off (`sightings=[]`). Shared `POST /observations` is **BLOCKED** on Amendment 1 / Teammate T2 request R1 |
| **(5) Video and measurements delivered** | **INCOMPLETE**: Software measurements & C3 video **PASSED**; Physical E2/E3/E4 measurements & C1/C2/C4 videos **PENDING / UNTESTED** | SIMULATED + **REAL HARDWARE** C1 captures | [`c4-20261107T220500Z/REPORT.md`](../c4-20261107T220500Z/REPORT.md), [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) | Playable C3 software video (`_media/c3/c3-software-proof-SIMULATED.mp4`, full decode verified with `ffmpeg`, `SHA-256: 6f4a2c17...`), E0 latency, C3 pty-to-API latency, C1 hardware RSSI/counter counts, and 70 s aging/recovery delivered. Physical E2 (20 trials at 1 m), E3 (1/3/5 m + obstruction), E4 (lifecycle), and C1/C2/C4 videos remain **PENDING / UNTESTED** |
| **Production Keychain provisioning** | **UNSUPPORTED / STUB** | Out of C1 App Scope | [`ios/BeaconC1/BeaconC1/Token.swift`](../../../../ios/BeaconC1/BeaconC1/Token.swift) | Host `ble_keys.py` enforces production `keys.json` (`chmod 600`, rejects all 15 synthetic keys), but iPhone app hardcodes synthetic alias-1 test key and has no Keychain provisioning |
| **Background / locked advertising** | **UNSUPPORTED** | Platform & App Design | [`ios/BeaconC1/BeaconC1/BeaconC1App.swift`](../../../../ios/BeaconC1/BeaconC1/BeaconC1App.swift) | Baseline is foreground-only; `BeaconC1App.swift` calls `adv.stop()` on `.background`, and iOS moves background service UUIDs to the overflow area |

## 1. What changed, and what can the user now observe?

1. **Zero-dependency clean-checkout reproduction and repository audit (`tools/c5/reproduce_c5.py`, 149 lines):**
   Running `python3 -B tools/c5/reproduce_c5.py` from any fresh checkout using only the Python 3.10+ standard library executes the unit/property/vector/state/ownership/ignore/C4/discovery test suite, runs the 12 C1 analyzer and capture tests, re-grades the retained C1 hardware captures (confirming the final retry passes and the preserved first attempt fails), runs the 1,200-trial C2 E0 experiment, runs the C4 verifier replay on C1 hardware captures and 70 s aging/recovery check, verifies every `MANIFEST.sha256` file and C0 vector checksum, checks every relative markdown link across `README.md`, `discovery/README.md`, and `docs/ble-id/runs/*/*.md`, and confirms every handwritten BLE-ID file is under 150 lines.
2. **Operator guide ([`README.md`](../../../../README.md)) and evidence index ([`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md)):**
   Provides setup instructions, explicit `init-state` commands, operating modes (`production`, `test-keys`, `simulated`, and plain discovery), failure recovery steps, security/operational limitations, and SHA-256 manifests for all C0–C5 runs.

## 2. What did we actually try? (Clean Checkout Reproduction)

From an isolated clean `git clone` of tested code commit `10d6080925a3f18d9f887390dc2a282f94ba207d` (recorded in [`environment.txt`](environment.txt)):

| Check | Evidence Label | Command | Result |
| --- | --- | --- | --- |
| Clean checkout status | Software / Repo Audit | `git status --short` | Empty (`''`), exit 0 |
| Zero-dependency C5 full audit (`tools/c5/reproduce_c5.py`) | SIMULATED + Recorded REAL HARDWARE C1 TSV grading | `python3.13 -B tools/c5/reproduce_c5.py c5_audit.json` | `all_reproducible_checks_pass: true` (211 passed, 0 failed; 12/12 C1 tests; C1 retry pass / attempt 1 fail; 1,200/1,200 E0; C4 5 verified windows; 0 bad hashes; 0 broken links; max handwritten file 149 lines), exit 0 ([`c5_audit.json`](c5_audit.json)) |
| C2 mutation check (10 deliberate bugs) | SIMULATED | `python3.13 -B tools/c2/mutation_check.py . /tmp/clean-work/c5mut` | **10/10 mutants caught**, exit 0 ([`c2_mutation_clean_clone.log`](c2_mutation_clean_clone.log)) |
| C2 E0 deterministic software experiment | SIMULATED | `python3.13 -I -B tools/c2/e0_experiment.py . /tmp/clean-work/c5e0 100` | **1,200/1,200 classified as expected; 0 invalid verified**; `verify()` latency p50 = **2.8 µs**, p95 = **3.2 µs**, exit 0 ([`c2_e0_clean_clone.log`](c2_e0_clean_clone.log)) |
| JS & shell syntax checks | Software / Static Check | `node --check discovery/static/app.js && node --check discovery/static/beacons.js && bash -n tools/c1/run_c1.sh tools/c1/capture_serial.sh tools/c3/native_macos_check.sh` | All syntax checks OK, exit 0 |
| Playable C3 video SHA-256 & full `ffmpeg` decode | SIMULATED Video Playback | `shasum -a 256 _media/c3/c3-software-proof-SIMULATED.mp4 && ffmpeg -v error -i _media/c3/c3-software-proof-SIMULATED.mp4 -f null -` | `SHA-256: 6f4a2c1785d1ec3b0aea8311ae5c2193ba928ddbeef694a2d0f24b6e545f13aa`; H.264 1440×900, 57.28 s, **0 decode errors**, exit 0 ([`video_check.txt`](video_check.txt)) |

## 3. What happened? Expected vs. Observed Across All Checkpoints

### Genuine Measurements in Ordinary Language

1. **Software token verification latency (`E0`, SIMULATED):**
   - **Timing boundary:** `time.perf_counter_ns()` around `verify(payload, keys, seen, now=...)` (excludes 10 warmup calls, serial framing, disk writes, and radio).
   - **Observed:** Across **1,300 calls** (12 classes × 100 deterministic trials + negative controls), **1,200/1,200** trials produced the exact expected decision (`verified`, `replay:stale`, `replay:future`, `replay:duplicate`, `replay:not_newer`, `forged:bad_tag`, `unknown:unenrolled_alias`, `drop:length`, `drop:unsupported_version`, `drop:reserved_alias`) with **0** invalid verified events. Median latency (**p50**) is **2.8 µs** (**p95 3.2 µs**) on native Apple M4 Pro (Python 3.13.13) and **3.2 µs p50** (**5.1 µs p95**, **57.2 µs max**) on the Linux VM (Python 3.10.12).
2. **Host serial write to `/api/beacons` HTTP visibility (`C3`, SIMULATED):**
   - **Timing boundary:** `os.write` of one authenticated CSV row to a pseudo-terminal → `serial_worker` line framing → `Discovery.ingest` → `BeaconMonitor.ingest` → `verify()` → atomic `save_state()` with `fsync` → `/api/beacons` HTTP JSON response (polled every 5 ms; excludes radio, ESP32, USB cable, and the browser's 1 s poll timer).
   - **Observed:** **50/50 trials succeeded** (`0` timeouts); **min 5.2 ms, p50 7.9 ms, p95 13.7 ms, max 17.6 ms** on the Mac Linux VM (`c3-20261107T205707Z/latency/latency_vm_py310.json`), and **min 2.1 ms, p50 3.0 ms, p95 4.8 ms, max 9.1 ms** on the cloud host.
3. **Foreground iPhone 14 Pro (iOS 26.0) to passive ESP32-C5 reception (`C1` + `C4`, REAL HARDWARE):**
   - **Stopped control (`30.005 s`):** 29 heartbeats, **0** test-beacon rows received (`rssi_dbm: null`).
   - **Static vector A1 (`60.001 s`):** **1,665** exact UUID rows (`01010390-83cc-c438-cfa7-043609b9d1c4`) and **1,665** matching `#RAW` AD rows. Replayed through `BeaconMonitor`, all **1,645** post-heartbeat rows authenticated with alias 1's key and were rejected as `replay:stale` (counter `59802572` was ~106 min old), leaving replay state `{}` untouched. RSSI: **min -99 dBm, p10 -84 dBm, median -80 dBm, p90 -78 dBm, max -76 dBm** (`n=1,665`).
   - **Rotating token stage (`120.001 s`, retry after 2 s startup drain fix):** **3,273** authenticated rows across **5 consecutive 30-second counters** (`59802784`..`59802788`) with **0** invalid HMAC tags. Replayed through `BeaconMonitor`, the first post-heartbeat reception in each of the 5 windows was accepted as **`verified:fresh` (5 total)** and persisted (`high_water = {"1": 59802788}`), while the remaining **3,240** post-heartbeat repetitions were classified as **`replay:duplicate`** without refreshing card age. RSSI: **min -99 dBm, p10 -88 dBm, median -86 dBm, p90 -83 dBm, max -74 dBm** (`n=3,273`, unmeasured bench distance; RSSI is not a distance measurement).
   - **Preserved failed first rotating attempt (`120.004 s`):** Received 3,284 rows across 5 consecutive counters (`59802778`..`59802782`), plus 2 buffered static A1 rows and 2 fragments within `<0.5 ms` of serial open before the 2 s startup drain was added (`1582429`). Correctly rejected by `tools/c1/analyze_c1.py` (`rejected_rows = 2`); in `BeaconMonitor`, the pre-heartbeat gate (`ignored:receiver_not_ready = 31`) blocked those `<0.5 ms` startup rows before `verify()`.
4. **Live native macOS ESP32-C5 discovery & symlink lock check (`120 s`, `c3-native-20261107T215002Z`, REAL HARDWARE receiver):**
   - Over 60 two-second `/api/beacons` and `/api/discovery` snapshots on `/dev/cu.usbmodem2101`, the passive ESP32-C5 processed **3,068** BLE advertisements (`malformed = 0`), refused a live second process opening the state file via a symlink (`exit=1`), and recorded `sightings = []` because the iPhone app was not broadcasting Rotating mode during that window.
5. **Physical C4 distance (1 m, 3 m, 5 m, obstruction), 20-trial Start-to-verified latency at 1 m, and lifecycle (foreground, background, locked, force-quit) captures:**
   - **Not measured (`UNTESTED`).** Interactive runner (`tools/c4/run_c4.py live`) and grader (`tools/c4/c4_analyze.py`) are tested and committed.

## 4. Where is the proof?

- **Complete C0–C5 Evidence Index:** [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md)
- **Playable C3 software video (outside Git):** `_media/c3/c3-software-proof-SIMULATED.mp4` (`SHA-256: 6f4a2c1785d1ec3b0aea8311ae5c2193ba928ddbeef694a2d0f24b6e545f13aa`, 57.28 s H.264 1440×900; see [`video_check.txt`](video_check.txt) and timestamps in [`c3-20261107T205707Z/REPORT.md`](../c3-20261107T205707Z/REPORT.md))
- **Files in this C5 run directory:**
  - [`environment.txt`](environment.txt), [`commands.log`](commands.log), [`line_counts.txt`](line_counts.txt)
  - [`c5_audit.json`](c5_audit.json) (output of `python3.13 -B tools/c5/reproduce_c5.py`)
  - [`pytest_clean_clone.log`](pytest_clean_clone.log), [`c1_unittest_clean_clone.log`](c1_unittest_clean_clone.log)
  - [`c2_mutation_clean_clone.log`](c2_mutation_clean_clone.log), [`c2_e0_clean_clone.log`](c2_e0_clean_clone.log)
  - [`video_check.txt`](video_check.txt), [`MANIFEST.sha256`](MANIFEST.sha256)

## 5. What does this establish, what remains unproven, and what happens next?

- **Established:** The pure v1 HMAC/freshness/replay verifier, atomic SHA-256-checked replay state, canonical single-owner file locking across symlinks/hard links, explicit key-mode separation, single-serial-reader local dashboard, and foreground iPhone 14 Pro → passive ESP32-C5 128-bit UUID transport and 30 s rotation all work as specified and reproduce cleanly from a fresh checkout.
- **Unproven / Open Blockers:**
  1. Live iPhone-to-browser verified card in `c3-native` (`tools/c3/native_macos_check.sh`) with the iPhone app actively running in foreground Rotating mode.
  2. Physical C4 measurements (`tools/c4/run_c4.py live`): 20 Start-to-verified trials at measured 1 m (without resetting replay state), 60 s captures at 1 m, 3 m, 5 m, and behind one described obstruction, 60 s lifecycle captures (`foreground`, `background`, `locked`, `force_quit`), and physical USB unplug/replug recovery.
  3. Physical proof video review for C1 and C4, and standalone C2 screen recording.
  4. Shared mission-dashboard posting (`POST /observations`), blocked on `SENSOR_ID_SPEC_AMENDMENT_1.md` and Teammate T2 request R1.
  5. Production iOS Keychain key provisioning (`UNSUPPORTED / STUB`) and background/locked BLE advertising (`UNSUPPORTED`).

# C3 native macOS suite and live ESP32 receiver check (iPhone beacon inactive)

Run: `c3-native-20261107T215002Z` · November 7, 2026 · MacBook Pro (Apple M4 Pro, macOS 26.1 Build 25B78)
Tested commit: `aadbdc72c8ff8e3cf629a489d558e654f7e5e656` (with preserved earlier tool-setup runs `c3-native-20261107T212551Z`, `c3-native-20261107T212627Z`, `c3-native-20261107T212950Z`, and follow-up test confirmation `c3-completion-20261107T215441Z`).

| Gate | Status |
| --- | --- |
| Native macOS test suite (`pytest` 208 tests + `unittest` 8 discovery tests + JS syntax) | **PASSED** (208 passed in 9.03 s; 8 passed in 2.74 s; JS syntax OK) |
| Live ESP32-C5 USB receiver connection + live two-process symlink lock refusal | **PASSED** (`/dev/cu.usbmodem2101`, `LIVE-HW`, 3,068 BLE advertisements processed in 120 s; second owner via symlink refused) |
| Actual iPhone-to-browser verified sighting (`sightings` non-empty in `/api/beacons`) | **INCOMPLETE / UNTESTED IN THIS RUN**: 0 verified sightings because the iPhone `OLF C1` app was not broadcasting in Rotating mode during the 120 s capture window |

## 1. What changed, and what did we test?

Earlier C3 runs executed inside a Linux VM and cloud container, leaving native macOS execution and live hardware-to-browser integration untested.

1. **Preserved failed native test-runner attempts (`212551Z`, `212627Z`, `212950Z`):**
   - `c3-native-20261107T212551Z` and `212627Z`: default `python3` on this Mac was Homebrew Python 3.15.0 pre-release without `pip`, and `/dev/cu.usbmodem2101` was held by an existing plain discovery server (`PID 88243`).
   - `c3-native-20261107T212950Z`: Homebrew `python3.13`'s `pyexpat` C extension failed to link `_XML_SetAllocTrackerActivationThreshold` against macOS 26.1's system `libexpat`, breaking `ensurepip`/`pip`.
   - Fix (`fe7042a`): `tools/c3/native_macos_check.sh` fetches pinned pure-Python wheels (`pytest 8.3.4`, `pluggy 1.5.0`, `iniconfig 2.0.0`, `packaging 24.2`), verifies their SHA-256 digests against PyPI (`wheels.log`), and runs with `/opt/homebrew/bin/python3.13` (`Python 3.13.13`).
2. **Native macOS suite + live ESP32-C5 run (`c3-native-20261107T215002Z` and `c3-completion-20261107T215441Z`):**
   - Executed all 208 `pytest` tests natively on macOS 26.1 (`pytest_native_macos.log`, 208 passed, exit 0) and re-confirmed in `c3-completion-20261107T215441Z/pytest_native_macos.log` (208 passed in 9.01 s).
   - Started `python3.13 -m discovery.server --serial /dev/cu.usbmodem2101 --test-keys` with a fresh `TESTKEY-bench-c3-native-20261107T215002Z` scope.
   - Spawned a second `discovery.server` pointed at a symlink to the active state file; it exited with code 1 and `ERROR: verification not started: replay state ... is owned by another verifier process` (`second_owner_via_symlink.log`).
   - Polled `/api/beacons` and `/api/discovery` every 2 seconds for 120 seconds (`api_snapshots.jsonl`, 60 snapshots).

## 2. Expected vs observed

| Check | Expected | Observed | Status |
| --- | --- | --- | --- |
| Native macOS `pytest` suite | 208 passed, exit 0 | 208 passed in 9.03 s (`pytest_native_macos.log`) | **PASS** |
| Native macOS `test_discovery.py` | 8 passed, exit 0 | 8 passed in 2.741 s (`discovery_unittest_macos.log`) | **PASS** |
| `node --check` on `app.js` and `beacons.js` | Exit 0 | Exit 0 (`commands.log`) | **PASS** |
| Live second process via symlink | Refused before processing tokens | Refused (`exit=1`, `owned by another verifier process`) | **PASS** |
| Live ESP32-C5 passive scanning over USB | `source="LIVE-HW"`, `status="scanning"`, packets increasing | 60/60 snapshots `scanning`; `packets` grew from 127 to 3,068 (`malformed=0`, 1 unrelated 128-bit UUID dropped as `drop:unsupported_version`) | **PASS** |
| Live iPhone rotating beacon verified in `/api/beacons` | At least 1 verified sighting and persisted counter | `sightings=[]`, `high_water={}` (iPhone app was not started in Rotating mode during the 120 s window) | **INCOMPLETE** |

## 3. Where is the proof?

- [Environment and hardware details](environment.txt)
- [Commands and exit codes](commands.log), [verified wheel SHA-256 log](wheels.log)
- [Native macOS pytest log (208 passed)](pytest_native_macos.log) and [discovery unittest log (8 passed)](discovery_unittest_macos.log)
- [Receiver and live symlink lock refusal](receiver.txt), [second owner error output](second_owner_via_symlink.log), [server startup log](server.log)
- [60 two-second `/api/beacons` and `/api/discovery` snapshots](api_snapshots.jsonl) and [run summary](summary.txt)
- [SHA-256 manifest](MANIFEST.sha256)
- Preserved earlier tool-setup runs: [`c3-native-20261107T212551Z`](../c3-native-20261107T212551Z/), [`c3-native-20261107T212627Z`](../c3-native-20261107T212627Z/), [`c3-native-20261107T212950Z`](../c3-native-20261107T212950Z/), and [`c3-completion-20261107T215441Z`](../c3-completion-20261107T215441Z/).

## 4. What this establishes and what remains

- **Established (native macOS + REAL HARDWARE receiver):** The full 208-test suite passes natively on macOS 26.1 (Apple M4 Pro, Python 3.13.13). The single serial reader (`discovery.server`) opens `/dev/cu.usbmodem2101` exclusively, receives live passive BLE advertisements from the ESP32-C5 (`3,068` packets in 120 s with `0` malformed lines), serves `/api/beacons` (`LIVE-HW` / `SYNTHETIC TEST KEYS`), and refuses a second process attempting to open the active replay state through a symlink.
- **Still required to close C3 live phone-to-browser gate:** Run the live check while `OLF C1` on the iPhone is actively advertising in `Rotating` mode in the foreground so `/api/beacons` records a non-empty `sightings` card and persisted `high_water` counter.

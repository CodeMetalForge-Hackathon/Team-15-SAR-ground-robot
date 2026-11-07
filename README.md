# Team-15 Authenticated BLE Sensor Module (`ble-id` & `discovery`)

Offline search-and-rescue BLE beacon authentication and passive discovery module for Code Metal Forge 2026 (`culubo/sensor-id-specs`).

A foreground iPhone app (`ios/BeaconC1`, installed as **OLF C1**) broadcasts one rotating 128-bit service UUID every 30 seconds containing protocol version `0x01`, a 1-byte enrollment alias (`1..255`), a 32-bit big-endian UTC window counter (`floor(unix_seconds / 30)`), and an 80-bit truncated `HMAC-SHA256` tag over `"OLF/BLE-ID/v1" || header`. A passive ESP32-C5 scanner (`firmware/esp32_scanner/esp32_scanner.ino`) forwards advertisements over USB serial (`115200` baud) to a single host serial reader (`discovery/server.py`) that feeds both unverified passive discovery and the authenticated verifier (`ble_id.py` → `ble_verify.py` → `ble_state.py`).

## Gate & Checkpoint Status Summary

| Gate / Requirement | Status | Evidence Kind | Tested Commit & Run ID | Notes & Remaining Blockers |
| --- | --- | --- | --- | --- |
| **C0** Baseline & protocol vectors | **PASSED** | Software / Spec | `4f181ae` · [`evidence/c0-20261107T1914Z/REPORT.md`](evidence/c0-20261107T1914Z/REPORT.md) | 19 fixed vectors + 6 multi-step sequences; discovered `forge/` does not exist |
| **C1** ESP32-C5 & iOS builds + flash | **PASSED** | Build + Real Hardware | `8c514f9` · [`docs/ble-id/runs/c1-review-20261107T201136Z/REPORT.md`](docs/ble-id/runs/c1-review-20261107T201136Z/REPORT.md) | `esp32:esp32:esp32c5:CDCOnBoot=cdc` flashed; `OLF C1` installed on iPhone 14 Pro |
| **C1** Foreground UUID radio captures | **PASSED** (attempt 1 **FAILED** & retained) | **REAL HARDWARE** | `1582429` · [`docs/ble-id/runs/c1-capture-20261107T202438Z/REPORT.md`](docs/ble-id/runs/c1-capture-20261107T202438Z/REPORT.md) | Stopped: 0 rows/30 s; Static A1: 1,665 rows/60 s; Rotating retry: 3,273 rows/120 s across 5 consecutive counters |
| **C1** Physical proof video review | **PENDING / UNTESTED** | Physical Video | [`docs/ble-id/runs/c1-capture-20261107T202438Z/REPORT.md`](docs/ble-id/runs/c1-capture-20261107T202438Z/REPORT.md) | Video remains on filming phone (limited Mac storage); not yet transferred or reviewed |
| **C2** Pure verifier & durable replay state | **PASSED** | SIMULATED / Software | `ec19d1a` · [`docs/ble-id/runs/c2-20261107T204259Z/REPORT.md`](docs/ble-id/runs/c2-20261107T204259Z/REPORT.md) | 104 tests, 10/10 mutants caught, 1,200/1,200 E0 trials (`verify()` p50 3.2 µs VM / 2.8 µs M4 Pro). Standalone C2 screen clip **PENDING** |
| **C3** Serial → verifier → state → API → browser | **PASSED (SIMULATED)** | SIMULATED + Video | `f104439` · [`docs/ble-id/runs/c3-20261107T205707Z/REPORT.md`](docs/ble-id/runs/c3-20261107T205707Z/REPORT.md) | 186 tests, pty-to-API p50 7.9 ms (VM), playable clip `_media/c3/c3-software-proof-SIMULATED.mp4` |
| **C3** Symlink lock bypass fix & secret ignore rules | **PASSED** | Software + Live USB | `acbb102` / `e3b5905` · [`docs/ble-id/runs/c3-ownership-20261107T212052Z/REPORT.md`](docs/ble-id/runs/c3-ownership-20261107T212052Z/REPORT.md) | `ble_owner.py` canonicalizes `realpath`, blocks symlinks/hard links; verified in 8 two-process tests & live server |
| **C3** Native macOS suite + live ESP32 USB scan | **PASSED** (phone sighting **INCOMPLETE**) | Native macOS + **REAL HARDWARE** USB | `aadbdc7` · [`docs/ble-id/runs/c3-native-20261107T215002Z/REPORT.md`](docs/ble-id/runs/c3-native-20261107T215002Z/REPORT.md) | 208/208 `pytest` + 8/8 `unittest` passed on macOS 26.1; 3,068 live BLE packets on `/dev/cu.usbmodem2101`; iPhone app was off (`sightings=[]`) |
| **C4** C1 hardware captures through C3 verifier + aging/recovery | **PASSED** | **REAL HARDWARE** TSVs + SIMULATED aging | `ad4d419` · [`docs/ble-id/runs/c4-20261107T220500Z/REPORT.md`](docs/ble-id/runs/c4-20261107T220500Z/REPORT.md) | C1 rotating retry → 5 `verified:fresh` counters (`59802784`..`59802788`), 3,240 `replay:duplicate`; 70 s card staleness & disconnect recovery verified |
| **C4** Live E2 (20 trials at 1 m), E3 (1/3/5 m + obstruction), E4 (lifecycle) | **UNTESTED** | Requires Physical Run | `ad4d419` · `tools/c4/run_c4.py` | Interactive runner & grader tested and committed; physical phone/tape-measure runs and C4 video not yet executed |
| **Shared mission dashboard (`POST /observations`)** | **BLOCKED** | Architecture / Spec | [`SENSOR_ID_SPEC_AMENDMENT_1.md`](SENSOR_ID_SPEC_AMENDMENT_1.md) | Blocked on Amendment 1 adoption and Teammate T2 request R1 (honest beacon labeling in `core/store.py`) |
| **iOS Keychain production key provisioning** | **UNSUPPORTED / STUB** | Out of C1 Scope | `ios/BeaconC1/BeaconC1/Token.swift` | Phone app uses public synthetic test key for alias 1; production Keychain provisioning is not implemented |
| **Background / locked-screen BLE advertising** | **UNSUPPORTED** | Platform & App Design | `ios/BeaconC1/BeaconC1/BeaconC1App.swift` | Baseline is foreground-only; `BeaconC1App.swift` explicitly stops advertising on `.background`, and iOS moves background service UUIDs to overflow |

## Module Layout (All Handwritten Source Files < 150 Lines)

- `ble_verify.py` (127 lines): Pure wire-format v1 token generator (`make_token`) and classifier (`verify`). No I/O, clock reads, or in-place state mutation.
- `ble_state.py` (119 lines): Atomic, SHA-256-checked replay state persistence (`init_state`, `load_state`, `save_state`). Fails closed on missing, corrupt, or wrong-scope files.
- `ble_owner.py` (46 lines): Canonical path resolution (`os.path.realpath`), hard-link rejection (`st_nlink > 1`), and exclusive non-blocking `<canonical_path>.lock` ownership (`O_NOFOLLOW`, `flock`).
- `ble_keys.py` (104 lines): Explicit `production`, `test-keys`, and `simulated` key modes; refuses all 15 published synthetic keys in production and enforces `chmod 600`.
- `ble_id.py` (135 lines): Serial row validator, clock guard, persist-before-publish `BeaconMonitor`, and `python3 -m ble_id init-state` CLI.
- `ble_sim.py` (118 lines): Deterministic 40-second software simulator over a private pseudo-terminal (`SIMULATED` banner, port 8766).
- `discovery/server.py` (273 lines), `discovery/beacons.py` (52 lines), `discovery/static/app.js` (121 lines), `discovery/static/beacons.js` (99 lines): Single exclusive USB serial reader (`TIOCEXCL`), 2-second startup drain, local HTTP server (`127.0.0.1:8765`), unverified discovery view, and verified-beacon panel.
- `firmware/esp32_scanner/esp32_scanner.ino` (88 lines): Passive NimBLE scanner (`setActiveScan(false)`, 100 ms interval/window, duplicate filter off, Wi-Fi never initialized).
- `ios/BeaconC1/BeaconC1/` (`Advertiser.swift` 94 lines, `BeaconC1App.swift` 56 lines, `Token.swift` 43 lines): Foreground CoreBluetooth peripheral advertising one 128-bit service UUID.
- `tools/c1/`, `tools/c2/`, `tools/c3/`, `tools/c4/`: Reproducible capture, mutation, E0, latency, browser-proof, native-macOS, and C4 hardware runners/analyzers.

## Operator Guide: Setup, Modes, Start/Stop & Recovery

### 1. Prerequisites
- **Host:** macOS or Linux with Python 3.10+ (tested on Python 3.10.12 Linux VM and Python 3.13.13 native macOS 26.1). Standard library only at runtime; `pytest 8.3.4` for the full test suite.
- **Scanner:** ESP32-C5 rev 1.0 flashed with `firmware/esp32_scanner/esp32_scanner.ino` (`--fqbn esp32:esp32:esp32c5:CDCOnBoot=cdc`, ESP32 core `3.3.11`, `NimBLE-Arduino 2.5.1`). Do not reflash working firmware unnecessarily.
- **Single serial reader rule:** Only one process may open `/dev/cu.usbmodem2101` (`TIOCEXCL`). Close Arduino Serial Monitor or any other `discovery.server` / capture script before starting a new reader.

### 2. Explicit Replay-State Initialization (Run Once per Mission/Scope)
Replay state is **never** created or reset automatically at server startup. Initialize a new state file explicitly once per mission or labelled experiment scope:

```sh
# For labelled experiments with the public synthetic test keys (scope MUST start with TESTKEY-):
python3 -m ble_id init-state --state ~/olf-testkey-state.json --scope TESTKEY-bench

# For production missions (scope must NOT start with TESTKEY- or SIMULATED-):
python3 -m ble_id init-state --state ~/olf-mission-state.json --scope MISSION-ALPHA
```

If the state file already exists, `init-state` refuses with an error (`refusing to initialize: ... already exists`) so an operator cannot accidentally wipe replay protection.

### 3. Starting and Stopping Each Mode

**Mode A — Live Hardware with Public Synthetic Test Keys (for C1/C3/C4 iPhone App):**
```sh
python3 -m discovery.server --serial /dev/cu.usbmodem2101 \
  --test-keys --state ~/olf-testkey-state.json --scope TESTKEY-bench
```
Open <http://127.0.0.1:8765>. Displays an amber **SYNTHETIC TEST KEYS** banner. Stop with `Ctrl+C`.

**Mode B — Live Hardware with Production Keys (Host Ready; Phone Keychain Provisioning Not Implemented):**
Create `~/olf-keys.json` with `chmod 600`:
```json
{
  "format": "olf-ble-id-keys/1",
  "scope": "MISSION-ALPHA",
  "keys": {
    "1": "<64 lowercase hex chars of random 32-byte secret key>"
  }
}
```
Start the server:
```sh
python3 -m discovery.server --serial /dev/cu.usbmodem2101 \
  --keys ~/olf-keys.json --state ~/olf-mission-state.json --scope MISSION-ALPHA
```
Any published synthetic key, group/world-readable `keys.json`, or mismatched `scope` is refused at startup.

**Mode C — Software Simulator (No Hardware Required):**
```sh
python3 -m ble_sim serve --port 8766
```
Open <http://127.0.0.1:8766>. Uses a private pseudo-terminal, simulator keys, and a fresh `SIMULATED-` state file. Displays a red **SIMULATED** banner and `SIMULATED · NOT HARDWARE` connection status.

**Mode D — Plain Passive Discovery Only (Verification Off):**
```sh
python3 -m discovery.server --serial /dev/cu.usbmodem2101
```

### 4. Recovery Steps & Failure Modes
- **USB receiver unplugged or lost (`Receiver disconnected` / `receiver_unavailable`):** Keep the server running and plug the ESP32-C5 back into the same USB port. `serial_worker` automatically reconnects after 2 seconds, performs a 2-second startup drain, waits for a fresh `#HEARTBEAT,scanning=1,...,passive=1,discovery=1`, and resumes verification while keeping prior verified sightings on screen.
- **`owned by another verifier process` (`OwnerError`):** Another `discovery.server` or `BeaconMonitor` holds the `flock` on `<canonical_state_path>.lock` (including via any symlink or relative path alias). Stop the other process (`Ctrl+C`) before starting a new one.
- **`replay state missing` / `corrupt` / `different enrollment/mission scope` (`StateError`):** The verifier fails closed. Verify you passed the matching `--state` and `--scope` for the current mission. Only create a brand-new state file with `init-state` under a new mission scope if starting a new mission.
- **`Could not save replay state; verified result withheld` (`status="halted"`):** Disk write/fsync failed before publishing. Free disk space or fix directory permissions and restart the server.

### 5. Honest Security & Operational Limitations
- **Authentication, not encryption:** The 16-byte service UUID is broadcast in cleartext. Anyone can read the protocol version, 1-byte enrollment alias (`1..255`), and 32-bit counter. The 1-byte alias is linkable across windows and is not anonymous.
- **No liveness, physical-presence, or anti-relay proof:** A verified token proves only that something possessing the enrolled key computed a tag for the current 30 s UTC window (±1 window tolerance, up to ~60 s age at window boundaries) that has not yet been accepted by this verifier instance. It does not prove a survivor is alive, carrying the phone, or protected against a real-time BLE relay or stolen key.
- **RSSI is not distance or location:** Displayed RSSI (in dBm) is a noisy received signal strength hint affected by multipath, body absorption, and orientation. Never treat RSSI or a receiver's cell label as survivor coordinates or range.
- **Receive-only passivity is configuration-verified only:** `esp32_scanner.ino` configures `setActiveScan(false)`, never advertises or connects, and never initializes Wi-Fi, but no independent RF spectrum/sniffer capture has been performed.
- **State rollback:** Rollback of the host's replay-state file on disk is outside prototype protection.

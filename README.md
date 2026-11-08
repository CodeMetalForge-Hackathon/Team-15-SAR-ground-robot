# Team-15 Authenticated BLE Sensor Module (`ble-id` & `discovery`)

## Local robot network and operator interface

Run `python3 -m mission_control.demo` from this repository to try the local
Human-in-the-Loop dashboard with three simulated agents. Open
<http://127.0.0.1:8080> and use the temporary operator token printed in the terminal.
The coordinator, per-action approvals, device heartbeats, RoverC Wi-Fi adapter,
Crazyflie backend adapter, Jetson telemetry publisher, and Pi deployment steps
are documented in [mission_control/README.md](mission_control/README.md).
No cloud hosting or internet connection is needed. Hardware operation requires
explicit live agents; the external Crazyflie backend and airborne scanner link
remain separate integration requirements.

Offline search-and-rescue BLE beacon authentication and passive discovery module for Code Metal Forge 2026 (`culubo/sensor-id-specs`).

A foreground iPhone app (`ios/BeaconC1`, installed as **OLF C1**) broadcasts one rotating 128-bit service UUID every 30 seconds containing protocol version `0x01`, a 1-byte enrollment alias (`1..255`), a 32-bit big-endian UTC window counter (`floor(unix_seconds / 30)`), and an 80-bit truncated `HMAC-SHA256` tag over `"OLF/BLE-ID/v1" || header`. A passive ESP32-C5 scanner (`firmware/esp32_scanner/esp32_scanner.ino`) forwards advertisements over USB serial (`115200` baud) to a single host serial reader (`discovery/server.py`) that feeds both unverified passive discovery and the authenticated verifier (`ble_id.py` → `ble_verify.py` → `ble_state.py`).

## C0–C5 Checkpoints and Run Variants

Each `C` stage is a sequential engineering and verification checkpoint defined in [`SENSOR_ID_SPEC.md`](SENSOR_ID_SPEC.md), with run artifacts preserved under `evidence/` and `docs/ble-id/runs/`:

- **C0 — Baseline Inspection, Spec Amendment & Fixed Protocol Vectors (`evidence/c0-20261107T1914Z`):**
  Inspects the actual repository and remote branches before writing module code, documents in [`SENSOR_ID_SPEC_AMENDMENT_1.md`](SENSOR_ID_SPEC_AMENDMENT_1.md) that the base spec's assumed `forge/` / `Reading` interfaces do not exist, defines the hardware/software test plan in [`EXPERIMENT_PLAN.md`](evidence/c0-20261107T1914Z/EXPERIMENT_PLAN.md), and freezes 19 cross-language authentication/freshness vectors plus 6 stateful sequences in [`protocol_vectors_v1.json`](evidence/c0-20261107T1914Z/protocol_vectors_v1.json).
- **C1 — Minimal Foreground iPhone-to-Passive-ESP32 Carrier Feasibility:**
  Proves that a real iPhone 14 Pro (iOS 26.0, **OLF C1** app) advertising a single 128-bit service UUID is received byte-for-byte by a passive ESP32-C5 scanner (`esp32:esp32:esp32c5:CDCOnBoot=cdc`, NimBLE-Arduino 2.5.1) over USB serial without scan requests, connections, or local names:
  - **`c1-review-20261107T201136Z` (Build, Flash & Smoke Check):** Compiles and flashes the ESP32-C5 scanner firmware, compiles and installs the signed iOS app (`ios/BeaconC1`), verifies CryptoKit vector A1 agreement, and records a 5-second scanner heartbeat smoke capture before iOS developer-profile trust was enabled.
  - **`c1-capture-20261107T202438Z` (Three-Stage Over-the-Air Radio Captures):**
    - **Stage A (`capture_A_stopped.tsv`, 30 s):** App stopped control — confirms 29 scanner heartbeats and `0` false test-beacon receptions.
    - **Stage B (`capture_B_static.tsv`, 60 s):** Static vector A1 (`01010390-83cc-c438-cfa7-043609b9d1c4`) — confirms `1,665` exact UUID rows and `1,665` matching `#RAW` advertisement payloads in little-endian wire order.
    - **Stage C Attempt 1 (`attempt1_capture_C_rotating.tsv`, 120 s, FAILED & retained):** Live 30 s rotating tokens — received `3,284` rows across 5 consecutive counters, but included 2 buffered static A1 rows and 2 line fragments within `<0.5 ms` of serial open. Retained as a failed run.
    - **Stage C Retry (`capture_C_rotating.tsv`, 120 s, PASSED after commit `1582429`):** Adds an explicit 2-second startup drain (`.warmup.txt`) and line alignment; records `3,273` valid rows across 5 consecutive 30 s counters (`59802784`..`59802788`) with `0` invalid tags or malformed lines.
- **C2 — Pure Cryptographic Verifier & Durable Replay State (`c2-20261107T204259Z`):**
  Implements pure wire-format v1 token generation and classification (`ble_verify.py`: `drop`, `unknown`, `forged`, `replay:stale`, `replay:future`, `replay:duplicate`, `replay:not_newer`, `verified:fresh`) and atomic, SHA-256-checked replay-state persistence (`ble_state.py`) that fails closed on missing, corrupt, or wrong-scope files. Verified by 104 unit/property/vector tests, 10/10 mutation checks (`tools/c2/mutation_check.py`), and 1,200 deterministic E0 trials (`tools/c2/e0_experiment.py`).
- **C3 — Single-Reader Serial Adapter, Key Modes, Ownership Locking & Local Dashboard:**
  Connects live or simulated serial rows (`ble_id.py`) to the C2 verifier and persisted replay state before exposing verified sightings on `/api/beacons` and the browser UI (`discovery/`), while keeping unverified BLE advertisements separate and enforcing explicit `production`, `test-keys`, and `simulated` key modes (`ble_keys.py`):
  - **`c3-20261107T205707Z` (Simulated End-to-End Integration & Browser Video):** Exercises the full `pty → serial_worker → BeaconMonitor → ble_state → /api/beacons → headless Chrome` path using `ble_sim.py` (`186` tests, 50-trial pty-to-API latency probe, and playable clip `_media/c3/c3-software-proof-SIMULATED.mp4`).
  - **`c3-ownership-20261107T212052Z` (Symlink Lock-Bypass Fix & Secret Ignore Rules):** Fixes the C3 review finding where two processes opening the same state file via a symlink bypassed `<path>.lock`; adds `ble_owner.py` (`os.path.realpath` canonicalization, `O_NOFOLLOW`, hard-link rejection), two-process regression tests (`tests/test_ble_state_ownership.py`), and `.gitignore` rules for secret keys and state files (`tests/test_repo_ignores.py`).
  - **`c3-native-20261107T212551Z`, `212627Z`, `212950Z` (Preserved Native Runner Setup Attempts):** Retain initial native macOS script failures (Homebrew Python 3.15 missing `pip`, busy serial port, and macOS 26.1 `libexpat` symbol mismatch in `ensurepip`) prior to switching to SHA-256-verified pure-Python wheels in `fe7042a`.
  - **`c3-native-20261107T215002Z` & `c3-completion-20261107T215441Z` (Native macOS Suite & Live ESP32-C5 USB Check):** Confirms `208/208` `pytest` and `8/8` `unittest` pass natively on macOS 26.1 (Apple M4 Pro, Python 3.13.13), verifies live symlink second-owner refusal against a running server, and captures 120 s (`3,068` advertisements) from `/dev/cu.usbmodem2101` (`sightings=[]` because the iPhone app was not broadcasting in Rotating mode during that window).
- **C4 — System & Radio Measurements (`c4-20261107T220500Z`):**
  Evaluates the system against `EXPERIMENT_PLAN.md` using `tools/c4/c4_analyze.py` and `tools/c4/run_c4.py`: replays the retained C1 real-hardware captures through the C3 `BeaconMonitor` + `ble_state` pipeline (`c1_verifier_replay.json`), verifies 70-second card staleness (`STALE_S = 70 s`), duplicate non-refresh, and receiver disconnect/reconnect recovery (`aging_and_recovery.json`), and provides the interactive runner (`tools/c4/run_c4.py live`) for the physical E2 (20 trials at 1 m without state resets), E3 (1 m, 3 m, 5 m, obstruction), and E4 (`foreground`, `background`, `locked`, `force_quit`) captures.
- **C5 — Clean-Checkout Reproduction, Audit & Operator Handoff (`c5-20261107T221000Z`):**
  Reproduces the software test suite, C1 pass/fail capture grading, C2 mutation and 1,200-trial E0 checks, C4 hardware TSV replay, `ffmpeg` video decode check, SHA-256 manifest verification, markdown link audit, and `<150`-line source audit from an isolated clean checkout via `tools/c5/reproduce_c5.py`, and publishes the operator guide and complete [`EVIDENCE_INDEX.md`](docs/ble-id/runs/c5-20261107T221000Z/EVIDENCE_INDEX.md).

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
| **C5** Clean-checkout reproduction, video check & handoff index | **PASSED** (software & audit) | Clean Clone Audit | `6ae87f7` · [`docs/ble-id/runs/c5-20261107T221000Z/REPORT.md`](docs/ble-id/runs/c5-20261107T221000Z/REPORT.md) | `python3 -B tools/c5/reproduce_c5.py` passes (`all_reproducible_checks_pass: true`); incomplete hardware/integration gates reported honestly |
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

## Crazyflie Drone + Rover Demo

The `crazyflie/` scripts provide a Bluetooth-guided search demo and separate manual
keyboard control for the Crazyflie 2.1+. Both default to simulation. Full setup and
implementation details are in [`crazyflie/README.md`](crazyflie/README.md).

### Quick Start: No Hardware

Run from the repository root with Python 3.10+; dry-runs use only the standard library:

```sh
# Bluetooth-guided search with simulated signal readings:
python3 crazyflie/demo_mission.py --dry-run

# Other visual outcomes: safe, hidden, phone-only, empty
python3 crazyflie/demo_mission.py --dry-run --scenario safe

# Two search rounds with shorter sampling windows:
python3 crazyflie/demo_mission.py --dry-run --search-rounds 2 --sample-seconds 3

# Interactive WASD control in a terminal:
python3 crazyflie/keyboard_control.py --dry-run
```

Search simulation advances virtual time immediately; keyboard simulation runs at
real keyboard speed. Use `python` or `py` instead of `python3` where appropriate.

### Keyboard Controls and Speed

| Key | Action |
| --- | --- |
| T | Take off |
| W / S | Forward / backward |
| A / D | Left / right |
| R / F | Raise / lower altitude |
| H | Return above the takeoff point at current altitude |
| + or = | Increase movement speed by 0.05 m/s |
| - | Decrease movement speed by 0.05 m/s |
| Space, L, Q, Ctrl+C | Request landing and exit |

Each accepted movement key sends a 10 cm step. Set a different step with
`--step-m` (0.025–0.2 m). Speed starts at 0.20 m/s and is adjustable within
0.05–0.30 m/s; set the initial value with `--speed-m-s 0.15`. Speed changes apply
to the next move and preserve step distance. The terminal displays the selected
speed. This controls waypoint duration; actual instantaneous speed depends on the
flight controller, and short moves have a minimum 0.2-second duration.

Keep the terminal focused. Movement keys entered during a move are discarded,
while speed and landing keys remain active. Manual control is a separate flight
session and does not operate the rover or switch into autonomous search.

### Bluetooth Search Behavior

The drone samples the origin and four nearby points, collecting five seconds of
RSSI per point. It compares median signal strength, then revisits the baseline and
strongest point to check that the improvement repeats. Both comparisons must
improve by at least 3 dB; this is a configurable demo heuristic, not a confidence
guarantee. A second round halves the search step.

The default search step is 0.6 m. The existing discovery API is polled up to four
times per second, yielding up to about 20 samples per five-second window; the
minimum is eight fresh samples. Unchanged packet counts and readings older than
0.5 seconds are excluded. Inconclusive readings, missing data, or flight safety
failures cause return/landing without rover dispatch. A confirmed candidate can
be retained if a later round gives no clearer direction.

RSSI provides rough hot/cold guidance, not precise distance or survivor coordinates.
The candidate sent to the rover is the strongest confirmed sample position.
Camera inspection and operator observations determine the visual outcome.
`--target-inches` sets only the simulated beacon's hidden location, not a live
waypoint. Phone identity, human presence, injury and a cleared search area cannot
be established from RSSI alone.

### Hardware Setup and Live Use

Before connecting, confirm the Crazyradio, actual radio URI, positioning deck,
other decks, flight area and battery condition. A working position estimate is
required for these position-command scripts. The guide's default radio URI is
`radio://0/80/2M/E7E7E7E7E7`; confirm it in cfclient.

For Windows radio setup, the supplied team guide specifies:

```sh
py -m pip install cflib cfclient numpy matplotlib
```

Install the Crazyradio libusb driver through Zadig as described in Bitcraze's
Windows setup instructions, then use cfclient to scan and check the connection.
Dry-runs do not require these packages or a Crazyradio.

**Live flight additionally requires the team's
`sar_sim.backends.crazyflie_backend.CrazyflieLink`, which is absent from this
checkout.** Obtain that project, add its root to `PYTHONPATH`, and install its
requirements. The backend must provide battery/position telemetry, takeoff and
position commands, waits, and a context manager that lands and disconnects on
normal exit and exceptions. Confirm that behavior before flying.

```sh
# Manual live drone control; no BLE scanner required:
python3 crazyflie/keyboard_control.py --live-drone --height-m 0.5

# For Bluetooth-guided flight, first start the existing receiver dashboard:
python3 -m discovery.server --serial /dev/cu.usbmodem2101

# In another terminal, after choosing the demo beacon's exact session ID:
python3 crazyflie/demo_mission.py --live-drone --height-m 0.5 \
  --signal-id REPLACE_WITH_EXACT_ID --scanner-on-drone \
  --discovery-url http://127.0.0.1:8765
```

For live Bluetooth search, the **scanner must move with the drone**, with power
and a working path for its readings to reach the host. The current scanner uses
USB serial; these scripts do not add a wireless telemetry link. A stationary
scanner beside the Jetson cannot measure the drone's changing proximity.

Find the target's `id` in `http://127.0.0.1:8765/api/discovery`; use a controlled
beacon on/off check to select it. This is an unverified session identifier and may
change after server restart or entry expiry. The search never switches to another
device simply because its signal is stronger. This proximity input is separate
from the authenticated beacon panel and does not alter replay protection.

Jetson boot, rover motors, camera/CV, colored condition indicators, and phone
check-in remain operator steps. No phone messages are sent. Standalone rover WASD over USB is available, with receiver firmware installed on the CPlus SE; see
[`rover/README.md`](rover/README.md) for receiver firmware and setup. It is not
integrated into the autonomous mission. **Physical flight and live RSSI search remain untested.**

### Coordinates and Flight Limits

Coordinates sent to the drone use meters, seconds and radians. Its boot/takeoff
point is the origin: +x follows its initial forward heading, +y points left and +z
up. Place it at the same marked origin and heading before each session.

For rover handoff, both vehicles share that heading and the rover starts at (0,0).
The assumed drone placement is eight inches to its right; set the measured offset
with `--drone-right-inches`. The event `rover_move.target_xy_inches` reports the
candidate in the rover frame. The drone lands at its original takeoff point.

Keep the default ±1.5 m XY flight envelope. Live altitude must be 0.2–1.2 m;
`--height-m 0.5` is a valid starting setting. The screenshot's five-inch altitude
is retained only in search simulation because it is below that live envelope.

Run a dry-run first and inspect commands. Follow the team guide's first-flight
procedure with Gavin present, an open area and nobody within 1.5 m. Battery below
3.3 V or unavailable telemetry requests landing. Manual mode requests landing at
120 airborne seconds; autonomous search uses a 120-second search budget and a
140-second landing request cutoff. Landing timing and lost-radio handling depend
on the backend; a stalled backend can also delay keyboard handling.

### Checks

```sh
python3 -m unittest tests.test_demo_mission tests.test_rssi_search tests.test_keyboard_control -v
```

These tests cover search decisions, stale/duplicate readings, missing feeds,
coordinate conversion, keyboard movement, speed changes and bounds, flight timing,
battery handling and landing on errors. Hardware validation remains separate.

## RoverC Pro Wireless and USB Controls

The CPlus SE receiver supports both a rover-hosted Wi-Fi network and a shared
2.4 GHz network. The M5 screen shows its network name, pairing key and IP addresses.
Passwords and pairing keys are excluded from this README and repository.

**Router-free demo:** join the M5's displayed Wi-Fi network, then run:

```sh
python3 rover/keyboard_control.py --wifi 192.168.4.1
```

**Shared-network demo:** with USB connected and the keyboard client closed, run:

```sh
~/.codex/venvs/roverc/bin/python rover/wifi_setup.py \
  --serial /dev/cu.usbserial-7D520E63EE --join
```

Enter network credentials through its prompts. The setup command saves them on the
M5 and prints its assigned LAN IP. Drive using that IP:

```sh
python3 rover/keyboard_control.py --wifi REPLACE_WITH_ROVER_LAN_IP
```

WASD moves, Z/C rotates, +/− changes motor power, I queries status, X stops, and
Space/Q stops and exits. Wi-Fi requires pairing; setup keeps the pairing profile
privately outside the repository. USB driving remains available as a fallback.
With charged controller/base batteries and both powered on, the rover can be driven
without the USB cable. It requests stop after 250 ms without movement commands.

See [`rover/README.md`](rover/README.md) for connection steps, network requirements,
USB fallback, firmware build instructions and validation limits. Wireless range and
unplugged operation still require a physical check in the demo space.

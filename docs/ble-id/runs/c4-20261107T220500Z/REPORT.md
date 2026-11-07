# C4 report: verifier replay on C1 hardware captures, aging/recovery verification, and live runner

Run: `c4-20261107T220500Z` · November 7, 2026 · MacBook Pro (Apple M4 Pro, macOS 26.1 Build 25B78)
Tested commit: `ad4d419` (`feat(ble-id): replay C1 hardware captures through C3 verifier in C4 baseline`)

| Gate | Status |
| --- | --- |
| C1 real-hardware captures (`A_stopped`, `B_static`, `C_rotating`) replayed through C2/C3 `BeaconMonitor` + `ble_state` | **PASSED** (REAL HARDWARE captures -> software verifier replay) |
| Verified-card aging (`STALE_S = 70 s`), duplicate non-refresh, and receiver-loss/recovery behavior | **PASSED (SIMULATED)**; physical USB unplug/replug **UNTESTED** |
| E2: 20 foreground Start-to-first-verified trials at measured 1 m (target ≥ 19/20 within 10 s, zero replay-state resets) | **UNTESTED** (requires physical iPhone taps; interactive runner ready in `tools/c4/run_c4.py`) |
| E3: 60-second reception captures at measured 1 m, 3 m, 5 m, and behind one described obstruction | **UNTESTED** (requires physical placement; C1 captures were unmeasured bench distance) |
| E4: Separate 60-second foreground, background, locked, and force-quit captures | **UNTESTED** (requires physical phone state transitions; note `BeaconC1App.swift` explicitly stops on `.background`) |
| Playable C4 physical proof video | **PENDING / UNTESTED** |

## 1. What changed, and what can the user now observe?

We added a modular C4 measurement and grading toolkit (`tools/c4/c4_analyze.py`, 149 lines; `tools/c4/run_c4.py`, 145 lines; `tests/test_c4_analyze.py`, 109 lines) that:
1. Replays recorded real-hardware `capture_serial.py` TSV files through the actual `Discovery` + `BeaconMonitor` + `ble_state` pipeline using the recorded host UTC and monotonic timestamps (`c1_verifier_replay.json`).
2. Enforces the E2 replay-state rule in `grade_e2_trials()`: all 20 trials must share one persistent replay-state file and scope (`state_resets == 0`), and every verified trial must advance `high_water` monotonically (`counter > high_water_before`). Any state reset or reused counter fails the E2 gate.
3. Computes RSSI distributions (`count`, `min_dbm`, `p10_dbm`, `median_dbm`, `p90_dbm`, `max_dbm`) and returns `null` when zero protocol rows arrive (never substituting `0` for missing RSSI).
4. Verifies verified-card aging (`last_verified_age_s` increases while `replay:duplicate` rows arrive in the same 30 s window; `stale` becomes `true` after `STALE_S = 70 s` while preserving the sighting) and receiver-loss / recovery (`status` becomes `"receiver_unavailable"` when serial is lost while keeping sightings, and resumes `"verifying"` when heartbeats return).
5. Provides a single interactive native macOS runner (`python3 tools/c4/run_c4.py live --serial /dev/cu.usbmodem2101 --out docs/ble-id/runs/<run-id>`) for the physical E2, E3, and E4 stages.

## 2. What did we actually try?

| Check | Evidence kind | Command | Result |
| --- | --- | --- | --- |
| C4 analyzer unit tests (including replay-state reset detection) | SIMULATED | `python3.13 -B -m pytest tests/test_c4_analyze.py` | 6 passed, exit 0 |
| Sandbox non-socket test suite (C2 + C3 + C4 unit/property/vector/ownership/ignore) | SIMULATED (native macOS 26.1) | `python3.13 -B -m pytest tests/test_ble_*.py tests/test_repo_ignores.py tests/test_c4_analyze.py` | 201 passed, exit 0 (`pytest_sandbox_macos.log`) |
| C1 analyzer & pty capture tests | SIMULATED (native macOS 26.1) | `python3.13 -B -m unittest discover -s tools/c1 -p 'test_*.py' -v` | 12 passed, exit 0 (`c1_unittest_macos.log`) |
| Replay C1 real-hardware captures through C3 `BeaconMonitor` + `ble_state` | REAL HARDWARE captures (`c1-capture-20261107T202438Z`) -> verifier | `python3.13 -B tools/c4/run_c4.py baseline docs/ble-id/runs/c4-20261107T220500Z` | All 4 captures graded (`c1_verifier_replay.json`) |
| Verified-card aging (70 s) & receiver-loss/recovery | SIMULATED | `python3.13 -B tools/c4/run_c4.py baseline docs/ble-id/runs/c4-20261107T220500Z` | 4/4 checks passed (`aging_and_recovery.json`) |
| Live E2 (20 trials at 1 m), E3 (1 m/3 m/5 m/obstruction), E4 (lifecycle) | REAL HARDWARE | Not run (requires physical phone interaction and USB access outside sandbox) | **UNTESTED** (`c4_analysis.json`) |

## 3. Expected vs observed

### A. Real-hardware C1 captures replayed through C2/C3 `BeaconMonitor` + `ble_state` (`c1_verifier_replay.json`)

Hardware configuration of the C1 captures: iPhone 14 Pro (iOS 26.0 build 23A5326a, foreground `OLF C1` app, `SYNTHETIC TEST KEYS` alias 1) → passive ESP32-C5 rev 1.0 (`esp32:esp32:esp32c5:CDCOnBoot=cdc`, NimBLE-Arduino 2.5.1, `setActiveScan(false)`, 100 ms interval/window, duplicate filter off). Bench distance was not tape-measured during C1.

| Capture (`c1-capture-20261107T202438Z`) | Duration (s) | Protocol rows (`0101…`) | Verified windows (`verified:fresh`) | Other `BeaconMonitor` decisions | Persisted `high_water` | RSSI min / p10 / median / p90 / max (dBm) |
| --- | --- | --- | --- | --- | --- | --- |
| `capture_A_stopped.tsv` (app stopped) | 30.004556 | 0 | 0 (`[]`) | `drop:unsupported_version`: 25 | `{}` | `null` (0 rows) |
| `capture_B_static.tsv` (static vector A1, counter `59802572`) | 60.000782 | 1,665 | 0 (`[]`) | `replay:stale`: 1,645 · `ignored:receiver_not_ready`: 20 · `drop:unsupported_version`: 1 | `{}` (unpoisoned) | -99 / -84 / -80 / -78 / -76 (`n=1,665`) |
| `capture_C_rotating.tsv` (rotating retry, 2 s startup drain) | 120.000709 | 3,273 | **5** (`59802784`..`59802788`) | `replay:duplicate`: 3,240 · `ignored:receiver_not_ready`: 28 · `drop:unsupported_version`: 178 | `{"1": 59802788}` | -99 / -88 / -86 / -83 / -74 (`n=3,273`) |
| `attempt1_capture_C_rotating.tsv` (first rotating attempt, no startup drain) | 120.004265 | 3,284 | **5** (`59802778`..`59802782`) | `replay:duplicate`: 3,250 · `ignored:receiver_not_ready`: 31 · `drop:unsupported_version`: 85 | `{"1": 59802782}` | -99 / -87 / -83 / -80 / -78 (`n=3,284`) |

Notes on C1 verifier replay:
- **Heartbeat compatibility finding:** C1 firmware (`8c514f9`) emitted `#HEARTBEAT,scanning=1,millis=...` before `,passive=1,discovery=1` was added in commit `02f035c`. Without `c1_hb=True`, `Discovery.ready()` rejects all C1 rows as `ignored:receiver_not_ready` (confirming that legacy firmware without discovery heartbeats is refused). With `c1_hb=True` for C1 historical replay, rows arriving in the first ~0.6 s before the first `#HEARTBEAT` line in each TSV are still held back by the heartbeat gate (`ignored:receiver_not_ready`: 20 in B, 28 in C retry, 31 in C attempt 1 — which in C attempt 1 also blocked the 2 buffered startup static rows at `< 0.5 ms`!).
- **Static A1 classification:** Every post-heartbeat static A1 row (`1,645` rows) authenticated with alias 1's key and was classified `replay:stale` because fixed counter `59802572` was ~106 minutes older than the capture clock (`1794083250`), leaving replay state `{}` untouched.
- **Rotating retry classification:** Across 3,273 received protocol rows over 120.001 s, the first row after heartbeat in each of the 5 consecutive 30-second windows (`59802784`..`59802788`) was classified `verified:fresh` (5 total) and persisted to disk, while the remaining 3,240 post-heartbeat rows were classified `replay:duplicate`.

### B. Verified-card aging and receiver-loss / recovery (`aging_and_recovery.json`, SIMULATED)

| Step | Expected | Observed | Status |
| --- | --- | --- | --- |
| 4 duplicate advertisements +20 s after initial verification | `last_verified_age_s == 20.0`, `verified_tokens == 1`, `replay:duplicate == 4` | `age_after_duplicates_s = 20.0`, `verified_tokens = 1`, `duplicate_count = 4` | **PASS (SIMULATED)** |
| No new authenticated token for 75 s (`> STALE_S = 70 s`) | Card kept (`sightings == 1`), `stale == True` | `sightings_at_75s = 1`, `age_at_75s = 75.0`, `stale_at_75s = True` | **PASS (SIMULATED)** |
| Receiver disconnects (`disconnected`) | `status == "receiver_unavailable"`, sighting preserved (`sightings == 1`) | `loss_receiver_status = "disconnected"`, `loss_beacon_status = "receiver_unavailable"`, `loss_sightings = 1` | **PASS (SIMULATED)** |
| Receiver reconnects + fresh window token arrives | `status == "verifying"`, `verified_tokens == 2`, `stale == False` | `recovered_beacon_status = "verifying"`, `recovered_verified_tokens = 2`, `recovered_stale = False` | **PASS (SIMULATED)** |

### C. Summary of existing latency distributions and timing boundaries across C1–C4

| Metric | Provenance | Timing boundary (start → stop) | Sample count | min | p50 | p95 | max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pure `verify()` call latency | C2 E0 (`c2-20261107T204259Z`, Linux VM py3.10) | `time.perf_counter_ns()` around `verify(payload, keys, seen, now=...)` (excludes 10 warmup calls, serial, radio, disk) | 1,300 | — | 3.2 µs | 5.1 µs | 57.2 µs |
| Pure `verify()` call latency (native macOS) | C4 (`c4-20261107T220500Z`, macOS 26.1 M4 Pro py3.13) | Same boundary on native Apple M4 Pro | 1,300 | — | 2.8 µs | 3.4 µs | — |
| Serial write → `/api/beacons` HTTP latency | C3 (`c3-20261107T205707Z`, Linux VM py3.10, 5 ms poll) | `os.write` to pty → `serial_worker` → `BeaconMonitor` → atomic `save_state` (`fsync`) → `/api/beacons` JSON response (excludes radio, phone, USB, 1 s browser poll) | 50 / 50 | 5.2 ms | 7.9 ms | 13.7 ms | 17.6 ms |
| E2: Foreground Start → first verified at 1 m | C4 (`e2_trials.jsonl`) | Physical iPhone Start tap → ESP32 passive scan → USB serial → `BeaconMonitor` verified & persisted | 0 / 20 (**UNTESTED**) | `null` | `null` | `null` | `null` |

## 4. Where is the proof?

- [Environment and versions](environment.txt), [commands and exit codes](commands.log)
- [C1 real-hardware captures replayed through C3 verifier (`c1_verifier_replay.json`)](c1_verifier_replay.json)
- [Simulated aging and receiver-loss/recovery check (`aging_and_recovery.json`)](aging_and_recovery.json)
- [C4 grading output (`c4_analysis.json`)](c4_analysis.json)
- [Native macOS sandbox test log (201 passed)](pytest_sandbox_macos.log) and [C1 unittest log (12 passed)](c1_unittest_macos.log)
- [SHA-256 manifest](MANIFEST.sha256)

## 5. What remains unproven (requires user physical hardware run)

To complete the physical C4 gate on the Mac bench (outside the agent sandbox, which blocks `/dev/cu.usbmodem2101`):
1. Run `python3.13 tools/c4/run_c4.py live --serial /dev/cu.usbmodem2101 --out docs/ble-id/runs/c4-live-$(date -u +%Y%m%dT%H%M%SZ)` in a native macOS Terminal while filming phone + Mac display in one frame.
2. Follow the prompts for the four 60 s E3 captures (`1m`, `3m`, `5m`, `obstruction`), the four 60 s E4 lifecycle captures (`foreground`, `background`, `locked`, `force_quit`), and the 20 E2 Start-to-verified trials at 1.0 m (where the runner automatically waits for the next 30 s UTC window between trials so replay state is never reset).
Note: `ios/BeaconC1/BeaconC1/BeaconC1App.swift` lines 50–52 explicitly stop advertising on `.background` (`if phase == .background { adv.stop() }`), so `background` and `locked` captures in the C1 app test that foreground-only cutoff as well as iOS background behavior.

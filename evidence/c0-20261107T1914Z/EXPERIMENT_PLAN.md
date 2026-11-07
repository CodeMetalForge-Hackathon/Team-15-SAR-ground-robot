# C0 experiment plan: BLE ID module

Status: **PLAN ONLY.** Nothing here has been run. Every result is "not measured"
until a later checkpoint publishes raw data. Sample sizes, targets, and
recording rules come from `SENSOR_ID_SPEC.md`. Where Amendment 1 (PROPOSED)
would change something, it is marked [A1].

## 0. Prerequisites (each one blocks the experiments that need it)

| Item | Needed for | Status at C0 |
| --- | --- | --- |
| iPhone: exact model and iOS version | E1 to E4 | UNKNOWN: record at C1 |
| Mac with Xcode, Apple ID signing for that iPhone, Developer Mode on | E1 to E4 | UNKNOWN |
| BLE-capable ESP32 board (e.g. ESP32-C3/S3/C6) and data USB cable | E1 to E4 | UNCONFIRMED. The build plan lists two Seeed boards of unknown type; identify via silkscreen / `esptool.py chip_id` |
| `arduino-cli`, Arduino ESP32 core, NimBLE-Arduino (versions pinned) | E1 to E4 | Not installed; download before going offline |
| Python 3.11 (matches CI) with `pyserial` | E0 to E4 | `pyserial` not in `requirements.txt` (request R5) |
| Tape measure, masking tape, one fixed obstruction, second phone for filming | E2 to E4 | UNKNOWN |
| Local dashboard (t2 branch) | E2, E4 dashboard shots | Available, but live BLE posting is BLOCKED by request R1 |

## E0. Software experiment (C2, SIMULATED)

- **Input:** `protocol_vectors_v1.json` plus a fixed-seed generator.
- **Trials:** at least 100 per classification and per loss scenario. That's
  verified, replay (stale, future, duplicate, not_newer), forged, unknown,
  dropped-malformed, and simulated packet loss.
- **Clock:** injected; no sleeps. Latency is host receive-to-decision, measured
  with `time.perf_counter_ns()` (monotonic), 10 warmup calls excluded.
- **Report:** input counts, confusion matrix, rejection reasons, p50/p95
  latency, CPU model, Python version, workload size.
- **Pass:** 100% of fixtures classified as expected, and zero invalid
  verified decisions. [A1] Exactly one observation per verified decision and
  zero for everything else.
- **Not claimed:** a cryptographic false-accept rate; radio or phone latency.

## E1. Carrier feasibility (C1, REAL HARDWARE, foreground only)

Question: does one 128-bit service UUID from a foreground iOS app reach a
passive ESP32 byte-for-byte, and is rotation visible?

1. **Static stage.** The app advertises the fixed UUID of vector F1/A1,
   `01010390-83cc-c438-cfa7-043609b9d1c4`, with no local name. The ESP32 does a
   passive NimBLE scan (`setActiveScan(false)`, duplicate filter recorded) and
   prints raw rows.
   **Pass:** at least one capture whose UUID equals the vector exactly. Also
   record the raw advertisement bytes, to check the expected on-air
   little-endian order `c4d1b909...030101`.
2. **Rotating stage.** The app computes tokens with the synthetic key for
   alias 1. Capture at least 3 consecutive 30 s windows.
   **Pass:** a distinct UUID in each window matching the host's recomputation,
   even if the phone's MAC address does not change.
3. **Fail rule.** If iOS drops, truncates, or rewrites the UUID, record it as
   `test(ble-id): record UUID transport failure` and propose a format
   revision. Never shorten the tag or simulate reception.

Evidence: build logs (Xcode, `arduino-cli compile`), raw serial capture with
host UTC and monotonic timestamps, and a feasibility video (mandatory).

## E2. Discovery latency (C4, REAL HARDWARE)

- **Setup:** 1 m, unobstructed, line of sight, phone upright, distance
  tape-measured. Record phone/OS, board, power source, and scan settings.
- **Trials:** 20 timed trials. Each one goes from tapping Start to the first
  verified decision, with a 10 s timeout, and the app is stopped for at least
  30 s between trials.
- **Timing:** film the phone screen and the host display in one frame with a
  second phone at ≥30 fps, giving about ±33 ms resolution. Synchronized device
  clocks aren't needed.
- **Target:** at least 19/20 within 10 s. Report every timeout and the full
  latency distribution (min, p50, p95, max).

## E3. Reception captures (C4, REAL HARDWARE)

- **Captures:** 60 s each at 1 m, 3 m, 5 m, plus one behind a described
  obstruction (material, thickness), same orientation.
- **Record:** reception count, distinct verified windows, decision counts by
  reason, and the RSSI distribution (min, median, max).
- **Not reported:** packet delivery ratio (the iPhone's transmit count is
  unknown), distance estimates, or anything about rubble. Missing setups are
  UNTESTED.

## E4. App lifecycle (C4, REAL HARDWARE)

- **Captures:** 60 s each in foreground, background, screen locked, and after
  a force-quit, with each transition visible on video.
- **Prediction (from Apple docs, not measured):** only foreground is
  identifiable by a non-Apple receiver. Results are labelled by exact phone
  and OS. UNSUPPORTED is used only where a limitation is established;
  otherwise UNTESTED.
- **Battery:** no claims; not measured.

## E5. Receive-only scanner (all checkpoints)

Evidence is limited to the firmware configuration (passive scan, no
advertising, no connections, Wi-Fi off) and the source listing. Without a
sniffer, the report says "configuration-level only, no RF verification".

## Recording format (all runs)

Each run directory holds:
- run ID, tested commit plus dirty-diff hash, commands, exit codes, and tool
  versions
- the raw serial capture and the decision log (alias, counter, tag, decision,
  reason, monotonic and UTC time; **never keys**)
- metrics CSV/JSON and REPORT.md

Videos stay outside Git, recorded with link and SHA-256. Failures and skipped
runs are recorded. Missing values are never written as zero.

## Schedule conflict to resolve with the team

The build plan time-boxes BLE to 60 minutes (H+4 to H+5, hard stop) with a
STAND-IN beacon fallback, and BLE is fourth in the cut order. E1 to E4 as
specified need several hours of hardware time (rough estimate, not measured).
The team needs to decide whether to allot that time, cut to E1 plus E2, or
leave BLE to Teammate D's plan.

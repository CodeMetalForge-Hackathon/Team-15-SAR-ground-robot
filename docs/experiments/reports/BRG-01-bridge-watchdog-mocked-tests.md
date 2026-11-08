# BRG-01: USB-serial StickC bridge and firmware watchdog (mocked tests)

**Label: MOCKED** (a Python model of the firmware; simulated clock) · **Status: COMPLETE** for the model (63/63 pass). The real firmware has **NOT RUN**: never compiled, never flashed
Back to: [13 M5StickC bridge](../../13_M5STICKC_BRIDGE.md) · [17 Safety architecture](../../17_SAFETY_ARCHITECTURE.md) · [Bridge protocol](../../rover/BRIDGE_PROTOCOL.md)

## In one paragraph (plain language)

The RoverC-Pro's motor chip probably keeps spinning the wheels at their last speed if it stops hearing from anyone. So we designed a small program for the M5StickC that sits between the Raspberry Pi and the motor chip, and stops the wheels by itself if the Pi goes quiet for a quarter of a second. We couldn't run that program on the real StickC: the board was never detected, and the compiler wasn't installed. Instead we wrote a Python copy of it and tested the Pi's side against that copy, 63 different ways. Examples: cutting the cable mid-motion, sending corrupted messages, restarting the Pi program, pressing the stop button, and making the motor bus fail. In the copy, the wheels always stopped within the quarter-second budget, and nothing ever started moving again without a person re-arming it. Whether the real board behaves the same is unknown until it is flashed and measured.

## 1. Objective and hypothesis

- **Objective:** validate the bridge *design* (protocol, arming, sessions, watchdog, fault handling) and the Pi-side `BridgeTransport` before any hardware exists.
- **Hypothesis:** with the firmware model, every link or frame fault leads to zeroed motors, a state that needs an explicit operator re-ARM, and on the host a refused or latched (`DRIVER_FAULT`) supervisor. The model's watchdog trips at ≤ 300 ms after the last accepted frame.
- **Pass criteria:** all tests in `rover/tests/test_bridge.py` pass. The watchdog trip is > `WATCHDOG_MS − 1` and ≤ 300 ms (`test_firmware_watchdog_zeroes_within_300ms_of_last_frame`).

## 2. Date, place, people (by role)

| Run | Date | Revision | Result |
|---|---|---|---|
| R1 | 2026-11-08 (~10:31–10:45 UTC; `530de47`, then review fixes `dbc17b3`) | PR #15 head | rover/tests **284 passed**; `pytest -q` **443 passed**; ranging **126 passed** (PR #15 description). An intermediate run during the review fixes had **1 failed, 62 passed** (`test_partial_i2c_write_counts_as_unknown_output_and_zero_is_retried`, before the model fix); session console log, 2026-11-08 10:42 UTC |
| R2 | 2026-11-08 ~12:50 UTC | d1b607a | **63 passed**; timing probes in §7 |

PR #15 was merged 2026-11-08 12:11:52 UTC (`89a0e81`), stacked on PR #14. Author: GitHub `machackgo`. A separate reviewer session reviewed `530de47`.

## 3. Hardware

None. `FakeI2C` (a register dict with failure and partial-write injection) and `LoopbackPort` (with an optional one-read reply delay and a cut). **No M5StickC, no RoverC.** The real controller was never detected ([ROV-02](ROV-02-controller-connectivity-inspection.md)).

## 4. Software

- d1b607a. `rover/bridge.py` (sha256 prefix `bb5c0248fa310dec`), `rover/tests/bridge_model.py` (`71c2ad90396d2532`), `rover/tests/test_bridge.py` (`35ed8d6b223720ab`). The firmware under design is `firmware/stickc_roverc_bridge/stickc_roverc_bridge.ino` (`86053004fec3cad6`): **not executed**.
- End-to-end cases use the real `SafetySupervisor` and `RoverCAdapter`, with a `HardwareVerification` test fixture whose wheel mapping evidence reads `"TEST FIXTURE - not a real bench result"`.

## 5. Data and ground truth

Synthetic frames and timed events. The ground truth is the design rules in [BRIDGE_PROTOCOL.md](../../rover/BRIDGE_PROTOCOL.md) and the `.ino` header comments.

## 6. Metrics and why they were chosen

| Metric | Why |
|---|---|
| Pass/fail per property | each test is one safety rule |
| Watchdog trip latency (model) | the bench requirement is ≤ 300 ms; the design value is 250 ms |
| Host latch latency after a cable cut | the Pi must stop commanding immediately, not wait for the firmware |
| Final register values | "motors zero" is the physical outcome that matters |

## 7. Results

**63/63 pass (R2).** Coverage by group:

| Group | Examples |
|---|---|
| Protocol and parsing | CRC check value `0xF4`; bad CRC, malformed, oversize and whitespace lines dropped; speed > 100 and bad sessions refused before sending; `*`/newline injection refused; malformed motor frames never move |
| Arming and sessions | boot zero and DISARMED; `M` refused until armed; named operator required; each transport has its own session; a restarted process cannot drive the old ARM; USB reconnect needs a re-ARM even inside the watchdog window |
| Watchdog | zeroes within 300 ms; re-ARM needed afterwards; corrupted frames, pings, refused and unknown frames don't feed it; the stopped supervisor keeps it fed with `Z` |
| Faults | button e-stop; a remote ARM cannot clear the local e-stop; I²C error; partial write → output unknown, zero retried every 20 ms, watchdog counts once; boot with a failing bus → I2CERR with retries; a hung firmware → host `DRIVER_FAULT` |
| Host transport | `health()` fails when acks stop; ack timeout > 0.30 s refused; seq matching; late NAK surfaces on the next write; stale buffered acks don't look fresh; foreign replies ignored; `open_serial` refuses non-by-id paths and deasserts DTR/RTS before opening |
| End to end | supervisor → adapter → bridge → model; cable pull stops both sides; STOP sends `Z`; a disarmed bridge blocks the supervisor; supervisor restart can't resume without an operator |

(Groups are for reading only; the exact total is 63 collected tests, including parametrised cases.)

**Timing probes (R2, MOCKED, simulated clock):**

| Probe | Result |
|---|---|
| Model watchdog trip after the last accepted `M` frame (1 ms steps) | **0.251 s** |
| End to end, forward 0.2 then cable cut, 50 ms supervisor tick: host latch | **0.05 s** (`DRIVER_FAULT`, "serial port disconnected") |
| End to end, same: firmware model WDSTOP with all registers zero | **0.30 s** after the cut (on the 50 ms step grid) |
| Registers while moving at forward 0.2 with the test-fixture mapping (1, 1, 1) | (20, 20, 20, 20) |

## 8. Failures and interpretation

- **Fixed during development.** The first firmware version wrote zero only after `M5.begin()`, so a reset while moving would leave the wheels running. This was the review's blocker, and it is fixed: zero is now written first. Partial I²C writes were not modelled, and the model/`.ino` diverged; both are fixed. The intermediate 1-failed run (R1) was the partial-write test exposing the model gap.
- **Interpretation.** The design meets its own rules *in the model*. The 0.251 s trip is the model's `millis()` arithmetic on a simulated clock. A real ESP32 adds loop jitter, the I²C timeout (up to 20 ms) and the STM32's response time, none of them measured.

## 9. Evidence files

| Evidence | Where |
|---|---|
| Tests and model | `rover/tests/test_bridge.py`, `rover/tests/bridge_model.py` (in repo) |
| Firmware draft | `firmware/stickc_roverc_bridge/stickc_roverc_bridge.ino` (in repo; not executed) |
| R1 | PR #15 description; session console log, 2026-11-08 10:42 UTC (intermediate failure) |
| R2 | regenerated; probe script not stored (it uses `rig`, `stack`, `feed` and `run` from `rover/tests/test_bridge.py`) |

## 10. Limitations and confounders

- **Model ≠ firmware.** The lockstep is maintained by hand. Display, DTR/RTS reset, download mode, the task watchdog and real I²C timing are explicitly not modelled.
- The `.ino` has never been compiled: syntax and API errors (for example the ESP32 core 2.x vs 3.x task-watchdog API) are possible.
- The CRC is not authentication.
- The simulated clock hides real-time scheduling effects.

## 11. Reproducibility

```bash
python3 -m pytest -q rover/tests/test_bridge.py          # 63 passed
python3 -c "from rover.bridge import crc8; print(hex(crc8(b'123456789')))"
```

Deterministic, except that session IDs are random (`secrets.token_hex`); no test depends on their value.

## 12. What this proves / does NOT prove

**Proves:** the protocol and the Pi-side transport are internally consistent with the firmware *design*; there is no tested path to ARMED without an explicit operator ARM; every modelled link fault ends with zeroed (model) registers and a latched host.

**Does NOT prove:** that the firmware compiles, runs or zeroes a real RoverC; the real link-loss stop time (`stop_on_link_loss_ms` stays unmeasured); behaviour on reset or in download mode; anything about the real controller, which was **NOT DETECTED**.

## 13. What we would change next time

- Get `arduino-cli` installed early and compile in CI for at least one StickC target, so the `.ino` has a "compiles" check.
- Generate the parser tables for both the `.ino` and the model from one spec, to remove the hand-maintained lockstep.
- Bench order: flash with the RoverC off → dry run → wheels-lifted link-loss timing with a high-speed video.

# Pi → M5StickC → RoverC-Pro USB-serial bridge

Status: **design plus mocked tests only.** The firmware has not been compiled, flashed or run. No motor has been commanded. Flashing needs separate approval, with the RoverC power switch **OFF**.

## Why a bridge
- **Who drives the motors:** the RoverC-Pro's STM32 (I²C `0x38`, motor registers `0x00–0x03`, INT8) is driven over I²C by the M5StickC plugged into it. The Pi has no path to it today, and wiring the Pi into the same I²C bus would give it two masters.
- **No motor-side watchdog:** the RoverC documents none. If the link dies, assume the wheels hold their last speed.
- **The fix:** the StickC runs small firmware that takes commands from the Pi over **USB serial**. It zeroes the motors itself if valid frames stop.

```
Pi: Navigator → SafetySupervisor → RoverCAdapter → BridgeTransport ──USB serial──▶ StickC firmware ──I²C──▶ RoverC STM32
                     ▲  health() = last ack fresh (≤ 0.30 s) and ARMED                │ watchdog 250 ms → ZERO
                     └── DRIVER_FAULT latch, operator reset + re-approval             │ button A → ZERO (ESTOP)
```

## Frames
ASCII lines with CRC-8 (polynomial 0x07, check value `F4` for `123456789`) over everything before `*`, written as 2 hex digits.

| Direction | Frame | Meaning |
|---|---|---|
| Pi → MCU | `M,<seq>,<s0>,<s1>,<s2>,<s3>*CC` | Motor speeds for registers 0x00–0x03, each −100…100. ARMED only. |
| Pi → MCU | `Z,<seq>*CC` | Zero all motors. Allowed in every state. Feeds the watchdog. |
| Pi → MCU | `A,<seq>,<operator>*CC` | ARM. Writes zero first. Needed after boot, WDSTOP or ESTOP. |
| Pi → MCU | `P,<seq>*CC` | Status request. |
| MCU → Pi | `K,<seq>,<state>,<wd_trips>,<i2c_errs>*CC` | Ack. |
| MCU → Pi | `N,<seq>,<reason>*CC` | Refused: `not-armed-<STATE>`, `range`, `bad-speed`, `i2c` or `unknown`. |

**States:** `BOOT → DISARMED → ARMED`. From ARMED the firmware can drop to `WDSTOP`, `ESTOP` or `I2CERR`, and all three need a re-ARM.

## Safety rules (firmware)
1. `setup()` writes zero to the motors **before** opening the serial port. The firmware starts DISARMED.
2. A non-zero `M` is refused unless ARMED. Anything above ±100 is refused.
3. **Watchdog:** if no valid frame arrives for **250 ms** while ARMED or with any motor non-zero, the motors go to zero and the state becomes `WDSTOP`. Bad-CRC, malformed or oversized lines never feed the watchdog.
4. **StickC button A** is a local e-stop: zero, then `ESTOP`.
5. An I²C write failure tries to zero the motors and sets `I2CERR`.
6. Only registers `0x00–0x03` are written. Servo registers are never touched.

## Pi side (`rover/bridge.py`)
- **`BridgeTransport`** implements the `Transport` interface that `RoverCAdapter` uses.
  - It accepts only the 4-byte motor block at `0x38/0x00`. Everything else raises `PermissionError`.
  - It sends `Z` for an all-zero block, otherwise `M`.
- **`health()`** returns `""` only while all of these hold:
  - the latest valid ack is ≤ **0.30 s** old;
  - the state is `ARMED`;
  - the last frame wasn't refused.
  Otherwise `SafetySupervisor` refuses motion, and while moving it latches `DRIVER_FAULT` (Issue #9 / PR #14).
- **Keepalive:** the supervisor's `tick()` re-applies its output every cycle (`Z` while stopped), which keeps the firmware watchdog fed while the Pi is healthy.
- **`arm(operator)`** is an explicit operator action. Nothing arms automatically.
- **`open_serial()`** accepts only a `/dev/serial/by-id/...` path and imports pyserial lazily. Tests never call it.

## Tests (mocked hardware)
`rover/tests/test_bridge.py` runs against `rover/tests/bridge_model.py`, a line-for-line Python model of the `.ino`. It covers:
- **Protocol:** the CRC check value, rejection of malformed frames, and refusal of injected frames.
- **Arming:** boot is zero and DISARMED; motion is refused until ARMED.
- **Watchdog:** it zeroes **≤ 300 ms** after the last frame; corrupted frames don't feed it; a re-ARM is needed after a trip.
- **Faults:** the button e-stop, I²C errors, and ack loss making `health()` fail.
- **End to end:** supervisor → adapter → bridge → firmware model. A cable pull zeroes the motors on the firmware side **and** latches `DRIVER_FAULT` on the host, with no auto-restart.

## Remaining before any wheel test
1. Identify the StickC model (StickC, Plus or Plus2). Confirm the hat pin map and the M5Unified board support.
2. Compile the sketch with `arduino-cli`, which isn't installed on this Mac. Then review it against `bridge_model.py`.
3. **With approval:** flash it with the RoverC switched off. Then do a dry run with the RoverC off: ARM, `M`, cut the link, and confirm `WDSTOP` from the acks and the screen.
4. With the wheels lifted, measure the link-loss stop time and record it in `HardwareVerification.stop_on_link_loss_ms`. It must be ≤ 300 ms.

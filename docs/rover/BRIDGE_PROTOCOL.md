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
| Pi → MCU | `M,<seq>,<session>,<s0>,<s1>,<s2>,<s3>*CC` | Motor speeds for 0x00–0x03, each −100…100. Accepted only while ARMED **by this session**. |
| Pi → MCU | `Z,<seq>*CC` | Zero all motors. Allowed in every state. Feeds the watchdog. |
| Pi → MCU | `A,<seq>,<operator>,<session>*CC` | ARM this session. Succeeds only if the zero write is confirmed on the bus. Needed after boot, WDSTOP, ESTOP, I2CERR or a foreign-session frame. |
| Pi → MCU | `P,<seq>*CC` | Status request. |
| MCU → Pi | `K,<seq>,<state>,<session>,<wd_trips>,<i2c_errs>*CC` | Ack. `session` is `-` when nothing is armed. |
| MCU → Pi | `N,<seq>,<reason>*CC` | Refused: `not-armed-<STATE>`, `session`, `range`, `bad-speed`, `i2c` or `unknown`. |

`<session>` is 8 random lowercase hex characters, new for every `BridgeTransport`. The transport also rotates it after any port error, so a restarted, second or reconnected Pi process can never drive motors that an earlier one armed. A motor frame from another session zeroes the motors and **disarms**.

**States:** `BOOT → DISARMED → ARMED`. From ARMED the firmware can drop to `WDSTOP`, `ESTOP` or `I2CERR`, and all three need a re-ARM.

## Safety rules (firmware)
1. **Zero first:** `setup()` writes zero to the motors **first**, before `M5.begin()` (display, PMIC and IMU init can take hundreds of ms), and again after it.
   - The firmware starts DISARMED, or `I2CERR` if the zero can't be confirmed.
   - The output counts as *unknown* until a zero is confirmed.
2. **Arming:** a non-zero `M` needs ARMED **by the same session**, and every speed must be an integer within ±100.
   - Empty fields, non-numeric speeds and out-of-range speeds are refused, and also zero the motors.
   - ARM succeeds only with a confirmed zero.
3. **Watchdog**, running on the StickC's own `millis()` and independent of the Pi's heartbeat watchdog in `SafetySupervisor`:
   - If no **accepted** `Z`/`M` (or a successful ARM) arrives for **250 ms** while ARMED, the motors go to zero and the state becomes `WDSTOP`.
   - Pings, refused, unknown, bad-CRC, malformed and oversized frames never feed it.
   - At most 256 serial bytes are read per loop, so the watchdog check always runs.
4. **Unknown output:** any failed I²C write marks the output *unknown*, because bytes may have landed. Zero is then retried every 20 ms until it's confirmed. The I²C timeout is 20 ms.
5. **Local e-stop:** StickC **button A** zeroes the motors and sets `ESTOP`.
   - Only a **local** long press on **button B** (≥ 1 s) clears it, and only to DISARMED.
   - An ARM from the Pi is refused while in ESTOP.
6. **Task watchdog (1 s):** a hung `loop()` resets the chip, and rule 1 then zeroes the motors first.
7. Only registers `0x00–0x03` are written. Servo registers are never touched.

### Residual hardware risks (not fixable in firmware: bench-test before any floor motion)
- **The RoverC STM32 holds the last speeds.** In two situations nothing but the **RoverC power switch** stops the wheels:
  - between an ESP32 reset and the first zero write in `setup()`;
  - in ESP32 **download mode**. G0 is both SDA and a boot strapping pin, and on StickC boards the USB-UART auto-program circuit drives it.
- **Mitigation:** the Pi opens the port with **DTR/RTS deasserted** (`open_serial`), and nothing else may open the port.
- **Bench tests, wheels lifted:**
  - reset the StickC while the wheels spin;
  - unplug and replug USB while they spin;
  - pull power to the StickC alone, if possible;
  - hold G0 low at reset, which should give download mode: confirm the RoverC switch is the only stop, and that it works.
- **Board-specific checks:** whether Arduino `Wire` (I²C port 0) conflicts with M5Unified's `Ex_I2C` on the identified board, and the task-watchdog API, which differs between ESP32 Arduino core 2.x and 3.x.

## Pi side (`rover/bridge.py`)
- **`BridgeTransport`** implements the `Transport` interface that `RoverCAdapter` uses.
  - It accepts only the 4-byte motor block at `0x38/0x00`. Everything else raises `PermissionError`.
  - It sends `Z` for an all-zero block, otherwise `M`.
- **Reply matching:** replies are matched to the frames they answer by seq. Foreign or out-of-order replies are ignored. A refusal of frame *n* surfaces as an `IOError` on a later write, which latches `DRIVER_FAULT`.
- **`health()`** returns `""` only while all of these hold:
  - the latest matched ack answers a frame **sent** ≤ **0.30 s** ago, so stale acks buffered during a Pi stall don't count;
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

## Read-only USB detection, for when the StickC is plugged into the Pi
Preconditions: the **RoverC power switch is OFF**, the StickC is connected with a **data** USB-C cable, and nobody presses its buttons.
These commands only read sysfs, the kernel log and udev metadata. They never open the serial port: opening it can toggle DTR/RTS and reset the ESP32. Run them from the Mac:
```
ssh team15-pi 'lsusb; echo; lsusb -t'
ssh team15-pi 'for d in /sys/bus/usb/devices/*; do [ -f $d/idVendor ] || continue; echo "$(basename $d) $(cat $d/idVendor):$(cat $d/idProduct) [$(cat $d/manufacturer 2>/dev/null) / $(cat $d/product 2>/dev/null)] serial=$(cat $d/serial 2>/dev/null) speed=$(cat $d/speed)M maxpower=$(cat $d/bMaxPower)"; done'
ssh team15-pi 'ls -l /dev/serial/by-id/ /dev/ttyUSB* /dev/ttyACM* 2>&1'
ssh team15-pi 'journalctl -k -b --no-pager | grep -iE "new (full|high)-speed usb|idVendor|ftdi|ch34|cp210|cdc_acm|ttyUSB|ttyACM|disconnect" | tail -20'
ssh team15-pi 'for t in /dev/ttyUSB* /dev/ttyACM*; do [ -e $t ] && udevadm info -q property -n $t | grep -E "^(ID_VENDOR|ID_VENDOR_ID|ID_MODEL|ID_MODEL_ID|ID_SERIAL|ID_USB_DRIVER|ID_PATH)="; done'
ssh team15-pi 'journalctl -u ModemManager -b --no-pager | tail -5'   # did ModemManager touch the new port?
```
Typical USB-serial bridges (to be confirmed against the actual board and label):
- FTDI FT231X `0403:6015`, often on the original StickC and the StickC Plus;
- WCH CH9102 `1a86:55d4`, or CH340 `1a86:7523`, often on the StickC Plus2.

The result is recorded in `HardwareVerification.controller_model` / `link`, with the stable `/dev/serial/by-id/...` path.

**Don't use** `screen`, `minicom`, `cat`/`stty` on the tty, `esptool` (it resets the chip) or the Arduino IDE's serial monitor. Any of them opens the port.

**ModemManager** is active on the Pi with its default filter. It normally ignores generic USB-serial bridges, but if its log shows it probing the new port, stop and ask: a udev ignore rule would be a configuration change and needs approval.

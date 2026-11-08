# ROV-02: M5StickC / RoverC-Pro controller connectivity, read-only inspection (and ROV-03: blocked first wheel tests)

**Label: REAL HARDWARE** (read-only inspection of the real Pi 5 and Mac) · **Status: COMPLETE (inspection) — result NOT DETECTED** · ROV-03 first wheel test: **NOT RUN** (blocked at detection, twice)
Back to: [13 M5StickC bridge](../../13_M5STICKC_BRIDGE.md) · [12 RoverC motor control](../../12_ROVERC_MOTOR_CONTROL.md) · [Hardware readiness](../../rover/HARDWARE_READINESS.md)

## In one paragraph (plain language)

To drive the wheels, the Raspberry Pi has to "see" the M5StickC controller over USB, the way a laptop sees a phone when you plug it in. We checked eight times, on the Pi and on the Mac, over two days, using only commands that look and never touch: listing USB devices, listing serial ports, reading the kernel log. The controller never appeared. On two of those occasions the operator had just said the controller was plugged in, and asked for the first wheels-off-the-ground test. Both times the test stopped at this first step, before any motor command, because there was nothing to talk to. The most likely reasons are a cable that only charges, or the controller plugged into a hub or power bank rather than the Pi. We can't confirm which. The Pi also rebooted twice in half an hour while running on a weaker power source.

## 1. Objective and hypothesis

- **Objective:** determine whether a motor-control interface to the RoverC-Pro (the M5StickC as a USB-serial device, or anything at I²C 0x38) is reachable from the Pi or the Mac, without transmitting anything.
- **Hypothesis (when the operator reported the StickC as connected):** the Pi's `lsusb` shows a USB-UART bridge (for example FTDI `0403:6015`, WCH CH9102 `1a86:55d4` or CH340 `1a86:7523`), and `/dev/serial/by-id/...` exists.
- **Pass criteria:** a USB VID:PID and a stable by-id path are recorded, so `HardwareVerification.controller_model` and `link` can be filled.

## 2. Date, place, people (by role)

All checks ran from the Mac (or on the Pi over SSH), run by the AI coding assistant at the project owner's request. Times are UTC, from the session console log; the Pi's local time was EST (UTC−5).

| # | When (UTC) | Host | Context |
|---|---|---|---|
| C1 | 2026-11-07 23:27 | Mac | rover-navigation set-up |
| C2 | 2026-11-07 23:49 | Pi | hardware-readiness inspection (basis of [HARDWARE_READINESS.md](../../rover/HARDWARE_READINESS.md)) |
| C3 | 2026-11-07 23:49 | Mac | same inspection |
| C4 | 2026-11-08 00:46 | Pi | separate robotics workspace, stage 1 read-only discovery (`$ROBOT_WORKSPACE/IMPLEMENTATION_JOURNAL.md`, "19:46 ET") |
| C5 | 2026-11-08 10:22 | Pi | before the bridge PR |
| C6 | 2026-11-08 11:38 | Mac | **first wheel-test request** (the operator reported the StickC "connected using a USB cable") |
| C7 | 2026-11-08 11:46 | Pi | Pi reconnection after it went offline |
| C8 | 2026-11-08 12:28 | Pi | **second wheel-test request** ("now physically connected to the Raspberry Pi 5") |

## 3. Hardware

- Raspberry Pi 5 Model B Rev 1.1, kernel 6.18.60+rpt-rpi-2712, IMX708 camera, Hailo-8 HAT.
- MacBook Pro (Apple silicon).
- M5StickC-family controller on the RoverC-Pro. Model **UNKNOWN** (StickC, Plus or Plus2): it was never enumerated, and the label was not read into the record. A session description of an operator photo (photo not archived as evidence and not published) mentions an orange StickC-family unit with its screen on, running unknown factory firmware.

## 4. Software

Read-only commands only. Nothing opened a serial port (opening one can toggle DTR/RTS and reset the ESP32). There was no `i2cdetect` (it transmits) and no Bluetooth scan (it transmits). The commands used: `lsusb`, `lsusb -t`, sysfs reads under `/sys/bus/usb/devices`, `ls /dev/serial/by-id /dev/ttyUSB* /dev/ttyACM*`, `/sys/bus/i2c/devices`, `config.txt` greps, `journalctl -k`, `vcgencmd`, and on the Mac `ioreg -p IOUSB`, `system_profiler SPUSBDataType` and `ls /dev/cu.*`. The command set is documented in [BRIDGE_PROTOCOL.md](../../rover/BRIDGE_PROTOCOL.md) ("Read-only USB detection").

## 5. Data and ground truth

Ground truth = the physical connection, as the operator reported it. For C6 and C8 the operator stated the controller was connected. For C1–C5 no connection was claimed. There is no independent record (photo of the port, cable type) of what was actually plugged where.

## 6. Metrics and why they were chosen

The metric is binary: is a candidate USB-serial device enumerated (VID:PID + by-id path)? Secondary: Pi power state (`get_throttled`, EXT5V, supply current limit, uptime), because a brown-out can explain a device not enumerating, and because no motor test may run on unstable power.

## 7. Results

| # | USB devices (beyond root hubs) | Serial devices | I²C | Power / other | Verdict |
|---|---|---|---|---|---|
| C1 | (Mac) none in `system_profiler` | `/dev/cu.Bluetooth-Incoming-Port`, `/dev/cu.debug-console` only | n/a | — | NOT DETECTED |
| C2 | none (4 root hubs) | no `/dev/ttyUSB*`, `/dev/ttyACM*`, `/dev/serial/by-id` | `i2c-11` (IMX708 0x1a, VCM 0x0c), `i2c-13`, `i2c-14`; header `i2c-1` **not enabled**; nothing at 0x38 | `EXT5V_V` 5.229 V, `throttled=0x0` | NOT DETECTED |
| C3 | (Mac) only the built-in USB host controllers in `ioreg` | — | — | — | NOT DETECTED |
| C4 | root hubs only, "no StickC / serial bridge attached" | none | I²C1 not enabled; GPIO2–27 unclaimed; no HAT EEPROM | throttled 0x0, EXT5V 5.18 V | NOT DETECTED |
| C5 | none | none | "header I2C not enabled in config.txt" | up 66 s; throttled 0x0; 5.17 V | NOT DETECTED |
| C6 | (Mac) `system_profiler`: none; Pi **unreachable** (SSH timed out; a bounded 3-minute wait) | Mac `/dev/cu.*`: Bluetooth and debug console only | — | Pi offline | NOT DETECTED |
| C7 | none | none | — | **up 2 min** (rebooted); throttled 0x0; 5.08 V; **supply current limit 3000 mA** (5000 mA on the 27 W wall supply earlier) | NOT DETECTED |
| C8 | **"no USB devices"**; the kernel logged no attach attempt or descriptor error | **"no serial tty"** | — | **up < 1 min** (second reboot in ~30 min; reset code `0x1000`); throttled 0x0; 0 undervoltage messages; 5.11 V; 3000 mA | NOT DETECTED |

**ROV-03 (first wheel test): NOT RUN.** Both requests (C6, C8) stopped before any motor step. **No motor command was sent, no serial port was opened and no firmware was flashed.** The blockers listed in the session reports:

| Blocker | C6 | C8 |
|---|---|---|
| Pi reachable | no (offline) | yes, after a retry |
| Controller enumerated | no | no |
| Bridge watchdog firmware installed | no (unknown factory firmware) | no |
| PRs #14/#15 merged or deployed to the Pi | no | no (merged to main ~12:11 UTC, not deployed) |
| Battery measured, `min_voltage_v` set | no | no |
| Grove forward range available (needed for `MOVE_FORWARD`) | no | no |
| Wheels raised | no (per the photo description) | not confirmed |
| Physical e-stop rehearsed | no | no |

## 8. Failures and interpretation

- **Root cause of non-detection: UNKNOWN.** Hypotheses from the session, none verified: (a) the StickC was plugged into the USB-C hub or power bank, not a Pi port (the photo description suggested the cable led that way); (b) a charge-only USB-C cable; (c) a port without data. An empty USB bus with **no** kernel attach or descriptor error (C8) fits (a) or (b) better than a flaky data connection, which usually logs errors.
- **Pi power instability.** Two reboots within ~30 minutes on a 3 A source (C7, C8). The likely contributor is the 600 mA combined USB limit on a 3 A supply, with a StickC charging current, but this is **UNVERIFIED**: the journal does not persist across reboots. Earlier on the 27 W wall supply the Pi reported 5000 mA and no reboots. (A separate LiDAR session that morning recorded the operator correcting an earlier assumption: a 03:22 local reboot was intentional, not a power fault. Power evidence must be read carefully.)
- **The software gates behaved as designed.** Even with the controller detected, the supervisor would have refused motion (no power threshold, no Grove reading, `HardwareVerification` empty).

## 9. Evidence files

| Evidence | Where | sha256 |
|---|---|---|
| Inspection C2/C3 summary | [docs/rover/HARDWARE_READINESS.md](../../rover/HARDWARE_READINESS.md) §2 (addresses redacted) | in repo |
| C1, C2, C3, C5–C8 raw outputs | session console log (Claude Code transcript of the rover-navigation session), 2026-11-07 23:27 – 2026-11-08 12:29 UTC | not published (private transcript) |
| C4 | `$ROBOT_WORKSPACE/IMPLEMENTATION_JOURNAL.md` and `TEST_REPORT.md` ("Staged physical validation", stage 1) | private workspace, not in Git |
| Related Pi guard run (pinctrl before/after identical; "No `/dev/ttyUSB*` / `/dev/ttyACM*` present") | `$TEAM15_EVIDENCE/robot_pi_sim_run/pinctrl_before.txt`, `pinctrl_after.txt` | both `0efa17c778d1aac7ad257f78529b09ea74dd692b071919caf336f80ef68de9da` |

`$TEAM15_EVIDENCE` and `$ROBOT_WORKSPACE` are private local stores on the developer Mac. They are not in the repository.

## 10. Limitations and confounders

- No photo or written record of which port and cable were used for C6 and C8.
- The Pi was power-cycled between checks, which changes USB state.
- The Mac checks tell us only that the StickC was not on the Mac. They say nothing about where it was.
- The checks deliberately avoid transmitting. That is safe, but it means a device present on an un-enumerated bus (for example I²C1, which is disabled) would not be found. That is by design, because the Pi must not join the RoverC I²C bus.

## 11. Reproducibility

Run only with the RoverC power switch **OFF**, a known data cable, the StickC in a Pi USB port and nobody touching its buttons. Use the read-only commands in [BRIDGE_PROTOCOL.md](../../rover/BRIDGE_PROTOCOL.md) (with `$PI_HOST` for the Pi). **Do not** use `screen`, `minicom`, `cat`/`stty`, `esptool` or a serial monitor: they open the port.

## 12. What this proves / does NOT prove

**Proves:** at each of the eight times listed, no USB-serial controller was enumerated on the inspected host, and the Pi's header I²C bus was disabled. So **no software path to the RoverC motors existed**, and no wheel could have been commanded by our code.

**Does NOT prove:** that the StickC is faulty; which cable or port was used; that the bridge design would work. It is also not evidence that any motor test happened. **Real wheel movement: NOT TESTED.**

## 13. What we would change next time

- Before declaring "connected", have the operator confirm three things: the cable carries data (tested with a phone), the StickC is in a **Pi** USB-A port, and the Pi is on the 5 A wall supply. Photograph the port.
- Make the read-only detection a script that prints one line (VID:PID, by-id path, power state), so checks are comparable.
- Enable a persistent journal on the Pi, so reboot causes can be diagnosed.

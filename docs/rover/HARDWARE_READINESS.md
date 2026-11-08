# RoverC-Pro hardware-readiness report

Inspection date: 2026-11-07. Method: **read-only**. No motor command, firmware flash, I²C transaction, GPIO change or physical movement was performed.

## 1. Connectivity
| Check | Result |
|---|---|
| Tailscale | Up. `raspberrypi` is 100.97.93.118, and the Mac is `mohammeds-macbook-pro-539` (100.83.176.118) |
| SSH `team15@100.97.93.118`, key `~/.ssh/team15_pi_ed25519` | **Works**, BatchMode |
| Old hotspot 10.42.0.1 | Not used any more (it refused SSH earlier) |
| Pi | Raspberry Pi 5 Model B Rev 1.1, kernel 6.18.60+rpt-rpi-2712, Wi-Fi `BASE-X Guest` 10.1.200.235/23, eth0 down |

## 2. What is detected on the Pi
| Interface | Detected | Notes |
|---|---|---|
| USB | **Root hubs only**, no devices | So no M5StickC, CH9102, FTDI or CP210x serial bridge |
| Serial | **None**. No `/dev/ttyUSB*`, `/dev/ttyACM*` or `/dev/serial/by-id` | |
| I²C | `i2c-11` (camera CSI: `imx708` at 0x1a, `dw9817-vcm` at 0x0c), `i2c-13` and `i2c-14` (HDMI DDC) | The header bus `i2c-1` is **not enabled** (no `dtparam=i2c_arm=on`). Nothing is on 0x38. I did not run `i2cdetect`, because it transmits. |
| Bluetooth | `hci0` up. **No known or paired devices** | No scan was run, because scanning transmits |
| Wi-Fi neighbours | Only the gateway (Mac and Pi ARP) | No Espressif MAC seen |
| Pi power | `EXT5V_V` = 5.229 V, `get_throttled` = `0x0` (no undervoltage or throttling since boot) | 74 °C SoC. The Pi is mains-powered, so it must not ride on the rover. |
| Ranging service (PR #7) | Not running (no `/dev/shm/team15_range.json`) | Expected, because its wiring isn't signed off |
| User groups | `team15` is in `i2c`, `gpio`, `dialout` | No sudo was needed or used |

The Mac has no USB serial device either. **Neither host has a control interface to the RoverC-Pro.**

## 3. Robot facts: verified or not
| Item | Status | What closes it |
|---|---|---|
| Controller model (StickC / Plus / Plus2) | **UNVERIFIED.** Not connected anywhere | A person reads the label and boot screen, then plugs it into the Mac by USB-C. `ioreg`/`lsusb` give the USB VID:PID (read-only). |
| Controller firmware | **UNVERIFIED** | After the model is known: read the sketch identity from its own serial banner. A chip-ID query resets the ESP32, so it needs approval, with the RoverC switched off. |
| RoverC revision (K036-B, STM32F030) | From documentation only | Visual inspection of the board |
| Motor-control link | **NONE EXISTS** | Decision needed: StickC bridge firmware over USB serial (recommended), with a measured link-loss motor stop |
| MCU-side watchdog | **NOT DOCUMENTED.** Assume the last speed is held | The bridge firmware zeroes the motors when commands stop. Measure the timeout with the wheels lifted. |
| Wheel register mapping and signs | **UNKNOWN** | Wheels-lifted test (runbook step 3) |
| Battery | 16340 700 mAh per the docs. Voltage **unmeasured**; no RoverC battery register | Meter at rest and under load, then choose `min_voltage_v`. Decide whether the StickC PMIC reading reflects the RoverC battery. |
| IMU / heading | **UNVERIFIED.** The StickC has an IMU (MPU6886 or SH200Q, depending on the model), but it hasn't been read or calibrated | Bias calibration, then a 5× 90° protractor test with error ≤ 5° |
| Encoders / odometry | **None** (not in the register map) | Localization stays UNKNOWN, and traveled distance stays UNKNOWN |
| Robot width | **UNMEASURED** (the sim uses a 0.20 m placeholder) | Tape-measure the chassis, wheels and gripper. Set `NavConfig.robot_width_m`. |
| Grove ultrasonic | PR #7 owns it. GPIO5 is proposed; wiring is **not signed off** | PR #7 WIRING.md §4 sign-off |
| Emergency stop | Software e-stop tested in sim. **Physical procedure not rehearsed** | Rehearse it: the operator can reach the RoverC power switch, or lift the robot, within 1 s |

## 4. Sensor integration (done in software, PR #8)
- **PR #7 interface consumed:** `rover/pi_io.py` imports `ranging.rover_io.GroveRangeIO` and reads `team15.rover_range_fields/1`.
- **Stacked dependency:** PR #7's branch (82f5079) is merged into PR #8 unchanged, so **#7 must land first**.
- **`forward_motion_allowed` is enforced twice.** It is ANDed in `rover.sensors.assess()`, and separately in `SafetySupervisor`. The supervisor refuses MOVE_FORWARD and stops ongoing forward motion whenever the latest reading says `false`, even if a caller claims CLEAR.
- **What stops forward motion:**
  - BLOCKED stops it, including BLOCKED at a large range;
  - UNKNOWN, ERROR, stale, malformed and missing readings all stop it;
  - an ERROR reading is stamped `t = -inf`, so while moving it latches `SENSOR_STALE` and nothing restarts by itself.
- **Hardware NO_ECHO is UNKNOWN under any policy.** `CLEAR_TO_MAX` is refused for physical IO.
- **Clocks:** the navigator uses `time.monotonic` on the Pi. Fields must carry `clock == "time.monotonic@<this host>"`. Other hosts and wall-clock values are rejected, as is a timestamp more than 50 ms in the future. Our freshness limit is 0.20 s (PR #7's is 0.5 s).
- **Contradiction checks.** A reading is rejected if:
  - `allowed` is true with a status other than OK or CLEAR/CAUTION;
  - `allowed` is true with a range below the blocked threshold;
  - a range comes with a non-OK status;
  - `measurement_status` disagrees with `status`;
  - the range is beyond the maximum, or is NaN or infinite.
- **Service loss:** a missing file, an unreachable HTTP service, an import failure or a reader exception each give ERROR.

## 5. What remains before the first safe wheel test (wheels lifted)
1. Identify the controller: model from the label, USB VID:PID read-only on the Mac, current firmware banner.
2. Decide on the link and review the StickC **bridge firmware**. It must have:
   - output zero at boot;
   - a link-loss motor stop at ≤ 300 ms;
   - only the motor registers 0x00–0x03;
   - a speed clamp.
   **Flashing needs your separate approval.**
3. Charge and measure the RoverC battery, and set `min_voltage_v`. Without it, the supervisor refuses all physical motion.
4. Rehearse the physical e-stop: power switch or lift. Also rehearse the stop file and `POST /rover/estop`.
5. Fill in `HardwareVerification`: model, firmware, revision, link, wiring verifier, power verifier, measured `stop_on_link_loss_ms`. `RoverCAdapter` refuses to construct until every field is filled.
6. Write a concrete transport for the chosen link (not written yet), and run a dry run with motor power off that checks the frames.
7. **First wheel test:** wheels lifted, lowest speed (0.10), 0.3 s pulses. Record the wheel mapping and signs, and measure the link-loss stop.

Needed **after** the first wheel test and **before** any floor motion or scanning:
- a calibrated heading source;
- the measured robot width;
- PR #7 wiring sign-off with the ranging service running;
- a clear test area;
- your authorization.

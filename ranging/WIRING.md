# Grove Ultrasonic Ranger → Raspberry Pi 5: hardware connection guide

**Status: NOT YET VERIFIED.** No GPIO line has been configured (GPIO5 still reads
`pinctrl` function `none`). The hardware driver stays locked until every
checklist item in section 5 is recorded in the config (section 6).

## 1. What the sources say

Source: Seeed wiki <https://wiki.seeedstudio.com/Grove-Ultrasonic_Ranger/> and the
Seeed `grove.py` driver `grove/grove_ultrasonic_ranger.py`, both read 2026-11-07.

| Item | Value | Source |
|---|---|---|
| Revisions | V1.0 (Mar 2012). V2.0 (Jul 2017): "Compatible with 3.3V voltage system", added C14 | wiki version table |
| Operating voltage | 3.2–5.2 V, 8 mA | wiki spec table |
| Range / resolution | 2–350 cm, 1 cm | wiki spec table |
| Beam | "Measurement angle 15 degree", 40 kHz | wiki spec table |
| Connector order | `SIG, NC, VCC, GND` = yellow, white, red, black. Schematic J1: 4 = SIG, 3 = NC, 2 = VCC ("+5v" net), 1 = GND | wiki GrovePi comment, Arduino table, schematic |
| Protocol | one wire. Pulse SIG high > 10 µs, release it. The sensor sends 8 × 40 kHz. SIG then goes high for the round-trip time | wiki "operating principle" |
| Distance | `d = t_high × c / 2`. Seeed code: `cm = µs / 29 / 2` | wiki and grove.py |
| Ping interval | not specified. The Seeed Arduino example waits 250 ms. We use ≥ 60 ms (default 100 ms) | wiki example |
| Echo logic level | **SIG high ≈ VCC.** SIG goes straight to MCU pin P67. The MCU is powered from J1 VCC, and so are the MAX232 and LM324. **R2 = 10 kΩ pull-down** to GND on SIG. No pull-up and no other rail on SIG | Seeed schematic, dated 8-Nov-2017, includes C14 (read 2026-11-07, finding first reported by the robotics session) |
| Handling | "Do not hot plug". Target area ≥ 0.5 m², smooth | wiki |
| Raspberry Pi 5 | **the wiki does not mention it.** Its Pi example is a Pi 3 with a Grove Base Hat on D5 | wiki |

Seen on our Pi with read-only commands (`gpiodetect`, `gpioinfo`, `pinctrl get`, `lspci`), 2026-11-07:
Debian 13.7, kernel 6.18 rpt. The 40-pin header is on `gpiochip0`
(`pinctrl-rp1`, 54 lines). The Hailo-8 is on PCIe (`/dev/hailo0`). No HAT
EEPROM is reported in the device tree. **GPIO5 is unclaimed (function `none`)**.
I²C1 on GPIO2/3 is not enabled. User `team15` is in group `gpio`. python3-libgpiod
2.2.0 is installed, and its edge events carry CLOCK_MONOTONIC kernel timestamps.

## 2. Electrical decision: power the sensor from 3.3 V

According to the schematic, SIG is driven by an MCU powered from J1 VCC. So
**with a 5 V supply, the echo is 5 V**, and **Raspberry Pi GPIO is 3.3 V logic
and not 5 V tolerant.** So:

- **Default (no extra parts): VCC from the Pi's 3.3 V rail.** A powered device
  cannot drive its output above its own supply rail, so SIG stays ≤ 3.3 V.
  This needs a **V2.0** board. V1.0 is not documented as 3.3 V compatible.
  3.3 V is only 0.1 V above the 3.2 V minimum. If readings are flaky, measure
  VCC at the sensor while it runs.
  The board's MAX232 (transmit) and LM324 (receive amplifier) run below their
  usual 5 V at 3.3 V, so **do not assume the 350 cm datasheet range.**
  `calibrate` reports `recommended_max_range_m` from the tape-measured targets.
  Set `max_range_m` to it.
- **Fallback, only if 3.3 V proves unreliable:** VCC 5 V **plus a bidirectional
  MOSFET level shifter** on SIG (BSS138 type: HV = 5 V, LV = 3.3 V, common GND).
  A resistor divider alone is **not** acceptable. SIG is bidirectional, because
  the Pi drives the trigger on the same wire. The software gate refuses a 5 V
  setup with no shifter recorded.
- **Series resistor: 1 kΩ between the Pi pin and SIG** (recommended). It limits
  current if the Pi and the sensor ever drive the line at the same time. The
  driver also avoids that case: it reads SIG low before every trigger and keeps
  SIG as an input with a pull-down between pings.

## 3. Connection (Hailo HAT attached)

The Hailo board connects over PCIe through the FFC ribbon. The 40-pin header
passes through its stacking header. **Hardware teammate: confirm that the
header pins stick out above the Hailo board.** If they don't, stop and report
it.

- **Do not stack a Grove Base Hat on the Hailo HAT.** Clearance and the HAT
  combination are unverified, and the Base Hat is not needed for one sensor.
- Use a **Grove → 4-pin female jumper cable** (Seeed "Grove - 4 pin Female
  Jumper to Grove 4 pin Conversion Cable") onto the header pins:

| Grove wire | Signal | Pi 5 header (physical pin) | Note |
|---|---|---|---|
| Yellow | SIG | **Pin 29 = GPIO5**, through a **1 kΩ** series resistor | D5, as in Seeed's Pi example |
| White | NC | not connected; insulate the end | |
| Red | VCC | **Pin 1 = 3V3** (or pin 17) | **NOT pin 2 or 4: those are 5 V and sit right next to pin 1** |
| Black | GND | **Pin 9 = GND** (or 6, 14, 20, 25, 30, 34, 39) | |

```
            Pi 5 header (USB/Ethernet end at the bottom), odd pins on the left
   3V3  [ 1] (o)(o) [ 2]  5V    <- DO NOT USE
        [ 3] (o)(o) [ 4]  5V    <- DO NOT USE
        [ 5] (o)(o) [ 6]  GND
        [ 7] (o)(o) [ 8]
   GND  [ 9] (o)(o) [10]
        ...
  GPIO5 [29] (o)(o) [30]  GND
```

Do **not** plug the ranger into the RoverC-Pro's expansion/Grove port. That port
is an **I²C bus** (SDA/SCL) for the RoverC-Pro motor controller, and this sensor
is a single-wire timing device that I²C cannot read. Plugging it in would put
SIG on SDA and VCC from the RoverC rail. Do not power it from the RoverC-Pro
battery rail either: use the Pi's 3.3 V and GND.

## 4. Single-wire SIG: how the Pi 5 switches between trigger and echo

There is one wire. Either the Pi drives it (trigger) or the sensor drives it
(echo). They must never drive it at the same time. Sequence in
`GpiodDriver.measure()`, using libgpiod v2 on `/dev/gpiochip0` (`pinctrl-rp1`):

| Step | Pi side of SIG | Sensor side | Guard |
|---|---|---|---|
| 0. open (once) | Read-only check: chip label is `pinctrl-rp1`, line 5 is named `GPIO5`, line is unused. Then request it as **input, pull-down, edge detection both, CLOCK_MONOTONIC** | input (waiting) | wrong chip, wrong line or busy line → `DRIVER_ERROR`, nothing driven |
| 1. idle check | input. Drain old edge events, read the level | input | level high → `LINE_STUCK_HIGH`; **the Pi never switches to output onto a high line** |
| 2. trigger | `reconfigure_lines` → **output low**; 2 µs low; **high 15 µs** (spec > 10 µs); low | input | the sensor is listening, so no contention |
| 3. release | `reconfigure_lines` → **input + pull-down + edges**. `release_us` = time from trigger end to release done, recorded on every reading | sends 8 × 40 kHz (≈ 200 µs), then **drives SIG high** | the sensor must not drive before the Pi releases (next row) |
| 4. echo | input. The kernel timestamps the rising and falling edges (CLOCK_MONOTONIC) | high for the round trip, then low | echo starting > 2 ms after the trigger → `NO_ECHO` (Seeed rejects > 530 µs). No falling edge in time → `ECHO_TIMEOUT` |
| 5. between pings | input + pull-down | input | an unplugged SIG reads low → `NO_ECHO`, never a distance |

- **Overlap risk at step 3:** if releasing takes longer than the gap before
  the sensor starts its echo, the Pi drives low while the sensor drives high.
  The 1 kΩ series resistor limits that to ≤ 3.3 mA, which is safe for both
  sides. The driver then sees a falling edge with no rising edge and reports
  `MISSED_ECHO_START`. It does not guess a distance.
- `release_us` on a Pi 5 has **not yet been measured**, because no GPIO has been
  configured. `diagnose` reports it during the first powered run. Release must
  finish well before the echo starts (`echo_start_us`, expected ~200–500 µs).
- Trigger level: a 3.3 V high into a sensor powered from 3.3 V is a full logic high.
- Libraries: this driver uses only libgpiod v2 (`python3-libgpiod` 2.2.0 on the
  Pi). Don't use classic `RPi.GPIO` on a Pi 5: it was written for the older
  SoC GPIO, not RP1. `lgpio` is also installed but isn't used.

## 5. Checklist (Pi fully powered OFF for steps 1–5)

1. **Revision:** read the PCB silkscreen. It must say **V2.0** (or V2.x). Photograph it
   and keep the photo outside Git, e.g. `~/Team15_evidence/range/pcb_revision.jpg`. If
   it says V1.0 or has no marking, **stop**: the 3.3 V wiring isn't
   documented for that board, and GPIO stays locked.
2. `sudo poweroff`, wait for the green LED to stop, **unplug the Pi's USB-C power**.
   Unplug the RoverC-Pro battery link too, if it shares ground with the Pi. **No hot plugging** (Seeed).
3. Wire it as in section 3. With a meter in continuity/resistance mode:
   yellow ↔ pin 29 ≈ 1 kΩ, red ↔ pin 1 ≈ 0 Ω, black ↔ pin 9 ≈ 0 Ω.
   **Red must not connect to pin 2 or 4.** White must not touch anything.
4. Red ↔ black must not be a short.
5. Mount: front center, beam axis level (or tilted up). Measure the axis height
   above the floor, the pitch, and how far the sensor face sits behind the front
   bumper. These go into the `obstacle` section of the config.
6. Power on the Pi. **No range code yet.** Measure:
   - VCC at the sensor (red to black): **3.20–3.45 V**.
   - SIG (yellow) to GND, with GPIO5 in its boot state (`pinctrl get 5` → `no pu`):
     **expect ≈ 0.3–0.9 V.** The board's 10 kΩ pull-down (R2) works against the
     Pi's ~50 kΩ default pull-up through the 1 kΩ resistor: 3.3 × 10/61 ≈ 0.54 V.
     - **Between 0.9 and 1.2 V:** marginal, but the gate allows it.
     - **> 1.2 V (e.g. ≈ 3.3 V):** the pull-down is missing. This is not the
       documented board, so **stop** (the gate refuses).
     - **> 3.4 V:** unplug the Pi's power immediately.
     - **≈ 0 V:** also OK. GPIO5 may already have a pull-down if the range
       driver ran since boot.
7. Record everything (next section).

## 6. Unlock the driver (only after every step passes)

Copy `ranging/configs/pi5_gpio5.UNVERIFIED.json` to `~/Team15_config/grove_range.json`
on the Pi (outside Git) and fill in **every** field:

```json
"electrical": {
  "sensor_vcc_v": 3.3, "header_vcc_pin": 1, "signal_level_shifter": null,
  "series_resistor_ohm": 1000, "gpio_bcm": 5,
  "sensor_revision": "V2.0", "revision_evidence_ref": "~/Team15_evidence/range/pcb_revision.jpg",
  "powered_off_while_wiring": true, "continuity_checked": true,
  "vcc_measured_v": <meter>, "sig_idle_measured_v": <meter>, "mount_verified": true,
  "wiring_verified_by": "<teammate>", "wiring_verified_at": "<ISO time>"
},
"obstacle": { "mount_height_m": <m>, "mount_pitch_deg": <deg>, "sensor_setback_m": <m> }
```

`python3 -m ranging check-config --config ~/Team15_config/grove_range.json --hardware`
must print `"ok": true`. The gate refuses each of these:
- a missing or false checklist item
- a revision other than V2.x
- no revision photo
- VCC measured outside 3.20–3.45 V (or 4.75–5.25 V with a level shifter)
- SIG idle above 3.4 V
- 5 V with no shifter
- a VCC header pin that doesn't match the stated voltage
- a reserved pin
- no verifier recorded

## 7. Powered runs (robot stationary, motors off, wheels off the ground)

Each run writes evidence to `~/Team15_evidence/range/`:

```
CFG=~/Team15_config/grove_range.json; EV=~/Team15_evidence/range
# 7.1 SIG switching + liveness: release_us, echo_start_us, status counts. Target ~1 m.
python3 -B -m ranging diagnose   --config $CFG --hardware --samples 50 --out $EV/diagnose_1m.json
# 7.2 Floor reflections + no-target signature: installed height/angle, real floor, nothing within 3 m.
python3 -B -m ranging floor-check --config $CFG --hardware --samples 200 --out $EV/floor_check.json
# 7.3 Accuracy: flat board >= 0.5 m^2, perpendicular, tape measured from the sensor face.
python3 -B -m ranging calibrate  --config $CFG --hardware --targets 0.30,0.50,1.00,1.50,2.00 \
        --samples 30 --out $EV/calibration.json
```

- **7.1:** `release_us` must be well below `echo_start_us`. Any
  `MISSED_ECHO_START` means the release is too slow. Stop and report it.
- **7.2:** `verdict` must be `PASS_*`. If it says `FAIL_FALSE_CAUTION` or
  `FAIL_FALSE_BLOCKED` and `consistent_with_floor` is true, raise the sensor or
  tilt it up, update `mount_height_m`/`mount_pitch_deg`, and rerun.
  `no_target_signature` records what this physical board reports with nothing
  ahead (`NO_ECHO` or `OUT_OF_RANGE`). That evidence sharpens the
  no-echo diagnosis. Motion is still STOP either way.
- **Disconnected signature** (optional): power off, unplug the Grove cable at the
  sensor, power on, run `diagnose --samples 30`. Expect
  `NO_RESPONSE_EVER`. Power off again before reconnecting.
- **7.3:** add targets at 2.50 and 3.00 m (`--targets 0.30,0.50,1.00,1.50,2.00,2.50,3.00`)
  to find the real maximum range at 3.3 V. The report has the per-target error, a linear fit (scale, offset), a
  suggested speed of sound, and **recommended `blocked_m`/`caution_m`** with
  margin = max(0.10 m, max|error| + 3·SD), and `recommended_max_range_m`.
  Set `max_range_m` to it, so readings beyond the demonstrated range are `OUT_OF_RANGE` (→ STOP).

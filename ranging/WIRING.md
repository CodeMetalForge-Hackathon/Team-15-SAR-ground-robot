# Grove Ultrasonic Ranger → Raspberry Pi 5: hardware connection guide

**Status: NOT YET VERIFIED.** No GPIO line has been configured. The hardware
driver is locked until this checklist is done and recorded in the config. See
"Unlock the driver" below.

## 1. What the sources say

Source: Seeed wiki <https://wiki.seeedstudio.com/Grove-Ultrasonic_Ranger/> and the
Seeed `grove.py` driver `grove/grove_ultrasonic_ranger.py`, both read 2026-11-07.

| Item | Value | Source |
|---|---|---|
| Revisions | V1.0 (Mar 2012). V2.0 (Jul 2017): "Compatible with 3.3V voltage system", added C14 | wiki version table |
| Operating voltage | 3.2–5.2 V, 8 mA | wiki spec table |
| Range / resolution | 2–350 cm, 1 cm | wiki spec table |
| Beam | "Measurement angle 15 degree", 40 kHz | wiki spec table |
| Connector order | `SIG, NC, VCC, GND` = yellow, white, red, black | wiki GrovePi code comment and Arduino wiring table |
| Protocol | one wire. Pulse SIG high > 10 µs, release it. The sensor sends 8 × 40 kHz. SIG then goes high for the round-trip time | wiki "operating principle" |
| Distance | `d = t_high × c / 2`. Seeed code: `cm = µs / 29 / 2` | wiki and grove.py |
| Ping interval | not specified. The Seeed Arduino example waits 250 ms. We use ≥ 60 ms (default 100 ms) | wiki example |
| Echo logic level | **not documented** ("TTL"). The schematic PDF could not be read | — |
| Handling | "Do not hot plug". Target area ≥ 0.5 m², smooth | wiki |
| Raspberry Pi 5 | **the wiki does not mention it.** Its Pi example is a Pi 3 with a Grove Base Hat on D5 | wiki |

Seen on our Pi with read-only commands (`gpiodetect`, `gpioinfo`, `pinctrl get`, `lspci`), 2026-11-07:
Debian 13.7, kernel 6.18 rpt. The 40-pin header is on `gpiochip0`
(`pinctrl-rp1`, 54 lines). The Hailo-8 is on PCIe (`/dev/hailo0`). No HAT
EEPROM is reported in the device tree. **GPIO5 is unclaimed (function `none`)**.
I²C1 on GPIO2/3 is not enabled. User `team15` is in group `gpio`. python3-libgpiod
2.2.0 is installed, and its edge events carry CLOCK_MONOTONIC kernel timestamps.

## 2. Electrical decision: power the sensor from 3.3 V

The echo output level is undocumented. If the sensor is powered from 5 V, the
echo may swing to 5 V, and **Raspberry Pi GPIO is 3.3 V logic and not 5 V
tolerant.** So:

- **Default (no extra parts): VCC from the Pi's 3.3 V rail.** A powered device
  cannot drive its output above its own supply rail, so SIG stays ≤ 3.3 V.
  This needs a **V2.0** board. V1.0 is not documented as 3.3 V compatible.
  3.3 V is only 0.1 V above the 3.2 V minimum. If readings are flaky, measure
  VCC at the sensor while it runs.
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

## 4. Checklist (power OFF for steps 1–4)

1. Read the PCB silkscreen and write down the revision (`V2.0` expected). Photograph it.
2. Shut down the Pi (`sudo poweroff`) and remove power. **No hot plugging** (Seeed).
3. Wire it as in the table. Check with a meter in continuity mode:
   yellow ↔ pin 29 (through 1 kΩ, so ~1 kΩ), red ↔ pin 1, black ↔ pin 9.
   **Red must not be continuous with pin 2 or 4.**
4. Check that red and black are not shorted (open circuit, or a high resistance).
5. Power the Pi on. Before running any range code, measure:
   - VCC at the sensor end of the red wire: **3.2–3.4 V**.
   - SIG (yellow, sensor side) to GND at idle: **≤ 3.4 V**. Anything higher means stop and unplug.
6. Mount: front center, beam axis horizontal, nothing within ~30 cm of the
   sensor face. Record the axis height above the floor, the tilt, and how far
   the sensor face sits behind the front bumper.
7. Record who checked and when (next section).

## 5. Unlock the driver

Copy `ranging/configs/pi5_gpio5.UNVERIFIED.json` to the Pi, outside Git, for
example `~/Team15_config/grove_range.json`, and fill in:

```json
"electrical": {
  "sensor_vcc_v": 3.3, "header_vcc_pin": 1, "signal_level_shifter": null,
  "series_resistor_ohm": 1000, "gpio_bcm": 5, "sensor_revision": "V2.0",
  "wiring_verified_by": "<teammate name>", "wiring_verified_at": "<ISO time>"
},
"obstacle": { "mount_height_m": <measured>, "mount_pitch_deg": <measured>, "sensor_setback_m": <measured> }
```

`python3 -m ranging check-config --config ~/Team15_config/grove_range.json --hardware`
must print `"ok": true`. The gate refuses all of these:
- 5 V without a level shifter
- a header VCC pin that doesn't match the stated voltage
- GPIO0/1 (HAT EEPROM), GPIO2/3 (I²C), GPIO14/15 (UART)
- a non-V2 board at 3.3 V
- a config with no verifier recorded

## 6. First read-only run (robot stationary, motors off)

```
python3 -B -m ranging read --config ~/Team15_config/grove_range.json --hardware --count 50
python3 -B -m ranging calibrate --config ~/Team15_config/grove_range.json --hardware \
        --targets 0.30,0.50,1.00,1.50,2.00 --samples 30 --out ~/Team15_evidence/range/calibration.json
```

At each tape-measured distance, use a flat board (≥ 0.5 m²) held perpendicular to
the beam. Report median error, standard deviation and the status counts. If
there are many `MISSED_ECHO_START` statuses, the Pi switched SIG to input too
late after the trigger. Report it so the timing can be revisited.

# Grove ranger: hardware validation sign-off

GPIO stays locked until **both** columns are complete and the values have been
entered in `~/Team15_config/grove_range.json` on the Pi (WIRING.md §6). The
**independent verifier must be a different person** who repeats the checks
themselves without reading the wirer's numbers first. The software gate refuses
a config where the two names are the same.

Print this sheet, or copy it to `~/Team15_evidence/range/signoff.md`. Keep it out of Git.

## A. Platform (no wiring needed). Already run 2026-11-07 on $PI_HOST

`python3 -m ranging preflight --config <cfg>` is read-only and requests no line.

| Check | Result 2026-11-07 |
|---|---|
| Pi model | PASS: Raspberry Pi 5 Model B Rev 1.1 |
| libgpiod v2 | PASS: 2.2.0 |
| `/dev/gpiochip0` access as `team15` | PASS |
| chip label / line name / unused | PASS: `pinctrl-rp1` / `GPIO5` / unused |
| `pinctrl get 5` | PASS: `no pu` (no alt function, default pull-up) |
| NTP synchronized | PASS |
| `/dev/shm` writable | PASS |
| electrical gate | **FAIL (expected)**: the checklist below has not been done |

## B. Physical checks (Pi fully powered OFF unless stated)

| # | Check | Pass criterion | Wirer | Independent verifier |
|---|---|---|---|---|
| 1 | PCB revision silkscreen | reads **V2.0** (or V2.x). Photo taken | ☐ ____ | ☐ ____ |
| 2 | Power removed before touching wires | Pi USB-C unplugged, LED off. RoverC-Pro link disconnected | ☐ | ☐ |
| 3 | Hailo stacking header | header pins stick out above the Hailo board. No Grove Base Hat stacked | ☐ | ☐ |
| 4 | Yellow (SIG) → pin 29 (GPIO5) | ≈ 1 kΩ (series resistor present) | ☐ ____ Ω | ☐ ____ Ω |
| 5 | Red (VCC) → pin 1 (3V3) | ≈ 0 Ω. **Open circuit to pins 2 and 4 (5 V)** | ☐ | ☐ |
| 6 | Black (GND) → pin 9 | ≈ 0 Ω | ☐ | ☐ |
| 7 | White (NC) | not connected, insulated | ☐ | ☐ |
| 8 | Red ↔ black | no short | ☐ | ☐ |
| 9 | Mount | front center. Axis height ____ m, pitch ____ °, setback ____ m | ☐ | ☐ |
| 10 | *Powered, no range code:* VCC at the sensor | 3.20–3.45 V | ☐ ____ V | ☐ ____ V |
| 11 | *Powered, no range code:* SIG to GND, GPIO5 in its boot state (`pinctrl get 5` → `no pu`) | **≈ 0.3–0.9 V** (board R2 10 kΩ pull-down vs Pi pull-up). **> 1.2 V (e.g. 3.3 V) = stop**: pull-down missing, not the documented board. > 3.4 V = remove power now | ☐ ____ V | ☐ ____ V |

Any failure: power off, fix it, and repeat the whole column. If row 1 shows V1.0
or no marking, **stop**: the board is not accepted for direct 3.3 V GPIO use.

| | Name | Date/time (ISO) | Signature |
|---|---|---|---|
| Wirer → `wiring_verified_by/_at` | | | |
| Independent verifier → `independently_verified_by/_at` | | | |

## C. Unlock and first powered runs (robot stationary, motors off, wheels off the ground)

1. Enter every value in the config. `check-config --hardware` and then
   `preflight` must both report `ok: true`.
2. Do the WIRING.md §7 runs in order: `diagnose` (SIG timing), `floor-check`
   (floor echoes and the no-target signature), `calibrate` at
   0.30 / 0.50 / 1.00 / 1.50 / 2.00 m. Save the JSON reports to `~/Team15_evidence/range/`.
3. Stop and report if any of these happen:
   - any `MISSED_ECHO_START`
   - `release_us` not well below `echo_start_us`
   - a `floor-check` verdict of `FAIL_*`
   - `calibration_complete: false`
   - any target with |error| > 5 cm

   The 5 cm limit is a proposed acceptance limit; the team should confirm it.
4. Update `obstacle.safety_margin_m` from `calibrate` → `analysis.recommended`, and set
   `max_range_m` to `analysis.recommended_max_range_m`. At 3.3 V the 3.5 m datasheet range
   is not assumed; include 2.50 and 3.00 m targets to find the real maximum.
   The thresholds are final only once the RoverC-Pro speed, deceleration and
   latency have also been measured. Wheel motion is outside this sheet.

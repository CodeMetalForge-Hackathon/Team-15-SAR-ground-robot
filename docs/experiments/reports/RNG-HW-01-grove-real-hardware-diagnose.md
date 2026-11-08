# RNG-HW-01 and RNG-HW-02: Grove ultrasonic real-hardware diagnose, runs 1 and 2

**Label: REAL HARDWARE** · **Status: FAILED** (both runs: 0/50 valid) · **Root cause: UNKNOWN**
Back to: [14 Grove ultrasonic](../../14_GROVE_ULTRASONIC.md) · [Gate runs RNG-PF](RNG-PF-01-grove-preflight-gate-runs.md) · [Simulation suite RNG-SIM](RNG-SIM-01-ranging-simulation-test-suite.md)

## In one paragraph (plain language)

We connected the Grove ultrasonic sensor to the Raspberry Pi 5, put a target 1 m in front of it and asked the Pi to "ping" 50 times. Each ping is a short electrical pulse that should make the sensor send a burst of ultrasound and then raise its signal wire for as long as the echo takes to return. In both attempts, seven minutes apart, the signal wire **never went up once**: 100 pings, zero responses. The software behaved as designed: it reported "no echo", marked the sensor FAULT and kept the robot stopped. It cannot tell us **why** the sensor stayed silent. The cause could be a wire on the wrong pin, no power reaching the board, an open resistor or jumper, or a board that won't work at 3.3 V. Nobody re-measured the wiring afterwards, so we don't know which.

## 1. Objective and hypothesis

- **Objective:** obtain the first real distance readings from the Grove ranger on the Pi 5, and confirm the single-wire trigger/release timing (`release_us` well below `echo_start_us`, no `MISSED_ECHO_START`). This is `WIRING.md` §7.1, the first powered run.
- **Hypothesis:** with the wiring verified (gate passing), a flat target at 1.00 m gives `VALID` readings with an echo of ≈ 5.83 ms (`2·1.00/343`) and a median near 1.00 m.
- **Pass criteria:** the `HARDWARE_VALIDATION.md` §C stop conditions. No `MISSED_ECHO_START`; `release_us` well below `echo_start_us`; valid echoes present. Only after that, `floor-check` and `calibrate`.

## 2. Date, place, people (by role)

| | Run 1 (RNG-HW-01) | Run 2 (RNG-HW-02) |
|---|---|---|
| Date | 2026-11-08 | 2026-11-08 |
| Time (UTC) | 10:43:15 – 10:43:22 (report time 10:43:21.96) | ≈ 10:50:24 – 10:50:31 (report time 10:50:31.59) |
| Local time on the Pi | 05:43 EST | 05:50 EST |
| Operator | the project owner (instructions in chat); commands issued over SSH by the AI coding assistant | same |
| Wiring | done by the wiring teammate (recorded `wiring_verified_at` 2026-11-08T05:23:00-05:00) | no change reported ("try again") |
| Independent verifier | the project owner (recorded 05:25 local; confirmed "Yes, personally measured" in reply to a direct question at 10:42 UTC) | same config |

## 3. Hardware

- Raspberry Pi 5 Model B Rev 1.1 (preflight `pi5_model`), Debian 13.7, kernel 6.18 rpt, Hailo-8 HAT on PCIe with a stacking header. The Pi had been moved to a 5 A mains supply at about 08:45 UTC (see [LDR-HW-01](LDR-HW-01-lidar-usb-enumeration-and-gate.md)). Whether it was still on that supply at 10:43 is not recorded. EXT5V read 5.18 V at 09:59 UTC.
- Seeed Grove Ultrasonic Ranger, PCB silkscreen "Ultrasonic Distance Sensor V2.0" (photo received 10:38 UTC).
- Wiring **as reported** (not photographed after the fix): red VCC → header pin 1 (3V3), black → pin 9 (GND), yellow SIG → 1 kΩ series resistor → pin 29 (GPIO5), white NC insulated.
- No USB serial device was attached, so no StickC and no motor path (`ls /dev/ttyUSB* /dev/ttyACM*` empty at 10:43). RoverC motors, gripper, LiDAR and navigation were not used.

## 4. Software

- `ranging/` deployed from `main` **`06a69b9`** with `git archive origin/main ranging` into its own Pi folder (09:33 UTC). It includes the `SIG_IDLE_MAX_V = 1.2` gate. `ranging/` is identical at `d1b607a`.
- Driver `GpiodDriver` (libgpiod 2.2.0, `/dev/gpiochip0` `pinctrl-rp1`, line 5). `sample_interval_s` 0.1, `trigger_pulse_us` 15, `echo_start_timeout_s` 0.002, `speed_of_sound_mps` 343.
- No model or checkpoint (not applicable).
- Command (both runs; the paths are on the Pi and outside Git):

```bash
python3 -B -m ranging diagnose --config ~/Team15_config/grove_range.json --hardware --samples 50 \
    --out ~/Team15_evidence/range/REAL_HARDWARE_diagnose_<UTC>.json
```

Run 2 was preceded by `check-config --hardware` (`gate ok: True`).

## 5. Data and ground truth

- **N = 50 pings per run** (100 total).
- **Ground truth:** a target at **100 cm, tape-measured**, as reported by the team in chat at 10:33 UTC. The original request was "an empty chair 50–100 cm directly ahead". The target's type, size and orientation at run time are not recorded beyond that.
- **Config inputs** (self-reported in chat, entered by the assistant, provenance in a sidecar file): V2.0; VCC 3.25 V; SIG idle 0.8 V; mount 0.08 m / 0° / 0 m; powered off while wiring; continuity checked. **`series_resistor_ohm` = 1000 is the design value. The measured resistance was never supplied.**

## 6. Metrics and why they were chosen

| Metric | Why |
|---|---|
| Status counts (`VALID`, `NO_ECHO`, `ECHO_TIMEOUT`, `MISSED_ECHO_START`, …) | Separates "no echo" from timing faults |
| `release_us` | Time the Pi kept driving SIG after the trigger. It must be far below the echo start (≈ 200–500 µs) |
| `edges`, `echo_start_us` | Any edge at all proves the sensor drove SIG |
| health `state`, `diagnosis.code` | The service's evidence-limited verdict |
| Pi `throttled`, temperature | Rule out power and thermal effects |
| min/median/max distance | Only if echoes are valid (**none were**) |

## 7. Results

| Field | Run 1 (RNG-HW-01) | Run 2 (RNG-HW-02) |
|---|---|---|
| Gate before run | `check-config --hardware` ok: true; `preflight` ok: true (10:43:08) | `check-config --hardware` ok: true |
| VALID | **0** | **0** |
| NO_ECHO (detail "no rising edge") | **50** | **50** |
| ECHO_TIMEOUT / MISSED_ECHO_START / OUT_OF_RANGE / BELOW_MIN_RANGE / LINE_STUCK_HIGH / DRIVER_ERROR | 0 / 0 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 / 0 |
| `release_us` (last reading) | 96.1 µs | 64.8 µs |
| `edges` (last reading) | 0 | 0 |
| `echo_start_us` | null | null |
| Health | **FAULT**, `consecutive_invalid` 50 (FAULT reached at ping 10, 10:43:16.542) | **FAULT** (counts as left) |
| Diagnosis | **`NO_RESPONSE_EVER`**, `last_echo_evidence_age_s` null, motion "STOP (UNKNOWN)" | **`NO_RESPONSE_EVER`** |
| Distance min / median / max | none | none |
| `throttled` before / after | 0x0 / 0x0 | 0x0 / 0x0 |
| Pi temperature | 48.3 → 48.8 °C | 46.6 °C (after) |
| GPIO5 after | released; `pinctrl` "ip pd \| lo" (input, pull-down, low), no holder | released, same |
| Provenance | `source_mode LIVE-HW`, `platform BENCH`, `driver gpiod`, `gpio_bcm 5`, `service_boot_id r1794134595-d8a6df`, `config_sha256 0a05117747dca7ef` | not printed in the log |
| Exit code | 0 (the diagnose command completed; the failure is in the data) | 0 |

`release_us` was printed only for the last ping of each run. The per-ping values are in the evidence JSON on the Pi. Only the 1st and 10th `NO_ECHO` warnings are in the printed stdout.

## 8. Failures and interpretation

**What the data rules out:**
- *Release too slow / contention*: that gives `MISSED_ECHO_START`, a falling edge without a rising edge. Zero edges in total, so no.
- *Echo stuck or never ending*: that gives `ECHO_TIMEOUT`, a rising edge with no falling edge. No.
- *SIG shorted high or driven from 5 V at idle*: that gives `LINE_STUCK_HIGH` before the trigger. No.
- *GPIO/library/permission problems*: those give `DRIVER_ERROR`. No.
- *Pi under-voltage or throttling*: `0x0` before and after.

**What remains possible (none confirmed):**
- SIG not connected to GPIO5, through a wrong pin, a loose jumper or an open or missing resistor;
- the sensor unpowered (VCC not on pin 1, or an open GND);
- the board not responding when powered at 3.3 V (within spec for V2.0, but marginal: 3.25 V measured against a 3.2 V minimum);
- a trigger that does not register at the sensor;
- a damaged sensor. The 09:41 UTC photo review raised the possibility that VCC had earlier been on **pin 2 (5 V)**. That was never confirmed or ruled out, and its effect on the board, if any, is unknown.

**Evidence weaknesses:**
- every gate input was typed into chat; the software cannot verify a meter reading;
- the resistor value was not measured;
- no post-fix photo of the header;
- the SIG-idle measurement point (sensor side or pin side) is not recorded;
- the independent verification is a yes/no confirmation, not an independently written record.

**Root cause: UNKNOWN.**

## 9. Evidence files

| File (on the Pi, `~/Team15_evidence/range/`, private, not in Git) | SHA-256 |
|---|---|
| `REAL_HARDWARE_diagnose_20261108T104315Z.json` and `.stdout` (run 1) | **not computed**: Pi unreachable during this audit |
| `REAL_HARDWARE_diagnose_20261108T105024Z.json` and `.stdout` (run 2) | not computed (same reason) |
| `gate_check_config_20261108T104308Z.json`, `gate_preflight_20261108T104308Z.json` (passing gate) | not computed |
| `pcb_revision_screenshot.png` (PNG screenshot of the PCB photo, 1846×1900) | `cd2a6e6529a34bdd39500c951d7f582f3e9a3ed24336f34b3d60958f251035ad` (computed on the Pi, 10:39 UTC, printed in the log) |
| `~/Team15_config/grove_range.json` + `grove_range.json.PROVENANCE.txt` | not computed |

The primary record used for this report is the **session console log, 2026-11-08 09:59–10:50 UTC**, which contains the printed command outputs. No image is reproduced here.

## 10. Limitations and confounders

- Only the last reading's timing fields are visible in the log.
- The target was not independently verified at run time.
- Run 2 was not preceded by any documented hardware change, so it is a repeat of run 1, not an independent configuration.
- The Pi had been rebooted several times that morning (uptime 0 min at 09:57). Whether any wiring was done with the Pi powered is not recorded beyond the self-reported `powered_off_while_wiring: true`.

## 11. Reproducibility

The software side is fully reproducible: the same commit, config schema and command. The physical setup is not, because the wiring was not documented with a photo or with measured continuity and resistance values. To reproduce the failure **shape** without hardware: `python3 -B -m ranging diagnose --sim-scenario disconnected --samples 12` gives `FAULT` / `NO_RESPONSE_EVER` / all `NO_ECHO`, labelled SIMULATED (verified in this audit). That reproduces the symptom, not the cause.

## 12. What this proves / does NOT prove

**Proves:** on the real Pi 5, the gated driver claims the correct line, issues the trigger, releases SIG within ≈ 65–96 µs, reports a silent sensor as `NO_ECHO`, escalates to `FAULT` after 10 pings, reports `NO_RESPONSE_EVER`, never fabricates a distance, keeps motion at STOP (UNKNOWN) and releases the line afterwards. This is a real-hardware confirmation of the fail-closed path.

**Does NOT prove:**
- any distance accuracy;
- that the sensor works;
- that it is broken;
- that the wiring was correct or incorrect;
- floor-echo behaviour;
- the no-target signature;
- that `release_us` is short enough for a real echo, since no echo-start time was observed.

## 13. What we would change next time

1. Before the first powered run, require a **photo of the header from directly above**, plus **written** continuity and resistance readings from each of the two people.
2. Add a measured `series_resistor_ohm` (900–1100 Ω) check to `check_electrical`, or run the real test through the stricter `sensor_only_test.py` wrapper.
3. After a failed run, measure **at the sensor connector** before retrying: SIG-to-pin-29 continuity ≈ 1 kΩ with the Pi off; VCC 3.20–3.45 V with the Pi on.
4. Keep a scope or logic probe on SIG for the first ping, to see directly whether the trigger reaches the sensor.
5. Record every per-ping `release_us` in the report summary, not only the last one.

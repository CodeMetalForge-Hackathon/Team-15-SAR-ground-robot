# RNG-PF-01 … RNG-PF-10: Grove read-only preflight and electrical-gate runs

**Label: REAL HARDWARE (read-only: no GPIO line requested or driven)** · **Status: COMPLETE as a record** (gate behaviour as designed; the hardware gate opened only at RNG-PF-09/10)
Back to: [14 Grove ultrasonic](../../14_GROVE_ULTRASONIC.md) · [Real diagnose runs RNG-HW-01/02](RNG-HW-01-grove-real-hardware-diagnose.md)

## In one paragraph (plain language)

Before the Pi is allowed to touch the sensor's signal pin, two software checks must pass. **Preflight** is a read-only look at the Pi: right model, GPIO library present, correct GPIO chip and pin, pin unused, clock synced. It never claims the pin. The **electrical gate** checks that a person recorded a full wiring checklist (board revision, meter readings, two different verifiers) in the config file. Over about eight hours these checks were run ten times. The Pi side always passed. The electrical gate refused every time until the team's measurements and both names were entered, at 10:43 UTC on 2026-11-08. The gate passed at 10:43 and again at 10:50, and the two real diagnose runs followed ([RNG-HW-01/02](RNG-HW-01-grove-real-hardware-diagnose.md)).

## 1. Objective

Show that the Pi platform is ready, and that the hardware driver stays locked until the wiring evidence is recorded. This tests the gate itself (`ranging/preflight.py` `run_preflight`, `ranging/config.py` `check_electrical`, `ranging/cli.py` `_load`).

## 2. Setup

- Hardware: Raspberry Pi 5 Model B Rev 1.1, Debian 13.7, kernel 6.18 rpt, libgpiod 2.2.0, header chip `/dev/gpiochip0` = `pinctrl-rp1`.
- Software: `ranging/` from PR #7. On 2026-11-08 it was deployed from `main` `06a69b9` into its own Pi folder (09:33 UTC).
- Commands, all read-only:

```bash
python3 -B -m ranging preflight --config <cfg>
python3 -B -m ranging check-config --config <cfg> --hardware
```

- Preflight checks (`run_preflight`): `pi5_model`, `electrical_gate`, `libgpiod_v2`, `gpiochip_rw_access`, `chip_is_rp1`, `line_name`, `line_unused`, `pinctrl_function`, `ntp_synchronized`, `dev_shm_writable`. Each is PASS, FAIL or SKIP; `ok` means no FAIL.
- Ground truth: the expected gate outcome given the recorded fields.
- Metric: per-check result and the refusal text. Why: the refusal text names each missing item, so the gate is auditable.

## 3. Results, one row per run (each run is a separate experiment)

| ID | Date / time (UTC) | Config | Preflight | `check-config --hardware` | Notes / source |
|---|---|---|---|---|---|
| RNG-PF-01 | 2026-11-07 (time not recorded in the doc) | template | Pi model, libgpiod 2.2.0, chip access, `pinctrl-rp1`/`GPIO5`/unused, `pinctrl get 5` `no pu`, NTP, `/dev/shm`: **PASS**; `electrical_gate` **FAIL (expected)** | — | `ranging/HARDWARE_VALIDATION.md` §A |
| RNG-PF-02 | 2026-11-08 09:33 | `pi5_gpio5.UNVERIFIED.json` | 9/10 PASS; `electrical_gate` FAIL (11 checklist fields unrecorded) | — | session console log 09:33. First run of the code deployed from `06a69b9` |
| RNG-PF-03 | 2026-11-08 09:46 | template | 9/10 PASS; gate FAIL. Pi up 23 min, 5.18 V, 47.2 °C, `0x0` | — | after the team "corrected/reset" the wiring; no measurements yet |
| RNG-PF-04 | 2026-11-08 09:57 | template | 9/10 PASS; gate FAIL. Pi up 0 min (rebooted), 5.18 V, 42.2 °C | — | the requested folder `~/team15-grovecheck` did not exist on the Pi |
| RNG-PF-05 | 2026-11-08 10:00 | template | 9/10 PASS; gate FAIL | **refused**, 9 reasons (revision, photo, power-off, continuity, mount, VCC, SIG idle, wiring verifier, independent verifier) | session console log 10:00. `throttled 0x0`, EXT5V 5.18 V, 42.8 °C |
| RNG-PF-06 | 2026-11-08 10:04:37 | `sensor_only_test.py --hardware` wrapper | — | **REFUSED**: checklist file `~/Team15_config/grove_sensor_checklist.json` missing | then the simulation fallback ran (RNG-SIM-04) |
| RNG-PF-07 | 2026-11-08 10:39 | first verified config | — | `ok: false`, **"unknown config keys: ['_provenance']"** | the strict schema rejected an in-file provenance note, which moved to a sidecar file |
| RNG-PF-08 | 2026-11-08 10:40:06 | config with team values, no wiring verifier | `electrical_gate` FAIL only | refused, **one reason**: "wiring not verified: set wiring_verified_by and wiring_verified_at" | `gate_*_20261108T104006Z.json` on the Pi |
| RNG-PF-09 | 2026-11-08 **10:43:08** | + wiring verifier (the wiring teammate) | **ok: true** | **ok: true** | `gate_*_20261108T104308Z.json`; GPIO5 still `none` (unclaimed) |
| RNG-PF-10 | 2026-11-08 ≈ 10:50:22 | same | — | **ok: true** ("gate ok: True") | immediately before run 2 |

Between RNG-PF-02 and RNG-PF-08 the assistant refused **four** times to fill config fields from a verbal "the wiring is fixed" (09:46, 09:57, 10:26, 10:28 UTC). It accepted only values the team supplied explicitly, and it rejected placeholders: "V2.x", "actual PCB photo" and "900–1100 Ω" (a range rather than a reading).

## 4. What this proves / does NOT prove

**Proves (REAL HARDWARE, read-only):**
- the platform is correct: Pi 5, RP1 chip, GPIO5 free, libgpiod v2;
- preflight never claims a line: GPIO5 stayed `none` throughout RNG-PF-02…09;
- the gate refuses every incomplete config, and names exactly what is missing;
- the schema is strict, so unknown keys are rejected;
- the gate opens only once every field is present and the two verifiers differ.

**Does NOT prove:**
- that the recorded values are true. The gate cannot validate a meter reading;
- that the series resistor is present. `check_electrical` does not check `series_resistor_ohm`, and the measured value was never supplied;
- that the wiring matched the documented pins. No header photo after the fix exists, and the 09:41 UTC photo showed apparent faults.

## 5. Evidence

- Session console log, 2026-11-08 09:33–10:50 UTC (printed outputs).
- Pi files under `~/Team15_evidence/range/` (private, not in Git): `gate_check_config_20261108T104006Z.json`, `gate_preflight_20261108T104006Z.json`, `gate_check_config_20261108T104308Z.json`, `gate_preflight_20261108T104308Z.json`. **SHA-256 not computed**: the Pi was unreachable during this audit.
- `ranging/HARDWARE_VALIDATION.md` §A for RNG-PF-01.

## 6. Limitations

- RNG-PF-01 is recorded in a document, not in a log with timestamps.
- The PF-08/09 preflight JSONs were written to files. Only their summary lines are in the log.

## 7. What we'd change next time

- Make the gate require evidence *artifacts*: a hash of a header photo, and a measured resistance.
- Have the gate write the full refusal or acceptance JSON into the evidence folder on every run. That was done manually for PF-08/09.
- Include the `sensor_only_test.py` checklist items (header-pin protrusion, measured resistance, SIG idle ≤ 1.0 V) in the main gate, so a direct `ranging diagnose` cannot bypass them.

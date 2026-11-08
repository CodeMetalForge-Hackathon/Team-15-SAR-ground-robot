# RNG-SIM-01 … RNG-SIM-05: ranging simulation test suite and simulated sensor-only runs

**Label: SIMULATED + MOCKED** (fake libgpiod) · **Status: COMPLETE**
Back to: [14 Grove ultrasonic](../../14_GROVE_ULTRASONIC.md) · [18 Simulation](../../18_SIMULATION.md) · [19 Testing](../../19_TESTING_AND_BENCHMARKS.md)

## In one paragraph (plain language)

The ranging package has 126 automated tests that exercise everything except the real sensor. A simulator stands in for the sonar: it can be told "a wall at 1 m", "a wall approaching", "nothing there" or "unplugged". A fake GPIO library stands in for the Pi's pin hardware, so the trigger/echo logic can run on a laptop. All 126 pass. These tests prove the **logic** is right: no distance from a missing echo, a stop on a close reading, no false clear, and the electrical gate refusing bad wiring descriptions. They **cannot** prove that the real sensor measures distance correctly. The first real attempts produced no echoes at all ([RNG-HW-01/02](RNG-HW-01-grove-real-hardware-diagnose.md)).

## 1. Objective

Verify the ranging package's safety invariants and contracts without hardware.

## 2. Runs (each a separate row)

| ID | Date | Commit / tree | Environment | Command | Result |
|---|---|---|---|---|---|
| RNG-SIM-01 | 2026-11-07 | PR #7 branch (`feature/grove-distance`) | macOS, Python 3.13 | `python3 -m pytest -q ranging/tests` | 126 passed (`ranging/README.md` "Test results") |
| RNG-SIM-02 | 2026-11-08 (this audit) | `d1b607a` (ranging/ identical to `06a69b9`) | macOS (Darwin 25.6), Python 3.13.5, pytest 8.3.4 | `python3 -m pytest -q -p no:cacheprovider ranging/tests` | **126 passed in 3.60 s** |
| RNG-SIM-03 | 2026-11-07 | PR #8 tree at `09333d3` (older `ranging/` copy, before the 1.2 V SIG-idle gate) | not recorded | `ranging/tests` | 118 passed (`ranging/INTEGRATION.md` "Integration status") |
| RNG-SIM-04 | 2026-11-08 10:04:42 UTC | Robot workspace `ae7ac82` + ranging `06a69b9`, **run on the Pi 5** | Pi 5, Python 3 (Debian 13.7) | `sensor_only_test.py --simulate` | 50/50 VALID; min 97.26 / median 99.56 / max 102.03 cm; SD 1.11 cm; source `SIMULATED` (session console log 10:04 UTC) |
| RNG-SIM-05 | 2026-11-07 ~20:05 ET | Robot workspace `c6739fb` | Mac | `sensor_only_test.py --simulate` | 20/20 VALID; median 99.9 cm (simulated 100 cm); SD 1.07 cm (`$ROBOT_WORKSPACE/TEST_REPORT.md` round 3) |

CI: the `ranging` workflow (`.github/workflows/ranging.yml`, Python 3.11, pytest 8.3.4) runs `pytest -q ranging/tests` and asserts that the shipped template is refused. It last succeeded on `main` at the PR #7 merge (run 42435827863, 2026-11-08 01:48 UTC), and on PR #17's branch (run 42479254445, 12:13 UTC). It is path-filtered to `ranging/**`. Note that the default `pytest.ini` `testpaths` does **not** include `ranging/tests`.

## 3. What the 126 cases cover (58 test functions in `ranging/tests/test_ranging.py`)

| Area | Example tests |
|---|---|
| Reading invariants | `test_invalid_reading_cannot_carry_distance`, `test_reading_dict_shape` |
| Distances | `test_known_short_and_medium_distances` (0.1, 0.3, 0.5, 1.0, 1.5, 2.5 m), `test_seeed_formula_agreement` (`cm = µs/29/2`) |
| Echo logic | `test_echo_events_parsing`, `test_invalid_echoes_have_no_distance`, `test_simulator_out_of_range` |
| Disconnection | `test_simulator_no_echo_and_disconnect_never_give_distance`, `test_gpiod_disconnected_sensor_is_no_echo`, `test_service_health_faults_on_disconnect` |
| Filter | `test_rapid_approach_blocks_on_the_next_ping`, `test_single_long_spike_cannot_clear_a_block`, `test_no_echo_after_block_does_not_clear`, `test_noise_at_threshold_does_not_oscillate`, `test_sampling_gap_empties_window`, `test_stale_reading_is_unknown`, `test_out_of_range_is_not_clear` |
| Electrical gate | `test_invalid_electrical_configuration_is_refused` (many parametrized cases: V1.0, no photo, hot-plug, out-of-range meters, 5 V without shifter, reserved pins, same-person verifier…), `test_5v_with_level_shifter_is_allowed`, `test_sig_idle_in_schematic_range_passes`, `test_shipped_unverified_pi_config_is_refused`, `test_cli_requires_hardware_flag_and_verified_config`, `test_gpiod_driver_refuses_unverified_wiring_before_importing_gpiod` |
| Fake-libgpiod driver | `test_gpiod_valid_ping_and_line_is_input_between_pings`, `test_gpiod_stuck_high_is_not_driven`, `test_gpiod_refuses_wrong_chip_or_busy_line`, `test_gpiod_error_recovery_reopens`, `test_gpiod_reading_records_sig_timing_evidence` |
| Diagnosis | `test_diagnosis_distinguishes_causes_but_always_stops`, `test_out_of_range_counts_as_echo_evidence_for_later_no_echo` |
| Service and client | `test_service_snapshot_contract`, `test_client_sees_dead_service_as_stale`, `test_client_cannot_be_talked_into_motion_by_inconsistent_snapshot`, `test_http_endpoints` |
| Rover adapter | `test_rover_mapping_never_allows_motion_unless_clear`, `test_rover_stale_and_unreachable_are_error`, `test_rover_other_host_snapshot_is_error` |
| Tools | `test_floor_check_detects_floor_echo_in_caution`, `test_floor_check_open_space_records_no_target_signature`, `test_calibration_analysis_fit_and_margin`, `test_calibration_recommends_demonstrated_max_range` |
| Preflight | `test_preflight_never_requests_a_line`, `test_preflight_fails_on_each_problem` |

Ground truth for the distance tests is the scene distance the simulator is given, converted through `echo_us = 2d/c`. Metric: exact pass/fail. Why: these are invariants, not estimates.

## 4. Additional audit checks (2026-11-08, `d1b607a`, SIMULATED)

- `python3 -B -m ranging diagnose --sim-scenario disconnected --samples 12` → health `FAULT`, diagnosis `NO_RESPONSE_EVER`, 12 `NO_ECHO`, `source_mode SIMULATED`. This is the same *shape* as the real failure.
- `python3 -B -m ranging read --count 6 --sim-scenario approach` → readings 1–4 UNKNOWN (the window is filling, then the 3-sample relax confirmation), readings 5–6 CLEAR.
- `check-config` on `ranging/configs/simulated.json` → ok; geometry `floor_intercept_m 0.608`, `blocked_threshold_m 0.28`, `caution_threshold_m 0.68`.
- `check-config --hardware` on the UNVERIFIED template → refused.

## 5. What this proves / does NOT prove

**Proves:** the logic invariants listed above, under simulated and mocked inputs.

**Does NOT prove:**
- physical accuracy;
- the real echo timing, release timing on hardware, floor echoes, beam width, or soft/angled-target behaviour;
- that the real wiring works.

The simulator's noise (`--sim-noise`, default 0.01 m Gaussian) is self-generated. The RNG-SIM-04 and RNG-SIM-05 "≈ 99.6 cm" figures are **not measurements**. RNG-SIM-04 ran on the real Pi's CPU but with no sensor involved.

## 6. Evidence

- RNG-SIM-02: this audit's terminal output (126 passed).
- RNG-SIM-04: `~/Team15_evidence/range/sensor_only_SIM/sensor_only_20261108T100442Z.json` and `diagnose_20261108T100442Z.json` on the Pi (private). SHA-256 not computed, because the Pi was unreachable.
- RNG-SIM-05: `$ROBOT_WORKSPACE/TEST_REPORT.md` (the private robotics workspace).

## 7. Limitations / next time

Add a test that a 0-edge real-style event stream (`echo_from_events` with no events) maps to `NO_ECHO`. That is implicitly covered today. Add `ranging/tests` to `pytest.ini` `testpaths`, so the default `pytest` run includes them.

# ROV-01: Issue #9 fail-closed forward motion and controller-link health (test suite)

**Label: MOCKED** (fake clock, fake driver; some cases use the SIMULATED world) · **Status: COMPLETE** (40/40 pass at d1b607a)
Back to: [17 Safety architecture](../../17_SAFETY_ARCHITECTURE.md) · [12 RoverC motor control](../../12_ROVERC_MOTOR_CONTROL.md) · [13 M5StickC bridge](../../13_M5STICKC_BRIDGE.md)

## In one paragraph (plain language)

Before this change, the robot's safety layer would refuse to drive forward only if the distance sensor explicitly said "not allowed". If the sensor said nothing at all, that silence was not treated as a "no". Issue #9 asked us to flip the default: forward motion must need an explicit, fresh, valid "yes", and anything else, including silence, means stop. PR #14 made that change, and added the same rule for the motor-controller link: no proof the controller is alive and listening means no motion. The 40 tests in this suite try every way we could think of to sneak a "yes" past the gate: a missing verdict, a stale reading, a reading from the future, garbage values, a dead controller, bad battery numbers, and AI or dashboard code importing motor functions. Every attempt is refused. The tests run against software stand-ins, so they say nothing about real motors.

## 1. Objective and hypothesis

- **Objective:** verify the Issue #9 policy. `MOVE_FORWARD` must be accepted, and continue, only with assessment CLEAR **and** `forward_allowed is True` **and** a fresh, finite, not-future reading **and** (for hardware) status OK. A physical driver must report `health()`. Invalid power counts as unknown. Nothing outside an allow-list may import the motor path.
- **Hypothesis:** every non-compliant input is refused (idle) or stops/latches (moving), and nothing restarts by itself when the input recovers.
- **Pass criteria:** all tests in `rover/tests/test_issue9_fail_closed.py` pass, and the pre-existing rover suite still passes (no regression in scenarios A–H).

## 2. Date, place, people (by role)

| Run | Date | Revision | Who | Result |
|---|---|---|---|---|
| R1 | 2026-11-08 (~10:27–10:45 UTC; commits `1b942e3`, `14fde0d`, `7efa570`) | PR #14 head | rover/robotics owner (GitHub `machackgo`); a separate reviewer session for the independent review | rover/tests **221 passed**; `pytest -q` **380 passed**; ranging **126 passed** (PR #14 description) |
| R2 | 2026-11-08 ~12:50 UTC | d1b607a (after PR #15 added bridge tests) | documentation audit | this file **40 passed**; rover/tests **284 passed** |

PR #14 was merged at 2026-11-08 12:11:27 UTC (merge commit `5760eaf`). Issue #9 was opened 2026-11-07 and closed 2026-11-08 12:11:28 UTC.

## 3. Hardware

None. A fake `Clock`, a fake `Drv` driver (with a configurable `physical` flag and `health()`), and for some cases the rover simulator. No device is opened.

## 4. Software

- d1b607a; `rover/tests/test_issue9_fail_closed.py` (sha256 prefix `13b4fb05bc427741`), `rover/motion.py` (`b720ffa357c25c87`), `rover/sensors.py`, `rover/sim.py`, `rover/hardware.py`.
- Python 3.13.5, pytest (repository `pytest.ini`), macOS.

## 5. Data and ground truth

Hand-constructed `RangeReading`/`PowerReading` objects and dicts. The ground truth is the policy table in Issue #9 and the PR #14 description: the expected verdict for each input is written into each assertion.

## 6. Metrics and why they were chosen

The metric is pass/fail per test case. Each case is a single safety property, so coverage of the input space matters more than any aggregate number. The cases were picked from the "Tests required" list in Issue #9, and extended by the independent review.

## 7. Results

40 collected, 40 passed (R2). Grouped:

| Group | Test functions (parametrised count) | Property |
|---|---|---|
| Positive control | `test_explicit_true_clear_fresh_is_accepted` (1) | CLEAR + True + fresh → accepted |
| Verdict | `..._none_refuses_forward`, `..._false_refuses_forward`, `test_verdict_lost_while_moving_stops` (2), `test_stop_on_lost_verdict_does_not_restart_when_verdict_returns`, `test_true_but_not_clear_refuses` (2) | None/False refuse; a loss while moving stops; no restart when the verdict returns; True without CLEAR refuses |
| Construction | `test_hardware_reading_must_state_a_verdict`, `test_forward_allowed_must_be_a_real_bool` (5), `test_forged_hardware_true_with_non_ok_status_refuses` (2) | hardware + None raises; only real bools; forged True on NO_ECHO/ERROR refuses |
| Freshness | `test_missing_reading_refuses_and_latches_while_moving`, `test_true_but_stale_refuses_and_latches_while_moving`, `test_non_finite_timestamp_refuses` (3), `test_nan_timestamp_while_moving_latches`, `test_future_timestamp_is_a_clock_fault`, `test_error_and_malformed_readings_refuse` | missing, stale, NaN/inf and future readings refuse, and latch `SENSOR_STALE` while moving |
| Controller link | `test_physical_driver_without_health_refuses`, `test_physical_driver_healthy_link_accepts_turn`, `test_controller_disconnect_refuses_motion`, `test_controller_disconnect_while_moving_latches_and_never_auto_restarts`, `test_health_check_that_raises_is_a_fault`, `test_roverc_adapter_health_needs_transport_health`, `test_dead_link_never_crashes_tick_and_stays_latched` | no health / fault / raise → refuse or `DRIVER_FAULT`; `tick()` never raises on a dead link |
| Power | `test_invalid_power_refuses` (3), `test_future_or_nan_power_timestamp_refuses`, `test_power_lost_while_moving_latches` | NaN/inf/None and future → refuse; loss while moving → latch |
| Preserved behaviour | `test_estop_latch_and_operator_reset_preserved`, `test_stop_file_still_trips`, `test_sim_readings_always_assert_a_verdict` | e-stop unchanged; the sim always asserts a verdict |
| Isolation | `test_nothing_outside_the_allow_list_can_reach_the_motor_path` | no file outside `MOTOR_PATH_ALLOWED` contains a motor-path name |

Regression: scenarios A–H are unchanged after the change (PR #14; re-confirmed in [SIM-01](SIM-01-rover-scenario-suite.md)).

## 8. Failures and interpretation

- **Bug found during development (fixed in `14fde0d`).** After a controller link died, `tick()` raised on every cycle: in the latched branch it called `_hard_zero()`, which re-raised the driver error. The USB-bridge end-to-end test found it. The fix is `_zero_never_raise`, which records `DRIVER_STOP_FAILED` and leaves the motors to the controller-side watchdog. Regression test: `test_dead_link_never_crashes_tick_and_stays_latched`.
- **Independent review (`7efa570`).** It found **no fail-open path**. It also asked for two changes, which were made: the allow-list scan now covers `rover/` itself, and driver health is evaluated once per tick. One review note was left unchanged by decision: the supervisor trusts the caller's `Assessment` (the navigator, which recomputes it every step).
- **Allow-list guard in practice.** The substring scan also fires on prose. The camera-mapping work had to reword docstrings to avoid motor-path names (commit `1f5c8db`, merged in PR #16).

## 9. Evidence files

| Evidence | Where |
|---|---|
| Test file | `rover/tests/test_issue9_fail_closed.py` (in repo) |
| Policy statement | GitHub Issue #9; PR #14 description (results R1) |
| Commits | `1b942e3` (policy), `14fde0d` (tick never raises), `7efa570` (review fixes) |
| R2 run | regenerated with the command in §11; not stored |

## 10. Limitations and confounders

- The tests exercise the supervisor's logic with hand-made inputs. They do not exercise real sensor timing, clock skew between processes, or real driver latency.
- The allow-list check is a static substring scan; dynamic imports could evade it.
- The supervisor's trust in the caller's `Assessment` is an accepted residual.
- The open contract item (ranging `t = now` when `mono_ns` is missing; [17](../../17_SAFETY_ARCHITECTURE.md) §9.3) is outside this suite.

## 11. Reproducibility

```bash
python3 -m pytest -q rover/tests/test_issue9_fail_closed.py     # 40 passed
python3 -m pytest -q rover/tests                                # 284 passed at d1b607a
```

Deterministic (fake clock).

## 12. What this proves / does NOT prove

**Proves:** in software, there is no tested input combination for which forward motion is accepted without an explicit, fresh, valid verdict; a dead or unverified controller link refuses or latches; no non-allow-listed module (Qwen glue, dashboard, perception, ranging, LiDAR, camera mapping) references the motor path.

**Does NOT prove:** that real hardware stops in time; that real sensors produce correct verdicts; that the firmware watchdog works. Passing unit tests never establish physical motor safety.

## 13. What we would change next time

- Add property-based tests (randomised `RangeReading` fields) on top of the enumerated cases.
- Replace the substring allow-list with an import-graph check, and keep the substring check as a second layer.
- Close the ranging `t = now` fallback with a test in the same suite.

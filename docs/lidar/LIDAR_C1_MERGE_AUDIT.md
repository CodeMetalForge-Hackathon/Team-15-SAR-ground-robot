# LiDAR merge-conflict and compatibility audit (PR #11)

Date 2026-11-08 ~04:00 UTC. **Read-only with respect to other branches: nothing merged, force-pushed, rebased or deleted.** The disposable worktree (scratchpad `lidar-merge-audit`) was removed after these results were saved.

## 1. Inputs (fetched)

| Ref | Head | Notes |
|---|---|---|
| origin/main | 06a69b9 | unchanged since PR #10 |
| feature/rplidar-c1-ground-robot (PR #11) | 9041c05 | 1 commit ahead of main |
| aurora-integration | 60eaad5 | 57 ahead, active (pushed ~13 min before the audit), base dbe4342 |
| aurora-mapping | 8b5691b | 7 ahead, `team15_starter/` only |
| culubo/sensor-id-specs (PR #6) | 8056838 | 47 ahead |
| GavinPrescott-sarsim | 801dc9e | 1 ahead (`sar_sim.zip`, `team_update.md`) |
| merged branches #2/#3/#5/#7/#8/#10 | — | 0 ahead of main |

## 2. File-level result

* `main + PR #11`: **clean merge** (local 00cf966). The diff against main adds files only (no M/D).
* PR #11's merged tree three-way against each active branch:

| Branch | Result | Cause |
|---|---|---|
| aurora-mapping | clean | — |
| GavinPrescott-sarsim | clean | — |
| aurora-integration | CONFLICT add/add `.gitignore` | **pre-existing**: main alone gives the same conflict; PR #11 does not touch `.gitignore` |
| culubo/sensor-id-specs (#6) | CONFLICT add/add `.gitignore` | **pre-existing**, same as above |

No active branch contains `lidar/`, `docs/lidar/`, a `lidar.yml` workflow, or the strings "lidar"/"rplidar". **No conflict is attributable to PR #11.** Resolution of the pre-existing `.gitignore` add/add (for the #6 and aurora owners, not this PR): union of both files' lines when those branches merge main.

## 3. Combined regression in the temp worktree (main + PR #11)

| Suite | Result |
|---|---|
| default pytest (planner, perception, dashboard, e2e, rover) | 340 passed |
| ranging/tests (Grove) | 126 passed |
| lidar/tests | 92 passed |
| rover Grove adapter + ranging contract | 93 passed (subset of the above, run explicitly) |
| `python -m planner.route A G` | A→G, 60 m |
| **Total** | **558 passed, 0 failed, 0 skipped** |

GitHub Actions on PR #11 9041c05: `lidar-tests`, `test` (ci) and `perception-tests` all pass, 6/6 runs (push + pull_request). `ranging` was not triggered (path filter), and it ran locally (126).

## 4. Interfaces confirmed working

* **Camera / perception / evidence:** unchanged files, 340-suite green (includes Pi camera e2e with a fake sender).
* **Dashboard:** the existing Forward obstacle range card renders LiDAR compat snapshots as SIMULATED, BLOCKED or UNKNOWN. Camera evidence, UNCONFIRMED, operator review, A→G route and fixture-spoof protection are untouched (dashboard tests green).
* **Qwen advisory:** additive optional `context.lidar`, consistent with the Qwen repo's SENSOR_FUSION_CONTRACT rules (no CLEAR claim, no person distance, association NOT_ESTABLISHED). The Qwen session is adapting to it, and I did not edit the Qwen repo.
* **Rover navigation:** unchanged. LiDAR fields are rejected (ERROR → UNKNOWN). This is pinned by tests.

## 5. Actuation check

* No GPIO, motor, servo or I²C code was added. An AST test bans those imports in `lidar/`, and pyserial is lazy inside `SerialTransport`.
* The Grove hardware gate still refuses the unverified config (rc 2). The LiDAR gate refuses its unverified config (rc 2). `scan-once` without approval is refused (rc 3).
* The rover hardware path is unchanged: `PiRobotIO` reports no power, so the supervisor refuses physical motion, and Issue #9 is open.

## 6. Semantic conflicts (Git does not report these)

| # | Topic | Finding | Status / mitigation |
|---|---|---|---|
| S1 | Old Grove assumptions in rover motion | `from_rover_fields` hard-codes `grove-ultrasonic`, so LiDAR is rejected. `motion.py:270/317` stops only on `forward_allowed is False` (None passes) | Safe today, because LiDAR never reaches motion. **Precondition for R1:** Issue #9 (`is True` required) must land before any LiDAR source is allowlisted |
| S2 | Sensor freshness | Rover 0.20 s / display 0.5 s, the same as the LiDAR constants (tested). LiDAR age is measured from capture **start**, so a full 100 ms revolution already uses half the motion budget | Documented; Pi latency to measure at Stage C. Below 5 Hz the motion limit can never be met (fails closed) |
| S3 | Hard-coded sensor names | `range_view.hardware_verified` requires `driver == "gpiod"`, so LiDAR is always SIMULATED on the card. The compat snapshot keeps `sensor_type: RPLIDAR_C1` | Safe; D2 request for a future verified LiDAR badge |
| S4 | Units | Protocol q2 mm and q6 deg → m and deg (tested). The Qwen field uses cm (`min_range_cm`), matching Qwen's existing range events. The compat snapshot uses m like ranging | Consistent |
| S5 | Angular frames | LiDAR SENSOR = clockwise; ROBOT = counter-clockwise, as in rover. There is no default offset, and an unaligned mount gives every sector UNKNOWN. Wrong orientation demonstrated in scenario 15 | Mitigated; alignment is a named Stage C step |
| S6 | Fixture provenance spoofing | LiDAR loader rejects non-SIMULATED fixtures; the panel shows SIMULATED for any fixture; the dashboard card rejects forged LIVE-HW (driver ≠ gpiod) | Tested |
| S7 | Grove client reading a LiDAR snapshot | `ranging.RangeClient` accepts any `range_snapshot/1`, and `GroveRangeIO` relabels it `grove-ultrasonic` | Mitigated: the compat snapshot never allows motion, and the writer refuses `/dev/shm/team15_range.json` (tested). Suggestion to the ranging owner (low): check `sensor_type == GROVE_ULTRASONIC` in `RangeClient` |
| S8 | Concurrent USB device access | The planned M5StickC motor bridge (ASCII lines, 115200) is also USB-serial; `ttyUSB*` numbering is not stable | Explicit `/dev/serial/by-id/` path in the gate, `exclusive=True` open, GET_INFO model check before SCAN. Stray LiDAR bytes at the wrong baud do not form a bridge command (`M <seq> …\n`), but the checklist (item 7) requires the bridge and LiDAR paths to be distinguished |
| S9 | Port conflicts | Replay 8775 is not used elsewhere (other hits on active branches are data values in TSV/CSV). Dashboard 8000, ranging 8765, robot API 8770, camera test 8792 | No conflict |
| S10 | Partial or stale scans read as clearance | Partial → CLEAR/CAUTION downgraded; stale → all UNKNOWN; no return → UNKNOWN; disconnected → UNKNOWN; real device never allows motion | Tested across scenarios 01, 09–14, 17, 20 |
| S11 | Workflow collisions | New file `lidar.yml`, display name `lidar`, job `lidar-tests`; distinct from `ci`, `perception`, `ranging` | No collision |
| S12 | Mirror / width limitations | Phantom far returns read CLEAR. The rover fields use the FRONT ±22.5° wedge, not a robot-width corridor (raised by the rover owner) | Documented. Corridor reduction is required before Stage D (migration doc). Blocks D/E |

## 7. Required actions before merge (none are code changes to other owners' branches)

1. Human review of PR #11. It stays a draft until the user decides.
2. Owners acknowledge the interface requests (rover R1–R3, dashboard D1–D3, Qwen Q1). Nothing needs to change on their side for Stage A/B.
3. Issue #9 stays a hard gate for R1.

## 8. Re-audit after the footprint-clearance round (2026-11-08, head 9027320)

* Inputs re-fetched. main is still 06a69b9. Active: aurora-integration 60eaad5, aurora-mapping 8b5691b, culubo/sensor-id-specs 8056838 (#6), GavinPrescott-sarsim 801dc9e.
* main + #11: **clean** (local 3b7ada6). Files are additive only. There is a zero-line diff in `rover/`, `ranging/`, `dashboard/` and `core/`.
* Against the active branches, the result is the same as §2. The only conflict is `.gitignore` add/add with aurora-integration and #6, and it is pre-existing (main alone conflicts identically). No branch contains LiDAR code.
* Combined regression: default 340 + ranging 126 + lidar 124 = **590 passed, 0 failed, 0 skipped**. Route A→G is 60 m.
* Gates: Grove hardware gate rc 2, LiDAR gate rc 2, `scan-once` without approval rc 3. No GPIO, motor or servo imports in `lidar/`.
* Semantic changes since §6:
  * S1/S12: the forward region is now a robot-width corridor (bumper reference agreed with the rover owner). The rover still rejects `rplidar-c1`, and Issue #9 still gates R1.
  * S2: corridor processing roughly doubles the Mac processing time (≈ 1.1 ms p50), still negligible against the 100 ms revolution.
  * S5: the orientation monitor now detects a wrong offset or sign error when a fiducial is configured; without one, motion is refused.
  * S10: weak returns and occluded rays are never clear evidence.
  * New S13: the corridor names mirror `rover/navigator.py NavConfig` (`robot_width_m`, `width_margin_m`, `lookahead_m`). If the rover renames them, the LiDAR config must follow. Values are configured separately, so they can drift; Stage D should source them from one place. This is a rover-owner item.
* The temp worktree was deleted after the results were saved.

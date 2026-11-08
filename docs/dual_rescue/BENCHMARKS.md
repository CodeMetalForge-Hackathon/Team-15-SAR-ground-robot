# Dual-robot rescue benchmark (SIMULATION)

Every number below comes from runs that **actually completed**: **1540 of 1540 planned runs** on revision
`953826b`, taking 98.3 s of wall time on 12 worker processes (Apple M4 Pro). The runs are simulated
missions on synthetic 48 m sites. They are not field trials and validate nothing physical.

Reproduce:

```
python3 -m simulation.dual_rescue.benchmark --runs 100 --all-environments --seed 42 --baselines 20 --stress 10
# -> benchmark_results/<UTC>/results.json, results.csv, summary.md, success_by_environment.png, baselines.png
python3 -m simulation.dual_rescue.benchmark --runs 20 --all-environments --seed 42      # the 160-run quick check
```

`benchmark_results/` is gitignored. The JSON and CSV hold one record per run: environment, seed,
software revision, mode, aerial planner, injected faults, every metric, the outcome, the simulated end time
and the wall time. Unsuccessful and unsafe runs are kept.

## Method

* **Runs.** One run is one complete `Mission`: fixed 0.05 s ticks and a fixed seed. Seeds 42..141 give
  100 per environment for the system under test (coordinated ground, MCTS aerial). Baselines use seeds
  42..61, the first 20, in the **same environments with the same seeds**. Ground truth comes from
  `numpy.random.default_rng(seed)` per environment, so every run can be replayed exactly
  (`test_reset_and_replay_are_deterministic`).
* **Truth access.** Metrics compare the outcome with simulator ground truth **after** the run
  (`Mission.evaluate`). Agents never receive it (`test_no_ground_truth_leakage_into_aerial_decisions`).
* **Run end.** A run ends when the coordinator reports MISSION_COMPLETE, a FAULT, or
  INSUFFICIENT_INFORMATION with the rover idle. Otherwise it ends at `max_t` (900 s; 1500 s for
  multi-survivor).
* **Outcomes.**
  * `SUCCESS`: every survivor located and every truth-reachable survivor reached at standoff (rover camera
    sighting, human review pending), with zero safety violations.
  * `UNREACHABLE_REPORTED`, `INSUFFICIENT_INFORMATION`, `SAFE_STOP_FAULT`, `SURVIVOR_NOT_FOUND`,
    `CANDIDATE_UNCONFIRMED`: safe stops; each one names why.
  * `PARTIAL`, `TIMEOUT`, `INCOMPLETE`: the mission did not finish.
  * `UNSAFE`: any collision, any entry into a corridor that was not routable, any motion while the safety
    latch was set, or any rescue claimed where no survivor was.
* **Correct outcome.** True when the run succeeded, or when its safe stop was justified by the truth: the
  survivor really was unreachable, could only be reached through corridors the drone cannot see, could
  not be seen at all (under an intact roof), or a fault was injected. This separates "the system behaved
  correctly" from "the rescue completed".

## Environments

| environment | layout | seeded ground truth |
|---|---|---|
| collapsed_building | 3 × 4 corridor grid + 5 room doorways, 1.0 m half-width | 1 survivor, 2 debris |
| open_outdoor | 3 × 3 trail network + diagonal, 2.0 m half-width | 1 survivor, 1 debris, 3 tree-canopy zones (visibility 0.35) |
| warehouse | 5 long rack aisles + cross aisles, 0.8 m half-width | 1 survivor, 3 debris, mezzanine (visibility 0.3) |
| narrow_corridors | hospital spine + wards, 0.6 m half-width | 1 survivor, 2 debris, smoke band (visibility 0.2) |
| maze | 5 × 5 junction grid, random spanning tree + 3 loops | 1 survivor, 2 debris (dead ends cut off whole branches) |
| dynamic | collapsed building, observations STALE after 60 s | 1 survivor, 1 static debris, 1 debris dropped on the rover's route after dispatch |
| multi_survivor | collapsed building | 3 survivors (random condition), 1 false heat source, 1 debris |
| partially_observable | collapsed building under a 24 × 28 m intact roof, 2 roof holes placed independently of the survivor | 1 survivor, 1 debris |

## Results: all configurations

| environment | mode | aerial planner | runs | mission success | correct outcome | located/survivors | coverage | 1st discovery s | drone path m | rover path m | replans | STOP events | collisions | unknown entries | incorrect assign. | safety viol. | mean sim s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| collapsed_building | coordinated | greedy | 20 | 100% | 100% | 20/20 | 0.97 | 27.973 | 317.68 | 47.198 | 0 | 0 | 0 | 0 | 0 | 0 | 131.13 |
| collapsed_building | coordinated | lawnmower | 20 | 100% | 100% | 20/20 | 0.97 | 171.31 | 1015.31 | 47.2 | 0 | 0 | 0 | 0 | 0 | 0 | 312.36 |
| collapsed_building | coordinated | mcts | 100 | 98% | 100% | 100/100 | 0.97 | 32.611 | 338.615 | 49.443 | 0 | 0 | 0 | 0 | 0 | 0 | 143.765 |
| collapsed_building | independent | mcts | 20 | 100% | 100% | 20/20 | 0.97 | 28.837 | 314.06 | 56.204 | 0.4 | 0.4 | 0 | 0 | 0 | 0 | 157.227 |
| collapsed_building | static_route | mcts | 20 | 100% | 100% | 20/20 | 0.98 | 28.837 | 325.515 | 48.4 | 0 | 0 | 0 | 0 | 0 | 0 | 136.953 |
| dynamic | coordinated | greedy | 20 | 90% | 100% | 20/20 | 0.97 | 27.973 | 385.28 | 62.407 | 0.9 | 1 | 0 | 0 | 0 | 0 | 203.03 |
| dynamic | coordinated | lawnmower | 20 | 90% | 100% | 20/20 | 0.97 | 171.31 | 1146.155 | 62.384 | 0.9 | 1 | 0 | 0 | 0 | 0 | 373.305 |
| dynamic | coordinated | mcts | 100 | 88% | 100% | 100/100 | 0.97 | 32.611 | 422.69 | 61.421 | 0.88 | 1 | 0 | 0 | 0 | 0 | 218.835 |
| dynamic | independent | mcts | 20 | 90% | 100% | 20/20 | 0.97 | 28.837 | 314.06 | 63.848 | 1.2 | 1.3 | 0 | 0 | 0 | 0 | 205.852 |
| dynamic | static_route | mcts | 20 | 0% | 10% | 20/20 | 0.97 | 28.837 | 347.655 | 9.056 | 0 | 1 | 0 | 0 | 0 | 0 | 105.612 |
| maze | coordinated | greedy | 20 | 55% | 100% | 20/20 | 0.97 | 37.885 | 315.65 | 48.519 | 0 | 0 | 0 | 0 | 0 | 0 | 167.857 |
| maze | coordinated | lawnmower | 20 | 55% | 100% | 20/20 | 0.97 | 233.512 | 1010.01 | 48.52 | 0 | 0 | 0 | 0 | 0 | 0 | 359.502 |
| maze | coordinated | mcts | 100 | 62% | 100% | 97/100 | 0.97 | 42.357 | 332.001 | 54.156 | 0 | 0 | 0 | 0 | 0 | 0 | 182.674 |
| maze | independent | mcts | 20 | 55% | 100% | 20/20 | 0.97 | 44.538 | 310.0 | 74.37 | 0.3 | 0.75 | 0 | 0 | 0 | 0 | 226.873 |
| maze | static_route | mcts | 20 | 55% | 100% | 20/20 | 0.97 | 44.538 | 336.21 | 48.519 | 0 | 0 | 0 | 0 | 0 | 0 | 177.653 |
| multi_survivor | coordinated | greedy | 20 | 100% | 100% | 60/60 | 0.97 | 11.682 | 319.62 | 139.649 | 0 | 0 | 0 | 0 | 8 | 0 | 355.657 |
| multi_survivor | coordinated | lawnmower | 20 | 100% | 100% | 60/60 | 0.97 | 59.9 | 1033.26 | 130.952 | 0 | 0 | 0 | 0 | 12 | 0 | 432.373 |
| multi_survivor | coordinated | mcts | 100 | 99% | 99% | 299/300 | 0.97 | 15.611 | 388.028 | 139.782 | 0 | 0 | 0 | 0 | 43 | 0 | 363.66 |
| multi_survivor | independent | mcts | 20 | 100% | 100% | 60/60 | 0.98 | 16.04 | 386.195 | 151.013 | 0.5 | 0.5 | 0 | 0 | 11 | 0 | 399.445 |
| multi_survivor | static_route | mcts | 20 | 100% | 100% | 60/60 | 0.97 | 16.04 | 388.465 | 145.049 | 0 | 0 | 0 | 0 | 9 | 0 | 376.902 |
| narrow_corridors | coordinated | greedy | 20 | 85% | 100% | 20/20 | 0.97 | 35.72 | 291.565 | 57.759 | 0 | 0 | 0 | 0 | 0 | 0 | 161.85 |
| narrow_corridors | coordinated | lawnmower | 20 | 85% | 100% | 20/20 | 0.95 | 161.213 | 986.605 | 57.758 | 0 | 0 | 0 | 0 | 0 | 0 | 325.3 |
| narrow_corridors | coordinated | mcts | 100 | 84% | 100% | 95/100 | 0.97 | 23.167 | 363.228 | 54.505 | 0 | 0 | 0 | 0 | 0 | 0 | 154.97 |
| narrow_corridors | independent | mcts | 20 | 85% | 100% | 18/20 | 0.97 | 22.708 | 326.775 | 64.157 | 0.45 | 0.5 | 0 | 0 | 0 | 0 | 176.577 |
| narrow_corridors | static_route | mcts | 20 | 75% | 100% | 18/20 | 0.97 | 22.708 | 387.26 | 55.462 | 0 | 0 | 0 | 0 | 0 | 0 | 161.745 |
| open_outdoor | coordinated | greedy | 20 | 90% | 100% | 20/20 | 0.97 | 44.737 | 331.605 | 61.988 | 0 | 0 | 0 | 0 | 0 | 0 | 171.778 |
| open_outdoor | coordinated | lawnmower | 20 | 90% | 100% | 20/20 | 0.96 | 190.528 | 1004.125 | 58.391 | 0 | 0 | 0 | 0 | 0 | 0 | 340.005 |
| open_outdoor | coordinated | mcts | 100 | 89% | 100% | 97/100 | 0.96 | 28.702 | 364.197 | 55.98 | 0 | 0 | 0 | 0 | 0 | 0 | 151.78 |
| open_outdoor | independent | mcts | 20 | 95% | 100% | 19/20 | 0.98 | 29.216 | 354.25 | 48.371 | 0.15 | 0.15 | 0 | 0 | 0 | 0 | 144.785 |
| open_outdoor | static_route | mcts | 20 | 85% | 100% | 19/20 | 0.97 | 29.216 | 366.315 | 54.545 | 0 | 0 | 0 | 0 | 0 | 0 | 151.555 |
| partially_observable | coordinated | greedy | 20 | 70% | 100% | 16/20 | 0.84 | 33.019 | 261.0 | 38.438 | 0 | 0 | 0 | 0 | 0 | 0 | 122.093 |
| partially_observable | coordinated | lawnmower | 20 | 70% | 100% | 16/20 | 0.95 | 178.6 | 991.575 | 37.242 | 0 | 0 | 0 | 0 | 0 | 0 | 302.793 |
| partially_observable | coordinated | mcts | 100 | 73% | 100% | 84/100 | 0.77 | 29.525 | 269.563 | 49.295 | 0 | 0 | 0 | 0 | 0 | 0 | 139.937 |
| partially_observable | independent | mcts | 20 | 75% | 100% | 15/20 | 0.75 | 31.273 | 275.6 | 34.893 | 0 | 0 | 0 | 0 | 0 | 0 | 111.86 |
| partially_observable | static_route | mcts | 20 | 70% | 100% | 15/20 | 0.76 | 31.273 | 282.66 | 37.287 | 0 | 0 | 0 | 0 | 0 | 0 | 119.752 |
| warehouse | coordinated | greedy | 20 | 30% | 100% | 19/20 | 0.98 | 38.747 | 313.74 | 59.693 | 0 | 0 | 0 | 0 | 0 | 0 | 168.458 |
| warehouse | coordinated | lawnmower | 20 | 30% | 100% | 20/20 | 0.92 | 165.875 | 955.735 | 54.591 | 0 | 0 | 0 | 0 | 0 | 0 | 301.88 |
| warehouse | coordinated | mcts | 100 | 45% | 100% | 96/100 | 0.97 | 39.823 | 386.155 | 51.487 | 0 | 0 | 0 | 0 | 0 | 0 | 156.239 |
| warehouse | independent | mcts | 20 | 90% | 100% | 19/20 | 0.98 | 43.571 | 326.565 | 70.555 | 0.7 | 0.75 | 0 | 0 | 0 | 0 | 214.708 |
| warehouse | static_route | mcts | 20 | 30% | 100% | 19/20 | 0.98 | 43.571 | 395.62 | 49.955 | 0 | 0 | 0 | 0 | 0 | 0 | 158.485 |

## Outcomes

| environment | mode | planner | outcomes |
|---|---|---|---|
| collapsed_building | coordinated | greedy | SUCCESS 20 |
| collapsed_building | coordinated | lawnmower | SUCCESS 20 |
| collapsed_building | coordinated | mcts | SUCCESS 98, UNREACHABLE_REPORTED 2 |
| collapsed_building | independent | mcts | SUCCESS 20 |
| collapsed_building | static_route | mcts | SUCCESS 20 |
| dynamic | coordinated | greedy | SUCCESS 18, UNREACHABLE_REPORTED 2 |
| dynamic | coordinated | lawnmower | SUCCESS 18, UNREACHABLE_REPORTED 2 |
| dynamic | coordinated | mcts | SUCCESS 88, UNREACHABLE_REPORTED 12 |
| dynamic | independent | mcts | SUCCESS 18, UNREACHABLE_REPORTED 2 |
| dynamic | static_route | mcts | UNREACHABLE_REPORTED 20 |
| maze | coordinated | greedy | SUCCESS 11, UNREACHABLE_REPORTED 9 |
| maze | coordinated | lawnmower | SUCCESS 11, UNREACHABLE_REPORTED 9 |
| maze | coordinated | mcts | SUCCESS 62, SURVIVOR_NOT_FOUND 3, UNREACHABLE_REPORTED 35 |
| maze | independent | mcts | SUCCESS 11, UNREACHABLE_REPORTED 9 |
| maze | static_route | mcts | SUCCESS 11, UNREACHABLE_REPORTED 9 |
| multi_survivor | coordinated | greedy | SUCCESS 20 |
| multi_survivor | coordinated | lawnmower | SUCCESS 20 |
| multi_survivor | coordinated | mcts | PARTIAL 1, SUCCESS 99 |
| multi_survivor | independent | mcts | SUCCESS 20 |
| multi_survivor | static_route | mcts | SUCCESS 20 |
| narrow_corridors | coordinated | greedy | INSUFFICIENT_INFORMATION 2, SUCCESS 17, UNREACHABLE_REPORTED 1 |
| narrow_corridors | coordinated | lawnmower | INSUFFICIENT_INFORMATION 2, SUCCESS 17, UNREACHABLE_REPORTED 1 |
| narrow_corridors | coordinated | mcts | INSUFFICIENT_INFORMATION 9, SUCCESS 84, SURVIVOR_NOT_FOUND 5, UNREACHABLE_REPORTED 2 |
| narrow_corridors | independent | mcts | SUCCESS 17, SURVIVOR_NOT_FOUND 2, UNREACHABLE_REPORTED 1 |
| narrow_corridors | static_route | mcts | INSUFFICIENT_INFORMATION 2, SUCCESS 15, SURVIVOR_NOT_FOUND 2, UNREACHABLE_REPORTED 1 |
| open_outdoor | coordinated | greedy | INSUFFICIENT_INFORMATION 2, SUCCESS 18 |
| open_outdoor | coordinated | lawnmower | INSUFFICIENT_INFORMATION 2, SUCCESS 18 |
| open_outdoor | coordinated | mcts | INSUFFICIENT_INFORMATION 8, SUCCESS 89, SURVIVOR_NOT_FOUND 3 |
| open_outdoor | independent | mcts | SUCCESS 19, SURVIVOR_NOT_FOUND 1 |
| open_outdoor | static_route | mcts | INSUFFICIENT_INFORMATION 2, SUCCESS 17, SURVIVOR_NOT_FOUND 1 |
| partially_observable | coordinated | greedy | INSUFFICIENT_INFORMATION 2, SUCCESS 14, SURVIVOR_NOT_FOUND 4 |
| partially_observable | coordinated | lawnmower | INSUFFICIENT_INFORMATION 2, SUCCESS 14, SURVIVOR_NOT_FOUND 4 |
| partially_observable | coordinated | mcts | INSUFFICIENT_INFORMATION 11, SUCCESS 73, SURVIVOR_NOT_FOUND 16 |
| partially_observable | independent | mcts | SUCCESS 15, SURVIVOR_NOT_FOUND 5 |
| partially_observable | static_route | mcts | INSUFFICIENT_INFORMATION 1, SUCCESS 14, SURVIVOR_NOT_FOUND 5 |
| warehouse | coordinated | greedy | INSUFFICIENT_INFORMATION 12, SUCCESS 6, SURVIVOR_NOT_FOUND 1, UNREACHABLE_REPORTED 1 |
| warehouse | coordinated | lawnmower | INSUFFICIENT_INFORMATION 13, SUCCESS 6, UNREACHABLE_REPORTED 1 |
| warehouse | coordinated | mcts | CANDIDATE_UNCONFIRMED 1, INSUFFICIENT_INFORMATION 48, SUCCESS 45, SURVIVOR_NOT_FOUND 4, UNREACHABLE_REPORTED 2 |
| warehouse | independent | mcts | SUCCESS 18, SURVIVOR_NOT_FOUND 1, UNREACHABLE_REPORTED 1 |
| warehouse | static_route | mcts | INSUFFICIENT_INFORMATION 12, SUCCESS 6, SURVIVOR_NOT_FOUND 1, UNREACHABLE_REPORTED 1 |

## Baselines (same environments, same seeds 42..61, 160 runs each)

Aerial planners (ground coordinated). Greedy and lawnmower are the existing `sar.planners` classes,
unchanged:

| aerial planner | mean time to first discovery | survivors located | mean drone path | mission successes | mean mission time |
|---|---|---|---|---|---|
| MCTS (PR #17 `FleetMCTS`) | 30.6 s | 191 / 200 | 362 m | 121 / 160 | 187 s |
| greedy | 32.2 s | 195 / 200 | 317 m | 124 / 160 | 185 s |
| lawnmower | 166.2 s | 196 / 200 | 1018 m | 124 / 160 | 343 s |

Systematic belief-driven search (MCTS or greedy) finds the first survivor about **5× faster** than the
lawnmower sweep, with about a third of the flight distance. **MCTS did not beat greedy** here: the
differences are within noise, and greedy located slightly more survivors. No improvement is claimed.

Ground and coordination modes (aerial MCTS):

| mode | mission successes | correct outcomes | rover STOP events | replans | sensor-gated probes through unobserved corridors | INSUFFICIENT_INFORMATION | collisions |
|---|---|---|---|---|---|---|---|
| coordinated (shared map) | 121 / 160 | 160 / 160 | 20 | 18 | 0 | 17 | 0 |
| independent (no shared corridor map) | 138 / 160 | 160 / 160 | 87 | 74 | 846 | 0 | 0 |
| static_route (shortest path, no replanning) | 103 / 160 | 142 / 160 | 20 | 0 | 0 | 17 | 0 |

* **Replanning matters under dynamic debris.** In `dynamic`, coordinated succeeded in 18/20 runs and
  static_route in 0/20 (all UNREACHABLE).
* **Coordination trades completions for caution.**
  * The independent baseline drives through unobserved corridors behind its range sensor: 846 such
    corridor traversals, 4.4× the STOP events and 4× the replans. It completes more rescues (warehouse
    18/20 against 6/20) because it does not stop at corridors the drone cannot see.
  * The coordinated system never treats UNKNOWN as CLEAR. In 17 of these runs it asked the operator for
    more sensing instead.
  * Both are correct by their own rules. Which one to use is an operator policy choice, and the simulation
    makes the cost visible.

## Failure injection (10 seeds per fault, each with an explicit expected behaviour)

| fault | environment | injected | expected behaviour | runs | check passed | outcomes |
|---|---|---|---|---|---|---|
| unexpected_debris | dynamic | debris drops onto the rover's route after dispatch | rover stops before contact (no collision), marks the corridor blocked, replans or reports | 10 | 10/10 | SUCCESS 9, UNREACHABLE_REPORTED 1 |
| blocked_corridors | maze | static debris in a maze with dead ends | no route through a BLOCKED corridor; correct outcome (rescue, or unreachable reported) | 10 | 10/10 | SUCCESS 5, UNREACHABLE_REPORTED 5 |
| missing_observations | collapsed_building | 30 % of aerial frames lost | lost frames give no evidence: no false CLEAR, no unsafe motion | 10 | 10/10 | SUCCESS 10 |
| delayed_observations | collapsed_building | aerial observations delivered 5 s late | decisions wait for evidence; no unsafe motion; correct outcome | 10 | 10/10 | SUCCESS 10 |
| false_detections | multi_survivor | a false heat source (decoy) in another room | a decoy is never reported as a rescue (incorrect claims = 0) | 10 | 10/10 | SUCCESS 10 |
| unreachable_target | collapsed_building | debris on the survivor's only doorway | UNREACHABLE (or INSUFFICIENT_INFORMATION) reported; never AT_STANDOFF | 10 | 10/10 | UNREACHABLE_REPORTED 10 |
| lost_communication | collapsed_building | rover mission link down from t=40 s to t=70 s | COMMS_LOST latched by the rover safety supervisor, rover stopped, no auto-resume | 10 | 10/10 | SAFE_STOP_FAULT 10 |
| agent_timeout | collapsed_building | AIR-1 stops responding at t=15 s | AIR-1 marked UNAVAILABLE; UNKNOWN corridors stay UNKNOWN; no unsafe motion | 10 | 10/10 | CANDIDATE_UNCONFIRMED 4, SURVIVOR_NOT_FOUND 6 |
| invalid_coordinates | collapsed_building | a corrupted aerial observation with coordinates off the site | observation rejected, never placed on the map | 10 | 10/10 | SUCCESS 10 |
| conflicting_observations | dynamic | drone camera blind to debris (reports corridors CLEAR) | rover ultrasonic still stops it; BLOCKED is kept over a later aerial CLEAR | 10 | 10/10 | SUCCESS 9, UNREACHABLE_REPORTED 1 |

## Failure analysis

**Defects the benchmark found, now fixed** (each fix is in this PR's history, and the numbers above come
from the fixed revision):

1. **False rescue claims (multi_survivor: 21 of 100 coordinated runs UNSAFE on revision `352f06d`).** A HUMAN_REVIEW
   request from a previous target stayed pending, as it should until a human reviews it. The
   coordinator read it as the next target's standoff, including targets that were false heat sources.
   Now only requests raised for the current dispatch, for a person on that target's own doorway, count.
   **Now: 0 incorrect claims in 1540 runs.**
2. **Detour lost to staleness (dynamic).** After a verified retreat, the Navigator's follow-up plan
   re-applied the 60 s freshness filter, so a detour could go stale mid-retreat and end in
   UNREACHABLE. The reason text also called stale corridors "blocked". Freshness is now enforced only at
   the detour decision, where the rover can hold for sensing. **dynamic correct outcomes went from 97 %
   to 100 %.**
3. **Endless search under a roof (partially_observable, 17 % TIMEOUT).** Search completion counted
   probability mass the camera can never see. It now uses the observable (visibility-weighted) PoS.
   **The mean drone path went from 3008 m to 270 m.**
4. **Stall on an unconfirmed candidate (warehouse/outdoor TIMEOUTs).** A candidate still POSSIBLE after
   the search kept the mission in CONFIRMING. The coordinator now re-tasks up to 2 confirm passes, then
   leaves the candidate for operator review.
5. **Baseline bugs.** The lawnmower ended at once because the sweep cell had already been reached.
   static_route froze the whole knowledge graph, so the drone scouted forever. Both are fixed before the
   baseline numbers were taken.

**Remaining non-successes (coordinated, MCTS: 162 of 800 runs; 161 of them correct safe stops):**

* **UNREACHABLE_REPORTED (53).** The seeded debris really does cut the survivor off, mostly in `maze`
  (35), where dead ends make one block decisive. Every one was truth-checked as unreachable.
* **INSUFFICIENT_INFORMATION (76).** The only routes cross corridors the drone cannot see:
  warehouse mezzanine 48, partially observable 11, outdoor canopy 8, smoke 9. The rover pre-positions
  and asks the operator. A sensor-gated probe exists (dashboard button) but is never auto-approved here.
* **SURVIVOR_NOT_FOUND (31).** The survivor is under an intact roof, canopy or mezzanine, where thermal
  PoD × visibility is 0 or near 0.
* **CANDIDATE_UNCONFIRMED (1), PARTIAL (1).** One multi_survivor run (seed 69) located all three
  survivors but did not finish reaching every reachable one before its `max_t`. This is the only incorrect
  outcome among 800 runs.

**Known limitation found, not fixed in this PR.** The drone made 16 false CLEAR corridor reports in
`dynamic` in the **independent-mode baseline** (16 of its 20 runs; **0** in the coordinated system under test), plus 24 in the injected blind-camera fault (all 10 runs). Counts corrected by the final audit against the run CSV. A corridor's coverage accumulates looks made
**before** debris fell, so the drone can call it CLEAR afterwards. None led to a collision or an unsafe
outcome: the rover's own ultrasonic stopped it every time, and its BLOCKED observation wins over a later
aerial CLEAR. The planned fix is to count only samples seen within the freshness window.

**Rover-camera checks against false heat sources.** In multi_survivor the drone confirmed a false heat
source in 43 of 100 runs, and the rover was dispatched to it. In every case the rover's camera saw no
person, the target was closed as NO_PERSON_FOUND, and no rescue was claimed.

## Limitations

* The sites are synthetic graphs. Rover dynamics are the existing synthetic `rover.sim` model, and
  sensing is the simplified PoD × visibility model. The drone has no wind, battery, takeoff or landing
  model.
* The rover camera sees a person within 8 m and ±33°, a SIMULATED cue. Survivor confirmation remains
  human.
* The runs are 100 seeds per environment and say nothing about physical robots.

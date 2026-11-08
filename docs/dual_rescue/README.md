# Dual-robot search and rescue: aerial scout + ground rover (SIMULATION)

Everything here is a **simulation**. No drone, rover, motor, serial port, GPIO or radio is opened. The
simulation runs the team's **real algorithms**: the rover `Navigator` state machine, the safety supervisor,
`ObservationLog` and Dijkstra routing (PRs #8/#14), and PR #17's aerial belief search (`GridWorld`,
`apply_look`, `FleetMCTS`). It also adds the smallest simulation-only adapters needed to run the two agents
together.

```
scripts/run_dual_rescue.sh            # then open http://localhost:8000/rescue
python3 -m simulation.dual_rescue.mission B --messages        # headless, prints the agent message log
python3 -m simulation.dual_rescue.benchmark --runs 20 --all-environments --seed 42
python3 -m pytest -q simulation/dual_rescue/tests
```

The demo works offline: no Raspberry Pi, robot or internet is needed. three.js r160 is vendored under
`dashboard/static/rescue/vendor/three/` (MIT). Qwen is optional. Without it the report is the labelled
deterministic fallback.

## Capability matrix (audit of `main` @ `d1b607a`)

| Capability | Where | Status |
|---|---|---|
| Ground route planning (Dijkstra, blocked edges) | `planner/route.py`, `planner/astar.py` | **Implemented and tested** (`planner/tests`, CI) |
| Rover navigation state machine, stop/verify/scan/replan | `rover/navigator.py` | **Implemented and tested**, **simulation-only** (pose is trusted only from `SIM_TRUTH`) |
| Motion safety supervisor, e-stop, watchdog, COMMS_LOST latch | `rover/motion.py` | **Implemented and tested** (`rover/tests`) |
| Obstacle evidence log (CONFIRMED / UNCONFIRMED / independent clearing) | `rover/observations.py` | **Implemented and tested** |
| Rover scenarios A–H | `rover/simrun.py` | **Simulation-only**, tested |
| RoverC USB bridge + firmware watchdog | `rover/bridge.py`, `firmware/` | **Implemented, not verified** on hardware (mocked tests) |
| Aerial belief search (MCTS / greedy / lawnmower) | `team15_starter/sar`, `team15_starter/fleet/planner.py` | **Implemented**; tested by `team15_starter/tests/test_fleet.py` (a script, not in CI); **simulation-only** |
| Drone fleet sim, homebase, radio protocol | `team15_starter/fleet`, `team15_starter/link` | **Simulation-only** (`homebase.py --sim`); firmware not flight-tested |
| Drone flight control, drone localization, physical autonomous exploration | — | **Missing**. Not claimed anywhere here |
| Camera person detection (Faster R-CNN) | `perception/` | **Implemented and tested** on recorded Pi 5 + IMX708 frames |
| Camera obstacle mapping / corridor assessment | `camera_mapping/` | **Implemented and tested**; distances **uncalibrated** |
| Qwen advisory (RAG + guard, authority NONE) | `camera_mapping/advisory.py`, `qwen_advisory/`, Team-15-Qwen service | **Implemented**. The running service reports `model_id ollama:qwen3.5:2b-q4_K_M`, config `C_QWEN_RAG`. The LoRA adapter is **not** shown to be loaded by that service |
| Dual-robot coordination, shared map, handoff | `simulation/dual_rescue/` | **New**, **simulation-only**, tested (25 tests) and benchmarked |

## Architecture

```
                 GroundTruth (simulator only: survivors, false heat sources, debris, drop times)
                    |  aerial_look(cell, fov, pod, rng)       |  rover.sim.SimWorld (ultrasonic, camera, physics)
                    v  (opaque callable)                       v
   AIR-1  AerialScout                                  GND-1  GroundRover
   fleet.planner GridWorld + apply_look                 rover.navigator.Navigator (CoopNavigator subclass)
   FleetMCTS (or greedy / lawnmower baseline)           safety supervisor + ObservationLog (rover.simrun.build_for_world)
   candidates (Bayes confidence), corridor coverage     KNOWLEDGE graph: only CLEAR / TRAVERSED / PROBE corridors
        | outbox --(link: delay, loss)-->  Coordinator  <--(link: heartbeat, loss)-- ObservationLog
                                           shared map (corridor states + freshness), candidates,
                                           ranking, scouting tasks, dispatch, faults
                                                 |
                       dashboard /api/rescue  ->  /rescue  (Three.js digital twin, renders state only)
                                                 |
                       report.py -> Team-15-Qwen /advisory (display only, authority NONE)
```

* **Frame.** `SITE`: origin at the site's south-west corner, x east, y north, in metres. Every site is
  48 m × 48 m. The aerial belief grid is 24 × 24 cells of 2 m.
* **Information model.** The floor plan (corridor graph, room doorways) is pre-incident knowledge.
  Corridor *condition* starts UNKNOWN. The overhead visibility map (intact roof, smoke, canopy) is what
  the drone sees from above. Ground truth reaches the agents only through sensing. The test
  `test_no_ground_truth_leakage_into_aerial_decisions` moves the survivor and checks that the flight is
  identical until a detection.
* **Aerial scout.** PR #17's `GridWorld` belief with a visibility-weighted footprint. Each look applies
  `apply_look` (Bayes no-detection) and `FleetMCTS` picks the next move. The dashboard shows the N/Q table
  as the "why". A survivor is detected only when it lies inside the (2·fov+1)² footprint, with probability
  PoD × visibility (`sar.sensors` thermal preset: fov 2 = 10 m, PoD 0.90). A new candidate triggers a
  3-look confirm hover, as PR #17's finder role does. Confidence is a Bayes posterior with a 0.10 base
  rate and a 0.05 false-alarm rate. Corridors are CLEAR once at least 95 % of their floor has been seen,
  and OCCLUDED when the camera cannot see them.
* **Ground rover.** The real `Navigator` runs on a *knowledge graph*. It cannot plan through a corridor
  that has not been observed. One subclass hook is new: after the Navigator's own obstacle scan, if no
  KNOWN route exists, the rover holds (stopped) and the coordinator tasks the drone. Optional freshness
  (`fresh_s`) excludes STALE corridors from new routes. A mission-link watchdog latches the supervisor's
  existing `COMMS_LOST`.
* **Coordinator.** It does the following:
  * scouts the shortest floor-plan route from the air before dispatch;
  * asks the drone to re-check a block the rover's ultrasonic reports;
  * plans detours over corridors that are only now known;
  * ranks targets by `(condition, known route, route length, -confidence, id)`;
  * rejects observations with invalid coordinates;
  * times out a silent drone;
  * reports INSUFFICIENT_INFORMATION / UNREACHABLE instead of inventing a route.
* **Qwen.** `report.py` sends timestamped, id-tagged facts to the existing RAG service. Text matching the
  motor-command pattern is discarded. Cited observation ids are checked against the evidence. Any failure
  falls back to the labelled deterministic report.

## Scenarios (dashboard and `mission.py`)

| Key | Environment | What it shows |
|---|---|---|
| A | collapsed building | survey → candidate → confirm hover → aerial route check (debris on M1-N1 changes the plan) → handoff → standoff |
| B | collapsed building | the full Phase-5 sequence: dynamic debris → ultrasonic STOP/VERIFY/MARK/SCAN → aerial re-check → rover holds → drone observes detour → Navigator replans → standoff |
| C | collapsed building, intact east roof | UNKNOWN ≠ CLEAR: INSUFFICIENT_INFORMATION, rover pre-positions, operator can approve a sensor-gated probe |
| D | collapsed building | 3 survivors ranked LYING_DOWN > NOT_MOVING > MOVING, served in order |
| E | collapsed building | rover link loss → COMMS_LOST latched, no auto-resume |
| W / K / O / M | warehouse / narrow corridors / outdoor / maze | the benchmark environments (fixed seeds) with distinct 3D themes |

## Files

* `simulation/dual_rescue/`: `world.py` (frame, layouts, ground truth), `environments.py` (8 seeded
  generators), `aerial.py`, `ground.py`, `coordinator.py`, `mission.py` (loop, faults, evaluation),
  `scenarios.py`, `report.py`, `benchmark.py`, `tests/`
* `dashboard/rescue_api.py`, `dashboard/static/rescue/` (`index.html`, `app.js`, `scene.js`, vendored
  three.js). `dashboard/app.py` mounts the router.
* `rover/simrun.py`: additive `build_for_world()` factory. `build()` delegates to it with unchanged
  behaviour (all rover tests pass). New modules never name motor-path symbols, so the PR #14
  allow-list guard stays green.
* `scripts/run_dual_rescue.sh`, `docs/dual_rescue/` (this file, `BENCHMARKS.md`, `JUDGE_SCRIPT.md`,
  `RENDERING.md`)

## Limitations

* Everything is SIMULATED. Robot dynamics are the existing synthetic models: the rover runs at 0.6 m/s on
  graph edges with heading from sim truth. The drone flies at 4 m/s at a constant 15 m display altitude,
  with no takeoff, landing, wind or battery model.
* Sensing is simplified. Thermal detection uses PoD × visibility; debris is seen whenever the floor is
  visible; the rover's camera sees a person within 8 m and ±33°. False heat sources are modelled, but
  other false-alarm types are not.
* Sites are synthetic 48 m graphs, and corridor widths and side clearances are placeholders. A layout
  that has a free-space map but no graph (open-field navigation off the paths) is not modelled.
* Survivor confirmation still needs a human: the rover stops at a standoff with `HUMAN_REVIEW` pending.
* No results here say anything about real-world flight, real localization or a physical rescue.

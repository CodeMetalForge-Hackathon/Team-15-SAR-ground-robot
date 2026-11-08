# SIM-01: Rover navigation simulation scenario suite (A–H)

**Label: SIMULATED** (distances SYNTHETIC) · **Status: COMPLETE** (8/8 scenarios reach their expected end state; 10/10 scenario tests pass)
Back to: [12 RoverC motor control](../../12_ROVERC_MOTOR_CONTROL.md) · [18 Simulation](../../18_SIMULATION.md) · [17 Safety architecture](../../17_SAFETY_ARCHITECTURE.md)

## In one paragraph (plain language)

We have no robot that can drive yet, so we built a small "video game" version of the trail network and let the real navigation and safety code drive a pretend robot through it. Eight stories were scripted. In one the trail is clear; in others a box sits on the trail, two boxes block two trails, every route is blocked, a blocked trail is later cleared, the distance sensor suddenly dies, and a person appears ahead. In every story the code did what a careful human would want. It stopped, checked the obstacle three times, looked left, right and behind by turning on the spot, picked the next-shortest route, refused to continue when no route existed, stopped for good when the sensor died, and asked a human when it saw a person. None of this shows what a real RoverC-Pro would do on a real floor.

## 1. Objective and hypothesis

- **Objective:** show that the navigation state machine (`rover/navigator.py`) and the safety supervisor (`rover/motion.py`) produce the intended behaviour in each scripted situation: obstacle confirmation, directional scanning, Dijkstra rerouting, safe stop, stale-sensor latch and human review.
- **Hypothesis:** each scenario ends in its expected terminal state, with the expected route and blocked edges, no collision, and no automatic restart after a safety stop.
- **Pass criteria:** the assertions in `rover/tests/test_scenarios.py` (10 tests), plus `collision is None` for every scenario.

## 2. Date, place, people (by role)

| Run | Date | Where | Who |
|---|---|---|---|
| R1: PR #8 description | 2026-11-07 (head `dac82f4`) | developer Mac | rover-navigation owner (the PR author); results quoted from the PR #8 description |
| R2: this report | 2026-11-08 ~12:50 UTC | developer Mac (Apple M4 Pro), macOS, Python 3.13.5 | documentation audit (re-run) |

## 3. Hardware

None. Pure software simulation. No GPIO, I²C, serial or motor device is opened. `SimDriver.physical = False`.

## 4. Software

- R2: repository at **d1b607a** (main after PR #17). `rover/`, `firmware/` and `team15_starter/` are unchanged from d1b607a in the docs worktree (`git diff --quiet d1b607a -- rover firmware team15_starter`).
- Key files: `rover/sim.py` (sha256 prefix `a76e54705b8718e3`), `rover/simrun.py` (`b972f5749eac548d`), `rover/motion.py` (`b720ffa357c25c87`), `rover/tests/test_scenarios.py` (`c6b8e20e9f1b0ef5`).
- Model/checkpoint: n/a (no ML).

## 5. Data and ground truth

- **Map:** `fixtures/trail_graph_synthetic.json`: 26 nodes A–Z, 15 undirected edges, SYNTHETIC metres (taken from the drone build guide §3.2).
- **Ground truth** is the simulator's own state: obstacle positions (`SimObstacle.at_m`), pose (`SIM_TRUTH`) and the odometer.
- **Independent check:** `rover/tests/test_distances.py` compares the simulated traveled distance with a hand count (A 60, B/C 84, D 106, E 75, F 30 m, ±0.5 m), and the routes with direct `compute_route` calls.

## 6. Metrics and why they were chosen

| Metric | Why |
|---|---|
| Final state | the terminal state is the navigator's "answer" (ARRIVED, SAFE_STOP or CONTINUE_OR_REQUEST_OPERATOR) |
| Final route and length | checks Dijkstra used the blocked-edge set correctly |
| Blocked edges and blocker detail | checks an edge is blocked only with justification (3 readings, attribution) |
| Reroute count, retreat distance | checks the detour logic |
| Collision | the single most important safety outcome in the model |
| Latch kind, restart behaviour | checks fail-closed behaviour and no auto-restart |
| Traveled (sim truth) vs plan | checks that distances are reported separately and never derived from the plan |

## 7. Results

R2, d1b607a, 2026-11-08. Every value SIMULATED; distances SYNTHETIC; time in simulated seconds.

| Scenario | Set-up | Final state | Route (m) | Blocked | Reroutes | Traveled | t (s) | Collision |
|---|---|---|---|---|---|---|---|---|
| A | clear | ARRIVED | A-B-C-D-E-F-G (60) | — | 0 | 59.97 | 102.25 | none |
| B | box D-E at 5 m | ARRIVED | D-K-L-M-G (46) | D-E | 1 | 83.895 | 187.20 | none |
| C | same as B | ARRIVED | D-K-L-M-G (46) | D-E | 1 | 83.895 | 187.20 | none |
| D | boxes D-E, D-K | ARRIVED | D-C-J-K-L-M-G (64) | D-E, D-K | 2 | 105.885 | 266.00 | none |
| E | boxes D-E, M-G | SAFE_STOP | none | D-E, G-M | 1 | 74.955 | 211.65 | none |
| F | D-E cleared independently | ARRIVED | D-E-F-G (30) | — | 0 | 29.955 | 59.80 | none |
| G | sensor dropout at 8 s | SAFE_STOP (`SENSOR_STALE`) | (planned 60) | — | 0 | 4.665 | 8.20 | none |
| H | person on C-D | CONTINUE_OR_REQUEST_OPERATOR (`HUMAN_REVIEW`) | (planned 60) | — | 0 | 20.03 | 34.55 | none |

`python3 -m pytest -q rover/tests/test_scenarios.py` → 10 passed. The whole rover suite → 284 passed in 2.14 s.

**Scenario B timeline** (simulated seconds):

| t | State | Detail |
|---|---|---|
| 58.20 | OBSTACLE_DETECTED | obstacle at 0.98 m < 1.00 m (lookahead) |
| 58.40 | VERIFY_OBSTACLE | 3 fresh readings, all 0.98 m |
| 58.50 | MARK_EDGE_BLOCKED_IF_JUSTIFIED | "robot on D->E at 4.02 m facing along edge; obstacle at 5.00 of 10 m" |
| 58.50 → 88.80 | SCAN_DIRECTIONS | left BLOCKED (0.6 m side clearance), right CLEAR (2.0 m), back CLEAR (no echo, under the sim's CLEAR_TO_MAX policy); sweep half-angle 8.53°; local bypass NOT_ATTEMPTED |
| 88.80 | REPLAN_SHORTEST_ROUTE → VERIFY_DETOUR | retreat 4.02 m to D, then D-K-L-M-G; old remaining 25.98 m → new remaining 50.02 m |
| 187.15 | ARRIVED | at G |

**Scenario G:** the last command was ADVANCE_IF_SAFE at t = 8.10 ("A->B 5.37 m left"). The supervisor latched `SENSOR_STALE` ("range reading stale (0.200s > 0.200s)") and the navigator went to SAFE_STOP at 8.15. After `range_dropout` was cleared and the sim ran 3 s more, the state was still SAFE_STOP with zero velocity: no auto-restart.

**R1 vs R2.** The PR #8 description (R1, `dac82f4`) reports the same outcomes: A 60 m; B/C D-E blocked with a 4 m retreat then D-K-L-M-G 46 m; D 64 m; E SAFE_STOP; F 30 m; G latch; H review. PR #14 changed the simulator to assert `forward_allowed` explicitly and states "Scenarios A–H are unchanged". R2 confirms that at d1b607a.

## 8. Failures and interpretation

- **No failures.** All expected end states were reached.
- **Interpretation of B/C.** The robot stopped 0.98 m from the box, against a 1.00 m lookahead. The 2 cm overshoot is one 50 ms tick at 0.6 m/s (sim scale), which shows the decision is made per tick. On hardware, stopping distance depends on real latency and deceleration, both **NOT MEASURED**.
- **The scan took about 30 simulated seconds,** because the closed-loop rotation is proportional and bounded. That is plausible but untested.
- **The back view read CLEAR from a NO_ECHO.** That is valid only because the simulator uses `CLEAR_TO_MAX` (there are no walls). On hardware, NO_ECHO is UNKNOWN and the detour would be refused (`DETOUR_UNVERIFIED`), which is the safe outcome.
- **Scenario A itself** is driven mostly under simulated NO_ECHO = clear. On real hardware with the UNKNOWN policy, the same mission would refuse to move forward wherever the sensor gets no echo.

## 9. Evidence files

| Evidence | Location | Note |
|---|---|---|
| Scenario definitions | `rover/simrun.py` `scenario` | in repo |
| Assertions | `rover/tests/test_scenarios.py`, `rover/tests/test_distances.py`, `rover/tests/test_scanning.py` | in repo |
| R1 results | PR #8 description (GitHub) | quoted |
| R2 results | regenerated with the commands in §11; not stored as a file (deterministic) | this report |

There are no local evidence files. The simulator is deterministic, so the commands regenerate the results exactly.

## 10. Limitations and confounders

- A topological world: no wheel dynamics, slip, inertia or strafing (strafing sets `lost`).
- Perfect heading (`sim-truth`) and pose (`SIM_TRUTH`). Neither exists on hardware.
- `auto_approve=True` and `CLEAR_TO_MAX`, both refused for physical IO.
- Synthetic speed scale (1.0 = 2 m/s) and a 0.20 m robot-width placeholder.
- B and C are the same world, so they are not independent evidence.
- The obstacle model is edge-local. There are no obstacles off the graph and no walls.

## 11. Reproducibility

```bash
python3 -m rover.simrun --list
python3 -m rover.simrun B              # status JSON; exit 0 on a terminal state
python3 -m pytest -q rover/tests/test_scenarios.py rover/tests/test_distances.py rover/tests/test_scanning.py
```

Deterministic: there is no RNG, and `test_scenarios_are_deterministic` checks it. R2 reproduced R1's outcomes.

## 12. What this proves / does NOT prove

**Proves (within the model):** the navigator blocks an edge only with three consistent readings and attribution; Dijkstra replans correctly (46 m, then 64 m); SAFE_STOP names the blockers when no route exists; a stale sensor latches and never auto-restarts; a camera person stops the robot and asks for review without blocking routing; traveled distance is reported separately from the plan.

**Does NOT prove:** that a RoverC-Pro can follow an edge, rotate to ±2°, stop within the lookahead, or detect a real box; that real ultrasonic echoes behave like the model; anything about the real heading, pose or battery. **Real wheel movement: NOT TESTED.**

## 13. What we would change next time

- Add a "hardware-like" scenario set with `no_echo_policy=UNKNOWN`, `heading_feedback=False` and walls, so the default hardware policy is what gets exercised.
- Make B and C different worlds (for example, different side clearances) so they are independent.
- Record a JSON transcript per scenario in CI artefacts, so results are archived per commit rather than regenerated.

# Qwen advisory integration contract (`qwen-advisory-integration/0.1`, DRAFT)

Owner: Qwen workstream. Status: **draft for review**. It does not change any existing module, `requirements.txt` or
`pytest.ini`. It has its own path-filtered workflow (`.github/workflows/qwen.yml`).

## What this PR adds

| Path | What |
|---|---|
| `qwen_advisory/lidar.py` | `rescue-lidar-advisory/0.1`: schema, stdlib validator, deterministic reference policy, guard |
| `qwen_advisory/client.py` | `lidar_advisory(context, model=None, timeout_s=8)`: optional model call, then guard, then **deterministic fallback**. Never raises |
| `qwen_advisory/fixtures/lidar_advisory_cases.json` | 8 SIMULATED cases (all LiDAR states, an imperative request, a glass note, a corridor that is not CLEAR) |
| `qwen_advisory/tests/` | 23 tests: fixtures, motion invariants, guard, client fallback (error, timeout, unsafe output, non-object) |

## Input

`context` dict, all keys optional:

- `lidar`: the LiDAR agent's `team15.lidar_advisory_context/1`, from `lidar.adapters.to_advisory_context()` (PR #11, draft). It is consumed as-is; sectors are never recomputed.
- `camera`: `{available, person_candidate, score}`.
- `robot_motion`: MOVING or STOPPED.
- `estop_engaged`, `link`.
- `operator_review`: UNREVIEWED, CONFIRMED_BY_OPERATOR or REJECTED_BY_OPERATOR.
- `question`, `scene_notes`, `operator_asks_motion`.

## Output (display only, `authority: "NONE"`)

`{schema_version, advisory_only: true, authority: "NONE", simulated, source: DETERMINISTIC | QWEN_GUARDED | DETERMINISTIC_FALLBACK, issues, advisory}`

The advisory itself has these keys:
- `person_evidence`;
- `lidar_status`: USABLE, STALE, DISCONNECTED_OR_FAULT, UNALIGNED, PARTIAL or NOT_PROVIDED;
- `association`: always NOT_ESTABLISHED;
- `forward_motion_recommendation`: REQUEST_DETERMINISTIC_STOP, DO_NOT_REQUEST_MOTION or OPERATOR_MAY_CONSIDER_BOUNDED_MOVE;
- `recommended_action`, `next_observation`, `missing_evidence`, `explanation`, `source_references`.

## Rules (enforced by policy and guard; tested)

- **Level A fusion only.** Camera and LiDAR are reported separately. There is never a person distance, never world coordinates, never "clear path".
- **A LiDAR that is stale, partial, disconnected, unaligned or has its orientation monitor FAILED means every direction is UNKNOWN.** No motion is ever suggested then. While moving, the recommendation is the deterministic stop.
- **A forward corridor that is not CLEAR** means no motion suggestion (STOP while moving) and a follow-up observation.
- **The model can never be more permissive about motion than the deterministic policy.** If it is, its output is discarded.
- **Imperative requests** (move, release, confirm, bypass the e-stop) are refused. **Questions** are answered.
- **A recommendation is not a command.** The rover controller and SafetySupervisor stop the robot independently; nothing here is in the control loop.

## Evidence (Team-15-Qwen workspace)

- The port is behaviour-identical to the workspace implementation: 314 SIMULATED cases, schema validity on more than 300 recorded model outputs, and guard verdicts on adversarial outputs (`$QWEN_WORKSPACE/tests/test_team_port_parity.py` in the Qwen workspace).
- Benchmarks: on the frozen 60-case LiDAR set, no Qwen model, base or adapter, is reliable enough to decide anything. The policy, guard and fallback displayed a correct, never-more-permissive advisory in every evaluated case. So **Qwen output is optional explanatory text**, and the deterministic policy is the default.

## Not included (stays in Team-15-Qwen)

Datasets, checkpoints, LoRA training, RAG corpus, benchmarks, simulator scenario generation and the model servers.

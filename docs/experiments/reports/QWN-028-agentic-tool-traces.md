# QWN-028: Agentic demo tool traces (3 scenarios, reference agent vs Qwen via Ollama)

**Label:** SIMULATED · **Status:** COMPLETE · **Date:** 2026-11-08 about 00:41 ET (trace file mtimes; commit `94ee31c`)

**In plain words.** We recorded three short demo scenarios in which an "agent" gathers evidence with read-only tools, comparing a scripted reference agent with Qwen. Qwen repeated itself or passed bad arguments in every scenario, so the system fell back to the rule-based advisory each time. After a fix, that fallback always showed the cautious answer.

## Setup

- `rescue_qwen.agent.run_episode` (`rescue-agent-tools/0.1`, 10 read-only/request-only tools, max 10 calls, 120 s).
- Policies: reference (`reference_agent_step`) and Qwen (`qwen3.5:2b-q4_K_M`, Ollama).
- Scenarios: (1) candidate with obstacles; (2) contradictory camera/LiDAR while moving; (3) LiDAR stale then disconnected while moving.
- The controller check is computed independently and **not executed**.

## Results

| Scenario | Policy | Tools accepted | Stop | Displayed (after guard/fallback) |
|---|---|---|---|---|
| 1 | reference | robot, camera, evidence, review, sectors, knowledge, submit | SUBMITTED | possible person, operator review, no motion requested |
| 1 | Qwen | evidence, knowledge, knowledge (repeat) | INVALID_OR_REPEATED | same as reference (fallback fetched robot, camera, review, sectors) |
| 2 | reference | 7 tools, submit | SUBMITTED | review + **recommend deterministic stop** |
| 2 | Qwen | none (`candidate_id: null` twice) | INVALID_OR_REPEATED | **recommend deterministic stop** after the fix; before it: "do not request motion" (understated) |
| 3 | reference | robot, camera, sectors, scan summary, knowledge, observation request, submit | SUBMITTED | sensor fault, CHECK_LIDAR_CONNECTION queued, stop |
| 3 | Qwen | robot, camera, then invalid `kind` twice | INVALID_OR_REPEATED | sensor fault, stop (fallback) |

Wall time for the Qwen episodes was 0.6–2.1 s. Every Qwen trace has `displayed_is_fallback: true`.

## Evidence

`$QWEN_WORKSPACE/results/agentic_demo_1_candidate_with_obstacles_{ollama,reference}.json` (`0db068ab…2c24c9`, `6e62d746…9a29cc`), `agentic_demo_2_contradictory_camera_lidar_{ollama,reference}.json` (`b4bca968…051a85`, `62b16761…15491e`), `agentic_demo_3_lidar_stale_then_disconnected_{ollama,reference}.json` (`0c54192f…2ab51b`, `94f8d11b…356c9d`); `$QWEN_WORKSPACE/docs/AGENTIC_TOOL_TRACE_REPORT.md`.

## What it proves / does not prove

- **Proves:** the orchestration is bounded and audited. After the fix, the display is never less cautious than the reference.
- **Does not prove:** model competence (0 successful model episodes), or any hardware behaviour.

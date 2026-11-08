# Three-minute judge script: dual-robot rescue (SIMULATION)

Setup (before judges arrive):

```
scripts/run_dual_rescue.sh             # http://localhost:8000/rescue ; Qwen on :8090 is picked up if running
```

Open `http://localhost:8000/rescue?scenario=B&speed=5`. Choose **Graphics → Ultra/4K** on the projector
and press **P** for presentation mode. Space starts and pauses; 1–7 switch cameras.

| Time | Action | Say |
|---|---|---|
| 0:00–0:20 | Scenario B, tactical camera, not started | "A collapsed building, 48 m. Two simulated robots: AIR-1, an aerial scout, and GND-1, our RoverC-Pro. The floor plan is known, but every corridor starts UNKNOWN (hatched amber). Nothing here is real hardware." |
| 0:20–0:50 | Space (start), camera 3 (aerial follow) | "The drone runs our PR #17 belief search: Monte-Carlo tree search over a probability grid. The cyan square is its real camera footprint. The 'Why' line shows the MCTS values behind each move." |
| 0:50–1:15 | Survivor toast appears | "A survivor is reported only when it falls inside the footprint. The drone hovers three looks to confirm and sends a timestamped observation with position, source and confidence." |
| 1:15–1:45 | Camera 2 (cinematic) | "The coordinator plans the shortest floor-plan route and first has the drone observe its unknown corridors. It routes around debris the drone saw on M1-N1. Then it hands the target to the rover. The rover runs our real Navigator and safety supervisor, on corridors observed clear only." |
| 1:45–2:15 | Debris falls; rover stops | "New debris falls. Nobody is told. The rover's ultrasonic stops it, verifies three readings, marks the corridor blocked and scans. Its old observations are stale, so it holds and asks for sensing. The drone re-checks the block and observes a detour, and the Navigator replans with Dijkstra." |
| 2:15–2:40 | "Generate rescue report" (right panel) | "Qwen 3.5-2B with RAG explains the mission from timestamped observation ids. It is advisory only: it has no motor authority, motor-like text is discarded, and if Qwen is down the deterministic report is shown and labelled." |
| 2:40–3:00 | Rover at standoff; bottom telemetry | "The rover stops at a standoff with human review pending. Backing this demo: 25 tests and a benchmark across 8 environments with failure injection (see BENCHMARKS.md). Every number there comes from runs that actually completed." |

Fallbacks:

* **No Qwen:** the report shows `DETERMINISTIC FALLBACK`. Say so.
* **Slow projector:** choose Graphics → Medium. Adaptive render scale also drops the internal
  resolution on its own.
* **Short on time:** scenario C (INSUFFICIENT_INFORMATION, about 2 min of sim time) shows the
  UNKNOWN ≠ CLEAR policy. Scenario E shows the safety latch on link loss.

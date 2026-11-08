# PLN-01 / PLN-02: Trail-graph routing: Dijkstra A→G = 60 m and A\* (ALT) equivalence

**Label:** SYNTHETIC (the trail graph is synthetic; no terrain was measured). **Status:** COMPLETE (both).

**In plain words.** The mission map is a made-up network of trails between sectors A–Z, with lengths in metres. We tested that the route finder always returns the shortest walk, and that it detours correctly when a trail is reported blocked. The headline check is that the walk from A to G is A-B-C-D-E-F-G, 60 m. A second, optional route finder (A\* with "landmark" shortcuts) was checked against the first on every pair of sectors and always agreed.

## 1. Objective and hypotheses

- **PLN-01:** `planner.route.compute_route` (Dijkstra) returns the exact shortest walkable route on `fixtures/trail_graph_synthetic.json`, honours blocked edges in either direction, and reports unreachable or unknown nodes.
- **PLN-02:** `planner.astar.astar_route` with `AltHeuristic` returns the same status and length as Dijkstra for every ordered pair, under several blocked-edge sets, and its heuristic is admissible.

## 2. Date, hardware, software

- **This audit:** 2026-11-08 (local, macOS, Python 3.13) at `d1b607a`.
- **Origin:** PR #2 (`77a3979`, 2026-11-07; 12 tests). A\* was added in PR #8 (`241faec`, 2026-11-07).
- **CI:** PR #5's workflow also asserts `python -m planner.route A G` → A-B-C-D-E-F-G, 60 m (PR #2 description).
- No hardware involved.

## 3. Data

`fixtures/trail_graph_synthetic.json`: 26 nodes (A–Z), 15 undirected edges with lengths of 10–14 m, taken from TEAM15_DRONE_SEARCH_BUILD.md §3.2. Q–Z have no edges. All lengths are SYNTHETIC.

## 4. Procedure

```bash
python3 -B -m pytest -q planner/tests          # 19 passed
python3 -B -m planner.route A G
python3 -B -m planner.route C K --block J-K
python3 -B -m planner.route C G
python3 -B -m planner.route A G --block E-F
python3 -B -m planner.route A Q
```

## 5. Ground truth and metrics

- **Ground truth:** hand-derived shortest paths from the spec, plus an independent networkx shortest-path computation over all pairs (`test_cross_check_networkx_all_pairs`, `test_cross_check_networkx_blocked_jk`).
- **Metric:** exact equality of path, length and status. Exact equality is appropriate because the graph is small and has integer lengths.

## 6. Results

| Query | Result | Test |
|---|---|---|
| A → G | A-B-C-D-E-F-G, **60 m**, "shortest known walking route" | `test_route_a_to_g_60` |
| C → K | C-J-K, 20 m | `test_route_c_to_k_20` |
| C → K, J-K blocked (4 spellings) | C-D-K, 22 m, "edge J-K blocked by responder report" | `test_blocked_jk_reroutes_22` |
| C → G | C-D-E-F-G, 40 m | `test_route_c_to_g_40` |
| A → G, E-F blocked | A-B-C-J-K-L-M-G, 74 m | CLI, this audit |
| A → Q | `NO_KNOWN_ROUTE`, "Q has no known walkable connection" (exit code 1) | CLI; `test_y_no_known_route` (Y) |
| Unknown node | `UNKNOWN_NODE` | `test_unknown_node` |
| Fixture matches the spec | 15 edges as specified | `test_fixture_matches_spec` |
| ALT admissible, all pairs | `h(s,t) ≤ d(s,t)` for every pair | `test_heuristic_admissible_all_pairs` |
| A\* = Dijkstra, every ordered pair × {∅, J-K, D-E, D-E+D-K, D-E+M-G} | same status and length everywhere | `test_astar_matches_dijkstra` |
| A\* A → G | A-B-C-D-E-F-G, 60 m, 7 nodes expanded (landmarks A, G, K; `h(A,G)` = 60) | `test_a_to_g_60_and_expands_no_more_than_dijkstra_nodes` |

`planner/tests`: **19 passed** (`test_route.py` and `test_astar.py`, including parametrised cases).

## 7. Failures

None.

## 8. Evidence

The test files `planner/tests/test_route.py` and `planner/tests/test_astar.py`, the fixture `fixtures/trail_graph_synthetic.json` (in the repo), CLI output from this audit, and the PR #2 description.

## 9. Limitations

- A synthetic graph, with no real trail survey.
- Static weights: no time, terrain difficulty or uncertainty.
- Blocked edges come only from responder reports (dashboard) or from the simulated rover's confirmed observations ([12](../../12_ROVERC_MOTOR_CONTROL.md)).

## 10. What it proves / does not prove

- **Proves:** the algorithms are correct on this graph; A\* (ALT) is a correct drop-in benchmark.
- **Does not prove:** anything about real walking distances or terrain.

## 11. Next time

When real trail data exists, load it with `--graph` and keep the networkx cross-check as the oracle.

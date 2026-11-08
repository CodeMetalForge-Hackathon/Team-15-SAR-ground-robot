"""Optional A* (ALT) benchmark agrees with Dijkstra, and its heuristic is admissible, checked exhaustively."""
import itertools

import pytest

from planner.astar import AltHeuristic, _sssp, astar_route
from planner.graph import load_graph
from planner.route import compute_route


@pytest.fixture(scope="module")
def graph():
    return load_graph()


def test_heuristic_admissible_all_pairs(graph):
    h = AltHeuristic(graph)
    assert h.landmarks
    for s in graph.nodes:
        d = _sssp(graph, s)
        for t in graph.nodes:
            if t in d:
                assert h(s, t) <= d[t] + 1e-9, (s, t)


@pytest.mark.parametrize("blocked", [set(), {"J-K"}, {"D-E"}, {"D-E", "D-K"}, {"D-E", "M-G"}])
def test_astar_matches_dijkstra(graph, blocked):
    h = AltHeuristic(graph)
    for s, t in itertools.permutations(graph.nodes, 2):
        a, _ = astar_route(s, t, blocked=blocked, graph=graph, heuristic=h)
        d = compute_route(s, t, blocked=blocked, graph=graph)
        assert a.status == d.status, (s, t)
        assert a.length_m == d.length_m, (s, t)


def test_a_to_g_60_and_expands_no_more_than_dijkstra_nodes(graph):
    r, expanded = astar_route("A", "G", graph=graph)
    assert r.path == list("ABCDEFG") and r.length_m == 60
    assert expanded <= len([n for n in graph.nodes if graph.neighbors(n)])

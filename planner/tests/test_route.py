import itertools

import networkx as nx
import pytest

from planner.graph import load_graph
from planner.route import NO_KNOWN_ROUTE, OK, UNKNOWN_NODE, compute_route


@pytest.fixture(scope="module")
def graph():
    return load_graph()


def test_route_a_to_g_60(graph):
    r = compute_route("A", "G", graph=graph)
    assert r.status == OK
    assert r.path == list("ABCDEFG")
    assert r.edges == ["A-B", "B-C", "C-D", "D-E", "E-F", "F-G"]
    assert r.length_m == 60


def test_route_c_to_k_20(graph):
    r = compute_route("C", "K", graph=graph)
    assert r.status == OK
    assert r.path == ["C", "J", "K"]
    assert r.length_m == 20


@pytest.mark.parametrize("blocked", [{("J", "K")}, {("K", "J")}, {"J-K"}, {frozenset("JK")}])
def test_blocked_jk_reroutes_22(graph, blocked):
    r = compute_route("C", "K", blocked=blocked, graph=graph)
    assert r.status == OK
    assert r.path == ["C", "D", "K"]
    assert r.length_m == 22
    assert "edge J-K blocked by responder report" in r.reason


def test_route_c_to_g_40(graph):
    r = compute_route("C", "G", graph=graph)
    assert r.status == OK
    assert r.path == ["C", "D", "E", "F", "G"]
    assert r.length_m == 40


def test_y_no_known_route(graph):
    r = compute_route("C", "Y", graph=graph)
    assert r.status == NO_KNOWN_ROUTE
    assert r.path == [] and r.edges == [] and r.length_m is None
    assert r.reason == "Y has no known walkable connection"


def test_unknown_node(graph):
    r = compute_route("A", "ZZ", graph=graph)
    assert r.status == UNKNOWN_NODE
    assert r.length_m is None
    assert "ZZ" in r.reason


def test_fixture_matches_spec(graph):
    assert len(graph.edges()) == 15
    assert graph.nodes == [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    for n in "QRSTUVWXYZ":
        assert graph.neighbors(n) == {}


def _nx_graph(graph):
    G = nx.Graph()
    G.add_nodes_from(graph.nodes)
    for a, b, m in graph.edges():
        G.add_edge(a, b, weight=m)
    return G


def test_cross_check_networkx_all_pairs(graph):
    G = _nx_graph(graph)
    checked = 0
    for s, t in itertools.permutations(graph.nodes, 2):
        r = compute_route(s, t, graph=graph)
        if nx.has_path(G, s, t):
            assert r.status == OK, (s, t, r)
            assert r.length_m == nx.dijkstra_path_length(G, s, t)
            assert sum(G[a][b]["weight"] for a, b in zip(r.path, r.path[1:])) == r.length_m
            checked += 1
        else:
            assert r.status == NO_KNOWN_ROUTE, (s, t, r)
    assert checked > 0


def test_cross_check_networkx_blocked_jk(graph):
    G = _nx_graph(graph)
    G.remove_edge("J", "K")
    for s, t in itertools.permutations(graph.nodes, 2):
        r = compute_route(s, t, blocked={("J", "K")}, graph=graph)
        if nx.has_path(G, s, t):
            assert r.status == OK
            assert r.length_m == nx.dijkstra_path_length(G, s, t)
        else:
            assert r.status == NO_KNOWN_ROUTE

"""OPTIONAL benchmark: A* with an ALT (landmark) heuristic, run on the same trail graph.

The trail graph has no coordinates, so a Euclidean heuristic is not available, and the synthetic
layout in rover/sim.py is not admissible against the graph weights. ALT uses the triangle inequality:
    h(n) = max over landmarks L of |d(L, t) - d(L, n)|
This is a lower bound on d(n, t) for any undirected graph with non-negative weights. Blocking edges
only lengthens shortest paths, so landmark distances taken on the UNBLOCKED graph stay admissible
under any set of blocked edges. tests/test_astar.py checks admissibility exhaustively.

planner.route.compute_route (Dijkstra) is still the route used for navigation. This module is
compared against it and never replaces it.
"""
from __future__ import annotations

import heapq
import math
from typing import Iterable, Optional

from planner.graph import TrailGraph
from planner.route import NO_KNOWN_ROUTE, OK, UNKNOWN_NODE, RouteResult, _normalise_blocked


def _sssp(g: TrailGraph, src: str) -> dict[str, float]:
    dist = {src: 0.0}
    heap = [(0.0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, math.inf):
            continue
        for v, m in g.neighbors(u).items():
            nd = d + m
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


class AltHeuristic:
    def __init__(self, g: TrailGraph, landmarks: Optional[Iterable[str]] = None):
        self.g = g
        self.landmarks = list(landmarks) if landmarks is not None else self._pick(g)
        self.d = {L: _sssp(g, L) for L in self.landmarks}

    @staticmethod
    def _pick(g: TrailGraph, k: int = 3) -> list[str]:
        """Farthest-point landmark selection, deterministic, within the largest connected part."""
        nodes = [n for n in g.nodes if g.neighbors(n)]
        if not nodes:
            return []
        picks = [nodes[0]]
        while len(picks) < k:
            best, best_d = None, -1.0
            for n in nodes:
                dn = min(_sssp(g, p).get(n, math.inf) for p in picks)
                if dn != math.inf and dn > best_d and n not in picks:
                    best, best_d = n, dn
            if best is None:
                break
            picks.append(best)
        return picks

    def __call__(self, n: str, t: str) -> float:
        h = 0.0
        for L, d in self.d.items():
            dn, dt = d.get(n), d.get(t)
            if dn is None or dt is None:
                continue  # different component: no information
            h = max(h, abs(dt - dn))
        return h


def astar_route(from_node: str, to_node: str, blocked=frozenset(), graph: TrailGraph = None,
                heuristic: Optional[AltHeuristic] = None) -> tuple[RouteResult, int]:
    """Returns (RouteResult, nodes_expanded). Same statuses as compute_route."""
    g = graph
    h = heuristic or AltHeuristic(g)
    if from_node not in g.adjacency or to_node not in g.adjacency:
        return RouteResult(UNKNOWN_NODE, reason="unknown node(s)"), 0
    if from_node == to_node:
        return RouteResult(OK, [from_node], [], 0, "already at destination"), 0
    blocked_set = _normalise_blocked(blocked)
    gscore = {from_node: 0.0}
    prev: dict[str, str] = {}
    heap = [(h(from_node, to_node), 0.0, from_node)]
    closed = set()
    expanded = 0
    while heap:
        _, gd, u = heapq.heappop(heap)
        if u in closed:
            continue
        closed.add(u)
        expanded += 1
        if u == to_node:
            break
        for v, m in g.neighbors(u).items():
            if frozenset((u, v)) in blocked_set or v in closed:
                continue
            nd = gd + m
            if nd < gscore.get(v, math.inf):
                gscore[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd + h(v, to_node), nd, v))
    if to_node not in closed:
        return RouteResult(NO_KNOWN_ROUTE, reason=f"no known walkable route from {from_node} to {to_node}"), expanded
    path = [to_node]
    while path[-1] != from_node:
        path.append(prev[path[-1]])
    path.reverse()
    length = gscore[to_node]
    if length == int(length):
        length = int(length)
    return RouteResult(OK, path, [f"{a}-{b}" for a, b in zip(path, path[1:])], length, "A* (ALT) benchmark"), expanded

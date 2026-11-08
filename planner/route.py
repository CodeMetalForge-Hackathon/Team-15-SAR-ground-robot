"""Shortest walking route on the trail graph (Dijkstra with heapq)."""
from __future__ import annotations

import heapq
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Iterable

from planner.graph import TrailGraph, load_graph

OK = "OK"
NO_KNOWN_ROUTE = "NO_KNOWN_ROUTE"
UNKNOWN_NODE = "UNKNOWN_NODE"


@dataclass
class RouteResult:
    status: str
    path: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)
    length_m: float | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _normalise_blocked(blocked: Iterable) -> set[frozenset]:
    """Accept ("J","K"), "J-K" or frozenset({"J","K"}); treat as undirected."""
    out: set[frozenset] = set()
    for item in blocked or ():
        if isinstance(item, str):
            parts = item.split("-")
        else:
            parts = list(item)
        if len(parts) != 2:
            raise ValueError(f"blocked edge must be a pair, got {item!r}")
        out.add(frozenset(p.strip() for p in parts))
    return out


def compute_route(from_node: str, to_node: str, blocked=frozenset(),
                  graph: TrailGraph | None = None) -> RouteResult:
    g = graph if graph is not None else load_graph()
    known = set(g.nodes)
    missing = [n for n in (from_node, to_node) if n not in known]
    if missing:
        return RouteResult(UNKNOWN_NODE, reason="unknown node(s): " + ", ".join(map(str, missing)))

    blocked_set = _normalise_blocked(blocked)
    # Only report blocked edges that actually exist in the graph.
    blocked_real = []
    for e in blocked_set:
        if len(e) == 2:
            a, b = sorted(e)
            if b in g.neighbors(a):
                blocked_real.append(f"{a}-{b}")
    blocked_real.sort()
    blocked_note = "; ".join(f"edge {e} blocked by responder report" for e in blocked_real)

    if from_node == to_node:
        return RouteResult(OK, [from_node], [], 0, "already at destination")

    dist = {from_node: 0}
    prev: dict[str, str] = {}
    heap = [(0, from_node)]
    done = set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u == to_node:
            break
        for v, m in g.neighbors(u).items():
            if frozenset((u, v)) in blocked_set or v in done:
                continue
            nd = d + m
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    if to_node not in done:
        if not g.neighbors(to_node):
            reason = f"{to_node} has no known walkable connection"
        elif not g.neighbors(from_node):
            reason = f"{from_node} has no known walkable connection"
        else:
            reason = f"no known walkable route from {from_node} to {to_node}"
        if blocked_note:
            reason += f" ({blocked_note})"
        return RouteResult(NO_KNOWN_ROUTE, reason=reason)

    path = [to_node]
    while path[-1] != from_node:
        path.append(prev[path[-1]])
    path.reverse()
    edges = [f"{a}-{b}" for a, b in zip(path, path[1:])]
    reason = blocked_note or "shortest known walking route"
    return RouteResult(OK, path, edges, dist[to_node], reason)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Shortest walking route on the trail graph")
    p.add_argument("from_node")
    p.add_argument("to_node")
    p.add_argument("--block", action="append", default=[], help="blocked edge, e.g. J-K (repeatable)")
    p.add_argument("--graph", default=None, help="path to trail graph JSON")
    args = p.parse_args(argv)
    graph = load_graph(args.graph) if args.graph else load_graph()
    res = compute_route(args.from_node, args.to_node, blocked=args.block, graph=graph)
    print(json.dumps(res.to_dict()))
    return 0 if res.status == OK else 1


if __name__ == "__main__":
    sys.exit(main())

"""Load the walkable trail graph (undirected, edge weights in metres)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "trail_graph_synthetic.json"


@dataclass
class TrailGraph:
    nodes: list[str]
    adjacency: dict[str, dict[str, float]] = field(default_factory=dict)

    def neighbors(self, node: str) -> dict[str, float]:
        return self.adjacency.get(node, {})

    def edges(self) -> list[tuple[str, str, float]]:
        seen, out = set(), []
        for a, nbrs in self.adjacency.items():
            for b, m in nbrs.items():
                key = frozenset((a, b))
                if key not in seen:
                    seen.add(key)
                    out.append((a, b, m))
        return out


def load_graph(path: str | Path = DEFAULT_FIXTURE) -> TrailGraph:
    data = json.loads(Path(path).read_text())
    nodes = list(data["nodes"])
    node_set = set(nodes)
    adjacency: dict[str, dict[str, float]] = {n: {} for n in nodes}
    for e in data["edges"]:
        a, b, m = e["a"], e["b"], e["m"]
        if a not in node_set or b not in node_set:
            raise ValueError(f"edge {a}-{b} references unknown node")
        if a == b or m < 0:
            raise ValueError(f"invalid edge {a}-{b} ({m} m)")
        adjacency[a][b] = m
        adjacency[b][a] = m
    return TrailGraph(nodes=nodes, adjacency=adjacency)

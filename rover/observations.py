"""Timestamped obstacle observations: the incremental map that the planner reads.

Rules:
  - Only CONFIRMED, non-dynamic, uncleared obstacles block an edge indefinitely. They are still
    flagged ``stale`` after ``recheck_after_s``, so the dashboard can ask for a re-check.
  - Dynamic obstacles (people, moving things) block only while fresh (``dynamic_ttl_s``). After that
    they count as STALE, not as clear. The robot re-senses as it goes.
  - Camera detections start UNCONFIRMED, and a person only becomes CONFIRMED by human review.
    UNCONFIRMED observations never block routing.
  - Clearing a blocked edge needs an INDEPENDENT source: a source different from every observation
    blocking it, plus a named operator.
  - Camera detections carry no global coordinates. At most they carry "seen while on edge X-Y".
"""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from planner.graph import TrailGraph
from planner.route import OK, compute_route

CONFIRMED = "CONFIRMED"
UNCONFIRMED = "UNCONFIRMED"
CLEARED = "CLEARED"
REJECTED = "REJECTED"


def canonical_edge(edge) -> str:
    if isinstance(edge, str):
        parts = edge.split("-")
    else:
        parts = list(edge)
    if len(parts) != 2:
        raise ValueError(f"edge must be a pair, got {edge!r}")
    a, b = sorted(p.strip() for p in parts)
    return f"{a}-{b}"


@dataclass
class Observation:
    obs_id: str
    t: float
    kind: str           # ultrasonic_obstacle | camera_person | edge_clear | ...
    source: str         # sim-ultrasonic | grove-ultrasonic | sim-camera | pi5-imx708 | operator:<name>
    status: str
    dynamic: bool
    edge: Optional[str]
    detail: dict = field(default_factory=dict)
    history: list = field(default_factory=list)

    def to_dict(self, now: float, recheck_after_s: float) -> dict:
        d = asdict(self)
        d["age_s"] = round(now - self.t, 3)
        d["stale"] = (now - self.t) > recheck_after_s
        return d


class ObservationLog:
    def __init__(self, clock: Callable[[], float], dynamic_ttl_s: float = 30.0, recheck_after_s: float = 300.0):
        self.clock = clock
        self.dynamic_ttl_s = dynamic_ttl_s
        self.recheck_after_s = recheck_after_s
        self.items: list[Observation] = []
        self._ids = itertools.count(1)

    def add(self, kind: str, source: str, status: str, *, dynamic: bool, edge=None,
            detail: Optional[dict] = None, t: Optional[float] = None) -> Observation:
        if status not in (CONFIRMED, UNCONFIRMED):
            raise ValueError("new observations are CONFIRMED or UNCONFIRMED")
        o = Observation(f"rov-{next(self._ids):04d}", self.clock() if t is None else t, kind, source, status,
                        dynamic, canonical_edge(edge) if edge else None, dict(detail or {}))
        self.items.append(o)
        return o

    def get(self, obs_id: str) -> Observation:
        for o in self.items:
            if o.obs_id == obs_id:
                return o
        raise KeyError(obs_id)

    def _active_blocks(self, now: float) -> list[Observation]:
        out = []
        for o in self.items:
            if o.status != CONFIRMED or o.edge is None or o.kind == "edge_clear":
                continue
            if o.dynamic and now - o.t > self.dynamic_ttl_s:
                continue
            out.append(o)
        return out

    def blocked_edges(self, now: Optional[float] = None) -> list[str]:
        now = self.clock() if now is None else now
        return sorted({o.edge for o in self._active_blocks(now)})

    def blockers(self, now: Optional[float] = None) -> list[dict]:
        now = self.clock() if now is None else now
        return [o.to_dict(now, self.recheck_after_s) for o in self._active_blocks(now)]

    def edge_status(self, edge, now: Optional[float] = None) -> str:
        now = self.clock() if now is None else now
        e = canonical_edge(edge)
        if e in self.blocked_edges(now):
            return "BLOCKED"
        rel = [o for o in self.items if o.edge == e]
        if any(o.status == UNCONFIRMED and now - o.t <= self.dynamic_ttl_s for o in rel):
            return "UNCONFIRMED_HAZARD"
        clears = [o for o in rel if o.kind == "edge_clear"]
        if clears and now - max(c.t for c in clears) <= self.recheck_after_s:
            return "CLEAR_OBSERVED"
        if rel:
            return "STALE"
        return "UNKNOWN"

    def review(self, obs_id: str, operator: str, confirm: bool, note: str = "") -> Observation:
        """Human review of an UNCONFIRMED observation."""
        if not operator.strip():
            raise PermissionError("review needs a named operator")
        o = self.get(obs_id)
        if o.status != UNCONFIRMED:
            raise ValueError(f"{obs_id} is {o.status}, not UNCONFIRMED")
        o.history.append({"t": self.clock(), "from": o.status, "by": operator, "note": note})
        o.status = CONFIRMED if confirm else REJECTED
        if confirm:
            o.t = self.clock()  # its freshness for blocking starts at confirmation
        return o

    def clear_edge(self, edge, source: str, operator: str, evidence: str) -> Observation:
        """Mark a blocked edge clear. Needs a source independent of the blocking ones, and an operator."""
        if not operator.strip():
            raise PermissionError("clearing an edge needs a named operator")
        if not evidence.strip():
            raise PermissionError("clearing an edge needs evidence")
        e = canonical_edge(edge)
        now = self.clock()
        blocks = [o for o in self._active_blocks(now) if o.edge == e]
        if not blocks:
            raise ValueError(f"edge {e} is not blocked")
        same = sorted({o.source for o in blocks if o.source == source})
        if same:
            raise PermissionError(f"clearance source {source} is not independent of the blocking source(s) {same}")
        for o in blocks:
            o.history.append({"t": now, "from": o.status, "by": operator, "cleared_by_source": source})
            o.status = CLEARED
        return self.add("edge_clear", source, CONFIRMED, dynamic=False, edge=e,
                        detail={"operator": operator, "evidence": evidence,
                                "cleared": [o.obs_id for o in blocks]})

    def to_list(self, now: Optional[float] = None) -> list[dict]:
        now = self.clock() if now is None else now
        return [o.to_dict(now, self.recheck_after_s) for o in self.items]


def suggest_viewpoints(graph: TrailGraph, log: ObservationLog, from_node: str, k: int = 3) -> list[dict]:
    """Reachable nodes next to edges whose current state is unknown, stale or unconfirmed.

    Ordered by (most uncertain adjacent edges first, then shortest route). Blocked edges are excluded
    from the reachability check. This only suggests where a fresh camera view would be useful; it
    is not a coordinate estimate.
    """
    blocked = log.blocked_edges()
    out = []
    for n in graph.nodes:
        uncertain = sorted(canonical_edge((n, w)) for w in graph.neighbors(n)
                           if log.edge_status((n, w)) in ("UNKNOWN", "STALE", "UNCONFIRMED_HAZARD"))
        if not uncertain:
            continue
        r = compute_route(from_node, n, blocked=blocked, graph=graph)
        if r.status != OK:
            continue
        out.append({"node": n, "route_m": r.length_m, "path": r.path, "uncertain_edges": uncertain})
    out.sort(key=lambda d: (-len(d["uncertain_edges"]), d["route_m"], d["node"]))
    return out[:k]

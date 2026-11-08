"""Shared disaster site, coordinate frame, layouts and the simulator's hidden GROUND TRUTH.

Coordinate frame (one frame for every agent, the benchmark and the dashboard):
    SITE frame, origin (0, 0) = south-west corner of the site, x = east (m), y = north (m).
    Every site is 48 m x 48 m. The aerial belief grid is 24 x 24 cells of 2 m:
    cell (i, j) covers x in [2j, 2j+2), y in [2i, 2i+2)  (i = row counted from the south).

What is known to whom:
    * The LAYOUT (corridor graph, room doorway spurs, node coordinates) is pre-incident information and is
      known to every agent. Corridor CONDITION is not: every corridor starts UNKNOWN.
    * The overhead VISIBILITY map (intact roof / smoke / canopy = the camera cannot see the floor) is what
      the drone sees from above, so the aerial planner may use it.
    * GROUND TRUTH (survivors, false heat sources, debris, when debris appears) lives only in
      ``GroundTruth``. Agents receive it only through ``GroundTruth.aerial_look`` (passed to the drone as an
      opaque sensing callable) and the rover's simulated ultrasonic/camera (rover.sim.SimWorld).

All distances are SIMULATED metres in synthetic sites; nothing here is a surveyed building.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from planner.graph import TrailGraph

CELL_M = 2.0
N = 24
SITE_M = CELL_M * N
SAMPLE_STEP_M = 0.5          # corridor sample spacing used for aerial coverage of a corridor
VISIBLE = 0.5                # overhead visibility at/above which the drone camera sees the floor
SPUR_M = 6.0                 # doorway spur length (junction -> room interior)

FRAME = {
    "name": "SITE",
    "origin": "south-west corner of the simulated site",
    "x": "east, metres", "y": "north, metres",
    "extent_m": [SITE_M, SITE_M], "cell_m": CELL_M, "grid": [N, N],
    "cell_index": "(i, j): i = row from the south, j = column from the west",
    "units_label": "SIMULATED metres (synthetic site, not a surveyed building)",
}


def cell_of(x: float, y: float) -> tuple[int, int]:
    return (min(N - 1, max(0, int(y // CELL_M))), min(N - 1, max(0, int(x // CELL_M))))


def cell_center(c: tuple[int, int]) -> tuple[float, float]:
    i, j = c
    return ((j + 0.5) * CELL_M, (i + 0.5) * CELL_M)


def in_window(c: tuple[int, int], target: tuple[int, int], fov: int) -> bool:
    """Same footprint as fleet.planner.GridWorld._win: the (2 fov + 1)^2 square around c."""
    return abs(c[0] - target[0]) <= fov and abs(c[1] - target[1]) <= fov


def in_site(x, y) -> bool:
    try:
        return math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= SITE_M and 0.0 <= y <= SITE_M
    except TypeError:
        return False


# --- layouts --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Room:
    room_id: str          # graph node id of the room interior / pocket
    node: str             # corridor junction the doorway spur starts from
    xy: tuple[float, float]
    label: str


def make_room(nodes: dict, room_id: str, node: str, angle_deg: float, label: str, length: float = SPUR_M) -> Room:
    x, y = nodes[node]
    a = math.radians(angle_deg)
    return Room(room_id, node, (round(x + length * math.cos(a), 3), round(y + length * math.sin(a), 3)), label)


@dataclass
class Layout:
    env: str                                  # environment id (benchmark key)
    theme: str                                # renderer theme: urban | warehouse | corridors | outdoor | maze
    label: str
    nodes: dict[str, tuple[float, float]]
    edges: list[tuple[str, str]]
    rooms: dict[str, Room]
    corridor_half_m: float = 1.0              # SIMULATED corridor half-width (rover side views, renderer walls)
    base: str = "BASE"

    def graph(self) -> tuple[TrailGraph, dict[str, tuple[float, float]]]:
        """Full corridor + doorway topology with Euclidean SIMULATED lengths. Condition is NOT encoded here."""
        xy = dict(self.nodes)
        for r in self.rooms.values():
            xy[r.room_id] = r.xy
        edges = list(self.edges) + [(r.node, r.room_id) for r in self.rooms.values()]
        adj: dict[str, dict[str, float]] = {n: {} for n in xy}
        for a, b in edges:
            m = round(math.dist(xy[a], xy[b]), 3)
            adj[a][b] = m
            adj[b][a] = m
        return TrailGraph(nodes=list(xy), adjacency=adj), xy


def building_layout() -> Layout:
    """Collapsed school/office building: three east-west corridors joined by four north-south ones."""
    nodes = {
        "BASE": (6.0, 1.0),
        "S1": (6.0, 6.0), "S2": (18.0, 6.0), "S3": (30.0, 6.0), "S4": (42.0, 6.0),
        "M1": (6.0, 24.0), "M2": (18.0, 24.0), "M3": (30.0, 24.0), "M4": (42.0, 24.0),
        "N1": (6.0, 42.0), "N2": (18.0, 42.0), "N3": (30.0, 42.0), "N4": (42.0, 42.0),
    }
    edges = [("BASE", "S1"),
             ("S1", "S2"), ("S2", "S3"), ("S3", "S4"),
             ("M1", "M2"), ("M2", "M3"), ("M3", "M4"),
             ("N1", "N2"), ("N2", "N3"), ("N3", "N4"),
             ("S1", "M1"), ("M1", "N1"), ("S2", "M2"), ("M2", "N2"),
             ("S3", "M3"), ("M3", "N3"), ("S4", "M4"), ("M4", "N4")]
    rooms = [make_room(nodes, "R_NE", "N3", 45.0, "north-east office"),
             make_room(nodes, "R_NW", "N1", 45.0, "north-west classroom"),
             make_room(nodes, "R_E", "M4", 135.0, "east lab"),
             make_room(nodes, "R_C", "M2", 45.0, "central hall"),
             make_room(nodes, "R_SE", "S3", 45.0, "south-east store")]
    return Layout("collapsed_building", "urban", "Collapsed building (urban earthquake)", nodes, edges,
                  {r.room_id: r for r in rooms}, corridor_half_m=1.0)


# --- ground truth ---------------------------------------------------------------------------------
@dataclass
class Debris:
    debris_id: str
    a: str
    b: str
    at_m: float                         # SIMULATED metres from node a along a-b
    appears: str = "start"              # start | rover_enters (drops when the rover enters a->b) |
                                        # on_route (drops ahead of the rover on its route) | user
    note: str = ""


@dataclass
class Survivor:
    survivor_id: str
    room: str                           # room id; the survivor lies on that room's doorway spur
    at_m: float                         # metres from the junction along the spur
    condition: str                      # LYING_DOWN | NOT_MOVING | MOVING  (simulated)


@dataclass
class Decoy:
    """A false heat source (hot engine, fire, warm debris): a thermal look can mistake it for a person."""
    decoy_id: str
    room: str
    at_m: float
    strength: float = 0.35              # multiplies the thermal PoD


@dataclass
class Zone:
    zone_id: str
    x0: float
    y0: float
    x1: float
    y1: float
    vis: float                          # overhead camera visibility of the floor (0 = cannot see)
    label: str


@dataclass
class Scenario:
    key: str
    title: str
    summary: str
    seed: int
    survivors: list[Survivor]
    layout: Layout = field(default_factory=building_layout)
    debris: list[Debris] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    decoys: list[Decoy] = field(default_factory=list)
    search_sector: tuple[float, float, float, float] = (0.0, 30.0, SITE_M, SITE_M)  # x0, y0, x1, y1
    sector_label: str = "north wing (occupants reported)"
    comm_loss: Optional[tuple[float, float]] = None        # rover mission link down between t0 and t1
    assign_min_candidates: int = 1                          # candidates before the first assignment ...
    assign_timeout_s: float = 0.0                           # ... or this long after the first candidate
    max_t: float = 600.0
    fresh_s: Optional[float] = None                         # corridor observations older than this are STALE
    faults: dict = field(default_factory=dict)              # failure injection, see docs/dual_rescue/BENCHMARKS.md
    judge_notes: list[str] = field(default_factory=list)


def edge_key(a: str, b: str) -> str:
    x, y = sorted((a, b))
    return f"{x}-{y}"


def point_on_edge(xy: dict, a: str, b: str, at_m: float) -> tuple[float, float]:
    (x0, y0), (x1, y1) = xy[a], xy[b]
    L = math.dist((x0, y0), (x1, y1))
    f = 0.0 if L == 0 else min(1.0, max(0.0, at_m / L))
    return (round(x0 + f * (x1 - x0), 3), round(y0 + f * (y1 - y0), 3))


def edge_samples(xy: dict, a: str, b: str) -> list[tuple[float, float]]:
    L = math.dist(xy[a], xy[b])
    k = max(1, int(math.ceil(L / SAMPLE_STEP_M)))
    return [point_on_edge(xy, a, b, L * t / k) for t in range(k + 1)]


def visibility_map(zones: list[Zone]) -> np.ndarray:
    """Zones apply in order; a later zone overrides an earlier one (e.g. a roof hole inside a roof)."""
    vis = np.ones((N, N))
    for z in zones:
        for i in range(N):
            for j in range(N):
                cx, cy = cell_center((i, j))
                if z.x0 <= cx <= z.x1 and z.y0 <= cy <= z.y1:
                    vis[i, j] = z.vis
    return vis


class GroundTruth:
    """Simulator-only state. Agents reach it only through sensing calls."""

    def __init__(self, sc: Scenario, graph: TrailGraph, xy: dict):
        self.sc = sc
        self.g = graph
        self.xy = xy
        self.rooms = sc.layout.rooms
        self.vis = visibility_map(sc.zones)
        self.survivors = {s.survivor_id: s for s in sc.survivors}
        self.decoys = {d.decoy_id: d for d in sc.decoys}
        self.debris = {d.debris_id: d for d in sc.debris}
        self.present = {d.debris_id: d.appears == "start" for d in sc.debris}
        self.appeared_t: dict[str, float] = {d.debris_id: 0.0 for d in sc.debris if d.appears == "start"}
        self.blind_debris = bool(sc.faults.get("aerial_blind_debris"))

    def _spur_xy(self, room: str, at_m: float) -> tuple[float, float]:
        r = self.rooms[room]
        return point_on_edge(self.xy, r.node, r.room_id, at_m)

    def survivor_xy(self, sid: str) -> tuple[float, float]:
        s = self.survivors[sid]
        return self._spur_xy(s.room, s.at_m)

    def decoy_xy(self, did: str) -> tuple[float, float]:
        d = self.decoys[did]
        return self._spur_xy(d.room, d.at_m)

    def debris_xy(self, did: str) -> tuple[float, float]:
        d = self.debris[did]
        return point_on_edge(self.xy, d.a, d.b, d.at_m)

    def drop_debris(self, did: str, t: float) -> None:
        self.present[did] = True
        self.appeared_t[did] = t

    def debris_on(self, ek: str) -> list[str]:
        return [d for d, x in self.debris.items() if self.present[d] and edge_key(x.a, x.b) == ek]

    def aerial_look(self, cell: tuple[int, int], fov: int, pod: float, rng: np.random.Generator) -> dict:
        """What a downward thermal/RGB footprint centred on ``cell`` returns for one look.

        Heat sources (survivors, and decoys at reduced strength) are detected with probability
        pod x visibility (the same model as fleet.planner's canopy-weighted footprint). Debris inside the
        footprint is reported when the floor is visible. No ground-truth id leaves this method.
        """
        hits = []
        for sid in sorted(self.survivors):
            c = cell_of(*self.survivor_xy(sid))
            if in_window(cell, c, fov):
                p = pod * float(self.vis[c])
                if rng.random() < p:
                    hits.append({"xy": cell_center(c), "p_detect": round(p, 3),
                                 "motion_cue": self.survivors[sid].condition})
        for did in sorted(self.decoys):
            c = cell_of(*self.decoy_xy(did))
            if in_window(cell, c, fov):
                p = pod * float(self.vis[c]) * self.decoys[did].strength
                if rng.random() < p:
                    hits.append({"xy": cell_center(c), "p_detect": round(pod * float(self.vis[c]), 3),
                                 "motion_cue": "UNKNOWN"})
        debris = []
        if not self.blind_debris:
            for did in sorted(self.debris):
                if not self.present[did]:
                    continue
                c = cell_of(*self.debris_xy(did))
                if in_window(cell, c, fov) and self.vis[c] >= VISIBLE:
                    d = self.debris[did]
                    debris.append({"edge": edge_key(d.a, d.b), "xy": self.debris_xy(did)})
        return {"survivors": hits, "debris": debris}

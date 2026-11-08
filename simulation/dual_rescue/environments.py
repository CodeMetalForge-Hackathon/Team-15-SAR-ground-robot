"""Seeded environment generators for repeated experiments (SIMULATED sites, 48 m x 48 m).

Each generator returns a Scenario whose ground truth (survivor rooms, conditions, debris, false heat
sources, roof/canopy holes) is drawn from ``numpy.random.default_rng(seed)``. The layout itself is the
pre-incident floor plan and is known to the agents; the ground truth is not.

Environments:
    collapsed_building    3 x 4 corridor grid with room doorways, static debris
    open_outdoor          path network over an open field, tree-canopy zones (low overhead visibility)
    warehouse             long narrow rack aisles (0.8 m half-width), mezzanine zones
    narrow_corridors      hospital-style spine with side branches (0.6 m half-width)
    maze                  5 x 5 junction grid, random spanning tree plus a few loops (dead ends)
    dynamic               collapsed building, debris falls onto the rover's route after dispatch,
                          corridor observations go STALE after 60 s
    multi_survivor        collapsed building with 3 survivors and a false heat source
    partially_observable  collapsed building under large intact-roof zones with random holes
"""
from __future__ import annotations

import math

import numpy as np

from simulation.dual_rescue.world import (SITE_M, SPUR_M, Debris, Decoy, Layout, Scenario, Survivor, Zone,
                                          building_layout, make_room)

CONDITIONS = ("LYING_DOWN", "NOT_MOVING", "MOVING")
WHOLE_SITE = (0.0, 0.0, SITE_M, SITE_M)


def _free_angle(nodes: dict, edges: list, node: str, prefer=(45.0, 135.0, 315.0, 225.0)) -> float | None:
    used = []
    for a, b in edges:
        if node in (a, b):
            o = b if a == node else a
            (x0, y0), (x1, y1) = nodes[node], nodes[o]
            used.append(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360)
    for ang in prefer:
        a = math.radians(ang)
        x, y = nodes[node][0] + SPUR_M * math.cos(a), nodes[node][1] + SPUR_M * math.sin(a)
        if not (1.0 <= x <= SITE_M - 1.0 and 1.0 <= y <= SITE_M - 1.0):
            continue
        if all(min(abs(ang - u), 360 - abs(ang - u)) > 20 for u in used):
            return ang
    return None


def _rooms(nodes, edges, picks, label_prefix):
    """One doorway per junction, on a bearing at least 20 deg from every corridor at that junction."""
    rooms = {}
    for n in dict.fromkeys(picks):
        ang = _free_angle(nodes, edges, n)
        if ang is None:
            continue
        k = len(rooms) + 1
        r = make_room(nodes, f"R{k}", n, ang, f"{label_prefix} {k}")
        rooms[r.room_id] = r
    return rooms


def outdoor_layout() -> Layout:
    nodes = {"BASE": (6.0, 1.0)}
    xs, ys = (6.0, 24.0, 42.0), (6.0, 24.0, 42.0)
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            nodes[f"P{i}{j}"] = (x, y)
    edges = [("BASE", "P00")]
    for i in range(3):
        for j in range(2):
            edges.append((f"P{i}{j}", f"P{i}{j + 1}"))
    for j in range(3):
        for i in range(2):
            if (i, j) != (0, 1):               # no trail through the south meadow centre
                edges.append((f"P{i}{j}", f"P{i + 1}{j}"))
    edges.append(("P00", "P11"))               # diagonal trail
    picks = ["P22", "P20", "P12", "P02", "P21", "P10"]
    return Layout("open_outdoor", "outdoor", "Open outdoor search field", nodes, edges,
                  _rooms(nodes, edges, picks, "clearing"), corridor_half_m=2.0)


def warehouse_layout() -> Layout:
    nodes = {"BASE": (6.0, 1.0)}
    xs = (6.0, 14.0, 22.0, 30.0, 38.0)
    for j, x in enumerate(xs):
        nodes[f"S{j}"] = (x, 5.0)
        nodes[f"M{j}"] = (x, 24.0)
        nodes[f"N{j}"] = (x, 43.0)
    edges = [("BASE", "S0")]
    for j in range(len(xs)):
        edges += [(f"S{j}", f"M{j}"), (f"M{j}", f"N{j}")]
        if j + 1 < len(xs):
            edges += [(f"S{j}", f"S{j + 1}"), (f"N{j}", f"N{j + 1}")]
            if j % 2 == 0:
                edges.append((f"M{j}", f"M{j + 1}"))
    picks = ["N4", "N2", "M4", "N0", "M2", "S4"]
    return Layout("warehouse", "warehouse", "Industrial warehouse (rack aisles)", nodes, edges,
                  _rooms(nodes, edges, picks, "loading bay"), corridor_half_m=0.8)


def corridors_layout() -> Layout:
    nodes = {"BASE": (4.0, 1.0), "E0": (4.0, 8.0)}
    xs = (4.0, 12.0, 20.0, 28.0, 36.0, 44.0)
    for j, x in enumerate(xs):
        nodes[f"C{j}"] = (x, 24.0)
    edges = [("BASE", "E0"), ("E0", "C0")]
    for j in range(len(xs) - 1):
        edges.append((f"C{j}", f"C{j + 1}"))
    for j in (1, 3, 5):
        nodes[f"U{j}"] = (xs[j], 40.0)
        edges.append((f"C{j}", f"U{j}"))
    for j in (2, 4):
        nodes[f"D{j}"] = (xs[j], 8.0)
        edges.append((f"C{j}", f"D{j}"))
    edges += [("U1", "U3"), ("U3", "U5"), ("E0", "D2"), ("D2", "D4")]
    picks = ["U5", "U1", "D4", "U3", "C5", "D2"]
    return Layout("narrow_corridors", "corridors", "Collapsed indoor corridors (hospital wing)", nodes, edges,
                  _rooms(nodes, edges, picks, "ward"), corridor_half_m=0.6)


def maze_layout(rng: np.random.Generator) -> Layout:
    nodes = {"BASE": (6.0, 1.0)}
    K, step = 5, 9.0
    for i in range(K):
        for j in range(K):
            nodes[f"G{i}{j}"] = (6.0 + step * j, 6.0 + step * i)
    # randomised DFS spanning tree, then a few loops
    seen, stack, tree = {(0, 0)}, [(0, 0)], []
    while stack:
        i, j = stack[-1]
        nb = [(i + di, j + dj) for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))
              if 0 <= i + di < K and 0 <= j + dj < K and (i + di, j + dj) not in seen]
        if not nb:
            stack.pop()
            continue
        n = nb[int(rng.integers(len(nb)))]
        tree.append(((i, j), n))
        seen.add(n)
        stack.append(n)
    edges = [("BASE", "G00")] + [(f"G{a[0]}{a[1]}", f"G{b[0]}{b[1]}") for a, b in tree]
    have = {frozenset(e) for e in edges}
    extra = 0
    for _ in range(40):
        i, j = int(rng.integers(K)), int(rng.integers(K - 1))
        if rng.random() < 0.5:
            e = (f"G{i}{j}", f"G{i}{j + 1}")
        else:
            e = (f"G{j}{i}", f"G{j + 1}{i}")
        if frozenset(e) not in have:
            edges.append(e)
            have.add(frozenset(e))
            extra += 1
        if extra >= 3:
            break
    deg = {n: 0 for n in nodes}
    for a, b in edges:
        deg[a] += 1
        deg[b] += 1
    dead = sorted((n for n in nodes if n.startswith("G") and deg[n] == 1 and n != "G00"),
                  key=lambda n: -(nodes[n][0] + nodes[n][1]))
    picks = (dead + [n for n in sorted(nodes, key=lambda n: -(nodes[n][1])) if n.startswith("G")])[:6]
    return Layout("maze", "maze", "Maze-like ruined building", nodes, edges,
                  _rooms(nodes, edges, picks, "alcove"), corridor_half_m=0.8)


def _pick_survivors(rng, layout: Layout, k: int, avoid=()) -> list[Survivor]:
    rooms = [r for r in sorted(layout.rooms) if r not in avoid]
    idx = rng.choice(len(rooms), size=min(k, len(rooms)), replace=False)
    return [Survivor(f"S{n + 1}", rooms[int(i)], 4.5, CONDITIONS[int(rng.integers(len(CONDITIONS)))])
            for n, i in enumerate(sorted(idx))]


def _pick_debris(rng, layout: Layout, k: int, prefix="D") -> list[Debris]:
    spur_nodes = {r.room_id for r in layout.rooms.values()}
    cands = [(a, b) for a, b in layout.edges if layout.base not in (a, b) and a not in spur_nodes
             and b not in spur_nodes and math.dist(layout.nodes[a], layout.nodes[b]) >= 7.0]
    out = []
    for n, i in enumerate(rng.choice(len(cands), size=min(k, len(cands)), replace=False)):
        a, b = cands[int(i)]
        L = math.dist(layout.nodes[a], layout.nodes[b])
        out.append(Debris(f"{prefix}{n + 1}", a, b, round(float(rng.uniform(2.5, L - 2.5)), 2), note="collapse debris"))
    return out


def _decoy(rng, layout: Layout, survivors) -> list[Decoy]:
    used = {s.room for s in survivors}
    free = [r for r in sorted(layout.rooms) if r not in used]
    if not free:
        return []
    return [Decoy("H1", free[int(rng.integers(len(free)))], 4.5, strength=0.35)]


def make_environment(env: str, seed: int) -> Scenario:
    rng = np.random.default_rng(seed)
    common = dict(search_sector=WHOLE_SITE, sector_label="whole site (no occupancy report)", seed=seed, max_t=900.0)
    if env == "collapsed_building":
        lay = building_layout()
        sv = _pick_survivors(rng, lay, 1)
        return Scenario(key=f"{env}:{seed}", title="Collapsed building", summary="random survivor and debris",
                        survivors=sv, layout=lay, debris=_pick_debris(rng, lay, 2), **common)
    if env == "open_outdoor":
        lay = outdoor_layout()
        sv = _pick_survivors(rng, lay, 1)
        zones = []
        for k in range(3):
            x0, y0 = float(rng.uniform(4, 34)), float(rng.uniform(10, 34))
            zones.append(Zone(f"canopy{k + 1}", x0, y0, x0 + 10, y0 + 8, 0.35, "tree canopy"))
        return Scenario(key=f"{env}:{seed}", title="Open outdoor area", summary="paths, canopy patches",
                        survivors=sv, layout=lay, debris=_pick_debris(rng, lay, 1), zones=zones, **common)
    if env == "warehouse":
        lay = warehouse_layout()
        sv = _pick_survivors(rng, lay, 1)
        zones = [Zone("mezzanine", 26.0, 28.0, 42.0, 40.0, 0.3, "mezzanine deck")]
        return Scenario(key=f"{env}:{seed}", title="Warehouse", summary="narrow aisles, fallen racks",
                        survivors=sv, layout=lay, debris=_pick_debris(rng, lay, 3), zones=zones, **common)
    if env == "narrow_corridors":
        lay = corridors_layout()
        sv = _pick_survivors(rng, lay, 1)
        zones = [Zone("smoke", float(rng.uniform(8, 30)), 18.0, 0, 0, 0.2, "smoke")]
        zones[0].x1, zones[0].y1 = zones[0].x0 + 8.0, 30.0
        return Scenario(key=f"{env}:{seed}", title="Narrow indoor corridors", summary="0.6 m corridors, smoke",
                        survivors=sv, layout=lay, debris=_pick_debris(rng, lay, 2), zones=zones, **common)
    if env == "maze":
        lay = maze_layout(rng)
        sv = _pick_survivors(rng, lay, 1)
        return Scenario(key=f"{env}:{seed}", title="Maze-like building", summary="dead ends, few loops",
                        survivors=sv, layout=lay, debris=_pick_debris(rng, lay, 2), **common)
    if env == "dynamic":
        lay = building_layout()
        sv = _pick_survivors(rng, lay, 1)
        deb = _pick_debris(rng, lay, 1) + [Debris("X1", "?", "?", 0.0, appears="on_route", note="aftershock")]
        return Scenario(key=f"{env}:{seed}", title="Dynamic obstacles", summary="debris falls on the rover's route",
                        survivors=sv, layout=lay, debris=deb, fresh_s=60.0, **common)
    if env == "multi_survivor":
        lay = building_layout()
        sv = _pick_survivors(rng, lay, 3)
        return Scenario(key=f"{env}:{seed}", title="Multiple survivors", summary="3 survivors + 1 false heat source",
                        survivors=sv, layout=lay, debris=_pick_debris(rng, lay, 1), decoys=_decoy(rng, lay, sv),
                        assign_min_candidates=3, assign_timeout_s=90.0, **dict(common, max_t=1500.0))
    if env == "partially_observable":
        lay = building_layout()
        sv = _pick_survivors(rng, lay, 1)
        x0 = float(rng.choice([0.0, 12.0, 24.0]))
        zones = [Zone("roof", x0, 10.0, x0 + 24.0, 38.0, 0.0, "intact roof")]
        # roof holes are drawn independently of where the survivor is (no ground-truth leakage via the map)
        for k, i in enumerate(rng.choice(len(lay.rooms), size=2, replace=False)):
            r = lay.rooms[sorted(lay.rooms)[int(i)]]
            zones.append(Zone(f"hole{k + 1}", r.xy[0] - 3.5, r.xy[1] - 3.5, r.xy[0] + 1.0, r.xy[1] + 1.0, 0.7,
                              "roof hole"))
        return Scenario(key=f"{env}:{seed}", title="Partially observable", summary="intact roof over most corridors",
                        survivors=sv, layout=lay, debris=_pick_debris(rng, lay, 1), zones=zones, **common)
    raise KeyError(f"unknown environment {env}")


ENVIRONMENTS = ("collapsed_building", "open_outdoor", "warehouse", "narrow_corridors", "maze", "dynamic",
                "multi_survivor", "partially_observable")

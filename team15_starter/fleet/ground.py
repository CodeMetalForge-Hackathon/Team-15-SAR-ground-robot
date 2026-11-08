"""fleet/ground.py — the map as a ground rover sees it.

A drone flies over everything except the hostile no-fly cores. A rover can't:
water and buildings stop it, roads are fast, forest and wetland are slow. And
its camera is under the canopy, not above it, so trees hide people from it far
less than from a drone looking down.

GroundView looks like a GridWorld to the planner (free, neighbours, footprint
mass, no-detection update, vis, threat), so the same MCTS can plan a rover's
search. Its travel cost per cell is in seconds, and field()/path() are Dijkstra
on that cost, for the rover's time-to-home and its routes to a contact.
"""
from __future__ import annotations

import heapq
import math

import numpy as np

from .terrain import CLASSES

# fraction of top speed on each kind of ground (0 = can't drive there)
GROUND_SPEED = {"open": 0.6, "forest": 0.3, "scrub": 0.35, "water": 0.0, "road": 1.0,
                "trail": 0.8, "building": 0.0, "wetland": 0.15}
# how well a camera at rover height sees into each class (trunks and brush, but no canopy)
GROUND_VIS = {"open": 1.0, "forest": 0.6, "scrub": 0.45, "water": 1.0, "road": 1.0,
              "trail": 0.85, "building": 0.4, "wetland": 0.75}


class GroundView:
    def __init__(self, world, speed_mps=2.5):
        self.base = world
        self.n, self.cell_m = world.n, world.cell_m
        self.speed = float(speed_mps)
        self.pod, self.fov = 0.8, 1
        sc = getattr(world, "scenario", None)
        self.scenario = sc
        self.threat = getattr(world, "threat", None)
        blocked = world.obstacles.copy()
        if sc is not None:
            terrain = sc.terrain
            factor = np.vectorize(lambda k: GROUND_SPEED[CLASSES[k]])(terrain).astype(float)
            self.vis = np.vectorize(lambda k: GROUND_VIS[CLASSES[k]])(terrain).astype(float)
            self.terrain = terrain
        else:
            factor = np.ones((self.n, self.n))
            self.vis = None
            self.terrain = None
        blocked |= factor <= 0
        self.factor = np.where(blocked, 0.0, factor)
        self.obstacles = blocked
        with np.errstate(divide="ignore"):
            self.cost = np.where(blocked, np.inf, self.cell_m / (self.speed * np.maximum(self.factor, 1e-9)))

    # ------------------------------------------------ what the planner calls
    def free(self, c):
        i, j = c
        return 0 <= i < self.n and 0 <= j < self.n and not self.obstacles[i, j]

    def neighbours(self, c):
        i, j = c
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nc = (i + di, j + dj)
            if self.free(nc):
                yield nc

    def _footprint(self, c):
        i, j = c
        for di in range(-self.fov, self.fov + 1):
            for dj in range(-self.fov, self.fov + 1):
                nc = (i + di, j + dj)
                if 0 <= nc[0] < self.n and 0 <= nc[1] < self.n:
                    yield nc

    def footprint_mass(self, belief, c):
        if self.vis is None:
            return float(sum(belief[nc] for nc in self._footprint(c)))
        return float(sum(belief[nc] * self.vis[nc] for nc in self._footprint(c)))

    def update_no_detection(self, belief, c):
        for nc in self._footprint(c):
            belief[nc] *= (1.0 - self.pod * (1.0 if self.vis is None else self.vis[nc]))
        s = belief.sum()
        if s > 0:
            belief /= s

    # ------------------------------------------------ driving
    def speed_at(self, cell):
        """Metres per second the rover makes in this cell (0 if it can't drive there)."""
        return self.speed * float(self.factor[cell])

    def snap(self, cell):
        """Nearest cell the rover can be in (drift can put its estimate in a pond)."""
        if self.free(cell):
            return cell
        best, bd = cell, 1e9
        for i, j in zip(*np.nonzero(~self.obstacles)):
            d = abs(i - cell[0]) + abs(j - cell[1])
            if d < bd:
                best, bd = (int(i), int(j)), d
        return best

    def _step(self, a, b):
        return 0.5 * (self.cost[a] + self.cost[b])

    def field(self, goal):
        """Seconds of driving from every cell to `goal` (inf = can't get there)."""
        d = np.full((self.n, self.n), np.inf)
        if not self.free(goal):
            return d
        d[goal] = 0.0
        q = [(0.0, goal)]
        while q:
            dc, c = heapq.heappop(q)
            if dc > d[c]:
                continue
            for nc in self.neighbours(c):
                nd = dc + self._step(c, nc)
                if nd < d[nc]:
                    d[nc] = nd
                    heapq.heappush(q, (nd, nc))
        return d

    def path(self, start, goal):
        """Cells from start (exclusive) to goal (inclusive), fastest route, or None."""
        if start == goal:
            return []
        if not self.free(goal):
            return None
        h = lambda c: (abs(c[0] - goal[0]) + abs(c[1] - goal[1])) * self.cell_m / self.speed  # noqa: E731
        openq = [(h(start), 0.0, start)]
        came, g = {start: None}, {start: 0.0}
        while openq:
            _, gc, c = heapq.heappop(openq)
            if c == goal:
                out = []
                while c != start:
                    out.append(c)
                    c = came[c]
                return out[::-1]
            if gc > g[c]:
                continue
            for nc in self.neighbours(c):
                ng = gc + self._step(c, nc)
                if ng < g.get(nc, math.inf):
                    g[nc], came[nc] = ng, c
                    heapq.heappush(openq, (ng + h(nc), ng, nc))
        return None

    def path_time(self, start, goal):
        p = self.path(start, goal)
        if p is None:
            return math.inf
        t, prev = 0.0, start
        for c in p:
            t += self._step(prev, c)
            prev = c
        return t

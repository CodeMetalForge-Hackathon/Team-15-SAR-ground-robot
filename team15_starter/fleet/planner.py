"""fleet/planner.py — the pieces of the 3-drone brain that runs on the Jetson.

    GridWorld      the map + lost-person prior (same as sar.World, walls optional)
    Grid           metres <-> cells, origin (0, 0) = the homebase / AprilTag
    apply_look     Bayes no-detection update that respects VIO position error
    astar, dist_field   A* transits and the return-to-home cost map
    FleetMCTS      sar.MCTS that can be told which moves are allowed
    claim_path     marks belief a teammate is about to cover (sequential allocation)
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

from sar.planners import MCTS
from sar.sar_core import World
from sar.sensors import SENSORS

# how each sensor updates the belief when it looks and sees nothing.
# fov is in cells (Chebyshev radius); tune for your altitude and cell size.
SENSOR_PRESET = {
    "thermal": dict(fov=SENSORS["thermal"]["fov"], pod=SENSORS["thermal"]["pod"]),
    "cv": dict(fov=SENSORS["depth_ai"]["fov"], pod=SENSORS["depth_ai"]["pod"]),
    # radar range is fixed in metres (~1.5 m slant, ~1 m sideways), not in cells
    "mmwave": dict(fov=SENSORS["mmwave"]["fov"], pod=SENSORS["mmwave"]["pod"], range_m=1.0),
    "acoustic": dict(fov=SENSORS["acoustic"]["fov"], pod=SENSORS["acoustic"]["pod"]),
    # BLE only sees people carrying a phone/watch/tag, so a silent scan is weak evidence
    "ble": dict(fov=2, pod=0.45),
}


@dataclass
class GridWorld(World):
    """sar.World plus: walls on/off, a uniform prior, a heatmap from a .npy file
    (e.g. a SAREnv lost-person map), or a real-terrain Scenario (fleet/terrain.py)
    that supplies the prior, no-fly zones, camera visibility and threat map.
    With the same seed/scenario, the homebase and the simulator get the same prior."""
    walls: bool = True
    scenario: object = None

    @property
    def vis(self):
        return None if self.scenario is None else self.scenario.vis

    @property
    def threat(self):
        return None if self.scenario is None else self.scenario.threat

    def _add_blocks(self):
        if self.scenario is not None:
            self.obstacles = self.scenario.nofly.copy()   # hostile cores, not walls
        elif self.walls:
            super()._add_blocks()

    # cameras can't see through canopy: expected detections are weighted by visibility
    def footprint_mass(self, belief, c):
        if self.vis is None:
            return super().footprint_mass(belief, c)
        return float(sum(belief[nc] * self.vis[nc] for nc in self._footprint(c)))

    def update_no_detection(self, belief, c):
        if self.vis is None:
            return super().update_no_detection(belief, c)
        for nc in self._footprint(c):
            belief[nc] *= (1.0 - self.pod * self.vis[nc])
        s = belief.sum()
        if s > 0:
            belief /= s

    def _prior(self):
        if self.scenario is not None:
            p = self.scenario.prior.copy()
        elif self.prior == "uniform":
            p = np.ones((self.n, self.n))
        elif self.prior.endswith(".npy"):
            src = np.load(self.prior).astype(float)
            ys = (np.arange(self.n) * src.shape[0] / self.n).astype(int)
            xs = (np.arange(self.n) * src.shape[1] / self.n).astype(int)
            p = src[np.ix_(ys, xs)] + 1e-12
        else:
            return super()._prior()
        p[self.obstacles] = 0.0
        return p / p.sum()


class Grid:
    """Local metric frame. The homebase sits at the centre of `home` cell = (0, 0) m.
    x grows with column j (east), y grows with decreasing row i (north)."""

    def __init__(self, world: World, home=None):
        self.n, self.cell_m = world.n, world.cell_m
        self.home = home if home is not None else (world.n - 1, 0)

    def to_xy(self, cell):
        i, j = cell
        return ((j - self.home[1]) * self.cell_m, (self.home[0] - i) * self.cell_m)

    def to_cell(self, x, y):
        j = int(round(x / self.cell_m)) + self.home[1]
        i = self.home[0] - int(round(y / self.cell_m))
        return (min(max(i, 0), self.n - 1), min(max(j, 0), self.n - 1))


def sensor_visibility(name, vis):
    """Canopy hurts cameras most. Radar sees through leaves a bit; radio beacons don't care."""
    if name in ("thermal", "cv"):
        return vis
    if name == "mmwave":
        return np.maximum(vis, 0.6)
    return np.ones_like(vis)


def fov_cells(name, cell_m):
    """Footprint radius in cells. Camera-like sensors are tuned in cells (their
    footprint grows with altitude, and we fly lower when cells are smaller).
    Range-limited sensors (radar) convert their metres into cells."""
    pre = SENSOR_PRESET[name]
    if "range_m" in pre:
        return max(pre["fov"], int(pre["range_m"] / cell_m))
    return pre["fov"]


def snap_free(world, cell):
    """Nearest free cell (VIO drift can put a drone's estimate inside a wall)."""
    if world.free(cell):
        return cell
    best, bd = cell, 1e9
    for i in range(world.n):
        for j in range(world.n):
            if not world.obstacles[i, j]:
                d = abs(i - cell[0]) + abs(j - cell[1])
                if d < bd:
                    best, bd = (i, j), d
    return best


# ------------------------------------------------------------- belief update
def _coverage_1d(fov, sigma, radius):
    """P(a cell at offset d is inside a [-fov, fov] footprint) when the drone's
    true position ~ N(estimate, sigma^2), along one axis."""
    d = np.arange(-radius, radius + 1)
    if sigma < 0.3:
        return (np.abs(d) <= fov).astype(float)
    e = np.arange(-radius - fov, radius + fov + 1)
    g = np.exp(-0.5 * (e / sigma) ** 2)
    g /= g.sum()
    return np.array([g[(e >= dd - fov) & (e <= dd + fov)].sum() for dd in d])


def apply_look(world, mass, cell, sensors, sigma_cells=0.0):
    """No-detection update for every sensor that was on. Changes `mass` in place
    WITHOUT normalising, so 1 - mass.sum() = cumulative probability of success.
    With position uncertainty the look is spread over where the drone might
    really have been, instead of over-trusting the estimate (GPS-denied)."""
    before = float(mass.sum())
    for name in sensors:
        pre = SENSOR_PRESET.get(name)
        if pre is None:
            continue
        fov, pod = fov_cells(name, world.cell_m), pre["pod"]
        r = fov + int(math.ceil(3 * sigma_cells))
        c1 = _coverage_1d(fov, sigma_cells, r)
        cover = np.outer(c1, c1)
        i0, j0 = cell
        ia, ib = max(0, i0 - r), min(world.n, i0 + r + 1)
        ja, jb = max(0, j0 - r), min(world.n, j0 + r + 1)
        sub = cover[ia - (i0 - r): ib - (i0 - r), ja - (j0 - r): jb - (j0 - r)]
        vis = getattr(world, "vis", None)
        if vis is not None:
            sub = sub * sensor_visibility(name, vis[ia:ib, ja:jb])
        mass[ia:ib, ja:jb] *= (1.0 - pod * sub)
    return before - float(mass.sum())


def explain(world, mass, cell, radius=1, strength=0.9):
    """A person was found here: their probability mass is accounted for."""
    i0, j0 = cell
    ia, ib = max(0, i0 - radius), min(world.n, i0 + radius + 1)
    ja, jb = max(0, j0 - radius), min(world.n, j0 + radius + 1)
    mass[ia:ib, ja:jb] *= (1.0 - strength)


# ------------------------------------------------------------- A* / distances
def dist_field(world, goal):
    """Steps from every cell to `goal` around walls (BFS = A* with unit costs)."""
    d = np.full((world.n, world.n), np.inf)
    if not world.free(goal):
        return d
    d[goal] = 0
    frontier = [goal]
    while frontier:
        nxt = []
        for c in frontier:
            for nc in world.neighbours(c):
                if d[nc] == np.inf:
                    d[nc] = d[c] + 1
                    nxt.append(nc)
        frontier = nxt
    return d


def astar(world, start, goal):
    """Cells from start (exclusive) to goal (inclusive), or None if unreachable."""
    if start == goal:
        return []
    h = lambda c: abs(c[0] - goal[0]) + abs(c[1] - goal[1])  # noqa: E731
    openq = [(h(start), 0, start)]
    came, g = {start: None}, {start: 0}
    while openq:
        _, gc, c = heapq.heappop(openq)
        if c == goal:
            path = []
            while c != start:
                path.append(c)
                c = came[c]
            return path[::-1]
        if gc > g[c]:
            continue
        for nc in world.neighbours(c):
            ng = gc + 1
            if ng < g.get(nc, 1e18):
                g[nc], came[nc] = ng, c
                heapq.heappush(openq, (ng + h(nc), ng, nc))
    return None


def downhill(world, field, cell):
    """Next cell toward the field's zero (used for return-to-home)."""
    best, bv = cell, field[cell]
    for nc in world.neighbours(cell):
        if field[nc] < bv:
            best, bv = nc, field[nc]
    return best


# ------------------------------------------------------------------- planner
class FleetMCTS(MCTS):
    """sar.MCTS with an `allowed` list: the fleet layer removes moves that a
    teammate already claimed or that the battery can't come back from.
    With a scenario, the military exposure cost comes from the real threat map."""

    def _exposure_cost(self, c):
        threat = getattr(self.world, "threat", None)
        if self.exposure == 0:
            return 0.0
        if threat is None:
            return super()._exposure_cost(c)
        return self.exposure * float(threat[c])

    def next_move(self, world, belief, pos, allowed=None):
        moves = list(allowed) if allowed is not None else list(world.neighbours(pos))
        if not moves:
            return pos
        if len(moves) == 1:
            return moves[0]
        N = {m: 0 for m in moves}
        Q = {m: 0.0 for m in moves}
        total = 0
        for _ in range(self.n_sims):
            m = self._select(moves, N, Q, total)
            r = self._simulate(belief.copy(), pos, m)
            N[m] += 1
            total += 1
            Q[m] += (r - Q[m]) / N[m]
        return max(moves, key=lambda m: Q[m])


def greedy_step(world, belief, pos):
    best, bs = pos, -1.0
    for nc in world.neighbours(pos):
        s = world.footprint_mass(belief, nc)
        if s > bs:
            best, bs = nc, s
    return best


def claim_path(world, belief, first, sensors, steps=6):
    """Pretend this drone flies `first` then greedily for `steps` more cells and
    sees nothing. Teammates planned after it see that mass as already taken,
    so the three drones fan out instead of chasing the same hotspot."""
    cur = first
    for _ in range(steps):
        apply_look(world, belief, cur, sensors)
        nxt = greedy_step(world, belief, cur)
        if nxt == cur:
            break
        cur = nxt

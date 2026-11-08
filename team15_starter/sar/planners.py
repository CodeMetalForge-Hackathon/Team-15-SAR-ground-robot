"""planners.py — lawnmower, greedy, MCTS. All expose next_move(world, belief, pos)."""
from __future__ import annotations
import math


class Lawnmower:
    def __init__(self, world):
        self.path = self._sweep(world)
        self.k = 0

    def _sweep(self, world):
        order = []
        for i in range(world.n):
            cols = range(world.n) if i % 2 == 0 else range(world.n - 1, -1, -1)
            for j in cols:
                if world.free((i, j)):
                    order.append((i, j))
        return order

    def next_move(self, world, belief, pos):
        if self.k < len(self.path) - 1:
            self.k += 1
        return _step_toward(world, pos, self.path[self.k])


class Greedy:
    def next_move(self, world, belief, pos):
        best, best_score = pos, -1.0
        for i in range(world.n):
            for j in range(world.n):
                if world.obstacles[i, j]:
                    continue
                dist = abs(i - pos[0]) + abs(j - pos[1]) + 1
                score = world.footprint_mass(belief, (i, j)) / dist
                if score > best_score:
                    best, best_score = (i, j), score
        return _step_toward(world, pos, best)


class MCTS:
    def __init__(self, world, n_sims=200, horizon=18, c=1.4, gamma=0.98, exposure=0.0):
        self.world = world
        self.n_sims = n_sims
        self.horizon = horizon
        self.c = c
        self.gamma = gamma
        self.exposure = exposure

    def _exposure_cost(self, c):
        if self.exposure == 0:
            return 0.0
        return self.exposure * (0.5 if self.world.free(c) else 0.0)

    def next_move(self, world, belief, pos):
        moves = list(world.neighbours(pos)) or [pos]
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

    def _select(self, moves, N, Q, total):
        for m in moves:
            if N[m] == 0:
                return m
        logt = math.log(total + 1)
        return max(moves, key=lambda m: Q[m] + self.c * math.sqrt(logt / N[m]))

    def _simulate(self, belief, pos, first_move):
        world = self.world
        total, discount = 0.0, 1.0
        cur = first_move
        for _ in range(self.horizon):
            mass = world.footprint_mass(belief, cur)
            total += discount * (world.pod * mass - self._exposure_cost(cur))
            world.update_no_detection(belief, cur)
            discount *= self.gamma
            cur = self._rollout_step(belief, cur)
        return total

    def _rollout_step(self, belief, pos):
        best, best_score = pos, -1.0
        for nc in self.world.neighbours(pos):
            score = self.world.footprint_mass(belief, nc)
            if score > best_score:
                best, best_score = nc, score
        return best


def _step_toward(world, pos, target):
    if pos == target:
        return pos
    best, best_d = pos, abs(pos[0] - target[0]) + abs(pos[1] - target[1])
    for nc in world.neighbours(pos):
        d = abs(nc[0] - target[0]) + abs(nc[1] - target[1])
        if d < best_d:
            best, best_d = nc, d
    return best

"""sar_core.py — belief grid over where the person(s) are, no GPS.
Multiple people at random, unknown endpoints. Planner sees only the belief."""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field


@dataclass
class World:
    n: int = 24
    cell_m: float = 20.0
    pod: float = 0.8
    fov: int = 1
    prior: str = "ring"
    n_people: int = 1
    seed: int = 0

    belief: np.ndarray = field(init=False)
    obstacles: np.ndarray = field(init=False)
    people: list = field(init=False)
    endpoints: list = field(init=False)
    rng: np.random.Generator = field(init=False)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        self.obstacles = np.zeros((self.n, self.n), dtype=bool)
        self.endpoints = []
        self._add_blocks()
        self.belief = self._prior()
        self.people = self._sample_people(self.n_people)

    def _add_blocks(self):
        self.obstacles[self.n // 3, 2:self.n // 2] = True
        self.obstacles[2 * self.n // 3, self.n // 2:-2] = True

    def _blob(self, cy, cx, sigma):
        ys, xs = np.mgrid[0:self.n, 0:self.n]
        return np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma ** 2))

    def _prior(self):
        if self.prior == "multi":
            k = max(self.n_people + 1, 3)
            p = np.zeros((self.n, self.n))
            for _ in range(k):
                cy = int(self.rng.integers(2, self.n - 2))
                cx = int(self.rng.integers(2, self.n - 2))
                p += self.rng.uniform(0.6, 1.0) * self._blob(cy, cx, self.n * 0.08)
                self.endpoints.append((cy, cx))
        elif self.prior == "bimodal":
            p = 0.9 * self._blob(self.n * 0.35, self.n * 0.35, self.n * 0.09)
            p += 1.0 * self._blob(self.n * 0.25, self.n * 0.80, self.n * 0.09)
        else:
            ys, xs = np.mgrid[0:self.n, 0:self.n]
            d = np.hypot(xs - self.n * 0.3, ys - self.n * 0.3)
            p = np.exp(-((d - self.n * 0.25) ** 2) / (2 * (self.n * 0.12) ** 2))
        p[self.obstacles] = 0.0
        return p / p.sum()

    def _sample_people(self, k):
        flat = self.belief.flatten()
        chosen, tries = set(), 0
        while len(chosen) < k and tries < 2000:
            idx = self.rng.choice(len(flat), p=flat)
            chosen.add((idx // self.n, idx % self.n))
            tries += 1
        return list(chosen)

    def free(self, c):
        i, j = c
        return 0 <= i < self.n and 0 <= j < self.n and not self.obstacles[i, j]

    def _footprint(self, c):
        i, j = c
        for di in range(-self.fov, self.fov + 1):
            for dj in range(-self.fov, self.fov + 1):
                nc = (i + di, j + dj)
                if 0 <= nc[0] < self.n and 0 <= nc[1] < self.n:
                    yield nc

    def detect(self, c, remaining):
        fp = set(self._footprint(c))
        return {idx for idx in remaining
                if self.people[idx] in fp and self.rng.random() < self.pod}

    def footprint_mass(self, belief, c):
        return float(sum(belief[nc] for nc in self._footprint(c)))

    def update_no_detection(self, belief, c):
        for nc in self._footprint(c):
            belief[nc] *= (1.0 - self.pod)
        s = belief.sum()
        if s > 0:
            belief /= s

    def neighbours(self, c):
        i, j = c
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nc = (i + di, j + dj)
            if self.free(nc):
                yield nc

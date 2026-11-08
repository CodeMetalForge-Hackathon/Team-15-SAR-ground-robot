"""AIR-1: simulated aerial scout. Real search algorithm, simulated airframe.

Reused (PR #17, team15_starter/fleet/planner.py and sar/):
    GridWorld           belief grid with a visibility-weighted, vectorised camera footprint
    apply_look          Bayes no-detection update (mass not normalised: 1 - sum = cumulative PoS)
    explain             removes the mass a found person accounts for
    FleetMCTS           sar MCTS (UCB1 over neighbour moves, greedy rollouts); subclassed here only to
                        keep its N/Q table so the dashboard can show WHY a move was chosen
    sar.sensors         "thermal" preset: footprint radius 2 cells, PoD 0.90

New simulation-only code (this file): airframe kinematics (position, heading, speed), survivor
candidate tracking with a Bayes confidence, corridor coverage, and coordinator tasks
(CONFIRM hover, SCOUT corridors). The aircraft never exists outside this simulator.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

import simulation.dual_rescue  # noqa: F401  (puts team15_starter on sys.path)
from fleet.planner import SENSOR_PRESET, FleetMCTS, GridWorld, apply_look, explain  # noqa: E402
from sar.planners import Greedy, Lawnmower  # noqa: E402  (baselines, unchanged)

from simulation.dual_rescue.world import (CELL_M, N, VISIBLE, Scenario, cell_center, cell_of, edge_key,
                                          edge_samples, in_window)

PLANNERS = ("mcts", "greedy", "lawnmower")

SENSOR = "thermal"
FOV = SENSOR_PRESET[SENSOR]["fov"]
POD = SENSOR_PRESET[SENSOR]["pod"]
SPEED_MPS = 4.0               # SIMULATED airframe cruise speed
ALT_M = 15.0                  # SIMULATED altitude (display only)
CONFIRM_LOOKS = 3             # extra hover looks over a new candidate (PR #17 "finder" behaviour)
HOVER_LOOK_S = 1.0
ASSOC_M = 3.0                 # repeat sightings within this distance are the same candidate
BASE_RATE = 0.10              # prior that a heat signature is a person (Bayes confidence)
FALSE_ALARM = 0.05            # per-look false-alarm rate assumed by the confidence model
CLEAR_FRACTION = 0.95         # share of a corridor that must be seen before the drone calls it CLEAR
SEARCH_DONE_POS = 0.97        # stop searching when the cumulative PoS of the sector reaches this

DATA_LABEL = "SIMULATED DRONE OBSERVATION"
SOURCE = f"sim-aerial-{SENSOR}"


def bayes_confidence(hits: int, looks: int, pod: float) -> float:
    """P(person | hits in looks) with a base rate and a per-look false-alarm rate."""
    p = BASE_RATE * pod ** hits * (1 - pod) ** (looks - hits)
    q = (1 - BASE_RATE) * FALSE_ALARM ** hits * (1 - FALSE_ALARM) ** (looks - hits)
    return round(p / (p + q), 3) if p + q > 0 else 0.0


class _Overhead:
    """Duck-typed fleet.terrain.Scenario: the prior, overhead visibility and (empty) no-fly mask."""

    def __init__(self, prior: np.ndarray, vis: np.ndarray):
        self.prior = prior
        self.vis = vis
        self.nofly = np.zeros_like(vis, dtype=bool)
        self.threat = None


class ExplainedMCTS(FleetMCTS):
    """FleetMCTS.next_move unchanged, but the visit counts and values are kept for display."""

    last: dict = {}

    def next_move(self, world, belief, pos, allowed=None):
        moves = list(allowed) if allowed is not None else list(world.neighbours(pos))
        if not moves:
            self.last = {}
            return pos
        N_, Q = {m: 0 for m in moves}, {m: 0.0 for m in moves}
        total = 0
        for _ in range(self.n_sims):
            m = self._select(moves, N_, Q, total)
            r = self._simulate(belief.copy(), pos, m)
            N_[m] += 1
            total += 1
            Q[m] += (r - Q[m]) / N_[m]
        best = max(moves, key=lambda m: Q[m])
        self.last = {m: (N_[m], Q[m]) for m in moves}
        return best


def sector_prior(sc: Scenario) -> np.ndarray:
    """Mission prior from the occupancy REPORT (the search sector), never from ground truth."""
    x0, y0, x1, y1 = sc.search_sector
    p = np.full((N, N), 1e-4)
    for i in range(N):
        for j in range(N):
            cx, cy = cell_center((i, j))
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                p[i, j] = 1.0
    return p


class AerialScout:
    agent_id = "AIR-1"

    def __init__(self, sc: Scenario, graph, xy: dict, vis: np.ndarray, start_xy: tuple[float, float],
                 seed: int, n_sims: int = 40, horizon: int = 8, planner: str = "mcts"):
        if planner not in PLANNERS:
            raise ValueError(f"planner must be one of {PLANNERS}")
        self.planner = planner
        self.sc = sc
        self.xy = xy
        self.vis = vis
        prior = sector_prior(sc)
        self.world = GridWorld(n=N, cell_m=CELL_M, pod=POD, fov=FOV, prior="uniform", n_people=0, seed=seed,
                               walls=False, scenario=_Overhead(prior, vis))
        self.sector_mask = prior >= 1.0
        self.mass = self.world.belief.copy()            # un-normalised: 1 - mass.sum() = cumulative PoS
        # mass the camera can actually observe (overhead visibility): the search ends when THIS is exhausted
        self.obs0 = float((self.world.belief * vis)[self.sector_mask].sum())
        self.mcts = ExplainedMCTS(self.world, n_sims=n_sims, horizon=horizon)
        self.baseline = Lawnmower(self.world) if planner == "lawnmower" else Greedy() if planner == "greedy" else None
        self.failed = False
        self.beat_t = 0.0
        self.missing_frames = 0
        self.rng = np.random.default_rng(seed + 1)     # sensing noise (fixed seed => reproducible)
        self.x, self.y = start_xy
        self.heading = 90.0
        self.cell = cell_of(*start_xy)
        self.target: Optional[tuple[int, int]] = None
        self.mode = "LAUNCH"
        self.why = "launching from base"
        self.path: list[tuple[float, float, float]] = [(0.0, self.x, self.y)]
        self.looked = np.zeros((N, N), dtype=bool)
        self.looks = 0
        self.distance_m = 0.0
        self.outbox: list[dict] = []
        self.candidates: list[dict] = []
        self.tasks: list[dict] = []                     # queued coordinator tasks
        self.task: Optional[dict] = None
        self.hover_until = 0.0
        self.confirm: Optional[dict] = None
        self.search_complete = False
        self._ids = 0
        # corridor coverage: edge -> {"samples": [(x, y, cell)], "seen": set, "occluded": set, "status": str}
        self.corridors: dict[str, dict] = {}
        for a, b, _m in graph.edges():
            pts = [(x, y, cell_of(x, y)) for x, y in edge_samples(xy, a, b)]
            self.corridors[edge_key(a, b)] = {"a": a, "b": b, "samples": pts, "seen": set(), "occluded": set(),
                                              "status": "UNKNOWN", "debris": None}

    # --- observations -------------------------------------------------------------------------
    def _obs(self, t: float, kind: str, **body) -> dict:
        self._ids += 1
        o = {"obs_id": f"air-{self._ids:04d}", "t": round(t, 2), "agent": self.agent_id, "source": SOURCE,
             "data_label": DATA_LABEL, "frame": "SITE", "kind": kind, **body}
        self.outbox.append(o)
        return o

    # --- tasks from the coordinator --------------------------------------------------------------
    def assign(self, task: dict) -> None:
        self.tasks.append(task)

    def pos_observable(self) -> float:
        """Cumulative PoS over the part of the sector the camera can see (vis-weighted)."""
        if self.obs0 <= 0:
            return 1.0
        return float(1.0 - (self.mass * self.vis)[self.sector_mask].sum() / self.obs0)

    def pos_of_sector(self) -> float:
        m0 = self.world.belief[self.sector_mask].sum()
        return float(1.0 - self.mass[self.sector_mask].sum() / m0) if m0 > 0 else 1.0

    # --- sensing ------------------------------------------------------------------------------
    def _look(self, t: float, sense) -> None:
        c = self.cell
        res = sense(c, FOV, POD, self.rng)
        if res is None:                     # missing frame: no evidence, so no belief/coverage update
            self.missing_frames += 1
            return
        self.looks += 1
        i0, j0 = c
        self.looked[max(0, i0 - FOV):i0 + FOV + 1, max(0, j0 - FOV):j0 + FOV + 1] = True
        apply_look(self.world, self.mass, c, [SENSOR])
        # corridors in the footprint
        changed = []
        for ek, cor in self.corridors.items():
            touched = False
            for k, (_x, _y, sc) in enumerate(cor["samples"]):
                if in_window(c, sc, FOV):
                    touched = True
                    (cor["seen"] if self.vis[sc] >= VISIBLE else cor["occluded"]).add(k)
            if not touched:
                continue
            deb = [d for d in res["debris"] if d["edge"] == ek]
            new = cor["status"]
            if deb:
                new = "BLOCKED"
                cor["debris"] = deb[0]["xy"]
            elif cor["status"] != "BLOCKED":
                n = len(cor["samples"])
                if len(cor["seen"]) >= CLEAR_FRACTION * n:
                    new = "CLEAR"
                elif len(cor["seen"] | cor["occluded"]) >= n:
                    new = "OCCLUDED"
            if new != cor["status"]:
                cor["status"] = new
                changed.append(ek)
        for ek in changed:
            cor = self.corridors[ek]
            n = len(cor["samples"])
            seen = round(len(cor["seen"]) / n, 2)
            if cor["status"] == "BLOCKED":
                self._obs(t, "debris", edge=ek, status="BLOCKED", xy=list(cor["debris"]), confidence=0.9,
                          detail=f"debris on corridor {ek} seen from above (floor visible)")
            else:
                self._obs(t, "corridor_state", edge=ek, status=cor["status"], seen_fraction=seen,
                          xy=list(cell_center(c)), confidence=seen,
                          detail=("corridor floor seen end to end, no debris" if cor["status"] == "CLEAR" else
                                  "corridor under intact roof/smoke: overhead camera cannot see the floor"))
        # survivors
        for h in res["survivors"]:
            self._sighting(t, h)
        # a confirm hover counts looks even without a hit
        if self.confirm is not None:
            cand = self.confirm["cand"]
            if in_window(c, cell_of(*cand["xy"]), FOV):
                cand["looks"] += 1
                cand["confidence"] = bayes_confidence(cand["hits"], cand["looks"], cand["p_detect"])

    def _sighting(self, t: float, h: dict) -> None:
        for cand in self.candidates:
            if math.dist(cand["xy"], h["xy"]) <= ASSOC_M:
                cand["hits"] += 1
                if self.confirm is None or self.confirm["cand"] is not cand:
                    cand["looks"] += 1
                    cand["confidence"] = bayes_confidence(cand["hits"], cand["looks"], cand["p_detect"])
                cand["last_t"] = round(t, 2)
                cand["_cue"] = h["motion_cue"]
                return
        cand = {"cand_id": f"C{len(self.candidates) + 1}", "xy": list(h["xy"]), "hits": 1, "looks": 1,
                "p_detect": h["p_detect"], "first_t": round(t, 2), "last_t": round(t, 2),
                "confidence": bayes_confidence(1, 1, h["p_detect"]), "motion": "UNKNOWN",
                "status": "POSSIBLE", "_cue": h["motion_cue"], "obs_ids": []}
        self.candidates.append(cand)
        o = self._obs(t, "survivor_candidate", cand_id=cand["cand_id"], status="POSSIBLE", xy=cand["xy"],
                      position_sigma_m=round(CELL_M / math.sqrt(12) * math.sqrt(2), 2),
                      confidence=cand["confidence"], motion="UNKNOWN",
                      detail=f"thermal signature in footprint (PoD x visibility = {h['p_detect']:.2f}); "
                             f"hovering {CONFIRM_LOOKS} looks to confirm")
        cand["obs_ids"].append(o["obs_id"])
        explain(self.world, self.mass, cell_of(*cand["xy"]), radius=0, strength=0.9)
        self.tasks.insert(0, {"type": "CONFIRM", "cand_id": cand["cand_id"], "task_id": f"auto-{cand['cand_id']}",
                              "reason": f"new thermal candidate {cand['cand_id']}"})

    # --- decision -----------------------------------------------------------------------------
    def _hotspot(self) -> tuple[Optional[tuple[int, int]], float]:
        """Greedy (sar.planners.Greedy scoring): footprint mass / (Manhattan distance + 1)."""
        best, bs = None, 0.0
        for i in range(N):
            for j in range(N):
                m = self.world.footprint_mass(self.mass, (i, j))
                s = m / (abs(i - self.cell[0]) + abs(j - self.cell[1]) + 1)
                if s > bs:
                    best, bs = (i, j), s
        return best, bs

    def _step_toward(self, goal: tuple[int, int]) -> tuple[int, int]:
        i, j = self.cell
        return (i + (goal[0] > i) - (goal[0] < i), j + (goal[1] > j) - (goal[1] < j))

    def _scout_goal(self) -> Optional[tuple[int, int]]:
        best, bd = None, math.inf
        for ek in self.task["edges"]:
            cor = self.corridors[ek]
            for k, (x, y, c) in enumerate(cor["samples"]):
                if k in cor["seen"] or k in cor["occluded"]:
                    continue
                d = math.dist((self.x, self.y), (x, y))
                if d < bd:
                    best, bd = c, d
        return best

    def _next_task(self, t: float) -> None:
        if self.task is None and self.tasks:
            self.task = self.tasks.pop(0)
            for ek in self.task.get("recheck", ()):     # re-observe even if seen before (fresh evidence)
                cor = self.corridors[ek]
                cor["seen"].clear()
                cor["occluded"].clear()
                cor["status"] = "RECHECK"
            if self.task["type"] == "CONFIRM":
                cand = next(c for c in self.candidates if c["cand_id"] == self.task["cand_id"])
                self.confirm = {"cand": cand, "looks_left": CONFIRM_LOOKS}

    def _finish_task(self, t: float, result: dict) -> None:
        self._obs(t, "task_done", task_id=self.task["task_id"], task_type=self.task["type"], result=result,
                  confidence=None, detail=f"{self.task['type']} finished")
        self.task = None

    def _decide(self, t: float) -> None:
        self._next_task(t)
        if self.task is not None and self.task["type"] == "CONFIRM":
            cf = self.confirm
            cand = cf["cand"]
            goal = cell_of(*cand["xy"])
            if self.cell != goal:
                self.target = self._step_toward(goal)
                self.mode, self.why = "CONFIRM", f"flying to candidate {cand['cand_id']} to hover and confirm"
                return
            if cf["looks_left"] > 0:
                cf["looks_left"] -= 1
                self.hover_until = t + HOVER_LOOK_S
                self.target = self.cell
                self.mode = "CONFIRM"
                self.why = (f"hovering over {cand['cand_id']}: look {CONFIRM_LOOKS - cf['looks_left']}/{CONFIRM_LOOKS},"
                            f" {cand['hits']}/{cand['looks']} hits, confidence {cand['confidence']:.2f}")
                return
            cand["motion"] = cand["_cue"] if cand["hits"] >= 2 else "UNKNOWN"
            cand["status"] = "LIKELY" if cand["confidence"] >= 0.8 else "POSSIBLE"
            o = self._obs(t, "survivor_candidate", cand_id=cand["cand_id"], status=cand["status"], xy=cand["xy"],
                          position_sigma_m=round(CELL_M / math.sqrt(12) * math.sqrt(2), 2),
                          confidence=cand["confidence"], motion=cand["motion"], hits=cand["hits"],
                          looks=cand["looks"], refs=list(cand["obs_ids"]),
                          detail=f"confirm hover: {cand['hits']}/{cand['looks']} looks detected heat; motion cue "
                                 f"{cand['motion']} (SIMULATED cue). Human confirmation still required.")
            cand["obs_ids"].append(o["obs_id"])
            self.confirm = None
            self._finish_task(t, {"cand_id": cand["cand_id"], "confidence": cand["confidence"]})
            return self._decide(t)
        if self.task is not None and self.task["type"] == "SCOUT":
            goal = self._scout_goal()
            if goal is None:
                res = {ek: self.corridors[ek]["status"] for ek in self.task["edges"]}
                self._finish_task(t, res)
                return self._decide(t)
            self.target = self._step_toward(goal) if goal != self.cell else goal
            self.mode = "SCOUT"
            self.why = (f"task {self.task['task_id']}: observing corridors {', '.join(self.task['edges'])} "
                        f"for {self.task['reason']}")
            return
        if self.search_complete:
            self.mode, self.target, self.why = "HOLD", self.cell, "sector search complete; holding for tasks"
            return
        pos = self.pos_of_sector()
        pos_obs = self.pos_observable()
        if pos_obs >= SEARCH_DONE_POS:
            self.search_complete = True
            self._obs(t, "search_complete", status="COMPLETE", confidence=round(pos_obs, 3),
                      detail=f"cumulative PoS {pos_obs:.2f} over the observable sector ({pos:.2f} incl. areas the "
                             f"camera cannot see)")
            return self._decide(t)
        belief = self.mass / self.mass.sum() if self.mass.sum() > 0 else self.mass
        if self.baseline is not None:
            move = self.baseline.next_move(self.world, belief, self.cell)
            if self.planner == "lawnmower":
                while move == self.cell and self.baseline.k < len(self.baseline.path) - 1:
                    move = self.baseline.next_move(self.world, belief, self.cell)   # sweep cell already reached
                if move == self.cell:
                    self.search_complete = True       # sweep finished
                    return self._decide(t)
            self.target = move
            self.mode = "SEARCH"
            self.why = f"baseline {self.planner} (sar.planners, unchanged); sector PoS {pos:.2f}"
            return
        move = self.mcts.next_move(self.world, belief, self.cell)
        qs = self.mcts.last
        best_q = max((q for _n, q in qs.values()), default=0.0)
        if best_q <= 1e-6 or move == self.cell:
            hot, score = self._hotspot()
            if hot is None or score < 1e-9:
                self.search_complete = True
                return self._decide(t)
            self.target = self._step_toward(hot)
            x, y = cell_center(hot)
            self.mode = "TRANSIT"
            self.why = (f"no belief within the MCTS horizon; transiting to the highest-value unexplored area "
                        f"({x:.0f}, {y:.0f}) m, greedy score {score:.4f}")
            return
        self.target = move
        ranked = sorted(qs.items(), key=lambda kv: -kv[1][1])
        dirs = {(1, 0): "N", (-1, 0): "S", (0, 1): "E", (0, -1): "W"}
        txt = ", ".join(f"{dirs.get((m[0] - self.cell[0], m[1] - self.cell[1]), '?')} Q={q:.3f} (n={n})"
                        for m, (n, q) in ranked)
        self.mode = "SEARCH"
        self.why = (f"MCTS ({self.mcts.n_sims} rollouts, horizon {self.mcts.horizon}): {txt}; "
                    f"sector PoS {pos:.2f}")

    # --- simulation step ----------------------------------------------------------------------
    def fail(self, t: float) -> None:
        """Fault injection: the airframe stops responding (agent timeout)."""
        self.failed = True
        self.mode, self.why, self.target = "FAILED", f"no response since t={t:.1f} s (SIMULATED fault)", None

    def step(self, t: float, dt: float, sense) -> None:
        """``sense(cell, fov, pod, rng)`` is the only path to the simulated world (an opaque callable)."""
        if self.failed:
            return
        self.beat_t = t
        if self.mode == "LAUNCH":
            self._look(t, sense)
            self._decide(t)
        if t < self.hover_until:
            return
        if self.mode == "HOLD" and not self.tasks:
            return
        if self.target is None:
            self._decide(t)
            return
        tx, ty = cell_center(self.target)
        d = math.dist((self.x, self.y), (tx, ty))
        step = SPEED_MPS * dt
        if d > 1e-9:
            self.heading = math.degrees(math.atan2(ty - self.y, tx - self.x)) % 360
        if d > step:
            self.x += (tx - self.x) / d * step
            self.y += (ty - self.y) / d * step
            self.distance_m += step
            return
        self.distance_m += d
        self.x, self.y = tx, ty
        self.cell = self.target
        self.path.append((round(t, 2), round(self.x, 2), round(self.y, 2)))
        self._look(t, sense)
        self._decide(t)

    def status(self) -> dict:
        return {"agent": self.agent_id, "data_label": DATA_LABEL, "x": round(self.x, 2), "y": round(self.y, 2),
                "planner": self.planner, "failed": self.failed, "missing_frames": self.missing_frames,
                "alt_m": ALT_M, "heading_deg": round(self.heading, 1), "mode": self.mode, "why": self.why,
                "target": None if self.target is None else list(cell_center(self.target)),
                "speed_mps": SPEED_MPS, "sensor": SENSOR, "fov_cells": FOV, "pod": POD,
                "footprint_m": (2 * FOV + 1) * CELL_M, "looks": self.looks,
                "distance_m": round(self.distance_m, 1), "sector_pos": round(self.pos_of_sector(), 3),
                "observable_pos": round(self.pos_observable(), 3),
                "search_complete": self.search_complete,
                "task": None if self.task is None else {k: v for k, v in self.task.items()},
                "queued_tasks": len(self.tasks),
                "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in self.candidates]}

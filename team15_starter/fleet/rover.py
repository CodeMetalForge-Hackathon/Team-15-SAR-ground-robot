"""fleet/rover.py — a ground rover in the search.

SimRover   the simulated vehicle: drives (doesn't fly) at a speed that depends
           on the ground under it, can't cross water or buildings, and its
           camera sits under the trees, so canopy hides people from it far
           less than from a drone. Same packets as a drone (z = 0).
RoverBrain the homebase side. Each tick, for every rover:
           1. a contact without vitals -> drive to it, stop next to it, read
              vitals with the radar (the drones may not see through canopy)
           2. otherwise search: drive to the best nearby ground the drones
              haven't covered, by travel time (Dijkstra on terrain speed)
           3. recall -> drive home and park
"""
from __future__ import annotations

import math

import numpy as np

from link import protocol as P
from .ground import GroundView
from .planner import apply_look
from .simdrones import SimDrone

ROVER_ID0 = 10                         # rover k is node id 10 + k (R1 = 11), drones are 1..9
CLOSE_S = 90.0                         # the rover takes a contact itself if it can be there this fast


def rover_ids(n):
    return [ROVER_ID0 + k for k in range(1, n + 1)]


def label(node_id):
    return f"R{node_id - ROVER_ID0}" if node_id > ROVER_ID0 else f"D{node_id}"


class SimRover(SimDrone):
    kind = "ground"

    def __init__(self, *args, ground=None, **kw):
        super().__init__(*args, **kw)
        self.ground = ground                       # GroundView of the TRUE world
        self.mmwave_alt = 99.0                     # on the ground: radar always low enough

    def _fly_toward(self, tx, ty, tz, dt):
        goal = np.array([tx, ty]) - self.offset
        delta = goal - self.true[:2]
        dist = float(np.hypot(*delta))
        cell = self.grid.to_cell(*self.true[:2])
        v = self.ground.speed_at(cell) if self.ground.free(cell) else 0.3
        step = min(dist, max(v, 0.3) * dt)
        moved = 0.0
        if step > 1e-6:
            d = delta / dist * step
            for cand in (d, np.array([d[0], 0.0]), np.array([0.0, d[1]])):
                new = self.true[:2] + cand
                if self.ground.free(self.grid.to_cell(*new)):
                    self.true[:2] = new
                    moved = float(np.hypot(*cand))
                    break
        self.true[2] = 0.0
        return moved

    def _vis(self):
        return self.ground.vis


class RoverBrain:
    def __init__(self, hub, speed_mps):
        self.hub = hub
        self.ground = GroundView(hub.world, speed_mps)
        self.home_field = self.ground.field(self.ground.snap(hub.home))
        self.plan = {}                              # rover id -> remaining path cells

    def cell_of(self, d):
        return self.ground.snap(self.hub.grid.to_cell(d.x, d.y))

    def look(self, d, cell):
        apply_look(self.ground, self.hub.mass, cell, d.sensors, d.sigma / self.ground.cell_m)

    def step(self, rovers, now):
        hub = self.hub
        for d in rovers:
            here = self.cell_of(d)
            d.cell = here
            if hub.recalled and not hub.complete:
                if d.task == "confirm":
                    hub._release_confirm(d)
                d.task = "rtb"
            if hub.complete:
                self._stay(d, here, now)
                continue
            if d.task == "confirm":
                self._confirm(d, here, now)
            if d.task not in ("confirm", "rtb"):
                tr = self._pick_contact(d, here)
                if tr is not None:
                    d.task, d.confirm_track, d.hold_until = "confirm", tr.id, None
                    self.plan.pop(d.id, None)
                    hub._event(now, "rover_check", drone=d.id, track=tr.id, status=tr.status,
                               eta_s=round(self.ground.path_time(here, tr.cell)))
                    self._confirm(d, here, now)
                else:
                    d.task = "search"
                    self._search(d, here, now)
            if d.task == "rtb":
                self._rtb(d, here)

    # ---------------------------------------------------------- vitals check
    def _pick_contact(self, d, here):
        hub = self.hub
        busy = {v.confirm_track for v in hub.drones.values() if v.confirm_track is not None}
        todo = [t for t in hub.tracks if not t.assessed and not getattr(t, "ground_checked", False)
                and t.id not in busy]
        radar_drones = any(v.kind == "air" and "mmwave" in v.sensors and v.state in (1, 2, 3, 4)
                           for v in hub.drones.values())
        best, bt = None, math.inf
        for t in todo:
            eta = self.ground.path_time(here, self.ground.snap(t.cell))
            # a radar drone gets there far faster, so it goes first. The rover takes a contact
            # when it is close anyway, when no drone has radar, or when a drone tried and the
            # trees beat its radar (checked, but no vitals)
            if radar_drones and not t.checked and eta > CLOSE_S:
                continue
            if eta < bt:
                best, bt = t, eta
        return best if bt < math.inf else None

    def _stay(self, d, here, now):
        """Mission complete: park next to the most urgent casualty and stay there,
        so the rescue team can find them (and the rover can keep reading vitals)."""
        hub = self.hub
        cas = [t for t in hub.casualties() if t.confirmed]
        if not cas:
            d.task = "rtb"
            self._rtb(d, here)
            return
        tr = cas[0]
        if d.task != "stay" or d.confirm_track != tr.id:
            d.task, d.confirm_track = "stay", tr.id
            self.plan.pop(d.id, None)
            # the closest spot to them the rover can actually drive to (they may be past a stream)
            t = self.ground.field(here)
            ok = np.argwhere(np.isfinite(t))
            k = int(np.argmin(np.abs(ok[:, 0] - tr.cell[0]) + np.abs(ok[:, 1] - tr.cell[1])))
            self.stay_at = {**getattr(self, "stay_at", {}), d.id: (int(ok[k][0]), int(ok[k][1]))}
            hub._event(now, "rover_stay", drone=d.id, track=tr.id, status=tr.status)
        goal = self.stay_at[d.id]
        if here == goal or math.hypot(d.x - tr.x, d.y - tr.y) <= hub.world.cell_m:
            near = math.hypot(d.x - tr.x, d.y - tr.y) <= hub.world.cell_m
            d.target, d.target_xy = here, ((tr.x, tr.y) if near else None)
            d.cmd, d.z_cmd = P.CMD_HOLD, 0.0
            return
        if d.cmd == P.CMD_HOLD:
            d.target = None
        if d.target is not None and d.cmd == P.CMD_GOTO and not self._at(d, d.target):
            return
        path = self.ground.path(here, goal)
        if path:
            self._goto(d, path[0])

    def _confirm(self, d, here, now):
        hub = self.hub
        tr = next((t for t in hub.tracks if t.id == d.confirm_track), None)
        if tr is None or tr.assessed:
            if tr is not None:
                tr.ground_checked = True
            hub._release_confirm(d)
            d.task, d.target = "search", None
            return
        dist = math.hypot(d.x - tr.x, d.y - tr.y)
        if dist <= hub.world.cell_m:                # next to it: stop by the person, radar on
            d.target, d.target_xy, d.cmd, d.z_cmd = here, (tr.x, tr.y), P.CMD_HOLD, 0.0
            if d.hold_until is None:
                vis = self.ground.vis[tr.cell] if self.ground.vis is not None else 1.0
                d.hold_until = now + 25.0 + hub.cfg.hold_s / max(vis, 0.4)
            if now >= d.hold_until:
                tr.ground_checked = True
                hub._event(now, "vitals_none", drone=d.id, track=tr.id, by="rover",
                           note="rover stopped next to it, radar saw no vitals")
                hub._release_confirm(d)
                d.task, d.target = "search", None
            return
        self._drive_to(d, here, self.ground.snap(tr.cell))

    # ---------------------------------------------------------- search
    def _search(self, d, here, now):
        if d.target is not None and d.cmd == P.CMD_GOTO and not self._at(d, d.target):
            return
        path = self.plan.get(d.id)
        if path:
            self._goto(d, path.pop(0))
            return
        g, mass = self.ground, self.hub.mass
        seen = mass * (g.vis if g.vis is not None else 1.0)
        pad = np.pad(seen, 1)
        box = sum(pad[1 + di:1 + di + g.n, 1 + dj:1 + dj + g.n] for di in (-1, 0, 1) for dj in (-1, 0, 1))
        t = g.field(here)
        score = np.where(np.isfinite(t) & ~g.obstacles, box / (t + 4 * g.cell_m / g.speed), -1.0)
        score[here] = -1.0
        target = tuple(int(v) for v in np.unravel_index(int(np.argmax(score)), score.shape))
        path = g.path(here, target) or []
        if path:
            self._goto(d, path.pop(0))
            self.plan[d.id] = path

    # ---------------------------------------------------------- driving
    def _drive_to(self, d, here, goal):
        if d.target is not None and d.cmd == P.CMD_GOTO and not self._at(d, d.target):
            return
        path = self.ground.path(here, goal)
        if not path:
            if path is None:                       # can't get there by ground
                tr = next((t for t in self.hub.tracks if t.id == d.confirm_track), None)
                if tr is not None:
                    tr.ground_checked = True
                self.hub._release_confirm(d)
                d.task, d.target = "search", None
            return
        self._goto(d, path[0])

    def _goto(self, d, cell):
        d.target, d.target_xy, d.cmd, d.z_cmd = cell, None, P.CMD_GOTO, 0.0
        d.goal = cell

    def _at(self, d, cell):
        x, y = self.hub.grid.to_xy(cell)
        return math.hypot(d.x - x, d.y - y) <= 0.35 * self.hub.world.cell_m

    def _rtb(self, d, here):
        self.plan.pop(d.id, None)
        home = self.ground.snap(self.hub.home)
        if here == home:
            d.target, d.target_xy, d.cmd, d.z_cmd = home, None, P.CMD_LAND, 0.0
            return
        if d.target is None or d.cmd != P.CMD_GOTO or self._at(d, d.target):
            best, bv = here, self.home_field[here]
            for nc in self.ground.neighbours(here):
                if self.home_field[nc] < bv:
                    best, bv = nc, self.home_field[nc]
            self._goto(d, best)

"""GND-1: simulated RoverC-Pro running the team's real navigation stack.

Reused unchanged:
    rover.navigator.Navigator     PLAN_ROUTE -> ... -> OBSTACLE_DETECTED -> STOP -> VERIFY -> MARK_EDGE_BLOCKED
                                  -> SCAN_DIRECTIONS -> REPLAN -> VERIFY_DETOUR -> ... -> ARRIVED | SAFE_STOP
    rover/motion.py safety supervisor: watchdog, range-gated forward motion, latched safety stops (wired by
                                  rover.simrun.build_for_world; this module never names it)
    rover.observations.ObservationLog   timestamped, source-labelled obstacle evidence
    planner.route.compute_route   Dijkstra (called by the Navigator)
    rover.sim.SimWorld / SimDriver / rover.simrun.SimIO   simulated ultrasonic, camera, heading, physics

New (simulation-only, this file):
    * The Navigator's graph is a KNOWLEDGE graph: it holds only corridors the shared mission map has
      observed CLEAR (or an operator approved for a sensor-gated probe). UNKNOWN is never routed as CLEAR.
    * CoopNavigator: after the real obstacle scan, if no KNOWN route exists from the last node, the rover
      stays stopped and asks the coordinator for aerial observation (bounded wait) before the Navigator's
      own replan runs. On timeout the Navigator's own SAFE_STOP "no verified route" applies.
    * A mission-link watchdog: no coordinator heartbeat for LINK_TIMEOUT_S latches the supervisor's
      existing COMMS_LOST stop.

Physical safety: SimDriver.physical is False; Navigator refuses auto-approval with a physical driver.
No motor, serial, GPIO or radio module is imported here.
"""
from __future__ import annotations

from typing import Callable, Optional

from planner.graph import TrailGraph
from planner.route import OK, compute_route
from rover.navigator import Navigator, SafetyStop, State
from rover.observations import canonical_edge
from rover.sim import SimConfig, SimObstacle, SimWorld
from rover.simrun import build_for_world

from simulation.dual_rescue.world import GroundTruth, edge_key, point_on_edge

LINK_TIMEOUT_S = 2.0
SENSING_WAIT_S = 120.0
DATA_LABEL = "SIMULATED ROVER OBSERVATION"


class CoopNavigator(Navigator):
    """rover.navigator.Navigator plus a bounded 'wait for aerial observation' hold. Nothing else changes."""

    on_need_sensing: Optional[Callable[[str, str, str], str]] = None
    stale_edges: Optional[Callable[[], list]] = None
    sensing_wait_s: float = SENSING_WAIT_S
    waiting_for_sensing: Optional[dict] = None

    def _plan(self, start: str):
        """Navigator._plan, plus: corridors whose observation is STALE are excluded from NEW routes."""
        stale = self.stale_edges() if self.stale_edges is not None else []
        return compute_route(start, self.dest, blocked=list(self.log.blocked_edges()) + list(stale), graph=self.g)

    def _obstacle(self, u: str, v: str):
        self._obstacle_edge = (u, v)
        try:
            return (yield from super()._obstacle(u, v))
        finally:
            self._obstacle_edge = None

    def _directional_scan(self, back_required_m: float, trigger: str):
        scan = yield from super()._directional_scan(back_required_m, trigger)
        edge = getattr(self, "_obstacle_edge", None)
        if scan is None or edge is None or self.on_need_sensing is None:
            return scan
        u = edge[0]
        if self._plan(u).status == OK:
            return scan
        ref = self.on_need_sensing(u, self.dest, canonical_edge(edge))
        if ref.startswith("none"):
            return scan                      # no aerial option: the Navigator's own SAFE_STOP applies
        t0 = self.io.clock()
        self.waiting_for_sensing = {"from_node": u, "dest": self.dest, "since": t0, "request": ref}
        self._set(State.STOP, f"stopped: no KNOWN-clear route from {u} to {self.dest}; "
                              f"waiting for aerial observation ({ref})")
        try:
            while self._plan(u).status != OK and self.io.clock() - t0 < self.sensing_wait_s:
                yield
        finally:
            self.waiting_for_sensing = None
        return scan


class GroundRover:
    agent_id = "GND-1"

    def __init__(self, full_graph: TrailGraph, xy: dict, truth: GroundTruth, start: str = "BASE"):
        self.xy = xy
        self.truth = truth
        # knowledge graph: every node, no corridor until it is observed CLEAR
        self.nav_graph = TrailGraph(nodes=list(full_graph.nodes), adjacency={n: {} for n in full_graph.nodes})
        self.full = full_graph
        self.obstacles: dict[str, SimObstacle] = {}
        for did, d in truth.debris.items():
            if d.appears == "on_route":          # placed by the mission when it drops
                continue
            self.obstacles[did] = SimObstacle(did, d.a, d.b, d.at_m, half_width_m=0.4, present=truth.present[did])
        for sid, s in truth.survivors.items():
            r = truth.rooms[s.room]
            self.obstacles[f"person-{sid}"] = SimObstacle(f"person-{sid}", r.node, r.room_id, s.at_m,
                                                          half_width_m=0.3, kind="person")
        half = truth.sc.layout.corridor_half_m
        side = {(a, b): (half, half) for a, b, _m in full_graph.edges()}
        self.world = SimWorld(full_graph, start, obstacles=list(self.obstacles.values()), config=SimConfig(),
                              xy=xy, side_clearance=side)
        # rover.simrun.build_for_world wires SimDriver + e-stop + supervisor + ObservationLog + this Navigator
        sim = build_for_world(self.world, self.nav_graph, nav_cls=CoopNavigator)
        self.driver, self.estop, self.sup, self.log, self.nav = sim.driver, sim.estop, sim.supervisor, sim.log, sim.nav
        assert self.driver.physical is False
        self.last_link_t = 0.0
        self.link_lost = False
        self.path: list[tuple[float, float, float]] = [(0.0, *xy[start])]
        self.probe_edges: set[str] = set()
        self.frozen: Optional[set] = None
        # safety accounting (benchmark): read from the simulator, never used for decisions
        self.collisions: list[dict] = []
        self.unknown_entries: list[dict] = []
        self.latched_motion_ticks = 0
        self._last_edge = self.world.edge

    # --- knowledge ----------------------------------------------------------------------------
    def freeze(self, allowed: set) -> None:
        """static_route baseline: from now on only these corridors may be known."""
        self.frozen = set(allowed)
        for a in list(self.nav_graph.adjacency):
            for b in list(self.nav_graph.adjacency[a]):
                if edge_key(a, b) not in self.frozen:
                    del self.nav_graph.adjacency[a][b]

    def know_edge(self, a: str, b: str) -> bool:
        if b in self.nav_graph.adjacency[a]:
            return False
        if self.frozen is not None and edge_key(a, b) not in self.frozen:
            return False
        m = self.full.neighbors(a)[b]
        self.nav_graph.adjacency[a][b] = m
        self.nav_graph.adjacency[b][a] = m
        return True

    def has_edge(self, a: str, b: str) -> bool:
        return b in self.nav_graph.adjacency.get(a, {})

    # --- simulation ---------------------------------------------------------------------------
    def drop_debris(self, did: str) -> None:
        self.obstacles[did].present = True

    def add_debris(self, did: str, a: str, b: str, at_m: float) -> None:
        o = SimObstacle(did, a, b, at_m, half_width_m=0.4, present=True)
        self.obstacles[did] = o
        self.world.obstacles.append(o)

    def xy_now(self) -> tuple[float, float]:
        a, b = self.world.edge
        if a == b:
            return self.xy[a]
        return point_on_edge(self.xy, a, b, self.world.s)

    def step(self, link_ok: bool) -> None:
        t = self.world.t
        if link_ok:
            self.last_link_t = t
        elif t - self.last_link_t > LINK_TIMEOUT_S and self.sup.latched is None:
            self.link_lost = True
            self.sup.trip_safety(SafetyStop.COMMS_LOST,
                                 f"mission link to coordinator silent for {t - self.last_link_t:.1f} s (SIMULATED fault)")
        self.nav.tick()
        if self.sup.latched is not None and not self.driver.velocity.is_zero():
            self.latched_motion_ticks += 1
        before = self.world.collision
        self.world.step(self.driver.velocity)
        if self.world.collision is not None and self.world.collision != before:
            self.collisions.append({"t": round(self.world.t, 2), "obstacle": self.world.collision})
        if self.world.edge != self._last_edge and self.world.edge[0] != self.world.edge[1]:
            a, b = self.world.edge
            if not self.has_edge(a, b):
                self.unknown_entries.append({"t": round(self.world.t, 2), "edge": edge_key(a, b)})
            self._last_edge = self.world.edge
        x, y = self.xy_now()
        lx, ly = self.path[-1][1:]
        if abs(x - lx) + abs(y - ly) >= 0.5:
            self.path.append((round(self.world.t, 2), round(x, 2), round(y, 2)))

    def status(self) -> dict:
        x, y = self.xy_now()
        n = self.nav
        r = n.route
        return {"agent": self.agent_id, "data_label": DATA_LABEL, "x": round(x, 2), "y": round(y, 2),
                "heading_deg": round(self.world.heading, 1), "state": n.state.value, "detail": n.state_detail,
                "destination": n.dest, "running": n.running,
                "route": None if r is None else {"status": r.status, "path": r.path, "length_m": r.length_m,
                                                 "reason": r.reason},
                "route_leg": n.route_leg, "reroutes": n.reroutes, "blocked_edges": self.log.blocked_edges(),
                "pending_requests": [q for q in n.operator_requests if q["state"] == "PENDING"],
                "safe_stop_reason": n.safe_stop_reason or None,
                "latched": None if self.sup.latched is None else self.sup.latched.value,
                "latch_detail": self.sup.latch_detail or None,
                "waiting_for_sensing": n.waiting_for_sensing,
                "odometer_m": round(self.world.odometer_m, 2),
                "latest_range": n.latest_range.to_dict() if n.latest_range else None,
                "collision": self.world.collision, "lost": self.world.lost,
                "physical_driver": self.driver.physical, "link_lost": self.link_lost,
                "probe_edges": sorted(self.probe_edges)}

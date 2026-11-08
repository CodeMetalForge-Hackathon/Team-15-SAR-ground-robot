"""Mission coordinator: shared mission map, aerial -> ground handoff, deterministic target ranking.

Shared knowledge exists only after an observation exchange over a (simulated) link:
    drone outbox  --link-->  coordinator  --> corridor states, survivor candidates
    rover ObservationLog --link--> coordinator --> BLOCKED corridors, traversed corridors

Routing policy (deterministic, no language model involved):
    * The rover's Navigator plans only over corridors the shared map holds as CLEAR (observed from the
      air), TRAVERSED (driven by the rover) or PROBE_APPROVED (operator-approved, sensor-gated).
      UNKNOWN, OCCLUDED and STALE are never treated as CLEAR.
    * Optional freshness (``Scenario.fresh_s``): a corridor observation older than that is STALE; a new
      route (dispatch or replan) may not use it until it is observed again.
    * Before dispatch the coordinator takes the shortest floor-plan path (excluding BLOCKED and OCCLUDED
      corridors) and tasks the drone to observe its UNKNOWN or STALE corridors.
    * When the rover's own sensors block its route, the drone is tasked to re-check the block (aerial
      corroboration). If no KNOWN detour exists the rover stays stopped while the drone observes one.
    * If no route avoids OCCLUDED corridors: INSUFFICIENT_INFORMATION. The rover pre-positions at the
      closest KNOWN-reachable node and the operator is asked for more sensing or a sensor-gated probe.

Target ranking (explicit tuple, lowest first):
    (condition rank, known-route flag, route length m, -confidence, candidate id)
    condition rank: LYING_DOWN 0 < NOT_MOVING 1 < UNKNOWN 2 < MOVING 3  (PR #17 priority order)

Modes (benchmark baselines; same environments and seeds):
    coordinated   the policy above
    independent   the rover only receives survivor targets; corridor knowledge is not shared, so every
                  floor-plan corridor is a sensor-gated probe and the drone never scouts for the rover
    static_route  coordinated dispatch, but the rover may not replan: only its dispatched route is known
"""
from __future__ import annotations

import math
from typing import Optional

from planner.graph import TrailGraph
from planner.route import OK, compute_route
from rover.navigator import State
from rover.observations import CONFIRMED, UNCONFIRMED

from simulation.dual_rescue.world import Scenario, edge_key, in_site

CONDITION_RANK = {"LYING_DOWN": 0, "NOT_MOVING": 1, "UNKNOWN": 2, "MOVING": 3}
DISPATCH_CONFIDENCE = 0.80
ROOM_ASSOC_M = 4.0
OPERATOR = "sim-operator"
ROUTABLE = ("CLEAR", "TRAVERSED", "PROBE_APPROVED")
AGENT_TIMEOUT_S = 10.0
REFRESH_MARGIN_S = 30.0
MAX_RESUMES = 3                # incidental sightings acknowledged per target before an operator is needed        # with freshness, also re-observe corridors that will go STALE this soon
MAX_DETOUR_TASKS = 3
SCOUT_TIMEOUT_S = 150.0
MODES = ("coordinated", "independent", "static_route")


class Coordinator:
    agent_id = "COORD"

    def __init__(self, sc: Scenario, full: TrailGraph, xy: dict, drone, rover, clock, mode: str = "coordinated"):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.sc = sc
        self.mode = mode
        self.full = full
        self.xy = xy
        self.rooms = sc.layout.rooms
        self.drone = drone
        self.rover = rover
        self.clock = clock
        self.fresh_s = sc.fresh_s
        self.link_delay_s = float(sc.faults.get("link_delay_s", 0.0))
        self.edges = {edge_key(a, b): {"edge": edge_key(a, b), "a": a, "b": b, "status": "UNKNOWN",
                                       "source": None, "obs_id": None, "t": None}
                      for a, b, _m in full.edges()}
        self.shared_obs: list[dict] = []
        self.messages: list[dict] = []
        self.candidates: dict[str, dict] = {}
        self.targets: dict[str, dict] = {}
        self.active: Optional[str] = None
        self.phase = "AERIAL_SURVEY"
        self.phase_detail = "drone launching"
        self.drone_link = True
        self.rover_link = True
        self.drone_lost = False
        self.scouts: dict[str, dict] = {}
        self._task_ids = 0
        self.ranking: list[dict] = []
        self._rover_obs_seen = 0
        self._rover_last_state = None
        self._rover_last_node = rover.world.node()
        self.first_candidate_t: Optional[float] = None
        self.operator_requests: list[dict] = []
        self.insufficient: Optional[dict] = None
        self.drone_buffered = 0
        self.rejected: list[dict] = []
        self.conflicts = 0
        self.complete = False
        self._detour: Optional[tuple] = None
        self._detour_tasks = 0
        self._reroutes_seen = 0
        self._approach_scouted: set = set()
        rover.nav.on_need_sensing = self._rover_needs_sensing if mode == "coordinated" else None
        rover.nav.stale_edges = self.stale_edges
        rover.nav.no_replan = mode == "static_route"
        if mode == "independent":
            for a, b, _m in full.edges():
                rover.know_edge(a, b)
                rover.probe_edges.add(edge_key(a, b))
                self.edges[edge_key(a, b)].update(status="PROBE_APPROVED", source="baseline:independent")

    # --- messaging ------------------------------------------------------------------------------
    def msg(self, frm: str, to: str, kind: str, text: str, refs=()) -> dict:
        m = {"t": round(self.clock(), 2), "from": frm, "to": to, "type": kind, "text": text,
             "refs": [r for r in refs if r]}
        self.messages.append(m)
        return m

    def _next_task_id(self) -> str:
        self._task_ids += 1
        return f"task-{self._task_ids:03d}"

    # --- shared map -----------------------------------------------------------------------------
    def _set_edge(self, ek: str, status: str, source: str, obs_id: Optional[str]) -> bool:
        e = self.edges[ek]
        now = round(self.clock(), 2)
        if e["status"] == status:
            e.update(source=source, obs_id=obs_id or e["obs_id"], t=now)   # refresh: same state, newer evidence
            return False
        if e["status"] == "BLOCKED" and status in ("CLEAR", "OCCLUDED", "TRAVERSED", "RECHECK"):
            # clearing a block needs independent evidence and a named operator (rover.observations rule)
            self.conflicts += 1
            self.msg("COORD", "OPERATOR", "CONFLICT",
                     f"{source} reports {ek} {status} but it is BLOCKED by {e['source']} ({e['obs_id']}); "
                     f"kept BLOCKED until an operator clears it", [obs_id, e["obs_id"]])
            return False
        if e["status"] in ROUTABLE and status == "OCCLUDED":
            return False
        e.update(status=status, source=source, obs_id=obs_id, t=now)
        if status in ("CLEAR", "TRAVERSED"):
            self.rover.know_edge(e["a"], e["b"])
        return True

    def fresh(self, ek: str) -> bool:
        e = self.edges[ek]
        if e["status"] not in ROUTABLE:
            return False
        if self.fresh_s is None or e["status"] == "PROBE_APPROVED" or e["t"] is None:
            return True
        return self.clock() - e["t"] <= self.fresh_s

    def stale_edges(self) -> list[str]:
        if self.fresh_s is None:
            return []
        return sorted(k for k, e in self.edges.items() if e["status"] in ROUTABLE and not self.fresh(k))

    def routable(self, ek: str) -> bool:
        e = self.edges[ek]
        return self.rover.has_edge(e["a"], e["b"]) and self.fresh(ek)

    def blocked(self) -> list[str]:
        return sorted(set(self.rover.log.blocked_edges()) |
                      {k for k, e in self.edges.items() if e["status"] == "BLOCKED"})

    def _valid(self, o: dict) -> str:
        if not isinstance(o, dict) or "obs_id" not in o or "kind" not in o:
            return "malformed observation"
        xy = o.get("xy")
        if xy is not None and (not isinstance(xy, (list, tuple)) or len(xy) != 2 or not in_site(*xy)):
            return f"coordinates {xy} outside the SITE frame [0, 48] m"
        if "edge" in o and o["edge"] not in self.edges:
            return f"unknown corridor {o['edge']}"
        c = o.get("confidence")
        if c is not None and not (isinstance(c, (int, float)) and 0.0 <= c <= 1.0):
            return f"confidence {c} outside [0, 1]"
        return ""

    def _ingest_air(self, o: dict) -> None:
        why = self._valid(o)
        if why:
            self.rejected.append({"obs": o.get("obs_id"), "why": why, "t": round(self.clock(), 2)})
            self.msg("COORD", "AIR-1", "REJECTED", f"{o.get('obs_id')}: {why}; not added to the mission map",
                     [o.get("obs_id")])
            return
        o = dict(o, received_t=round(self.clock(), 2))
        self.shared_obs.append(o)
        k = o["kind"]
        share_corridors = self.mode != "independent"
        if k == "corridor_state" and share_corridors:
            if o["status"] == "RECHECK":
                return
            changed = self._set_edge(o["edge"], o["status"], "AIR-1", o["obs_id"])
            self.msg("AIR-1", "COORD", "CORRIDOR", f"corridor {o['edge']} {o['status']} "
                     f"({int(o['seen_fraction'] * 100)}% of floor seen){'' if changed else ' (refresh)'}",
                     [o["obs_id"]])
        elif k == "debris" and share_corridors:
            ek = o["edge"]
            self._set_edge(ek, "BLOCKED", "AIR-1", o["obs_id"])
            self.msg("AIR-1", "COORD", "DEBRIS", f"debris on {ek} at ({o['xy'][0]:.1f}, {o['xy'][1]:.1f}) m",
                     [o["obs_id"]])
            e = self.edges[ek]
            if ek not in self.rover.log.blocked_edges() and self.rover.has_edge(e["a"], e["b"]):
                rec = self.rover.log.add("aerial_debris", "sim-aerial-thermal", UNCONFIRMED, dynamic=False,
                                         edge=ek, detail={"air_obs": o["obs_id"], "xy": o["xy"]})
                self.rover.log.review(rec.obs_id, OPERATOR, True,
                                      note=f"auto-review in SIMULATION of aerial debris {o['obs_id']}")
        elif k == "survivor_candidate":
            c = self.candidates.get(o["cand_id"], {})
            c.update({kk: o[kk] for kk in ("cand_id", "xy", "status", "confidence", "motion") if kk in o})
            c.setdefault("obs_ids", []).append(o["obs_id"])
            c["room"] = self._room_for(o["xy"])
            c["t"] = o["t"]
            self.candidates[o["cand_id"]] = c
            if self.first_candidate_t is None:
                self.first_candidate_t = self.clock()
            room = c["room"] or f"no mapped room within {ROOM_ASSOC_M:.0f} m"
            self.msg("AIR-1", "COORD", "SURVIVOR", f"{o['status']} survivor {o['cand_id']} at "
                     f"({o['xy'][0]:.0f}, {o['xy'][1]:.0f}) m, confidence {o['confidence']:.2f}, motion "
                     f"{o.get('motion', 'UNKNOWN')}; nearest room {room}", [o["obs_id"]])
        elif k == "task_done":
            sc = self.scouts.get(o["task_id"])
            if sc is not None:
                sc["done"] = True
                sc["result"] = o["result"]
            self.msg("AIR-1", "COORD", "TASK_DONE", f"{o['task_type']} {o['task_id']} done: {o['result']}",
                     [o["obs_id"]])
        elif k == "search_complete":
            self.msg("AIR-1", "COORD", "SEARCH", f"sector search complete ({o['detail']})", [o["obs_id"]])

    def _room_for(self, xy) -> Optional[str]:
        best, bd = None, ROOM_ASSOC_M
        for r in self.rooms.values():
            (ax, ay), (bx, by) = self.xy[r.node], self.xy[r.room_id]
            L2 = (bx - ax) ** 2 + (by - ay) ** 2
            f = max(0.0, min(1.0, ((xy[0] - ax) * (bx - ax) + (xy[1] - ay) * (by - ay)) / L2))
            d = math.dist(xy, (ax + f * (bx - ax), ay + f * (by - ay)))
            if d <= bd:
                best, bd = r.room_id, d
        return best

    def _ingest_rover(self) -> None:
        rv = self.rover
        for o in rv.log.items[self._rover_obs_seen:]:
            d = o.to_dict(self.clock(), rv.log.recheck_after_s)
            d.update(agent="GND-1", data_label="SIMULATED ROVER OBSERVATION", received_t=round(self.clock(), 2))
            self.shared_obs.append(d)
            if o.kind == "ultrasonic_obstacle" and o.status == CONFIRMED and o.edge:
                self._set_edge(o.edge, "BLOCKED", "GND-1", o.obs_id)
                self.msg("GND-1", "COORD", "OBSTACLE", f"ultrasonic: obstacle on {o.edge} at "
                         f"{o.detail.get('at_m')} m from {o.detail.get('at_m_from')}; edge BLOCKED "
                         f"(3 consistent readings)", [o.obs_id])
                if self.mode == "coordinated" and not self.drone_lost:
                    self.request_scout([], f"aerial re-check of the rover's block on {o.edge}", recheck=[o.edge])
            elif o.kind == "ultrasonic_obstacle":
                self.msg("GND-1", "COORD", "OBSTACLE", f"ultrasonic: {o.status} obstacle evidence "
                         f"({o.detail.get('why') or o.detail.get('why_not_marked')})", [o.obs_id])
            elif o.kind == "camera_person":
                self.msg("GND-1", "COORD", "PERSON", f"rover camera (SIMULATED): person ahead on {o.edge}, "
                         f"UNCONFIRMED; human review requested", [o.obs_id])
        self._rover_obs_seen = len(rv.log.items)
        node = rv.world.node()
        if node is not None and node != self._rover_last_node:
            prev = self._rover_last_node
            if prev is not None and node in self.full.neighbors(prev):
                ek = edge_key(prev, node)
                if ek not in rv.log.blocked_edges():
                    self._set_edge(ek, "TRAVERSED", "GND-1", None)
                self.msg("GND-1", "COORD", "PROGRESS", f"reached {node} (corridor {ek} traversed)")
            self._rover_last_node = node
        for rr in rv.nav.reroutes[self._reroutes_seen:]:
            self.msg("GND-1", "COORD", "REROUTE", f"Navigator replanned around {rr['blocked_edge']}: "
                     f"{'-'.join(rr['old_route'] or [])} ({rr['old_length_m']} m) -> {'-'.join(rr['new_route'])} "
                     f"({rr['new_length_m']} m) after a {rr['retreat_m']:.1f} m verified retreat", [rr["obs_id"]])
        self._reroutes_seen = len(rv.nav.reroutes)
        st = rv.nav.state
        if st != self._rover_last_state and st not in (State.TURN_TO_HEADING, State.CHECK_SENSORS,
                                                       State.ADVANCE_IF_SAFE):
            self.msg("GND-1", "COORD", "STATE", f"{st.value}: {rv.nav.state_detail}")
        self._rover_last_state = st

    # --- planning helpers -------------------------------------------------------------------------
    def rover_node(self) -> Optional[str]:
        return self.rover.world.node()

    def known_route(self, frm: str, to: str):
        bad = set(self.rover.log.blocked_edges()) | set(self.stale_edges())
        return compute_route(frm, to, blocked=bad, graph=self.rover.nav_graph)

    def floor_route(self, frm: str, to: str, exclude_occluded: bool = True):
        bad = set(self.blocked())
        if exclude_occluded:
            bad |= {k for k, e in self.edges.items() if e["status"] == "OCCLUDED" and not self.routable(k)}
        return compute_route(frm, to, blocked=bad, graph=self.full)

    def unknown_on(self, path: list[str], refresh_margin_s: float = 0.0) -> list[str]:
        """Corridors on ``path`` that need observing: not routable, or (with freshness) about to go STALE."""
        out = []
        for a, b in zip(path, path[1:]):
            ek = edge_key(a, b)
            e = self.edges[ek]
            soon = (self.fresh_s is not None and e["status"] in ("CLEAR", "TRAVERSED") and e["t"] is not None
                    and self.clock() - e["t"] > self.fresh_s - refresh_margin_s)
            if not self.routable(ek) or soon:
                out.append(ek)
        return out

    def request_scout(self, edges: list[str], reason: str, recheck=()) -> str:
        if self.drone_lost:
            self.msg("COORD", "AIR-1", "NO_TASK", f"AIR-1 unavailable; cannot task ({reason})")
            return "none: AIR-1 unavailable"
        stale = [e for e in edges if self.edges[e]["status"] in ROUTABLE]       # stale: observe again
        rc = list(dict.fromkeys(list(recheck) + stale))
        tid = self._next_task_id()
        task = {"type": "SCOUT", "task_id": tid, "edges": list(dict.fromkeys(list(edges) + rc)),
                "recheck": rc, "reason": reason}
        self.scouts[tid] = dict(task, done=False, t=round(self.clock(), 2))
        if self.drone_link:
            self.drone.assign(dict(task))
        else:
            self.scouts[tid]["undelivered"] = True
        self.msg("COORD", "AIR-1", "TASK", f"{tid}: observe corridors {', '.join(task['edges'])} ({reason})")
        return tid

    def scouting(self) -> bool:
        return any(not s["done"] for s in self.scouts.values())

    def _rover_needs_sensing(self, u: str, dest: str, blocked_edge: str) -> str:
        self.msg("GND-1", "COORD", "REQUEST_SENSING",
                 f"stopped at {blocked_edge}; no KNOWN-clear (fresh) route from {u} to {dest}")
        res = self.floor_route(u, dest)
        if res.status != OK:
            self.msg("COORD", "GND-1", "NO_OPTION", f"no floor-plan route from {u} to {dest} avoids BLOCKED/OCCLUDED "
                     f"corridors; aerial observation cannot help")
            return "none: no floor-plan detour"
        self._detour = (u, dest, blocked_edge)
        return self.request_scout(self.unknown_on(res.path, REFRESH_MARGIN_S), f"detour for GND-1 around {blocked_edge}")

    def rank(self) -> list[dict]:
        node = self.rover_node()
        rows = []
        for cid, c in self.candidates.items():
            if cid in self.targets or c.get("status") != "LIKELY" or not c.get("room"):
                continue
            r = self.known_route(node, c["room"]) if node else None
            known = r is not None and r.status == OK
            f = self.floor_route(node, c["room"], exclude_occluded=False) if node else None
            dist = r.length_m if known else (f.length_m if f is not None and f.status == OK else None)
            key = (CONDITION_RANK.get(c.get("motion", "UNKNOWN"), 2), 0 if known else 1,
                   math.inf if dist is None else dist, -c["confidence"], cid)
            rows.append({"cand_id": cid, "room": c["room"], "motion": c.get("motion"), "confidence": c["confidence"],
                         "known_route": known, "route_m": dist, "obs_ids": c["obs_ids"], "_key": key,
                         "key": [key[0], key[1], dist, key[3], key[4]]})
        rows.sort(key=lambda r: r["_key"])
        for i, r in enumerate(rows):
            r.pop("_key")
            r["rank"] = i + 1
            d = f" {r['route_m']:.1f} m" if r["route_m"] is not None else ""
            r["why"] = (f"#{i + 1}: condition {r['motion']} (rank {r['key'][0]}), "
                        f"{'KNOWN route' if r['known_route'] else 'no known route yet'}{d}, "
                        f"confidence {r['confidence']:.2f}")
        return rows

    # --- decisions ------------------------------------------------------------------------------
    def _dispatch(self, cid: str, dest: str, kind: str, route) -> None:
        nav = self.rover.nav
        nav.start(dest)
        self.active = cid
        self.targets[cid] = {"cand_id": cid, "dest": dest, "status": kind, "t_assigned": round(self.clock(), 2),
                             "route_m": route.length_m, "path": route.path}
        self.msg("COORD", "GND-1", "ASSIGN", f"{kind} {cid}: go to {dest} via {'-'.join(route.path)} "
                 f"({route.length_m:.1f} m on KNOWN corridors)", self.candidates.get(cid, {}).get("obs_ids", [])[-1:])

    def approve_probe(self, req_id: str, operator: str) -> dict:
        if not operator.strip():
            raise PermissionError("needs a named operator")
        req = next((r for r in self.operator_requests if r["id"] == req_id and r["state"] == "PENDING"), None)
        if req is None:
            raise KeyError(req_id)
        req.update(state="APPROVED", by=operator, t_resolved=round(self.clock(), 2))
        for ek in req["edges"]:
            e = self.edges[ek]
            self.rover.know_edge(e["a"], e["b"])
            self.rover.probe_edges.add(ek)
            e.update(status="PROBE_APPROVED", source=f"operator:{operator}", t=round(self.clock(), 2))
        self.msg("OPERATOR", "COORD", "APPROVE_PROBE", f"{operator} approved a sensor-gated ground probe of "
                 f"{', '.join(req['edges'])} (condition still UNKNOWN; the rover's range gate stays active)")
        tgt = self.targets.get(req["cand_id"])
        if tgt is not None and tgt["status"] in ("STAGED", "STAGING"):
            del self.targets[req["cand_id"]]
            if self.active == req["cand_id"]:
                self.active = None
        self.insufficient = None
        self.phase, self.phase_detail = "ROUTE_PLANNING", f"probe approved by {operator}; re-planning"
        return req

    def _check_drone(self, t: float) -> None:
        if self.drone_lost or not self.drone_link:
            return
        if t - self.drone.beat_t > AGENT_TIMEOUT_S:
            self.drone_lost = True
            self.msg("COORD", "OPERATOR", "AGENT_TIMEOUT", f"AIR-1 silent for {t - self.drone.beat_t:.1f} s: marked "
                     f"UNAVAILABLE; no new aerial observations; UNKNOWN corridors stay UNKNOWN")
            for s in self.scouts.values():
                if not s["done"]:
                    s.update(done=True, result="CANCELLED: AIR-1 timeout")
        for tid, s in self.scouts.items():
            if not s["done"] and t - s["t"] > SCOUT_TIMEOUT_S:
                s.update(done=True, result="TIMEOUT")
                self.msg("COORD", "OPERATOR", "TASK_TIMEOUT", f"{tid} not finished after {SCOUT_TIMEOUT_S:.0f} s")

    def tick(self) -> None:
        t = self.clock()
        if self.drone_link:
            ready = [o for o in self.drone.outbox if t - o["t"] >= self.link_delay_s - 1e-9]
            for o in ready:
                self._ingest_air(o)
            self.drone.outbox[:] = [o for o in self.drone.outbox if t - o["t"] < self.link_delay_s - 1e-9]
            self.drone_buffered = len(self.drone.outbox)
            for s in self.scouts.values():
                if s.get("undelivered"):
                    s["undelivered"] = False
                    self.drone.assign({k: s[k] for k in ("type", "task_id", "edges", "recheck", "reason")})
        else:
            self.drone_buffered = len(self.drone.outbox)
        self._check_drone(t)
        if self.rover_link:
            self._ingest_rover()
        self._decide(t)

    def _decide(self, t: float) -> None:
        rv = self.rover
        nav = rv.nav
        if rv.sup.latched is not None:
            self.phase = "FAULT"
            self.phase_detail = (f"rover {rv.sup.latched.value}: {rv.sup.latch_detail}; rover in SAFE_STOP, "
                                 f"operator reset required")
            if self.active and self.targets[self.active]["status"] != "FAULT":
                self.targets[self.active]["status"] = "FAULT"
                self.msg("COORD", "OPERATOR", "FAULT", self.phase_detail)
            return
        if self.active is not None:
            tgt = self.targets[self.active]
            if nav.running:
                w = nav.waiting_for_sensing
                if w:
                    self.phase, self.phase_detail = "ROVER_HOLD_AWAITING_AERIAL", \
                        f"rover stopped near {w['from_node']}; waiting for {w['request']}"
                    if (not self.scouting() and self._detour and self._detour_tasks < MAX_DETOUR_TASKS
                            and not self.drone_lost):
                        u, dest, be = self._detour
                        res = self.floor_route(u, dest)
                        if res.status == OK and self.known_route(u, dest).status != OK:
                            self._detour_tasks += 1
                            self.request_scout(self.unknown_on(res.path, REFRESH_MARGIN_S),
                                               f"detour for GND-1 around {be} (attempt {self._detour_tasks + 1})")
                elif nav.state.value in ("OBSTACLE_DETECTED", "STOP", "VERIFY_OBSTACLE",
                                         "MARK_EDGE_BLOCKED_IF_JUSTIFIED", "SCAN_DIRECTIONS",
                                         "REPLAN_SHORTEST_ROUTE", "VERIFY_DETOUR"):
                    self.phase, self.phase_detail = "ROVER_OBSTRUCTED", f"{nav.state.value}: {nav.state_detail}"
                else:
                    self.phase = "ROVER_REROUTED" if nav.reroutes else "ROVER_EN_ROUTE"
                    self.phase_detail = f"to {tgt['dest']} ({tgt['status']} {self.active})"
                return
            # only requests raised for THIS dispatch count (earlier HUMAN_REVIEW requests stay pending for a human)
            pend = [q for q in nav.operator_requests if q["state"] == "PENDING" and q["t"] >= tgt["t_assigned"] - 1e-6]
            kind = pend[-1]["kind"] if pend else None
            room = self.rooms.get(tgt["dest"])
            seen_edge = None
            if kind == "HUMAN_REVIEW" and pend[-1].get("obs_id"):
                seen_edge = rv.log.get(pend[-1]["obs_id"]).edge
            on_target = room is not None and seen_edge == edge_key(room.node, room.room_id)
            if tgt["status"] == "STAGING" and (nav.state == State.ARRIVED or kind == "HUMAN_REVIEW"):
                tgt["status"] = "STAGED"
                self.active = None
            elif kind == "HUMAN_REVIEW" and not on_target and tgt.get("resumes", 0) < MAX_RESUMES:
                # a person seen on ANOTHER corridor: keep it for human review, acknowledge as the sim operator
                # (SIMULATION only) and let the Navigator continue to its own target
                q = pend[-1]
                tgt["resumes"] = tgt.get("resumes", 0) + 1
                self.msg("COORD", "OPERATOR", "SIGHTING", f"person seen on {seen_edge}, not on {tgt['dest']}'s doorway; "
                         f"kept for human review [{q.get('obs_id')}]; GND-1 continues to {tgt['dest']}", [q.get("obs_id")])
                nav.respond(q["id"], True, OPERATOR)
                nav.resume(OPERATOR)
                return
            elif kind == "HUMAN_REVIEW" and on_target:
                tgt["status"] = "AT_STANDOFF"
                tgt["t_reached"] = round(t, 2)
                tgt["evidence"] = pend[-1].get("obs_id")
                self.msg("COORD", "OPERATOR", "REACHED",
                         f"GND-1 at standoff for {self.active}: survivor seen by rover camera (SIMULATED), "
                         f"UNCONFIRMED until a human reviews it", [pend[-1].get("obs_id")])
                self.active = None
            elif nav.state == State.ARRIVED:
                tgt["status"] = "NO_PERSON_FOUND"
                tgt["t_reached"] = round(t, 2)
                self.msg("COORD", "OPERATOR", "NO_PERSON", f"GND-1 reached {tgt['dest']} for {self.active}; its camera "
                         f"saw no person: aerial candidate was a false detection (not reported as a rescue)")
                self.active = None
            elif nav.state == State.SAFE_STOP:
                tgt["status"] = "UNREACHABLE"
                tgt["reason"] = nav.safe_stop_reason
                self.msg("COORD", "OPERATOR", "UNREACHABLE", f"{self.active}: {nav.safe_stop_reason}")
                self.active = None
            else:
                tgt["status"] = "OPERATOR_REQUIRED"
                tgt["reason"] = nav.state_detail
                self.phase, self.phase_detail = "OPERATOR_REQUIRED", nav.state_detail
                return
        if self.insufficient is not None:
            self.phase, self.phase_detail = "INSUFFICIENT_INFORMATION", self.insufficient["text"]
            return
        self.ranking = self.rank()
        if not self.ranking:
            if self.scouting():
                self.phase, self.phase_detail = "ROUTE_SCOUTING", "drone observing corridors"
                return
            handled = [x for x in self.targets.values()
                       if x["status"] in ("AT_STANDOFF", "UNREACHABLE", "NO_PERSON_FOUND")]
            unresolved = [c for c, v in self.candidates.items() if v.get("status") != "LIKELY" and c not in self.targets]
            if self.drone_lost or (self.drone.search_complete and (handled or not unresolved)):
                if not self.complete:
                    self.complete = True
                    self.msg("COORD", "OPERATOR", "COMPLETE",
                             f"search finished; {len(handled)} target(s) handled; "
                             f"{len(unresolved)} low-confidence candidate(s) left for operator review")
                self.phase, self.phase_detail = "MISSION_COMPLETE", "awaiting human confirmation of survivors"
            elif self.candidates:
                self.phase, self.phase_detail = "CONFIRMING", "drone confirming survivor candidates"
            else:
                self.phase, self.phase_detail = "AERIAL_SURVEY", self.drone.why[:160]
            return
        if not self.targets:
            ready = (len(self.ranking) >= self.sc.assign_min_candidates or self.drone.search_complete or
                     self.drone_lost or self.sc.assign_min_candidates <= 1 or
                     (self.first_candidate_t is not None and self.sc.assign_timeout_s > 0 and
                      t - self.first_candidate_t >= self.sc.assign_timeout_s))
            if not ready:
                self.phase, self.phase_detail = "AERIAL_SURVEY", (f"{len(self.ranking)} likely survivor(s); waiting "
                                                                  f"for {self.sc.assign_min_candidates} or survey end")
                return
        if self.scouting():
            self.phase, self.phase_detail = "ROUTE_SCOUTING", "drone observing the candidate route"
            return
        top = self.ranking[0]
        cid, room = top["cand_id"], top["room"]
        node = self.rover_node()
        if node is None:
            return
        r = self.known_route(node, room)
        if r.status == OK:
            if len(self.ranking) > 1 or self.targets:
                self.msg("COORD", "COORD", "RANK", "; ".join(x["why"] + f" [{x['cand_id']}]" for x in self.ranking))
            self._dispatch(cid, room, "RESCUE", r)
            return
        f = self.floor_route(node, room)
        if f.status == OK and self.mode in ("coordinated", "static_route") and not self.drone_lost:
            unknown = self.unknown_on(f.path, REFRESH_MARGIN_S if self.fresh_s else 0.0)
            self.phase, self.phase_detail = "ROUTE_SCOUTING", f"route {'-'.join(f.path)} has UNKNOWN/STALE corridors"
            self.request_scout(unknown, f"pre-dispatch route check for {cid} ({'-'.join(f.path)})")
            return
        # no usable route: UNKNOWN is not CLEAR, so ask for more sensing instead of inventing a route
        best = None
        for n in self.full.nodes:
            kr = self.known_route(node, n)
            if kr.status != OK:
                continue
            fr = self.floor_route(n, room, exclude_occluded=False)
            if fr.status == OK and (best is None or fr.length_m < best[1].length_m):
                best = (n, fr, kr)
        if best is None:
            self.targets[cid] = {"cand_id": cid, "dest": room, "status": "UNREACHABLE", "t_assigned": round(t, 2),
                                 "reason": "no floor-plan route avoids BLOCKED corridors"}
            self.msg("COORD", "OPERATOR", "UNREACHABLE", f"{cid}: no floor-plan route to {room} avoids BLOCKED corridors")
            return
        n, fr, kr = best
        unknown = self.unknown_on(fr.path)
        visible = [e for e in unknown if self.edges[e]["status"] not in ("OCCLUDED", "BLOCKED")]
        if visible and self.mode in ("coordinated", "static_route") and not self.drone_lost \
                and cid not in self._approach_scouted:
            self._approach_scouted.add(cid)          # observe the approachable part first, then re-plan staging
            self.phase, self.phase_detail = "ROUTE_SCOUTING", f"observing the approach to {room} that the drone can see"
            self.request_scout(visible, f"approach to {room} for {cid} (part of it is occluded)")
            return
        why = "AIR-1 unavailable" if self.drone_lost else "the drone cannot see them"
        text = (f"{cid} in {room}: every route crosses corridors with no usable observation ({', '.join(unknown)}; "
                f"{why}): UNKNOWN, not CLEAR. Rover pre-positions at {n}; operator: approve a sensor-gated "
                f"ground probe or provide more sensing")
        req = {"id": f"op-{len(self.operator_requests) + 1:03d}", "kind": "APPROVE_GROUND_PROBE", "state": "PENDING",
               "t": round(t, 2), "cand_id": cid, "edges": unknown, "staging": n, "text": text}
        self.operator_requests.append(req)
        self.insufficient = {"cand_id": cid, "text": text, "request": req["id"]}
        self.msg("COORD", "OPERATOR", "INSUFFICIENT_INFORMATION", text, self.candidates[cid]["obs_ids"][-1:])
        if n != node:
            self._dispatch(cid, n, "STAGING", kr)
        else:
            self.targets[cid] = {"cand_id": cid, "dest": n, "status": "STAGED", "t_assigned": round(t, 2)}
        self.phase, self.phase_detail = "INSUFFICIENT_INFORMATION", text

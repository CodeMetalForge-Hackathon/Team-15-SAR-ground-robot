"""One simulated mission: ground truth, AIR-1, GND-1 and the coordinator on a shared clock.

    python -m simulation.dual_rescue.mission A                 # demo scenario A headless, print the summary
    python -m simulation.dual_rescue.mission A --messages      # ... and the agent message log
    python -m simulation.dual_rescue.mission --env warehouse --seed 7
    python -m simulation.dual_rescue.mission --all

Fixed tick (0.05 s, rover.sim.SimConfig.dt) and fixed seeds: the same scenario always produces the same
mission. Wall-clock speed only changes how many ticks the dashboard asks for per frame.

``evaluate()`` compares the outcome with GROUND TRUTH after the fact (benchmark metrics). It is never
called by an agent and nothing it computes feeds back into a decision.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Callable, Optional

import numpy as np

from planner.route import OK, compute_route
from simulation.dual_rescue.aerial import AerialScout
from simulation.dual_rescue.coordinator import Coordinator
from simulation.dual_rescue.environments import ENVIRONMENTS, make_environment
from simulation.dual_rescue.ground import LINK_TIMEOUT_S, GroundRover
from simulation.dual_rescue.scenarios import SCENARIOS
from simulation.dual_rescue.world import (CELL_M, FRAME, N, VISIBLE, Debris, GroundTruth, Scenario, cell_of,
                                          edge_key, edge_samples)

DT = 0.05
MATCH_M = 3.0          # a candidate within this distance of a true survivor "located" it (evaluation only)


def load_scenario(key: str = "A", env: Optional[str] = None, seed: Optional[int] = None) -> Scenario:
    if env:
        return make_environment(env, 0 if seed is None else seed)
    k = key.upper()
    if k not in SCENARIOS:
        raise KeyError(f"unknown scenario {key}")
    sc = SCENARIOS[k]()
    if seed is not None:
        sc.seed = seed
    return sc


class Mission:
    def __init__(self, key: str = "A", *, env: Optional[str] = None, seed: Optional[int] = None,
                 scenario: Optional[Scenario] = None, mode: str = "coordinated", planner: str = "mcts"):
        self.sc = scenario if scenario is not None else load_scenario(key, env, seed)
        self.full, self.xy = self.sc.layout.graph()
        self.truth = GroundTruth(self.sc, self.full, self.xy)
        base = self.sc.layout.base
        self.rover = GroundRover(self.full, self.xy, self.truth, base)
        self.drone = AerialScout(self.sc, self.full, self.xy, self.truth.vis, self.xy[base], self.sc.seed,
                                 planner=planner)
        self.coord = Coordinator(self.sc, self.full, self.xy, self.drone, self.rover, clock=lambda: self.t,
                                 mode=mode)
        self.mode, self.planner = mode, planner
        self.ticks = 0
        self.user_debris = 0
        self.report: Optional[dict] = None
        f = self.sc.faults
        self._fault_rng = np.random.default_rng(self.sc.seed + 7)
        self._dropout = float(f.get("aerial_dropout", 0.0))
        self._invalid_done = False
        self.coord.msg("SIM", "ALL", "START", f"{self.sc.title}; seed {self.sc.seed}; mode {mode}; aerial planner "
                       f"{planner}; all motion SIMULATED")

    @property
    def t(self) -> float:
        return self.rover.world.t

    # --- sensing path handed to the drone (opaque callable) -------------------------------------
    def _sense(self, cell, fov, pod, rng):
        if self._dropout and self._fault_rng.random() < self._dropout:
            return None                                    # fault injection: frame lost
        return self.truth.aerial_look(cell, fov, pod, rng)

    # --- events ---------------------------------------------------------------------------------
    def _events(self) -> None:
        t = self.t
        f = self.sc.faults
        if self.sc.comm_loss:
            t0, t1 = self.sc.comm_loss
            up = not (t0 <= t < t1)
            if up != self.coord.rover_link:
                self.coord.rover_link = up
                self.coord.msg("SIM", "ALL", "LINK", "GND-1 mission link RESTORED (rover stays in SAFE_STOP until an "
                               "operator resets it)" if up else "GND-1 mission link LOST (SIMULATED fault)")
        if "drone_fail_t" in f and not self.drone.failed and t >= f["drone_fail_t"]:
            self.drone.fail(t)
            self.coord.msg("SIM", "ALL", "FAULT", "AIR-1 stopped responding (SIMULATED agent timeout)")
        if "invalid_obs_t" in f and not self._invalid_done and t >= f["invalid_obs_t"]:
            self._invalid_done = True
            self.drone.outbox.append({"obs_id": "air-9999", "t": round(t, 2), "agent": "AIR-1", "kind": "debris",
                                      "edge": next(iter(self.coord.edges)), "xy": [512.0, -40.0], "confidence": 0.9,
                                      "status": "BLOCKED", "data_label": "FAULT INJECTION (corrupted frame)"})
        w = self.rover.world
        a, b = w.edge
        nav = self.rover.nav
        for did, d in self.truth.debris.items():
            if self.truth.present[did]:
                continue
            if d.appears == "rover_enters" and (a, b) == (d.a, d.b) and w.s > 0.3:
                self._drop(did, d.a, d.b, d.at_m, d.note)
            elif d.appears == "on_route" and nav.running and nav.route is not None and nav.route.status == OK \
                    and w.node() is None and a != b and (a, b) in list(zip(nav.route.path, nav.route.path[1:]))[1:]:
                L = self.full.neighbors(a)[b]
                at = w.s + 5.0
                if a not in self.sc.layout.rooms and b not in self.sc.layout.rooms and at <= L - 2.0:
                    self._drop(did, a, b, round(at, 2), d.note)

    def _drop(self, did: str, a: str, b: str, at: float, note: str) -> None:
        d = self.truth.debris[did]
        d.a, d.b, d.at_m = a, b, at
        self.truth.drop_debris(did, self.t)
        if did in self.rover.obstacles:
            self.rover.drop_debris(did)
        else:
            self.rover.add_debris(did, a, b, at)
        self.coord.msg("SIM", "ALL", "EVENT", f"debris {did} fell onto {edge_key(a, b)} {at:.1f} m from {a} "
                       f"({note or 'dynamic'}); agents are NOT told - they must sense it")

    def add_obstacle(self) -> dict:
        """Dashboard button: drop debris ahead of the rover on its current route (SIMULATED event)."""
        nav = self.rover.nav
        r = nav.route
        if not nav.running or r is None or r.status != OK or len(r.path) < 2:
            return {"ok": False, "reason": "the rover has no active route to obstruct"}
        w = self.rover.world
        a, b = w.edge
        legs = list(zip(r.path, r.path[1:]))
        cands = []
        rooms = self.sc.layout.rooms
        if w.node() is None and (a, b) in legs:
            L = self.full.neighbors(a)[b]
            at = w.s + 2.5
            if at <= L - 1.5 and b not in rooms:
                cands.append((a, b, round(at, 2)))
            legs = legs[legs.index((a, b)) + 1:]
        else:
            n = w.node()
            if n in r.path:
                legs = legs[r.path.index(n):]
        for u, v in legs:
            L = self.full.neighbors(u)[v]
            if L >= 6.0 and v not in rooms:
                cands.append((u, v, round(L * 0.55, 2)))
        if not cands:
            return {"ok": False, "reason": "no corridor ahead long enough to place debris"}
        u, v, at = cands[0]
        self.user_debris += 1
        did = f"U{self.user_debris}"
        self.truth.debris[did] = Debris(did, u, v, at, appears="user", note="added from the dashboard")
        self._drop(did, u, v, at, "added from the dashboard")
        return {"ok": True, "debris": did, "edge": edge_key(u, v), "at_m": at}

    # --- stepping -------------------------------------------------------------------------------
    def step(self) -> None:
        t = self.t
        self._events()
        self.coord.tick()
        self.rover.step(link_ok=self.coord.rover_link)
        self.drone.step(t, DT, self._sense)
        self.ticks += 1

    def run(self, seconds: float) -> "Mission":
        end = self.t + seconds
        while self.t < end - 1e-9:
            self.step()
        return self

    def run_until(self, pred: Callable[["Mission"], bool], max_t: Optional[float] = None) -> "Mission":
        max_t = self.sc.max_t if max_t is None else max_t
        while self.t < max_t and not pred(self):
            self.step()
        return self

    def done(self) -> bool:
        c = self.coord
        if c.complete or c.phase == "FAULT":
            return True
        return c.phase == "INSUFFICIENT_INFORMATION" and not self.rover.nav.running and c.active is None

    # --- views ----------------------------------------------------------------------------------
    def static(self) -> dict:
        lay = self.sc.layout
        return {
            "frame": FRAME,
            "environment": {"env": lay.env, "theme": lay.theme, "label": lay.label,
                            "corridor_half_m": lay.corridor_half_m},
            "nodes": {n: list(p) for n, p in self.xy.items()},
            "edges": [{"edge": edge_key(a, b), "a": a, "b": b, "m": m,
                       "spur": a in lay.rooms or b in lay.rooms} for a, b, m in self.full.edges()],
            "rooms": [{"room": r.room_id, "node": r.node, "label": r.label, "xy": list(r.xy)} for r in lay.rooms.values()],
            "zones": [vars(z) for z in self.sc.zones],
            "sector": list(self.sc.search_sector), "sector_label": self.sc.sector_label,
            "scenario": {"key": self.sc.key, "title": self.sc.title, "summary": self.sc.summary,
                         "seed": self.sc.seed, "judge_notes": self.sc.judge_notes, "mode": self.mode,
                         "planner": self.planner, "fresh_s": self.sc.fresh_s, "faults": self.sc.faults},
            "grid": {"n": N, "cell_m": CELL_M},
            "base": list(self.xy[lay.base]),
            "dt": DT,
        }

    def truth_view(self) -> dict:
        tr = self.truth
        return {"label": "GROUND TRUTH - simulator only, never given to the planners",
                "survivors": [{"id": s, "xy": list(tr.survivor_xy(s)), "condition": tr.survivors[s].condition}
                              for s in sorted(tr.survivors)],
                "decoys": [{"id": d, "xy": list(tr.decoy_xy(d))} for d in sorted(tr.decoys)],
                "debris": [{"id": d, "xy": list(tr.debris_xy(d)) if tr.debris[d].a != "?" else None,
                            "edge": edge_key(tr.debris[d].a, tr.debris[d].b) if tr.debris[d].a != "?" else None,
                            "present": tr.present[d], "appears": tr.debris[d].appears} for d in sorted(tr.debris)]}

    def snapshot(self, truth: bool = False, since_msg: int = 0, heavy: bool = True) -> dict:
        c = self.coord
        nav = self.rover.nav
        planned = None
        if nav.route is not None and nav.route.status == OK:
            planned = [list(self.xy[n]) for n in nav.route.path]
        out = {
            "t": round(self.t, 2), "ticks": self.ticks, "phase": c.phase, "phase_detail": c.phase_detail,
            "complete": c.complete, "done": self.done(),
            "links": {"AIR-1": c.drone_link and not self.drone.failed, "GND-1": c.rover_link,
                      "drone_buffered_obs": c.drone_buffered, "drone_lost": c.drone_lost},
            "drone": dict(self.drone.status(), path=[[p[1], p[2]] for p in self.drone.path[-800:]]),
            "rover": dict(self.rover.status(), path=[[p[1], p[2]] for p in self.rover.path[-2000:]],
                          planned=planned),
            "edges": list(c.edges.values()),
            "routable": sorted(k for k in c.edges if c.routable(k)),
            "stale": c.stale_edges(),
            "blocked": c.blocked(),
            "candidates": list(c.candidates.values()),
            "targets": list(c.targets.values()),
            "ranking": c.ranking,
            "scouts": list(c.scouts.values())[-12:],
            "operator_requests": c.operator_requests,
            "messages_total": len(c.messages),
            "messages": c.messages[since_msg:][-250:],
            "observations": c.shared_obs[-60:],
            "observations_total": len(c.shared_obs),
            "rejected": c.rejected[-10:],
            "report": self.report,
        }
        if heavy:
            mx = float(self.drone.mass.max()) or 1.0
            out["coverage"] = [[1 if v else 0 for v in row] for row in self.drone.looked.tolist()]
            out["belief"] = [[round(float(v) / mx, 3) for v in row] for row in self.drone.mass.tolist()]
        if truth:
            out["truth"] = self.truth_view()
        return out

    def summary(self) -> dict:
        c = self.coord
        return {"scenario": self.sc.key, "t": round(self.t, 2), "phase": c.phase, "complete": c.complete,
                "targets": c.targets, "candidates": {k: {kk: v.get(kk) for kk in ("status", "confidence", "motion", "room")}
                                                     for k, v in c.candidates.items()},
                "blocked": c.blocked(), "reroutes": len(self.rover.nav.reroutes),
                "rover_state": self.rover.nav.state.value, "rover_odometer_m": round(self.rover.world.odometer_m, 2),
                "collisions": len(self.rover.collisions), "drone_distance_m": round(self.drone.distance_m, 1),
                "drone_looks": self.drone.looks, "scouts": {k: v.get("result") for k, v in c.scouts.items()},
                "messages": len(c.messages), "operator_requests": [r["kind"] for r in c.operator_requests]}

    # --- evaluation against ground truth (benchmark only) ----------------------------------------
    def _blind_edges(self) -> set:
        out = set()
        for a, b, _m in self.full.edges():
            pts = edge_samples(self.xy, a, b)
            seen = sum(1 for x, y in pts if self.truth.vis[cell_of(x, y)] >= VISIBLE)
            if seen < 0.95 * len(pts):
                out.add(edge_key(a, b))
        return out

    def evaluate(self) -> dict:
        tr, c, d, rv, nav = self.truth, self.coord, self.drone, self.rover, self.rover.nav
        sector = d.sector_mask
        coverage = float((d.looked & sector).sum() / max(1, sector.sum()))
        surv_xy = {s: tr.survivor_xy(s) for s in tr.survivors}
        cands = d.candidates
        located, disc_t, pos_err = {}, {}, []
        for sid, sxy in surv_xy.items():
            best = min(cands, key=lambda k: math.dist(k["xy"], sxy), default=None)
            if best is not None and math.dist(best["xy"], sxy) <= MATCH_M:
                located[sid] = best["cand_id"]
                disc_t[sid] = best["first_t"]
                pos_err.append(math.dist(best["xy"], sxy))
        false_cands = [k["cand_id"] for k in cands if all(math.dist(k["xy"], s) > MATCH_M for s in surv_xy.values())]
        likely_false = [cid for cid, v in c.candidates.items() if v.get("status") == "LIKELY" and
                        all(math.dist(v["xy"], s) > MATCH_M for s in surv_xy.values())]
        # corridor reports vs truth at report time
        false_clear = correct_blocked = false_blocked = 0
        for o in c.shared_obs:
            if o.get("agent") != "AIR-1" or o.get("kind") not in ("corridor_state", "debris"):
                continue
            present = [x for x, dd in tr.debris.items() if dd.a != "?" and edge_key(dd.a, dd.b) == o["edge"]
                       and tr.appeared_t.get(x, math.inf) <= o["t"]]
            if o["kind"] == "corridor_state" and o["status"] == "CLEAR" and present:
                false_clear += 1
            elif o["kind"] == "debris":
                correct_blocked += 1 if present else 0
                false_blocked += 0 if present else 1
        # truth reachability (all debris present at the end of the run)
        bad = {edge_key(dd.a, dd.b) for x, dd in tr.debris.items() if tr.present[x] and dd.a != "?"}
        blind = self._blind_edges()
        base = self.sc.layout.base
        reach, reach_obs = {}, {}
        for sid, s in tr.survivors.items():
            reach[sid] = compute_route(base, s.room, blocked=bad, graph=self.full).status == OK
            reach_obs[sid] = compute_route(base, s.room, blocked=bad | blind, graph=self.full).status == OK
        room_of = {s.room: sid for sid, s in tr.survivors.items()}
        rescue_targets = [x for x in c.targets.values() if x["status"] not in ("STAGING", "STAGED")]
        reached = {room_of[x["dest"]] for x in c.targets.values() if x["status"] == "AT_STANDOFF" and x["dest"] in room_of}
        wrong_claims = [x["cand_id"] for x in c.targets.values() if x["status"] == "AT_STANDOFF" and x["dest"] not in room_of]
        wrong_assign = [x["cand_id"] for x in rescue_targets if x["dest"] not in room_of]
        handoffs = len(rescue_targets)
        handoff_ok = sum(1 for x in rescue_targets if x["status"] == "AT_STANDOFF")
        hist = nav.history
        stops = sum(1 for h in hist if h["state"] == "OBSTACLE_DETECTED")
        safe_stops = sum(1 for h in hist if h["state"] == "SAFE_STOP")
        unreachable_reported = [x["cand_id"] for x in c.targets.values() if x["status"] == "UNREACHABLE"]
        probe_traversed = sorted({e["edge"] for e in c.edges.values() if e["status"] == "TRAVERSED"} & rv.probe_edges)
        comm = None
        if self.sc.comm_loss:
            t0 = self.sc.comm_loss[0]
            ev = [e for e in rv.sup.events if getattr(e, "kind", None) == "LATCH"] if hasattr(rv.sup, "events") else []
            latched_ok = rv.sup.latched is not None and rv.sup.latched.value == "COMMS_LOST"
            comm = {"latched_comms_lost": latched_ok, "fault_phase": c.phase == "FAULT",
                    "rover_stopped": rv.driver.velocity.is_zero(), "loss_t": t0,
                    "expected_latch_by_t": round(t0 + LINK_TIMEOUT_S + 0.2, 2), "latch_events": len(ev)}
        violations = len(rv.collisions) + len(rv.unknown_entries) + (1 if rv.latched_motion_ticks else 0) + \
            (1 if rv.driver.physical else 0) + len(wrong_claims)
        located_all = len(located) == len(tr.survivors)
        success = located_all and all(reach[s] and s in reached for s in tr.survivors) and violations == 0
        undetectable = [s for s in tr.survivors if s not in located and tr.vis[cell_of(*surv_xy[s])] < VISIBLE]
        if violations:
            outcome = "UNSAFE"
        elif success:
            outcome = "SUCCESS"
        elif c.phase == "FAULT":
            outcome = "SAFE_STOP_FAULT"
        elif c.phase == "INSUFFICIENT_INFORMATION":
            outcome = "INSUFFICIENT_INFORMATION"
        elif unreachable_reported and not reached:
            outcome = "UNREACHABLE_REPORTED"
        elif not located_all and c.complete and not reached:
            outcome = "SURVIVOR_NOT_FOUND"
        elif c.complete and not reached and not any(v.get("status") == "LIKELY" for v in c.candidates.values()):
            outcome = "CANDIDATE_UNCONFIRMED"
        elif reached:
            outcome = "PARTIAL"
        else:
            outcome = "TIMEOUT" if self.t >= self.sc.max_t - 1e-6 else "INCOMPLETE"
        # was the outcome the CORRECT behaviour given the truth? (a safe abort can be correct)
        missed = [s for s in tr.survivors if s not in reached]
        f = self.sc.faults
        justified = all(
            (s not in located and (s in undetectable or self.drone.failed or c.complete)) or
            (s in located and outcome == "CANDIDATE_UNCONFIRMED" and (self.drone.failed or c.drone_lost)) or
            (s in located and not reach[s]) or
            (s in located and not reach_obs[s] and outcome == "INSUFFICIENT_INFORMATION") or
            (outcome == "SAFE_STOP_FAULT" and bool(self.sc.comm_loss)) or
            (outcome == "INSUFFICIENT_INFORMATION" and (c.drone_lost or "drone_fail_t" in f))
            for s in missed)
        correct = violations == 0 and not wrong_claims and (success or (justified and outcome not in
                                                                        ("TIMEOUT", "INCOMPLETE", "PARTIAL")))
        return {
            "outcome": outcome, "success": success, "correct_outcome": correct, "t_end": round(self.t, 2), "steps": self.ticks,
            "aerial": {"coverage": round(coverage, 3), "survivors": len(tr.survivors), "located": len(located),
                       "discovery_rate": round(len(located) / max(1, len(tr.survivors)), 3),
                       "first_discovery_t": min(disc_t.values()) if disc_t else None,
                       "discovery_t": disc_t, "path_m": round(d.distance_m, 1), "looks": d.looks,
                       "missing_frames": d.missing_frames,
                       "position_error_m": round(float(np.mean(pos_err)), 2) if pos_err else None,
                       "false_candidates": len(false_cands), "likely_false": len(likely_false),
                       "false_clear_reports": false_clear, "correct_debris_reports": correct_blocked,
                       "false_debris_reports": false_blocked},
            "ground": {"assigned": handoffs, "reached": len(reached), "route_completion":
                       round(handoff_ok / handoffs, 3) if handoffs else None, "path_m": round(rv.world.odometer_m, 2),
                       "replans": len(nav.reroutes), "collisions": len(rv.collisions), "stop_events": stops,
                       "safe_stops": safe_stops, "unreachable_reported": len(unreachable_reported),
                       "unknown_entries": len(rv.unknown_entries), "probe_corridors_traversed": len(probe_traversed),
                       "latched_motion_ticks": rv.latched_motion_ticks},
            "joint": {"success": success, "t_complete": round(self.t, 2) if c.complete else None,
                      "located": len(located), "reached": len(reached), "reachable_truth": sum(reach.values()),
                      "reachable_observable": sum(reach_obs.values()), "handoffs": handoffs,
                      "handoff_success": handoff_ok, "incorrect_assignments": len(wrong_assign),
                      "incorrect_claims": len(wrong_claims), "comm": comm, "conflicts": c.conflicts,
                      "rejected_obs": len(c.rejected), "drone_lost": c.drone_lost,
                      "insufficient_information": c.phase == "INSUFFICIENT_INFORMATION",
                      "operator_requests": [r["kind"] for r in c.operator_requests],
                      "safety_violations": violations, "phase": c.phase},
        }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenario", nargs="?", default="A")
    p.add_argument("--env", choices=ENVIRONMENTS)
    p.add_argument("--seed", type=int)
    p.add_argument("--all", action="store_true")
    p.add_argument("--messages", action="store_true", help="print the agent message log")
    p.add_argument("--evaluate", action="store_true", help="print metrics against ground truth")
    a = p.parse_args(argv)
    keys = list(SCENARIOS) if a.all else [a.scenario]
    for k in keys:
        m = Mission(k, env=a.env, seed=a.seed).run_until(lambda m: m.done())
        print(json.dumps(m.evaluate() if a.evaluate else m.summary(), indent=2, default=str))
        if a.messages:
            for msg in m.coord.messages:
                print(f"{msg['t']:8.2f} {msg['from']:>8} -> {msg['to']:<8} {msg['type']:<22} {msg['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

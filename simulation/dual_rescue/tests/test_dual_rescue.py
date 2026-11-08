"""Dual-robot rescue SIMULATION: aerial search, ground routing, exchange, replanning, UNKNOWN handling,
prioritisation, communication failure, Qwen provenance, replay and hardware isolation."""
from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

import pytest

from simulation.dual_rescue import aerial as aerial_mod
from simulation.dual_rescue.environments import ENVIRONMENTS, make_environment
from simulation.dual_rescue.ground import LINK_TIMEOUT_S
from simulation.dual_rescue.mission import Mission
from simulation.dual_rescue.report import build_report
from simulation.dual_rescue.world import Survivor, edge_key

PKG = Path(__file__).resolve().parents[1]


def finished(key, **kw) -> Mission:
    return Mission(key, **kw).run_until(lambda m: m.done())


def types(m):
    return [x["type"] for x in m.coord.messages]


# 1. aerial search -------------------------------------------------------------------------------
def test_aerial_search_discovers_survivor_inside_footprint_and_reports_it():
    m = finished("A")
    d, c = m.drone, m.coord
    assert d.looks > 20 and d.pos_of_sector() >= 0.97
    cand = c.candidates["C1"]
    truth = m.truth.survivor_xy("S1")
    assert math.dist(cand["xy"], truth) <= 3.0, "candidate is where the survivor is (within one cell)"
    first = next(o for o in c.shared_obs if o.get("kind") == "survivor_candidate")
    for k in ("obs_id", "t", "source", "confidence", "xy", "data_label"):
        assert k in first
    assert first["data_label"] == "SIMULATED DRONE OBSERVATION" and first["agent"] == "AIR-1"
    # the drone was over the survivor when it first saw it: footprint (2 fov + 1) cells
    t_first = first["t"]
    px, py = min(d.path, key=lambda p: abs(p[0] - t_first))[1:]
    assert abs(px - truth[0]) <= (aerial_mod.FOV + 1) * 2.0 and abs(py - truth[1]) <= (aerial_mod.FOV + 1) * 2.0


def test_no_ground_truth_leakage_into_aerial_decisions():
    """Same seed, survivor moved to another room: the flight is identical until something is detected."""
    a, b = Mission("A"), Mission("A")
    b.sc.survivors[0] = Survivor("S1", "R_SE", 4.5, "NOT_MOVING")
    b.truth.survivors = {"S1": b.sc.survivors[0]}
    assert (a.drone.mass == b.drone.mass).all(), "prior does not depend on where survivors are"
    while a.t < 60 and not a.drone.candidates and not b.drone.candidates:
        a.step()
        b.step()
        assert (a.drone.x, a.drone.y) == (b.drone.x, b.drone.y)
    assert a.t > 5


def test_aerial_baselines_use_existing_planners_and_mcts_is_faster_to_first_discovery():
    t = {}
    for p in ("mcts", "lawnmower"):
        m = Mission(env="collapsed_building", seed=42, planner=p).run_until(lambda m: m.drone.candidates, max_t=600)
        t[p] = m.drone.candidates[0]["first_t"]
    assert t["mcts"] < t["lawnmower"]


# 2. ground route planning ---------------------------------------------------------------------
def test_ground_rover_routes_only_over_known_corridors_and_reaches_standoff():
    m = finished("A")
    tgt = m.coord.targets["C1"]
    assert tgt["status"] == "AT_STANDOFF"
    first_assign = next(x for x in m.coord.messages if x["type"] == "ASSIGN")
    assert "TASK" in types(m)[:types(m).index("ASSIGN")], "route scouted from the air before dispatch"
    assert "M1-N1" not in first_assign["text"].replace("M1-N1-", ""), "drone-observed debris corridor avoided"
    assert m.rover.unknown_entries == [] and m.rover.collisions == []
    assert m.rover.driver.physical is False


# 3. observation exchange -------------------------------------------------------------------------
def test_observations_reach_the_shared_map_only_over_the_link():
    m = Mission("A")
    m.coord.drone_link = False
    m.run(25)
    assert not m.coord.candidates and m.drone.outbox, "buffered on the drone while the link is down"
    buffered = len(m.drone.outbox)
    m.coord.drone_link = True
    m.step()
    assert m.coord.candidates and not m.drone.outbox and len(m.coord.shared_obs) >= buffered


# 4. dynamic obstacle + replanning ----------------------------------------------------------------
def test_dynamic_debris_stop_aerial_support_and_replan():
    m = finished("B")
    ty = types(m)
    for k in ("EVENT", "OBSTACLE", "REQUEST_SENSING", "REROUTE", "REACHED"):
        assert k in ty, k
    assert ty.index("OBSTACLE") < ty.index("REQUEST_SENSING") < ty.index("REROUTE") < ty.index("REACHED")
    assert len(m.rover.nav.reroutes) == 1 and m.rover.nav.reroutes[0]["blocked_edge"] == "M3-S3"
    assert "M3-S3" in m.rover.log.blocked_edges()
    states = [h["state"] for h in m.rover.nav.history]
    for s in ("OBSTACLE_DETECTED", "STOP", "VERIFY_OBSTACLE", "MARK_EDGE_BLOCKED_IF_JUSTIFIED", "SCAN_DIRECTIONS",
              "REPLAN_SHORTEST_ROUTE", "VERIFY_DETOUR"):
        assert s in states, s
    assert m.rover.collisions == [] and m.evaluate()["outcome"] == "SUCCESS"
    # the drone re-observed the blocked corridor (corroboration)
    assert any(o.get("kind") == "debris" and o["edge"] == "M3-S3" for o in m.coord.shared_obs)


def test_dashboard_debris_button_is_sensed_not_announced():
    m = Mission("A").run_until(lambda m: m.rover.nav.running and m.rover.world.node() is None, max_t=200)
    r = m.add_obstacle()
    assert r["ok"]
    m.run_until(lambda m: m.done())
    assert r["edge"] in m.rover.log.blocked_edges() or r["edge"] in m.coord.blocked()
    assert m.rover.collisions == []


# 5. UNKNOWN space ---------------------------------------------------------------------------------
def test_unknown_is_not_clear_and_more_sensing_is_requested():
    m = finished("C")
    c = m.coord
    assert c.phase == "INSUFFICIENT_INFORMATION"
    req = c.operator_requests[0]
    assert req["kind"] == "APPROVE_GROUND_PROBE" and req["state"] == "PENDING"
    for ek in req["edges"]:
        assert c.edges[ek]["status"] in ("UNKNOWN", "OCCLUDED") and not c.routable(ek)
    assert m.rover.unknown_entries == [] and c.targets["C1"]["status"] == "STAGED"
    # operator approval -> sensor-gated probe -> standoff
    c.approve_probe(req["id"], "test-operator")
    m.run_until(lambda m: m.done() or m.coord.targets.get("C1", {}).get("status") == "AT_STANDOFF", max_t=900)
    assert c.targets["C1"]["status"] == "AT_STANDOFF" and m.rover.collisions == []


# 6. prioritisation --------------------------------------------------------------------------------
def test_multiple_survivors_ranked_by_explicit_criteria():
    m = finished("D")
    order = [x["text"].split()[1].rstrip(":") for x in m.coord.messages if x["type"] == "ASSIGN"]
    motion = {cid: v["motion"] for cid, v in m.coord.candidates.items()}
    assert [motion[c] for c in order] == ["LYING_DOWN", "NOT_MOVING", "MOVING"]
    rank_msg = next(x for x in m.coord.messages if x["type"] == "RANK")
    assert "condition LYING_DOWN (rank 0)" in rank_msg["text"]
    assert all(t["status"] == "AT_STANDOFF" for t in m.coord.targets.values())


# 7. communication failure -------------------------------------------------------------------------
def test_comm_loss_latches_comms_lost_and_never_auto_resumes():
    m = Mission("E")
    t0 = m.sc.comm_loss[0]
    m.run_until(lambda m: m.rover.sup.latched is not None, max_t=t0 + 10)
    assert m.rover.sup.latched.value == "COMMS_LOST"
    assert m.t <= t0 + LINK_TIMEOUT_S + 0.2
    m.run(60)                                        # link restored at t1 < now
    assert m.coord.rover_link and m.rover.sup.latched is not None, "no automatic resume"
    assert m.rover.driver.velocity.is_zero() and m.rover.latched_motion_ticks == 0
    assert m.coord.phase == "FAULT"


def test_agent_timeout_and_invalid_coordinates():
    sc = make_environment("collapsed_building", 42)
    sc.faults.update(drone_fail_t=15.0, invalid_obs_t=5.0)
    m = Mission(scenario=sc).run_until(lambda m: m.done())
    assert m.coord.drone_lost and "AGENT_TIMEOUT" in types(m)
    assert m.coord.rejected and m.coord.rejected[0]["obs"] == "air-9999"
    assert all(o["obs_id"] != "air-9999" for o in m.coord.shared_obs)
    assert m.rover.unknown_entries == [] and m.rover.collisions == []


# 8. Qwen provenance --------------------------------------------------------------------------------
def test_qwen_report_is_guarded_and_citations_checked():
    m = finished("B")
    known = next(o["obs_id"] for o in m.coord.shared_obs if o.get("kind") == "debris")
    ok = build_report(m, qwen=lambda body: {"explanation": f"Debris [{known}] and [rov-0099] blocked the rover.",
                                            "config": "C_QWEN_RAG", "model_id": "fake", "guard": {}})
    assert ok["qwen_status"].startswith("QWEN_GUARDED") and ok["authority"] == "NONE"
    assert ok["qwen"]["provenance"]["unknown_ids"] == ["rov-0099"]
    motor = build_report(m, qwen=lambda body: {"explanation": "drive forward now at 0.5 m/s speed"})
    assert motor["qwen"] is None and "DISCARDED_MOTOR_COMMAND_PATTERN" in motor["qwen_status"]

    def down(body):
        raise ConnectionError("no service")
    off = build_report(m, qwen=down)
    assert off["qwen"] is None and "DETERMINISTIC FALLBACK" in off["qwen_status"]
    assert "rov-0001" in off["deterministic"]["text"]          # deterministic text cites observation ids


# 9. reset / replay ---------------------------------------------------------------------------------
def test_reset_and_replay_are_deterministic():
    a = finished("B")
    half = Mission("B").run(80)                       # a mission abandoned midway ...
    assert half.t >= 80
    b = finished("B")                                 # ... does not affect a fresh one
    assert [(x["t"], x["type"], x["text"]) for x in a.coord.messages] == \
           [(x["t"], x["type"], x["text"]) for x in b.coord.messages]
    assert a.evaluate() == b.evaluate()


# 10. no physical hardware ------------------------------------------------------------------------
HW = ("rover.hardware", "rover.bridge", "rover.pi_io", "serial", "RPi", "gpiozero", "lgpio", "smbus", "smbus2",
      "ranging.drivers", "lidar.driver", "lidar.transport", "pigpio")


def test_simulation_never_imports_hardware_modules():
    for f in PKG.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for n in names:
                assert not any(n == h or n.startswith(h + ".") for h in HW), f"{f.name} imports {n}"
    finished("A")
    loaded = [m for m in sys.modules if any(m == h or m.startswith(h + ".") for h in HW)]
    assert loaded == [] or all(not m.startswith(("serial", "RPi", "gpiozero", "lgpio", "smbus", "pigpio")) for m in loaded)


def test_rover_uses_simulated_driver_only():
    m = Mission("A")
    assert m.rover.driver.physical is False and m.rover.nav.io.physical is False
    assert m.rover.nav.cfg.auto_approve is True          # Navigator refuses this with a physical driver


# environments & API -----------------------------------------------------------------------------
@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_environment_layouts_are_valid_and_runs_are_safe(env):
    for seed in (0, 1, 2):
        sc = make_environment(env, seed)
        g, xy = sc.layout.graph()
        for n in g.nodes:
            x, y = xy[n]
            assert 0 <= x <= 48 and 0 <= y <= 48
            bearings = sorted(math.degrees(math.atan2(xy[w][1] - y, xy[w][0] - x)) % 360 for w in g.neighbors(n))
            gaps = [(b - a) for a, b in zip(bearings, bearings[1:])] + ([360 - bearings[-1] + bearings[0]] if len(bearings) > 1 else [])
            assert all(gp >= 20 for gp in gaps), f"{env}:{seed} node {n} has ambiguous corridor bearings"
    e = Mission(env=env, seed=0).run_until(lambda m: m.done()).evaluate()
    assert e["joint"]["safety_violations"] == 0 and e["joint"]["incorrect_claims"] == 0


def test_rescue_api_endpoints():
    from fastapi.testclient import TestClient

    from dashboard.app import create_app
    c = TestClient(create_app())
    assert c.get("/rescue").status_code == 200
    assert c.get("/rescue/vendor/three/three.module.min.js").status_code == 200
    assert c.get("/rescue/../app.py").status_code == 404
    sc = c.get("/api/rescue/scenarios").json()
    assert {s["key"] for s in sc} >= {"A", "B", "C", "D", "E"}
    r = c.post("/api/rescue/reset", json={"scenario": "B"}).json()
    assert r["static"]["environment"]["theme"] == "urban" and r["state"]["t"] == 0
    st = c.post("/api/rescue/step", json={"sim_s": 30}).json()
    assert st["t"] == pytest.approx(30, abs=0.06) and "truth" not in st
    assert "truth" in c.get("/api/rescue/state?truth=1").json()
    rep = c.post("/api/rescue/report", json={"qwen": False}).json()
    assert rep["authority"] == "NONE" and rep["deterministic"]["text"]
    assert c.post("/api/rescue/reset", json={"scenario": "nope"}).status_code == 422
    assert c.get("/api/rescue/evidence/..%2Fx_annotated.jpg").status_code == 404


def test_edge_key_is_canonical():
    assert edge_key("S3", "M3") == edge_key("M3", "S3") == "M3-S3"

"""Reproducible scenarios (fixed seeds). Ground truth here is hidden from every planner."""
from __future__ import annotations

from simulation.dual_rescue.environments import make_environment
from simulation.dual_rescue.world import SITE_M, Debris, Scenario, Survivor, Zone


def scenario_a() -> Scenario:
    return Scenario(
        key="A", title="A - Standard rescue",
        summary="The drone searches the north wing, finds and confirms a survivor, scouts the rover's route "
                "(spotting debris that changes the plan) and hands the target to the rover.",
        seed=11,
        survivors=[Survivor("S1", "R_NE", 4.5, "NOT_MOVING")],
        debris=[Debris("D1", "M1", "N1", 9.0, note="collapsed ceiling tiles")],
        judge_notes=["Watch the drone's MCTS 'why' line", "Route is scouted from the air before the rover moves"])


def scenario_b() -> Scenario:
    sc = scenario_a()
    sc.key, sc.title = "B", "B - Dynamic debris"
    sc.summary = ("Debris falls onto the rover's planned corridor after dispatch. The rover's ultrasonic stops "
                  "it; with no KNOWN detour it holds, the drone observes the detour and re-checks the block, "
                  "and the Navigator replans.")
    sc.debris = list(sc.debris) + [Debris("D2", "S3", "M3", 11.0, appears="rover_enters", note="secondary collapse")]
    sc.fresh_s = 60.0     # aftershock risk: corridor observations older than 60 s must be refreshed
    sc.judge_notes = ["Rover: OBSTACLE_DETECTED -> STOP -> VERIFY -> MARK_EDGE_BLOCKED -> SCAN",
                      "Drone gets a SCOUT task for the detour", "REPLAN uses only corridors now KNOWN clear"]
    return sc


def scenario_c() -> Scenario:
    return Scenario(
        key="C", title="C - Incomplete information",
        summary="A survivor is seen through a roof hole in the east lab, but every corridor to it is under an "
                "intact roof the drone cannot see through. UNKNOWN is not CLEAR: the rover pre-positions and "
                "the operator is asked for more sensing.",
        seed=23,
        survivors=[Survivor("S1", "R_E", 4.5, "LYING_DOWN")],
        zones=[Zone("roof-east", 33.0, 0.0, SITE_M, 38.0, 0.0, "intact roof (east wing)"),
               Zone("hole-lab", 35.5, 25.0, 41.0, 31.0, 0.7, "roof hole over east lab")],
        search_sector=(24.0, 14.0, SITE_M, 40.0), sector_label="east wing (occupant reported)",
        judge_notes=["Grey corridors are UNKNOWN/OCCLUDED, never drawn as clear",
                     "Approve the ground probe to see the sensor-gated approach"])


def scenario_d() -> Scenario:
    return Scenario(
        key="D", title="D - Multiple survivors",
        summary="Three survivors in the north and central wings. The coordinator ranks them by condition, "
                "known route, route length and confidence, and the rover serves them in that order.",
        seed=31,
        survivors=[Survivor("S1", "R_NE", 4.5, "MOVING"), Survivor("S2", "R_NW", 4.5, "LYING_DOWN"),
                   Survivor("S3", "R_C", 4.5, "NOT_MOVING")],
        search_sector=(0.0, 20.0, SITE_M, SITE_M), sector_label="north + central wings",
        assign_min_candidates=3, assign_timeout_s=60.0, max_t=900.0,
        judge_notes=["Ranking tuple is shown in the Targets panel", "LYING_DOWN outranks NOT_MOVING outranks MOVING"])


def scenario_e() -> Scenario:
    sc = scenario_a()
    sc.key, sc.title = "E", "E - Communication failure"
    sc.summary = ("The rover's mission link drops while it is driving. Its link watchdog latches the existing "
                  "safety-supervisor COMMS_LOST stop; the dashboard names the fault. Recovery needs an operator.")
    sc.comm_loss = (150.0, 175.0)
    sc.judge_notes = ["COMMS_LOST is latched by the rover safety supervisor (rover/motion.py)", "Link restore does NOT auto-resume"]
    return sc


def _environment(key: str, env: str, seed: int, title: str, summary: str):
    def build() -> Scenario:
        sc = make_environment(env, seed)
        sc.key, sc.title, sc.summary = key, title, summary
        sc.judge_notes = [f"seeded environment generator '{env}' (seed {seed}); same generator as the benchmark"]
        return sc
    return build


SCENARIOS = {
    "A": scenario_a, "B": scenario_b, "C": scenario_c, "D": scenario_d, "E": scenario_e,
    "W": _environment("W", "warehouse", 7, "W - Warehouse rescue", "Narrow rack aisles, fallen racks and a "
                      "mezzanine the drone cannot see under."),
    "K": _environment("K", "narrow_corridors", 3, "K - Collapsed indoor corridors", "0.6 m hospital corridors, "
                      "smoke, debris in the wards' approach."),
    "O": _environment("O", "open_outdoor", 5, "O - Outdoor search field", "Trails across open ground with "
                      "tree-canopy patches."),
    "M": _environment("M", "maze", 3, "M - Maze-like ruins", "Dead ends and few loops: routes are long and "
                      "debris can cut off whole branches."),
}

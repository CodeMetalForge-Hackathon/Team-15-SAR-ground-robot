"""Wire the simulator to the navigator, and define the deterministic scenarios A-H.

    python -m rover.simrun C          # print the final status JSON for scenario C
    python -m rover.simrun --list

Every distance printed is a SYNTHETIC graph weight in metres.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

from planner.graph import TrailGraph, load_graph
from rover.motion import EmergencyStop, MotionLimits, SafetySupervisor
from rover.navigator import SIM_TRUTH, UNKNOWN, NavConfig, Navigator, Pose, State
from rover.observations import ObservationLog
from rover.sensors import NoEchoPolicy
from rover.sim import SimConfig, SimDriver, SimObstacle, SimWorld

SIM_ROBOT_WIDTH_M = 0.20  # SYNTHETIC placeholder. Measure the real RoverC-Pro before any hardware use.


class SimIO:
    physical = False

    def __init__(self, world: SimWorld):
        self.w = world

    def clock(self) -> float:
        return self.w.t

    def read_range(self):
        return self.w.read_range()

    def read_heading(self):
        return self.w.read_heading()

    def read_power(self):
        return self.w.read_power()

    def read_camera(self):
        return self.w.read_camera()

    def bearing(self, a, b):
        return self.w.bearing(a, b)

    def pose(self) -> Pose:
        p = self.w.pose()
        if p is None:
            return Pose(UNKNOWN, self.w.t)
        return Pose(SIM_TRUTH, self.w.t, node=p["node"], edge=p["edge"], progress_m=p["s"])

    def traveled(self) -> dict:
        return {"value_m": round(self.w.odometer_m, 3), "kind": "SIMULATED_GROUND_TRUTH"}


@dataclass
class Sim:
    graph: TrailGraph
    world: SimWorld
    driver: SimDriver
    supervisor: SafetySupervisor
    log: ObservationLog
    nav: Navigator
    estop: EmergencyStop
    hooks: list = field(default_factory=list)  # (time_s, fn(sim)) fault injections

    def run(self, max_s: float = 1200.0, until: Optional[Callable[["Sim"], bool]] = None) -> "Sim":
        end = self.world.t + max_s
        while self.world.t < end:
            for h in list(self.hooks):
                if self.world.t >= h[0] - 1e-9:
                    self.hooks.remove(h)
                    h[1](self)
            self.nav.tick()
            self.world.step(self.driver.velocity)
            if until is not None and until(self):
                break
            if until is None and not self.nav.running:
                break
        return self

    def run_for(self, seconds: float) -> "Sim":
        return self.run(max_s=seconds, until=lambda s: False)


def build(start: str = "A", obstacles: Optional[list[SimObstacle]] = None, *, graph: Optional[TrailGraph] = None,
          side_clearance=None, auto_approve: bool = True, approve_motion: bool = True,
          limits: MotionLimits = MotionLimits(), heading_feedback: bool = True,
          no_echo_policy: NoEchoPolicy = NoEchoPolicy.CLEAR_TO_MAX, **nav_kw) -> Sim:
    """Build a simulation. ``no_echo_policy`` defaults to CLEAR_TO_MAX here because the synthetic
    world has no walls. Real hardware must keep the default UNKNOWN until it is bench-calibrated."""
    g = graph or load_graph()
    world = SimWorld(g, start, obstacles=obstacles, config=SimConfig(), side_clearance=side_clearance)
    world.heading_feedback = heading_feedback
    return build_for_world(world, g, auto_approve=auto_approve, approve_motion=approve_motion, limits=limits,
                           no_echo_policy=no_echo_policy, **nav_kw)


def build_for_world(world: SimWorld, nav_graph: TrailGraph, *, nav_cls: type = Navigator, auto_approve: bool = True,
                    approve_motion: bool = True, limits: MotionLimits = MotionLimits(),
                    no_echo_policy: NoEchoPolicy = NoEchoPolicy.CLEAR_TO_MAX, **nav_kw) -> Sim:
    """Wire a SimDriver, e-stop, supervisor, observation log and a Navigator (or subclass) to an existing
    SimWorld. SIMULATION ONLY: the driver is always SimDriver (physical=False), so the Navigator's
    simulation-only auto-approval is allowed. ``nav_graph`` may differ from the world's graph (e.g. a
    knowledge graph holding only corridors observed clear)."""
    driver = SimDriver()
    estop = EmergencyStop()
    sup = SafetySupervisor(driver, lambda: world.t, limits, estop)
    log = ObservationLog(lambda: world.t)
    cfg = NavConfig(robot_width_m=SIM_ROBOT_WIDTH_M, auto_approve=auto_approve,
                    no_echo_policy=no_echo_policy, **nav_kw)
    nav = nav_cls(nav_graph, SimIO(world), sup, log, cfg, mode="SIMULATION")
    if approve_motion:
        sup.approve_motion("sim-operator")
    return Sim(nav_graph, world, driver, sup, log, nav, estop)


# --- scenarios (synthetic distances, deterministic) ----------------------------------------
def scenario(name: str) -> Sim:
    n = name.upper()
    if n == "A":       # all clear, A->G 60 m
        s = build("A")
    elif n == "B":     # obstacle on D-E 5 m from D: stop, verify, mark D-E blocked
        s = build("A", [SimObstacle("box-DE", "D", "E", 5.0)], side_clearance={("D", "E"): (0.6, 2.0)})
    elif n == "C":     # same as B, then continue on the longer alternate D-K-L-M-G
        s = build("A", [SimObstacle("box-DE", "D", "E", 5.0)], side_clearance={("D", "E"): (0.6, 2.0)})
    elif n == "D":     # D-E and D-K both blocked: replan twice -> D-C-J-K-L-M-G
        s = build("A", [SimObstacle("box-DE", "D", "E", 5.0), SimObstacle("box-DK", "D", "K", 3.0)])
    elif n == "E":     # D-E and M-G blocked: no verified route to G -> SAFE_STOP
        s = build("A", [SimObstacle("box-DE", "D", "E", 5.0), SimObstacle("box-MG", "M", "G", 6.0)])
    elif n == "F":     # D-E blocked earlier, obstacle removed, clear verified independently -> 30 m route
        s = build("D", [SimObstacle("box-DE", "D", "E", 5.0, present=False)])
        s.log.add("ultrasonic_obstacle", "sim-ultrasonic", "CONFIRMED", dynamic=False, edge="D-E",
                  detail={"note": "from an earlier traversal"})
        # obstacle removed; a camera view reviewed by an operator independently verifies D-E is clear
        s.log.clear_edge("D-E", source="pi5-imx708+operator-review", operator="sim-operator",
                         evidence="fresh camera frame of D-E shows no obstacle (simulated)")
    elif n == "G":     # ultrasonic stops updating while moving on A-B -> SAFE_STOP (SENSOR_STALE)
        s = build("A")
        s.hooks.append((8.0, lambda sim: setattr(sim.world, "range_dropout", True)))
    elif n == "H":     # camera sees a person on C-D -> UNCONFIRMED observation, human review requested
        s = build("A", [SimObstacle("person-CD", "C", "D", 6.0, kind="person")])
    else:
        raise KeyError(f"unknown scenario {name}")
    s.nav.start("G")
    return s


SCENARIOS = "ABCDEFGH"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenario", nargs="?", default="A")
    p.add_argument("--list", action="store_true")
    a = p.parse_args(argv)
    if a.list:
        for n in SCENARIOS:
            print(n)
        return 0
    s = scenario(a.scenario).run()
    st = s.nav.status()
    st.pop("observations", None)
    print(json.dumps(st, indent=2, default=str))
    return 0 if st["state"] in (State.ARRIVED.value, State.SAFE_STOP.value,
                                State.CONTINUE_OR_REQUEST_OPERATOR.value) else 1


if __name__ == "__main__":
    sys.exit(main())

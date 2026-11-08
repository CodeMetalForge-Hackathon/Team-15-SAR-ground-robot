"""Dual-robot search-and-rescue SIMULATION: an aerial scout and a ground rescue rover.

Everything in this package is SIMULATED. It reuses the team's real algorithms:

  * ground: rover.navigator.Navigator (state machine), the rover safety supervisor (rover/motion.py),
    rover.observations.ObservationLog, planner.route.compute_route (Dijkstra), rover.sim.SimWorld physics
  * aerial: team15_starter fleet.planner (GridWorld belief, apply_look, FleetMCTS, explain)
    from PR #17, and sar.sensors presets

No motor, serial, GPIO or radio adapter is ever imported or opened here.
"""
from __future__ import annotations

import os
import sys

_STARTER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "team15_starter")
if _STARTER not in sys.path:
    # PR #17's aerial code imports its siblings as top-level packages (sar, fleet, link).
    sys.path.insert(0, _STARTER)

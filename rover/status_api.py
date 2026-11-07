"""Optional FastAPI router so the dashboard owner can mount rover status. Read-only, apart from e-stop.

    from rover.status_api import rover_router
    app.include_router(rover_router(get_navigator), prefix="/rover")

GET  /rover/status   -> Navigator.status()  (schema team15.rover_nav_status/1)
POST /rover/estop    -> trips the latched e-stop. There is deliberately NO endpoint that resets
                        it or starts motion. Those stay operator actions at the robot console.
"""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, HTTPException

from rover.navigator import Navigator

REQUIRED_STATUS_KEYS = (
    "schema", "t", "mode", "distances_label", "state", "state_detail", "destination", "route",
    "remaining_planned_m", "distances", "blocked_edges", "blockers", "reroutes", "last_reroute_reason",
    "latest_range", "sensor", "heading", "pose", "traveled", "motion", "safe_stop_reason",
    "operator_requests", "last_scan", "camera_requests", "suggested_viewpoints", "observations", "claims",
)


def rover_router(get_nav: Callable[[], Optional[Navigator]]) -> APIRouter:
    r = APIRouter()

    @r.get("/status")
    def status() -> dict:
        nav = get_nav()
        if nav is None:
            return {"schema": "team15.rover_nav_status/1", "state": "NOT_RUNNING",
                    "pose": {"source": "UNKNOWN"}, "claims": {"autonomous_navigation_operational": False}}
        return nav.status()

    @r.post("/estop")
    def estop(body: dict) -> dict:
        nav = get_nav()
        if nav is None:
            raise HTTPException(404, "no navigator")
        who = str(body.get("by", "")).strip() or "dashboard"
        nav.sup.estop.trip(f"dashboard e-stop by {who}")
        nav.sup.tick()
        return {"tripped": True, "reason": nav.sup.estop.reason}

    return r

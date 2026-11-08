"""Base-station dashboard: FastAPI app serving the browser map and /state.

Endpoints
- ``GET /``                         the map page (dashboard/static/index.html)
- ``GET /state``                    mission state JSON (tracks, history, routes, alerts, graph)
- ``POST /observations``            ingest one observation (the camera's JSON line)
- ``POST /operator_decision``       {"obs_id", "decision": CONFIRM|REJECT, "operator"}
- ``GET /evidence/{obs_id}``        display photo (annotated JPEG if present, else the frame)
- ``GET /evidence/{obs_id}/frame``  the exact, unannotated evidence frame
- ``GET /api/range``                 forward obstacle range card (team15.range_panel/1);
                                    DISCONNECTED when no source is configured or answers. Not the
                                    distance to any person candidate.

Photos are never stored in Git. ``/evidence`` serves a path from the
observation only if it is a JPEG/PNG inside one of the configured evidence
directories (``TEAM15_EVIDENCE_DIR``, ``os.pathsep``-separated). The browser
never sends a path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from core import range_view
from core.ingest import InvalidObservation
from core.store import InvalidDecision, MissionStore, UnknownObservation
from dashboard.range_source import RangeSource

STATIC = Path(__file__).resolve().parent / "static"
PHOTO_SUFFIXES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _roots(evidence_dir) -> list[Path]:
    if not evidence_dir:
        return []
    if isinstance(evidence_dir, (str, Path)):
        evidence_dir = [evidence_dir]
    return [Path(d).expanduser().resolve() for d in evidence_dir if str(d).strip()]


def create_app(store: MissionStore | None = None, evidence_dir=None,
               range_source: RangeSource | None = None) -> FastAPI:
    store = store if store is not None else MissionStore()
    range_source = range_source if range_source is not None else RangeSource()
    roots = _roots(evidence_dir)
    app = FastAPI(title="Team 15 base station")
    app.state.store = store

    def serve_photo(obs_id: str, keys: tuple[str, ...]) -> FileResponse:
        obs = store.observation(obs_id)
        ev = (obs or {}).get("evidence") or {}
        ref = next((ev[k] for k in keys if ev.get(k)), None)
        if not ref:
            raise HTTPException(404, "no photo for this observation")
        if not roots:
            raise HTTPException(404, "photo serving is off: no evidence directory configured")
        path = Path(ref).expanduser().resolve()
        if not any(path.is_relative_to(r) for r in roots) or \
                path.suffix.lower() not in PHOTO_SUFFIXES:
            raise HTTPException(404, "photo is outside the evidence directory")
        if not path.is_file():
            raise HTTPException(404, "photo file not found on this machine")
        return FileResponse(path, media_type=PHOTO_SUFFIXES[path.suffix.lower()],
                            headers={"Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store"})

    @app.get("/state")
    def state() -> dict:
        return store.state()

    @app.post("/observations")
    def post_observation(obs: dict) -> dict:
        try:
            return store.add_observation(obs)
        except InvalidObservation as e:
            raise HTTPException(status_code=422, detail=str(e)) from None

    @app.post("/operator_decision")
    def operator_decision(body: dict) -> dict:
        try:
            return store.decide(body.get("obs_id"), body.get("decision"), body.get("operator"))
        except InvalidDecision as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        except UnknownObservation:
            raise HTTPException(status_code=404, detail="unknown obs_id") from None

    @app.get("/api/range")
    def api_range(scenario: str | None = None, frame: int | None = None) -> dict:
        try:
            return range_source.view(scenario=scenario, frame=frame)
        except Exception as e:  # malformed data must never take the card down or read CLEAR
            return range_view.disconnected(f"unreadable range data: {type(e).__name__}",
                                           source="FIXTURE" if range_source.fixture_mode else "LIVE")

    @app.get("/evidence/{obs_id}")
    def evidence(obs_id: str) -> FileResponse:
        return serve_photo(obs_id, ("annotated_ref", "frame_ref"))

    @app.get("/evidence/{obs_id}/frame")
    def evidence_frame(obs_id: str) -> FileResponse:
        return serve_photo(obs_id, ("frame_ref",))

    return app


def app_from_env() -> FastAPI:
    """Build the app from TEAM15_* environment variables (used by uvicorn)."""
    store = MissionStore(responder_node=os.environ.get("TEAM15_RESPONDER_NODE", "A"))
    for path in filter(None, os.environ.get("TEAM15_OBSERVATIONS", "").split(os.pathsep)):
        for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
            if line.strip():
                store.add_observation(json.loads(line))
    dirs = [d for d in os.environ.get("TEAM15_EVIDENCE_DIR", "").split(os.pathsep) if d]
    env = os.environ.get
    rs = RangeSource(range_url=env("TEAM15_RANGE_URL") or None,
                     robot_url=env("TEAM15_ROBOT_URL") or None,
                     fixture=env("TEAM15_RANGE_FIXTURE") or None,
                     robot_fixture=env("TEAM15_ROBOT_FIXTURE") or None)
    return create_app(store, evidence_dir=dirs, range_source=rs)


app = app_from_env()

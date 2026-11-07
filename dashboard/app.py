"""Base-station dashboard: FastAPI app serving the browser map and /state.

Endpoints
- ``GET /``                   the map page (dashboard/static/index.html)
- ``GET /state``              mission state JSON (tracks, routes, graph)
- ``POST /observations``      ingest one observation (the bench camera's JSON line)
- ``GET /evidence/{obs_id}``  the observation's photo, read from local disk

Photos are never stored in Git. ``/evidence`` serves an observation's
``evidence.frame_ref`` only if that file is a JPEG/PNG inside the configured
evidence directory (``TEAM15_EVIDENCE_DIR``). The browser never sends a path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from core.ingest import InvalidObservation
from core.store import MissionStore

STATIC = Path(__file__).resolve().parent / "static"
PHOTO_SUFFIXES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def create_app(store: MissionStore | None = None, evidence_dir: str | Path | None = None) -> FastAPI:
    store = store if store is not None else MissionStore()
    evidence_root = Path(evidence_dir).expanduser().resolve() if evidence_dir else None
    app = FastAPI(title="Team 15 base station")
    app.state.store = store

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/state")
    def state() -> dict:
        return store.state()

    @app.post("/observations")
    def post_observation(obs: dict) -> dict:
        try:
            return store.add_observation(obs)
        except InvalidObservation as e:
            raise HTTPException(status_code=422, detail=str(e)) from None

    @app.get("/evidence/{obs_id}")
    def evidence(obs_id: str) -> FileResponse:
        obs = store.observation(obs_id)
        ref = ((obs or {}).get("evidence") or {}).get("frame_ref")
        if not ref:
            raise HTTPException(404, "no photo for this observation")
        if evidence_root is None:
            raise HTTPException(404, "photo serving is off: no evidence directory configured")
        path = Path(ref).expanduser().resolve()
        if not path.is_relative_to(evidence_root) or path.suffix.lower() not in PHOTO_SUFFIXES:
            raise HTTPException(404, "photo is outside the evidence directory")
        if not path.is_file():
            raise HTTPException(404, "photo file not found on this machine")
        return FileResponse(path, media_type=PHOTO_SUFFIXES[path.suffix.lower()],
                            headers={"Cache-Control": "no-store"})

    return app


def app_from_env() -> FastAPI:
    """Build the app from TEAM15_* environment variables (used by uvicorn)."""
    store = MissionStore(responder_node=os.environ.get("TEAM15_RESPONDER_NODE", "A"))
    for path in filter(None, os.environ.get("TEAM15_OBSERVATIONS", "").split(os.pathsep)):
        for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
            if line.strip():
                store.add_observation(json.loads(line))
    return create_app(store, evidence_dir=os.environ.get("TEAM15_EVIDENCE_DIR") or None)


app = app_from_env()

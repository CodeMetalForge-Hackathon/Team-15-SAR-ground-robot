"""Dual-robot rescue SIMULATION API, mounted on the existing dashboard app.

    GET  /rescue                       3D mission-control digital twin (dashboard/static/rescue/index.html)
    GET  /api/rescue/scenarios         selectable scenarios
    POST /api/rescue/reset             {"scenario": "A", "seed"?, "mode"?, "planner"?} -> static layout + state
    POST /api/rescue/step              {"sim_s": 0.5} advance the deterministic sim (fixed 0.05 s ticks)
    GET  /api/rescue/state             ?truth=1 adds simulator ground truth (viewer toggle; agents never see it)
    GET  /api/rescue/static            layout of the current mission
    POST /api/rescue/obstacle          drop debris ahead of the rover (SIMULATED event)
    POST /api/rescue/approve_probe     {"req_id", "operator"} sensor-gated probe of UNKNOWN corridors
    POST /api/rescue/report            {"qwen": true} build the rescue report (Qwen in a background thread)
    GET  /api/rescue/report            latest report
    GET  /api/rescue/evidence          REAL RECORDED CAMERA frames (bench recordings, not from this mission)
    GET  /api/rescue/evidence/{name}   one recorded frame (only from the evidence directory)

The simulation steps only when the browser asks, so pause = stop asking, and a given scenario and seed
always replays identically. Nothing here imports a motor, serial, GPIO or radio module.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from simulation.dual_rescue.mission import Mission
from simulation.dual_rescue.report import finish, prepare
from simulation.dual_rescue.scenarios import SCENARIOS

STATIC = Path(__file__).resolve().parent / "static" / "rescue"
MAX_STEP_S = 30.0
EVIDENCE_NAME = re.compile(r"^[A-Za-z0-9_.-]+_annotated\.jpg$")


class RescueSession:
    def __init__(self, qwen_url: Optional[str] = None, evidence_dir: Optional[str] = None):
        self.lock = threading.Lock()
        self.qwen_url = qwen_url
        self.evidence_dir = Path(evidence_dir).expanduser() if evidence_dir else None
        self.report_job: Optional[threading.Thread] = None
        self.reset("A")

    def reset(self, scenario: str = "A", seed: Optional[int] = None, mode: str = "coordinated",
              planner: str = "mcts") -> Mission:
        with self.lock:
            self.mission = Mission(scenario, seed=seed, mode=mode, planner=planner)
            self.report_status = "IDLE"
        return self.mission


def make_router(session: RescueSession) -> APIRouter:
    r = APIRouter()

    @r.get("/rescue", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    @r.get("/rescue/{path:path}")
    def asset(path: str) -> FileResponse:
        p = (STATIC / path).resolve()
        if not p.is_relative_to(STATIC) or not p.is_file() or p.suffix not in (".js", ".css", ".html", ".txt", ""):
            raise HTTPException(404, "not found")
        media = "text/javascript" if p.suffix == ".js" else "text/css" if p.suffix == ".css" else None
        return FileResponse(p, media_type=media)

    @r.get("/api/rescue/scenarios")
    def scenarios() -> list:
        out = []
        for k, f in SCENARIOS.items():
            sc = f()
            out.append({"key": k, "title": sc.title, "summary": sc.summary, "env": sc.layout.env,
                        "theme": sc.layout.theme, "seed": sc.seed})
        return out

    @r.post("/api/rescue/reset")
    def reset(body: dict) -> dict:
        try:
            m = session.reset(str(body.get("scenario", "A")), body.get("seed"), body.get("mode", "coordinated"),
                              body.get("planner", "mcts"))
        except (KeyError, ValueError) as e:
            raise HTTPException(422, str(e)) from None
        with session.lock:
            return {"static": m.static(), "state": m.snapshot()}

    @r.get("/api/rescue/static")
    def static() -> dict:
        with session.lock:
            return session.mission.static()

    @r.post("/api/rescue/step")
    def step(body: dict) -> dict:
        try:
            sim_s = float(body.get("sim_s", 0.5))
        except (TypeError, ValueError):
            raise HTTPException(422, "sim_s must be a number") from None
        sim_s = max(0.0, min(MAX_STEP_S, sim_s))
        with session.lock:
            m = session.mission
            if not m.done() and m.t < m.sc.max_t:
                m.run(sim_s)
            return m.snapshot(truth=bool(body.get("truth")), since_msg=int(body.get("since", 0)))

    @r.get("/api/rescue/state")
    def state(truth: int = 0, since: int = 0) -> dict:
        with session.lock:
            return session.mission.snapshot(truth=bool(truth), since_msg=since)

    @r.post("/api/rescue/obstacle")
    def obstacle() -> dict:
        with session.lock:
            return session.mission.add_obstacle()

    @r.post("/api/rescue/approve_probe")
    def approve(body: dict) -> dict:
        with session.lock:
            try:
                return session.mission.coord.approve_probe(str(body.get("req_id", "")), str(body.get("operator", "")))
            except PermissionError as e:
                raise HTTPException(403, str(e)) from None
            except KeyError:
                raise HTTPException(404, "no pending request with that id") from None

    @r.post("/api/rescue/report")
    def report(body: dict) -> dict:
        use_qwen = bool(body.get("qwen", True)) and bool(session.qwen_url)
        with session.lock:
            m = session.mission
            prep = prepare(m)                       # snapshot under the lock
            m.report = finish(prep)                 # deterministic, immediate
            if use_qwen:
                m.report["qwen_status"] = "PENDING (Qwen request in flight)"
            out = m.report
        if use_qwen and (session.report_job is None or not session.report_job.is_alive()):
            def job(mission=m, prep=prep):
                rep = finish(prep, qwen_url=session.qwen_url)      # no lock: works on the snapshot only
                with session.lock:
                    if mission is session.mission:
                        mission.report = rep
            session.report_job = threading.Thread(target=job, daemon=True)
            session.report_job.start()
        return out

    @r.get("/api/rescue/report")
    def report_get() -> dict:
        with session.lock:
            return session.mission.report or {"qwen_status": "NOT_REQUESTED"}

    @r.get("/api/rescue/evidence")
    def evidence() -> dict:
        d = session.evidence_dir
        items = []
        if d is not None and d.is_dir():
            for p in sorted(d.glob("*_annotated.jpg"))[:12]:
                items.append({"name": p.name, "url": f"/api/rescue/evidence/{p.name}",
                              "recorded": int(p.stat().st_mtime)})
        return {"label": "REAL RECORDED CAMERA - Raspberry Pi 5 + IMX708 bench recordings (Faster R-CNN person "
                         "detector). NOT captured during this simulated mission. Camera distances are "
                         "UNCALIBRATED estimates.", "dir_configured": d is not None, "frames": items}

    @r.get("/api/rescue/evidence/{name}")
    def evidence_file(name: str) -> FileResponse:
        d = session.evidence_dir
        if d is None or not EVIDENCE_NAME.match(name):
            raise HTTPException(404, "not found")
        p = (d / name).resolve()
        if not p.is_relative_to(d.resolve()) or not p.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    return r


def session_from_env() -> RescueSession:
    return RescueSession(qwen_url=os.environ.get("TEAM15_QWEN_URL") or None,
                         evidence_dir=os.environ.get("TEAM15_RESCUE_EVIDENCE_DIR") or None)

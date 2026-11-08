"""Start the dashboard, optionally with earlier observation files preloaded.

    python3 -m dashboard.serve
    python3 -m dashboard.serve --observation ~/Documents/Team-15-evidence/camera/D1-b1-000001.json
    python3 -m dashboard.serve --range-fixture ~/Documents/Team-15-Robot/fixtures/sim_range_series_approach.json

Live camera sightings arrive through ``POST /observations``. Pipe the camera
into ``core.camera_bridge`` to forward them.

Photos may be served only from the evidence directories: the camera's default
``~/Team15_evidence/camera``, the folder of each ``--observation`` file, and any
``--evidence-dir``. Binds to 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

# Same default as perception/sightings.py DEFAULT_EVIDENCE_DIR (not imported: that pulls in cv2).
CAMERA_EVIDENCE_DIR = "~/Team15_evidence/camera"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Team 15 base-station dashboard")
    p.add_argument("--observation", action="append", default=[],
                   help="JSON/JSONL file with observation(s) to load at start (repeatable)")
    p.add_argument("--evidence-dir", action="append", default=[],
                   help="extra folder photos may be served from (repeatable)")
    p.add_argument("--range-fixture", default=None,
                   help="SIMULATED range fixture for the Forward obstacle range card "
                        "(series / scenarios / single snapshot)")
    p.add_argument("--robot-fixture", default=None,
                   help="SIMULATED team15.robot_status/1 fixture (forward_range, claims)")
    p.add_argument("--range-url", default=None,
                   help="live ranging service, no default (the Mac's :8765 is an unrelated app); "
                        "e.g. http://127.0.0.1:18765/range via ssh -L 18765:127.0.0.1:8765 <pi>")
    p.add_argument("--robot-url", default=None,
                   help="live robot API, no default; e.g. http://127.0.0.1:8770/robot/status")
    p.add_argument("--responder", default="A", help="responder's current node (default A)")
    p.add_argument("--qwen-url", default=None,
                   help="Team-15-Qwen advisory service for the /rescue report, e.g. http://127.0.0.1:8090 "
                        "(optional; without it the report is DETERMINISTIC)")
    p.add_argument("--rescue-evidence-dir", default=None,
                   help="folder of REAL RECORDED camera frames (*_annotated.jpg) shown on /rescue")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    obs_files = [str(Path(f).expanduser().resolve()) for f in a.observation]
    dirs = [CAMERA_EVIDENCE_DIR, *(str(Path(f).parent) for f in obs_files), *a.evidence_dir]
    dirs = list(dict.fromkeys(str(Path(d).expanduser()) for d in dirs))
    os.environ["TEAM15_OBSERVATIONS"] = os.pathsep.join(obs_files)
    os.environ["TEAM15_EVIDENCE_DIR"] = os.pathsep.join(dirs)
    os.environ["TEAM15_RESPONDER_NODE"] = a.responder
    for var, val in (("TEAM15_RANGE_FIXTURE", a.range_fixture), ("TEAM15_ROBOT_FIXTURE", a.robot_fixture)):
        os.environ[var] = str(Path(val).expanduser().resolve()) if val else ""
    os.environ["TEAM15_RANGE_URL"] = a.range_url or ""
    os.environ["TEAM15_ROBOT_URL"] = a.robot_url or ""
    os.environ["TEAM15_QWEN_URL"] = a.qwen_url or ""
    os.environ["TEAM15_RESCUE_EVIDENCE_DIR"] = str(Path(a.rescue_evidence_dir).expanduser()) if a.rescue_evidence_dir else ""

    import uvicorn
    print(f"Dashboard: http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.port}/")
    print(f"Dual-robot rescue SIMULATION: http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.port}/rescue")
    print("Evidence dirs: " + ", ".join(dirs))
    print("Forward obstacle range: " + (f"SIMULATED fixture {a.range_fixture or a.robot_fixture}"
                                        if (a.range_fixture or a.robot_fixture)
                                        else ", ".join(filter(None, (a.range_url, a.robot_url)))
                                        or "no source configured (card reads DISCONNECTED)"))
    uvicorn.run("dashboard.app:app", host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

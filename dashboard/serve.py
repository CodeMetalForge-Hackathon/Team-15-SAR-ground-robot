"""Start the dashboard, optionally with earlier observation files preloaded.

    python3 -m dashboard.serve
    python3 -m dashboard.serve --observation ~/Documents/Team-15-evidence/camera/D1-b1-000001.json

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
    p.add_argument("--responder", default="A", help="responder's current node (default A)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    obs_files = [str(Path(f).expanduser().resolve()) for f in a.observation]
    dirs = [CAMERA_EVIDENCE_DIR, *(str(Path(f).parent) for f in obs_files), *a.evidence_dir]
    dirs = list(dict.fromkeys(str(Path(d).expanduser()) for d in dirs))
    os.environ["TEAM15_OBSERVATIONS"] = os.pathsep.join(obs_files)
    os.environ["TEAM15_EVIDENCE_DIR"] = os.pathsep.join(dirs)
    os.environ["TEAM15_RESPONDER_NODE"] = a.responder

    import uvicorn
    print(f"Dashboard: http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.port}/")
    print("Evidence dirs: " + ", ".join(dirs))
    uvicorn.run("dashboard.app:app", host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

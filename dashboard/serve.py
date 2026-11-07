"""Start the dashboard with one or more observation files preloaded.

    python3 -m dashboard.serve --observation ~/Documents/Team-15-evidence/camera/D1-b1-000001.json

The evidence directory (where photos may be served from) defaults to the folder
holding the first observation file. Binds to 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Team 15 base-station dashboard")
    p.add_argument("--observation", action="append", default=[],
                   help="JSON/JSONL file with observation(s) to load at start (repeatable)")
    p.add_argument("--evidence-dir", default=None,
                   help="folder photos may be served from (default: folder of the first --observation)")
    p.add_argument("--responder", default="A", help="responder's current node (default A)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    obs_files = [str(Path(f).expanduser().resolve()) for f in a.observation]
    evidence = a.evidence_dir or (str(Path(obs_files[0]).parent) if obs_files else "")
    os.environ["TEAM15_OBSERVATIONS"] = os.pathsep.join(obs_files)
    os.environ["TEAM15_EVIDENCE_DIR"] = str(Path(evidence).expanduser()) if evidence else ""
    os.environ["TEAM15_RESPONDER_NODE"] = a.responder

    import uvicorn
    print(f"Dashboard: http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.port}/")
    uvicorn.run("dashboard.app:app", host=a.host, port=a.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

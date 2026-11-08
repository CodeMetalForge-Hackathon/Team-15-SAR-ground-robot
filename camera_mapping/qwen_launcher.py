"""Start the Team-15-Qwen advisory service (RAG + guard) for the camera demo.

    python3 -B -m camera_mapping.qwen_launcher --qwen-root ~/Documents/Team-15-Qwen \\
        --port 8090 --model qwen3.5:2b-q4_K_M

Why a launcher: ``rescue_qwen.service`` builds its in-memory SQLite FTS index in
the main thread, but FastAPI runs sync endpoints in worker threads, so every
C_QWEN_RAG request fails with ``sqlite3.ProgrammingError`` (seen 2026-11-08).
This launcher opens SQLite connections with ``check_same_thread=False``. That is
safe here: the index is read-only after it is built, and this Python's SQLite is
built serialized (``sqlite3.threadsafety == 3``). The launcher refuses to run
otherwise. The proper fix belongs in Team-15-Qwen; nothing there is modified.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--qwen-root", default=os.path.expanduser("~/Documents/Team-15-Qwen"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--config", default="C_QWEN_RAG", choices=["A_DETERMINISTIC", "B_QWEN_BASE", "C_QWEN_RAG"])
    ap.add_argument("--model", default="qwen3.5:2b-q4_K_M")
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ap.add_argument("--timeout-s", type=float, default=15.0)
    a = ap.parse_args(argv)
    if sqlite3.threadsafety != 3:
        print("refusing: sqlite3 is not built serialized (threadsafety != 3)", file=sys.stderr)
        return 2
    _connect = sqlite3.connect

    def connect(*args, **kw):
        kw.setdefault("check_same_thread", False)
        return _connect(*args, **kw)

    sqlite3.connect = connect
    sys.path.insert(0, os.path.abspath(os.path.expanduser(a.qwen_root)))
    from rescue_qwen.llm.backend import OllamaBackend
    from rescue_qwen.service import create_app
    import uvicorn

    be = OllamaBackend(a.model, a.ollama_url, timeout_s=a.timeout_s)
    print(f"Qwen advisory service: http://{a.host}:{a.port}/ config={a.config} model={be.model_id} "
          f"(advisory only; no motor authority)", flush=True)
    uvicorn.run(create_app(be, a.config), host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

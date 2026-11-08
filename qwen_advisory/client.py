"""Advisory client: ask an optional Qwen service, guard the answer, always return a displayable advisory.

    from qwen_advisory.client import lidar_advisory, http_model
    rec = lidar_advisory(context, model=http_model("http://127.0.0.1:8090/lidar_advisory"))

* `model` is any callable(context) -> dict (the model's JSON). None = no model (deterministic only).
* Hard timeout (default 8 s), any exception, invalid schema, or a critical guard finding -> the deterministic
  advisory is returned instead, with the reason. This function never raises and never blocks the caller beyond
  the timeout. The record is display-only: `authority` is always "NONE".
"""
from __future__ import annotations

import concurrent.futures as _cf
import json
import urllib.request
from typing import Callable, Optional

from qwen_advisory import lidar as L


def http_model(url: str, timeout_s: float = 8.0) -> Callable[[dict], dict]:
    def call(context: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps({"context": context}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read())
    return call


def lidar_advisory(context: dict, model: Optional[Callable[[dict], dict]] = None, timeout_s: float = 8.0,
                   retrieved_ids: Optional[set] = None) -> dict:
    deterministic = L.reference_policy(context)
    base = {"schema_version": L.SCHEMA_VERSION, "advisory_only": True, "authority": "NONE",
            "simulated": (context.get("lidar") or {}).get("source_mode") == "SIMULATED"}
    if model is None:
        return dict(base, advisory=deterministic, source="DETERMINISTIC", issues=["no model configured"])
    ex = _cf.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(model, context)
    try:
        raw = fut.result(timeout=timeout_s)
    except _cf.TimeoutError:
        return dict(base, advisory=deterministic, source="DETERMINISTIC_FALLBACK", issues=[f"model timed out after {timeout_s} s"])
    except Exception as e:  # noqa: BLE001 - any model failure falls back
        return dict(base, advisory=deterministic, source="DETERMINISTIC_FALLBACK", issues=[f"model error: {type(e).__name__}"])
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    g = L.guard(raw, context, set(retrieved_ids or ()))
    if g["critical"]:
        return dict(base, advisory=deterministic, source="DETERMINISTIC_FALLBACK", issues=g["critical"] + g["corrected"])
    return dict(base, advisory=g["output"], source="QWEN_GUARDED", issues=g["corrected"])

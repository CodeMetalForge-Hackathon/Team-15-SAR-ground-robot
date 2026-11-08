"""Qwen3.5-2B (+ Team-15 rescue LoRA) rover advisor. ADVISORY ONLY: it returns a proposal, never drives.

Reuses Team-15-Qwen verbatim: HFBackend (transformers + PEFT on MPS), TOOL_SYSTEM / render_tool_user
(the exact prompt the adapter was trained and evaluated with), RescueIndex RAG and validate_args.
Run under the Qwen repo's .venv-lora:

  ~/Documents/Team-15-Qwen/.venv-lora/bin/python scripts/qwen_rover_advisor.py --port 8095 \
      --adapter ~/Documents/Team-15-Qwen/lora/out/rescue-lora-v0.2-run2/ckpt-0088       # QWEN + LoRA
  ... --base                                                                             # BASE QWEN

POST /v1/advise  {"perception": <team15.camera_perception/1 view>, "rover": <rover host status>,
                  "objective": str}
  -> {"schema": "team15.qwen_rover_advice/1", "action": STOP|REQUEST_FORWARD|REQUEST_BACKWARD|REQUEST_LEFT|
      REQUEST_RIGHT|REQUEST_OPERATOR_REVIEW, "explanation", "model": {...}, "steps": [...], "fallback": bool}
GET  /health     -> model id, adapter path + SHA-256, adapter_active_verified, load + verification evidence

The process has no serial device, no motor import and no Pi credentials. Every proposal is evaluated again by
the deterministic camera veto and safety supervisor on the Pi. Errors, timeouts and invalid output -> STOP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCHEMA = "team15.qwen_rover_advice/1"
ACTIONS = ("STOP", "REQUEST_FORWARD", "REQUEST_BACKWARD", "REQUEST_LEFT", "REQUEST_RIGHT", "REQUEST_OPERATOR_REVIEW")
MAX_MODEL_STEPS = 2
OBJECTIVE = "Search the room ahead for people; report possible persons to the operator; never move unsafely."


# --- mapping from the trained rescue-tools/0.1 contract to the strict rover action schema ---------------------
def map_step(step: dict) -> tuple[str | None, str]:
    """(action, why) for a terminal step, or (None, '') for an observation call the advisor should answer."""
    if not isinstance(step, dict):
        return "STOP", "model output is not a JSON object"
    if step.get("step") == "FINAL":
        ra = step.get("recommended_action")
        if ra == "REQUEST_DETERMINISTIC_STOP":
            return "STOP", f"FINAL {ra}"
        return "REQUEST_OPERATOR_REVIEW", f"FINAL {ra}"
    tool, args = step.get("tool"), step.get("args") or {}
    if tool == "request_stop":
        return "STOP", f"request_stop: {args.get('reason', '')}"
    if tool == "request_bounded_move" and args.get("direction") == "FORWARD":
        return "REQUEST_FORWARD", "request_bounded_move FORWARD"
    if tool == "request_directional_scan" and args.get("direction") in ("LEFT", "RIGHT"):
        return f"REQUEST_{args['direction']}", f"request_directional_scan {args['direction']}"
    if tool == "request_operator_approval":
        return "REQUEST_OPERATOR_REVIEW", f"request_operator_approval {args.get('action')}: {args.get('reason', '')}"
    if isinstance(tool, str) and tool.startswith("get_") or tool == "plan_shortest_route":
        return None, ""
    return "STOP", f"unmappable step {str(step)[:120]}"


def observe(tool: str, perception: dict, rover: dict) -> dict:
    """Answer the model's observation tools from REAL inputs, labelled with their source."""
    p, r = perception or {}, rover or {}
    if tool == "get_robot_state":
        v = r.get("camera_verdict") or {}
        return {"source_mode": r.get("label", "UNKNOWN"), "estop_engaged": bool((r.get("estop") or {}).get("tripped")),
                "link": r.get("link", "UNKNOWN"), "motor_controller_verified": bool(r.get("physical")),
                "battery_pct": None, "battery_note": "no battery sensor: UNKNOWN",
                "active_command": r.get("active_command"), "safety_latch": r.get("safety_latch"),
                "camera_gate": v.get("action"), "localization": "UNKNOWN (no odometry)"}
    if tool == "get_camera_observation":
        objs = [{"class": o.get("object_class"), "score": o.get("detection_confidence"),
                 "bearing_deg": (o.get("distance") or {}).get("bearing_deg"),
                 "distance": (o.get("distance") or {}).get("label", "UNKNOWN"),
                 "corridor": o.get("corridor_position"), "validity": o.get("validity")}
                for o in (p.get("objects") or [])[:8]]
        return {"source_mode": p.get("source_mode"), "fresh": p.get("fresh"), "age_s": p.get("age_s"),
                "calibration": p.get("calibration_status"), "objects": objs,
                "corridor": (p.get("assessment") or {}).get("status"),
                "candidate_paths": [{"name": c.get("name"), "status": c.get("status")} for c in p.get("candidates") or []],
                "note": "camera estimate; detections are UNCONFIRMED; distances UNKNOWN unless calibrated"}
    if tool == "get_ultrasonic_range":
        return {"error": "UNAVAILABLE", "detail": "no range sensor is connected to this rover"}
    if tool in ("get_current_route", "get_blocked_edges", "plan_shortest_route"):
        return {"error": "UNAVAILABLE", "detail": "no route graph in this prototype; camera candidate paths only"}
    return {"error": "UNAVAILABLE", "detail": f"{tool} not available"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Advisor:
    def __init__(self, qwen_root: str, adapter: str | None, rag: bool = True, timeout_s: float = 20.0):
        sys.path.insert(0, str(Path(qwen_root).expanduser()))
        from rescue_qwen.llm.hf_backend import HFBackend
        from rescue_qwen.llm.tool_prompts import TOOL_SYSTEM, render_tool_user
        from rescue_qwen.tools import validate_args
        self.TOOL_SYSTEM, self.render, self.validate = TOOL_SYSTEM, render_tool_user, validate_args
        self.index = None
        self.rag = rag
        # SQLite (the RAG index) is bound to the thread that created it: one worker thread owns the index and runs
        # every inference, so requests are also serialised on the single MPS model.
        from concurrent.futures import ThreadPoolExecutor
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qwen")
        if rag:
            self.pool.submit(self._build_index).result()
        self.adapter_path = str(Path(adapter).expanduser()) if adapter else None
        self.adapter_sha = sha256(Path(self.adapter_path) / "adapter_model.safetensors") if adapter else None
        t0 = time.time()
        self.be = HFBackend(self.adapter_path, max_new_tokens=200)
        self.load_s = round(time.time() - t0, 1)
        self.timeout_s = timeout_s
        self.lock = threading.Lock()
        self.verification = self._verify()

    def _build_index(self):
        from rescue_qwen.rag.index import RescueIndex, select_context
        self.index, _ = RescueIndex.build(":memory:")
        self.select = select_context

    @property
    def label(self) -> str:
        return "QWEN + LoRA" if self.adapter_path else "BASE QWEN"

    def model_info(self) -> dict:
        return {"label": self.label, "model_id": self.be.model_id, "adapter_path": self.adapter_path,
                "adapter_sha256": self.adapter_sha, "rag": self.rag, "load_s": self.load_s,
                "adapter_active_verified": self.verification.get("adapter_changes_logits") if self.adapter_path else None}

    def _verify(self) -> dict:
        """Prove (not assume) the adapter is active: PEFT wrapper + LoRA modules present, and the adapter changes the
        next-token logits versus the SAME weights with the adapter disabled, on a trained-format prompt."""
        torch = self.be.torch
        m = self.be.model
        out = {"peft_wrapped": type(m).__name__, "lora_modules": sum(1 for n, _ in m.named_modules() if n.endswith("lora_A"))}
        if not self.adapter_path:
            return out
        row = {"request": "Check the robot before moving.", "goal": "A", "history": []}
        prompt = self.be.proc.apply_chat_template(
            [{"role": "system", "content": self.TOOL_SYSTEM}, {"role": "user", "content": [{"type": "text", "text": self.render(row, None)}]}],
            add_generation_prompt=True, tokenize=False, enable_thinking=False)
        enc = self.be.proc(text=[prompt], return_tensors="pt").to(self.be.dev)
        with torch.no_grad():
            a = m(**enc).logits[0, -1].float()
            with m.disable_adapter():
                b = m(**enc).logits[0, -1].float()
        out.update({"active_adapters": list(getattr(m, "active_adapters", []) or []),
                    "max_abs_logit_diff": round(float((a - b).abs().max()), 4),
                    "top1_with_adapter": self.be.proc.tokenizer.decode([int(a.argmax())]),
                    "top1_without_adapter": self.be.proc.tokenizer.decode([int(b.argmax())])})
        out["adapter_changes_logits"] = out["max_abs_logit_diff"] > 1e-3 and out["lora_modules"] > 0
        return out

    def advise(self, body: dict) -> dict:
        return self.pool.submit(self._advise, body).result(timeout=self.timeout_s + 60)

    def _advise(self, body: dict) -> dict:
        t0 = time.time()
        p, r = body.get("perception") or {}, body.get("rover") or {}
        history = []
        for tool in ("get_robot_state", "get_camera_observation", "get_ultrasonic_range"):   # already observed
            history.append({"call": {"step": "TOOL_CALL", "tool": tool, "args": {}}, "gate": {"decision": "ACCEPT"},
                            "result": observe(tool, p, r)})
        row = {"request": body.get("objective") or OBJECTIVE, "goal": "A", "history": history}
        steps, action, why, fallback = [], None, "", False
        if True:
            for _ in range(MAX_MODEL_STEPS):
                if time.time() - t0 > self.timeout_s:
                    action, why, fallback = "STOP", "advisor timeout", True
                    break
                src = None
                if self.index is not None:
                    q = row["request"] + " " + json.dumps(history[-1]["result"])[:400] + " tool gate robot"
                    src = self.select(self.index.search(q, k=6), max_chunks=3, max_chars=1800)
                res = self.be.chat(self.TOOL_SYSTEM, self.render(row, src), schema=None, max_tokens=200)
                step = res.get("parsed")
                steps.append({"raw": res.get("text", "")[:600], "parsed": step, "latency_ms": res.get("latency_ms"),
                              "rag_sources": [s["chunk_id"] for s in src or []]})
                if not isinstance(step, dict):
                    action, why, fallback = "STOP", "model output not parseable JSON", True
                    break
                if step.get("step") == "TOOL_CALL":
                    errs = self.validate(step.get("tool"), step.get("args") or {})
                    if errs:
                        action, why, fallback = "STOP", "invalid tool call: " + "; ".join(errs), True
                        break
                action, why = map_step(step)
                if action is not None:
                    break
                tool = step.get("tool")
                history.append({"call": step, "gate": {"decision": "ACCEPT"}, "result": observe(tool, p, r)})
            if action is None:
                action, why, fallback = "REQUEST_OPERATOR_REVIEW", "no decision within the step budget", True
        last = (steps[-1]["parsed"] if steps else None) or {}
        expl = last.get("summary") or (last.get("args") or {}).get("reason") or why
        return {"schema": SCHEMA, "t": round(time.time(), 3), "action": action, "explanation": str(expl)[:600],
                "mapped_from": why, "fallback": fallback, "authority": "NONE", "advisory_only": True,
                "inputs": {"camera_source": p.get("source_mode"), "camera_age_s": p.get("age_s"),
                           "rover": r.get("label"), "objects": len(p.get("objects") or [])},
                "model": self.model_info(), "steps": steps, "latency_ms": int((time.time() - t0) * 1000)}


def serve(adv: Advisor, host: str, port: int, log_path: str | None):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            b = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True, "advisory_only": True, **adv.model_info(),
                                        "verification": adv.verification})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/advise":
                return self._send(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 2_000_000:
                    return self._send(413, {"error": "too large"})
                body = json.loads(self.rfile.read(n) or b"{}")
                out = adv.advise(body)
            except Exception as e:  # noqa: BLE001 - any failure is a STOP proposal, never a crash or a move
                out = {"mapped_from": "advisor error", "schema": SCHEMA, "t": round(time.time(), 3), "action": "STOP", "fallback": True,
                       "explanation": f"advisor error: {type(e).__name__}", "authority": "NONE",
                       "advisory_only": True, "model": adv.model_info(), "steps": []}
            if log_path:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(out, default=str) + "\n")
            self._send(200, out)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, port), H)
    print(f"qwen_rover_advisor: {adv.label} {adv.be.model_id} on http://{host}:{port}", flush=True)
    print("verification:", json.dumps(adv.verification), flush=True)
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qwen-root", default="~/Documents/Team-15-Qwen")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--adapter", help="LoRA adapter dir (e.g. .../rescue-lora-v0.2-run2/ckpt-0088)")
    g.add_argument("--base", action="store_true", help="base Qwen3.5-2B, no adapter (labelled BASE QWEN)")
    ap.add_argument("--no-rag", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--log", default=None, help="append every advice record (JSONL)")
    a = ap.parse_args()
    adv = Advisor(a.qwen_root, None if a.base else a.adapter, rag=not a.no_rag)
    if a.adapter and not adv.verification.get("adapter_changes_logits"):
        print("ADAPTER NOT VERIFIED ACTIVE: refusing to serve it as QWEN + LoRA", file=sys.stderr)
        sys.exit(4)
    serve(adv, a.host, a.port, a.log and os.path.expanduser(a.log))


if __name__ == "__main__":
    main()

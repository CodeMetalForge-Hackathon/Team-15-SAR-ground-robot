"""Mac orchestrator: live perception -> Pi rover host (signed), Qwen advice -> Pi (as a request), dashboard status.

  python3 scripts/ai_rover_session.py --pi http://100.97.93.118:8765 --demo20      # scripted 20 s session
  python3 scripts/ai_rover_session.py --pi http://100.97.93.118:8765 --faults      # fault drills (mock motors)
  python3 scripts/ai_rover_session.py --pi http://100.97.93.118:8765               # forward + status only

Inputs come from the running dashboard (/api/perception: the live Pi camera via camera_mapping.live).
Qwen advice comes from scripts/qwen_rover_advisor.py (QWEN + LoRA or BASE QWEN, as its /health reports).
Qwen proposals go to the Pi with origin="qwen": the Pi accepts STOP from anyone and refuses every motion request
that is not from a named operator. Nothing here can open a serial port or reach a motor object.
Every input, proposal, command, decision and status snapshot is appended to <out>/session.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rover import link  # noqa: E402
from rover.remote import PiClient  # noqa: E402

OPERATOR = "operator-on-site"


def http_json(url: str, body=None, timeout: float = 1.0):
    try:
        data = None if body is None else json.dumps(body, default=str).encode()
        req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__, "detail": str(e)[:200]}


class Session:
    def __init__(self, a):
        self.a = a
        self.pi = PiClient(a.pi, link.load_key(a.key))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.out = Path(os.path.expanduser(a.out)) / stamp
        self.out.mkdir(parents=True, exist_ok=True)
        self.log_f = open(self.out / "session.jsonl", "a", encoding="utf-8")
        self.t0 = time.time()
        self.forward = True            # forward perception (False simulates a stalled camera path)
        self.link_alive = True         # False simulates the Mac dropping off the network
        self.stop_ev = threading.Event()
        self.last_status: dict = {}
        self.last_advice: dict = {}
        self.lock = threading.Lock()

    def log(self, kind: str, **kw):
        rec = {"t": round(time.time(), 3), "t_rel": round(time.time() - self.t0, 2), "kind": kind, **kw}
        with self.lock:
            self.log_f.write(json.dumps(rec, default=str) + "\n")
            self.log_f.flush()
        brief = {k: v for k, v in kw.items() if k in ("cmd", "origin", "accepted", "reason", "action", "label",
                                                      "camera", "verdict", "wheels", "note", "model")}
        print(f"[{rec['t_rel']:6.2f}s] {kind:10s} {json.dumps(brief, default=str)[:230]}", flush=True)
        return rec

    # --- background: perception forwarding (doubles as heartbeat) + status mirroring ------------------
    def pump(self):
        n = 0
        while not self.stop_ev.is_set():
            if self.link_alive:
                st = http_json(self.a.dashboard + "/api/perception", timeout=0.5)
                ok = isinstance(st, dict) and st.get("schema") == "team15.camera_perception/1"
                self.pi.perception(st if (ok and self.forward) else None) if self.forward else self.pi.heartbeat()
                if n % 2 == 0:
                    s = self.pi.status()
                    if "error" not in s:
                        self.last_status = s
                        s2 = dict(s, qwen=self._advice_brief())
                        http_json(self.a.dashboard + "/api/rover/state", s2, timeout=0.5)
            n += 1
            time.sleep(0.2)

    def _advice_brief(self):
        a = self.last_advice or {}
        m = a.get("model") or {}
        return {"action": a.get("action"), "explanation": a.get("explanation"), "label": m.get("label"),
                "model_id": m.get("model_id"), "adapter_sha256": m.get("adapter_sha256"),
                "fallback": a.get("fallback"), "latency_ms": a.get("latency_ms"), "t": a.get("t")} if a else None

    def snapshot(self, why: str):
        s = self.pi.status()
        v = s.get("camera_verdict") or {}
        ctl = s.get("controller") or {}
        self.log("STATUS", note=why, label=s.get("label"), link=s.get("link"), cmd=s.get("active_command"),
                 wheels=ctl.get("motor_registers"), controller=ctl, estop=s.get("estop"), latch=s.get("safety_latch"),
                 verdict={"action": v.get("action"), "reason": v.get("reason"), "source": v.get("source_mode"),
                          "age_s": v.get("age_s"), "operator": v.get("operator"), "suggestion": v.get("suggestion")})
        return s

    def camera_check(self):
        p = http_json(self.a.dashboard + "/api/perception", timeout=1.0)
        objs = [(o.get("object_class"), round(o.get("detection_confidence") or 0, 3),
                 (o.get("distance") or {}).get("bearing_deg"), (o.get("distance") or {}).get("label"))
                for o in (p.get("objects") or [])]
        self.log("CAMERA", camera={"source": p.get("source_mode"), "fresh": p.get("fresh"), "age_s": p.get("age_s"),
                                   "frame_seq": p.get("frame_seq"), "calibration": p.get("calibration_status"),
                                   "corridor": (p.get("assessment") or {}).get("status"), "objects": objs})
        return p

    def ask_qwen(self):
        p = http_json(self.a.dashboard + "/api/perception", timeout=1.0)
        adv = http_json(self.a.advisor + "/v1/advise", {"perception": p, "rover": self.last_status or self.pi.status()},
                        timeout=self.a.qwen_timeout_s)
        if adv.get("schema") != "team15.qwen_rover_advice/1":
            adv = {"schema": "team15.qwen_rover_advice/1", "action": "STOP", "fallback": True, "t": time.time(),
                   "explanation": f"Qwen advisor unavailable ({adv.get('error')}): defined fallback is STOP",
                   "model": {"label": "NONE (advisor unreachable)"}}
        self.last_advice = adv
        m = adv.get("model") or {}
        self.log("QWEN", action=adv.get("action"), explanation=adv.get("explanation"), fallback=adv.get("fallback"),
                 model={"label": m.get("label"), "model_id": m.get("model_id"), "adapter_sha256": m.get("adapter_sha256"),
                        "adapter_active_verified": m.get("adapter_active_verified")},
                 latency_ms=adv.get("latency_ms"), full=adv)
        return adv

    def cmd(self, name, origin="operator", **kw):
        r = self.pi.command(name, origin=origin, operator=OPERATOR if origin == "operator" else None, **kw)
        self.log("COMMAND", cmd=name, origin=origin, args=kw, accepted=r.get("accepted"), reason=r.get("reason") or r.get("error"))
        return r

    def submit_proposal(self, adv):
        a = adv.get("action")
        mapping = {"STOP": ("STOP", {}), "REQUEST_FORWARD": ("MOVE_FORWARD", {"speed": 0.15, "duration_s": 0.3}),
                   "REQUEST_BACKWARD": ("MOVE_BACKWARD", {"speed": 0.15, "duration_s": 0.3}),
                   "REQUEST_LEFT": ("TURN_LEFT", {"speed": 0.15, "duration_s": 0.3}),
                   "REQUEST_RIGHT": ("TURN_RIGHT", {"speed": 0.15, "duration_s": 0.3})}
        if a not in mapping:
            self.log("PROPOSAL", action=a, note="REQUEST_OPERATOR_REVIEW: nothing sent to the rover; operator decides")
            return None
        name, kw = mapping[a]
        return self.cmd(name, origin="qwen", proposal={"action": a, "model": (adv.get("model") or {}).get("label")}, **kw)

    def wait_until(self, t_rel):
        while time.time() - self.t0 < t_rel and not self.stop_ev.is_set():
            time.sleep(0.05)

    # --- scripted runs --------------------------------------------------------------------------------
    def demo20(self):
        self.log("PHASE", note="0-5 s: controller link, STOP state, camera availability")
        th = threading.Thread(target=self.ask_qwen)      # Qwen + LoRA takes ~8-11 s on MPS: start it first
        th.start()
        self.cmd("STOP")
        s = self.snapshot("after STOP")
        if s.get("safety_latch"):            # e.g. COMMS_LOST from an earlier silent link: a named operator clears it
            self.cmd("RESET_LATCH")
        self.camera_check()
        self.cmd("APPROVE")
        self.wait_until(5)
        self.log("PHASE", note="5-10 s: detections + Qwen recommendation")
        self.camera_check()
        th.join(timeout=max(0.5, 10.5 - (time.time() - self.t0)))
        if th.is_alive():
            self.log("QWEN", action="STOP", fallback=True, explanation="no Qwen answer by t=10.5 s: STOP fallback used",
                     model={"label": "NONE (deadline)"})
            self.cmd("STOP", origin="qwen-deadline")
        self.wait_until(10)
        self.log("PHASE", note="10-15 s: validation of the proposal and of unsafe requests")
        if self.last_advice:
            self.submit_proposal(self.last_advice)
        self.cmd("MOVE_FORWARD", speed=0.2, duration_s=0.5)                  # camera veto expected
        self.cmd("MOVE_BACKWARD", speed=0.2, duration_s=0.3)                 # no rear-clear: refused
        self.cmd("TURN_LEFT", origin="qwen", speed=0.15, duration_s=0.3)     # model-originated motion: refused
        r = self.cmd("TURN_LEFT", speed=0.15, duration_s=0.4)                # operator, bounded
        time.sleep(0.25)
        self.snapshot("during operator TURN_LEFT" + (" (accepted)" if r.get("accepted") else " (refused)"))
        self.wait_until(15)
        self.log("PHASE", note="15-20 s: STOP and final status")
        self.cmd("STOP")
        time.sleep(0.3)
        self.snapshot("final")
        self.wait_until(20)

    def faults(self):
        self.cmd("STOP")
        if self.snapshot("start").get("safety_latch"):
            self.cmd("RESET_LATCH")
        self.cmd("APPROVE")
        self.log("PHASE", note="stale camera while turning")
        self.cmd("TURN_LEFT", speed=0.15, duration_s=1.0)
        time.sleep(0.2)
        self.snapshot("turning")
        self.forward = False
        time.sleep(1.5)
        self.snapshot("camera forwarding stopped 1.5 s")
        self.forward = True
        time.sleep(0.6)
        self.log("PHASE", note="Mac link loss")
        self.cmd("APPROVE")
        self.cmd("TURN_RIGHT", speed=0.15, duration_s=1.0)
        time.sleep(0.2)
        self.link_alive = False
        time.sleep(1.0)
        self.link_alive = True
        time.sleep(0.5)
        self.snapshot("Mac link restored after 1.0 s silence")
        self.cmd("TURN_RIGHT", speed=0.15, duration_s=0.5)                   # refused: COMMS_LOST latched
        self.cmd("RESET_LATCH")
        self.cmd("APPROVE")
        self.log("PHASE", note="Qwen offline")
        old = self.a.advisor
        self.a.advisor = "http://127.0.0.1:9"                                 # nothing listens: unreachable
        self.submit_proposal(self.ask_qwen())
        self.a.advisor = old
        self.log("PHASE", note="emergency stop (remote trip; reset only at the Pi)")
        self.cmd("TURN_LEFT", speed=0.15, duration_s=1.0)
        time.sleep(0.2)
        self.cmd("EMERGENCY_STOP")
        time.sleep(0.2)
        self.snapshot("after EMERGENCY_STOP")
        self.cmd("TURN_LEFT", speed=0.15, duration_s=0.3)
        self.cmd("RESET_LATCH")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", default="http://100.97.93.118:8765")
    ap.add_argument("--key", default=link.DEFAULT_KEY)
    ap.add_argument("--dashboard", default="http://127.0.0.1:8000")
    ap.add_argument("--advisor", default="http://127.0.0.1:8095")
    ap.add_argument("--qwen-timeout-s", type=float, default=25.0)
    ap.add_argument("--out", default="~/Team15_evidence/ai_rover_sessions")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--demo20", action="store_true")
    g.add_argument("--faults", action="store_true")
    a = ap.parse_args()
    s = Session(a)
    health = http_json(a.advisor + "/health", timeout=2.0)
    s.log("START", note="session start", pi=a.pi, advisor_health={k: health.get(k) for k in (
        "label", "model_id", "adapter_path", "adapter_sha256", "adapter_active_verified", "rag", "error")},
          pi_status=s.pi.status().get("label"))
    th = threading.Thread(target=s.pump, daemon=True)
    th.start()
    time.sleep(1.0)
    try:
        if a.demo20:
            s.demo20()
        elif a.faults:
            s.faults()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        s.cmd("STOP")
        s.stop_ev.set()
        s.log("END", note=f"log: {s.out / 'session.jsonl'}")


if __name__ == "__main__":
    main()

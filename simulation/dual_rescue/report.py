"""Operator rescue report: a deterministic summary with citations, plus an optional guarded Qwen explanation.

Qwen is reached only through the existing Team-15-Qwen advisory service (POST /advisory, RAG + guard),
the same path as camera_mapping.advisory. Its text is display-only (``authority: NONE``): nothing here
is passed back to the coordinator, the planners or any motion interface. Text with a motor-command
pattern is discarded. Observation ids cited by Qwen are checked against the evidence packet.
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

from camera_mapping.advisory import MOTOR_PATTERN, http_qwen

OBS_ID = re.compile(r"\b(?:air|rov)-\d{4}\b")


def evidence(m) -> list[dict]:
    """Timestamped, source-labelled facts. Every fact carries the observation ids it is built from."""
    c = m.coord
    facts = []
    for cid, v in c.candidates.items():
        facts.append({"id": v["obs_ids"][-1], "t": v.get("t"), "source": "AIR-1 (SIMULATED drone thermal)",
                      "text": f"{v['status']} survivor {cid} at ({v['xy'][0]:.0f}, {v['xy'][1]:.0f}) m SITE frame, "
                              f"confidence {v['confidence']:.2f}, motion {v.get('motion')}, room {v.get('room')}",
                      "refs": v["obs_ids"]})
    for o in c.shared_obs:
        if o.get("kind") == "debris":
            facts.append({"id": o["obs_id"], "t": o["t"], "source": "AIR-1 (SIMULATED drone camera)",
                          "text": f"debris on corridor {o['edge']} at ({o['xy'][0]:.1f}, {o['xy'][1]:.1f}) m", "refs": [o["obs_id"]]})
        elif o.get("agent") == "GND-1" and o.get("kind") == "ultrasonic_obstacle" and o.get("status") == "CONFIRMED":
            facts.append({"id": o["obs_id"], "t": o["t"], "source": "GND-1 (SIMULATED rover ultrasonic)",
                          "text": f"obstacle confirmed on {o['edge']} ({(o.get('detail') or {}).get('justification', '')})",
                          "refs": [o["obs_id"]]})
        elif o.get("agent") == "GND-1" and o.get("kind") == "camera_person":
            facts.append({"id": o["obs_id"], "t": o["t"], "source": "GND-1 (SIMULATED rover camera)",
                          "text": f"person ahead on {o['edge']} (UNCONFIRMED, human review requested)", "refs": [o["obs_id"]]})
    for r in m.rover.nav.reroutes:
        facts.append({"id": r["obs_id"], "t": round(r["t"], 2), "source": "GND-1 Navigator (Dijkstra replan)",
                      "text": f"route changed around {r['blocked_edge']}: {'-'.join(r['old_route'] or [])} -> "
                              f"{'-'.join(r['new_route'])} ({r['new_length_m']} m)", "refs": [r["obs_id"]]})
    for tgt in c.targets.values():
        facts.append({"id": f"target-{tgt['cand_id']}", "t": tgt.get("t_reached", tgt["t_assigned"]),
                      "source": "COORD", "text": f"target {tgt['cand_id']} -> {tgt['dest']}: {tgt['status']}"
                      + (f" ({tgt['reason']})" if tgt.get("reason") else ""), "refs": [tgt.get("evidence")]})
    facts.sort(key=lambda f: (f["t"] if f["t"] is not None else 0.0, f["id"]))
    return facts


def deterministic_report(m) -> dict:
    c, nav = m.coord, m.rover.nav
    facts = evidence(m)
    lines = [f"Mission {m.sc.title} at t={m.t:.1f} s (SIMULATION). Phase: {c.phase}."]
    found = [v for v in c.candidates.values()]
    if found:
        lines.append("Aerial scout: " + "; ".join(
            f"{v['cand_id']} {v['status']} at ({v['xy'][0]:.0f}, {v['xy'][1]:.0f}) m, confidence {v['confidence']:.2f}, "
            f"motion {v.get('motion')} [{v['obs_ids'][-1]}]" for v in found) + ".")
    else:
        lines.append(f"Aerial scout: no survivor candidate yet ({m.drone.status()['sector_pos'] * 100:.0f}% PoS of the sector).")
    blocks = [f for f in facts if "obstacle confirmed" in f["text"] or f["text"].startswith("debris")]
    if blocks:
        lines.append("Obstructions: " + "; ".join(f"{f['text']} [{f['id']}, t={f['t']}]" for f in blocks) + ".")
    if nav.reroutes:
        r = nav.reroutes[-1]
        lines.append(f"Route change: {'-'.join(r['old_route'] or [])} replaced by {'-'.join(r['new_route'])} after "
                     f"{r['blocked_edge']} was blocked [{r['obs_id']}]; the detour used only corridors observed clear.")
    for tgt in c.targets.values():
        lines.append(f"Target {tgt['cand_id']} ({tgt['dest']}): {tgt['status']}" +
                     (f" - {tgt['reason']}" if tgt.get("reason") else "") + ".")
    if c.insufficient:
        lines.append("Information gap: " + c.insufficient["text"] + ".")
    lines.append("All survivor reports are UNCONFIRMED until a human reviews them. Distances are SIMULATED metres.")
    return {"source": "DETERMINISTIC", "text": " ".join(lines), "evidence": facts,
            "cited": sorted({r for f in facts for r in f["refs"] if r})}


def prepare(m) -> dict:
    """Snapshot everything the report needs (call while holding the mission lock)."""
    det = deterministic_report(m)
    notes = [f"[{f['id']} t={f['t']}] {f['source']}: {f['text']}" for f in det["evidence"]][-24:]
    body = {"sighting": None,
            "context": {"scene_notes": notes,
                        "question": ("Write a short operator rescue report: what the drone found, what blocked the "
                                     "rover, why the route changed, and what the operator should verify. Cite the "
                                     "observation ids in brackets."),
                        "robot_motion": "MOVING" if m.rover.nav.running else "STOPPED",
                        "platform_type": "UGV_GROUND_ROBOT", "viewpoint": "GROUND_LEVEL", "now": time.time()}}
    return {"schema": "team15.dual_rescue_report/1", "advisory_only": True, "authority": "NONE",
            "generated_at": round(time.time(), 3), "sim_t": round(m.t, 2), "deterministic": det,
            "qwen": None, "qwen_status": "NOT_CONFIGURED (deterministic report only)",
            "label": "MODEL ADVISORY - display only; deterministic planning and the safety supervisor decide motion",
            "_body": body}


def finish(prep: dict, qwen: Optional[Callable[[dict], dict]] = None, qwen_url: Optional[str] = None,
           timeout_s: float = 30.0) -> dict:
    """Ask Qwen (no lock needed: works only on the prepared snapshot) and guard the answer."""
    out = {k: v for k, v in prep.items() if k != "_body"}
    det = out["deterministic"]
    if qwen is None and qwen_url:
        qwen = http_qwen(qwen_url, timeout_s=timeout_s)
    if qwen is None:
        return out
    t0 = time.perf_counter()
    try:
        rec = qwen(prep["_body"])
    except Exception as e:  # noqa: BLE001 - Qwen is optional; any failure -> deterministic only
        out["qwen_status"] = f"UNAVAILABLE ({type(e).__name__}) - showing the DETERMINISTIC FALLBACK"
        return out
    out["qwen_latency_ms"] = int((time.perf_counter() - t0) * 1000)
    if not isinstance(rec, dict):
        out["qwen_status"] = "INVALID_RESPONSE - showing the DETERMINISTIC FALLBACK"
        return out
    text = " ".join(str(rec.get(k) or "") for k in ("explanation", "recommended_action", "suggested_next_observation"))
    if MOTOR_PATTERN.search(text):
        out["qwen_status"] = "DISCARDED_MOTOR_COMMAND_PATTERN - showing the DETERMINISTIC FALLBACK"
        return out
    known = {f["id"] for f in det["evidence"]} | set(det["cited"])
    cited = sorted(set(OBS_ID.findall(text)))
    out["qwen"] = {k: rec.get(k) for k in ("explanation", "recommended_action", "suggested_next_observation",
                                           "uncertainty", "missing_evidence", "config", "model_id",
                                           "inference_latency_ms", "guard")}
    out["qwen"]["provenance"] = {"cited_ids": cited, "unknown_ids": [i for i in cited if i not in known],
                                 "evidence_ids_given": sorted(known)}
    g = rec.get("guard") if isinstance(rec.get("guard"), dict) else {}
    out["qwen_status"] = ("QWEN_FELL_BACK_TO_DETERMINISTIC" if g.get("fell_back_to_deterministic") else
                          "QWEN_GUARDED (RAG)" if rec.get("config") == "C_QWEN_RAG" else f"QWEN ({rec.get('config')})")
    return out


def build_report(m, qwen: Optional[Callable[[dict], dict]] = None, qwen_url: Optional[str] = None,
                 timeout_s: float = 30.0) -> dict:
    return finish(prepare(m), qwen=qwen, qwen_url=qwen_url, timeout_s=timeout_s)

"""Rescue explanation: deterministic scene summary + optional guarded Qwen (RAG).

Qwen is reached ONLY through the existing Team-15-Qwen service
(``python -m rescue_qwen.service``, POST /advisory, schema rescue-advisory/0.1),
which applies its own retrieval, guard and deterministic fallback. This module:

  * builds the evidence packet (each fact carries its timestamp and source);
  * never passes Qwen output back into the pipeline, the map, the assessment
    or any rover interface (the result is display-only, ``authority: NONE``);
  * drops any Qwen text that contains a motor-command pattern and falls back
    to the deterministic summary.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from typing import Callable, Optional

MOTOR_PATTERN = re.compile(
    r"\b(set_?speed|set_?wheels?|motor\w*\s*[:=(]|pwm|throttle\s*[:=]|"
    r"(?:drive|move|go|turn|strafe|advance)\s+(?:forward|ahead|left|right|now)\b.*\b(?:m/s|rpm|%|speed))", re.I)

RECON_ACTIONS = {
    "BLOCKED": "Hold position. Operator review of the obstacle; observe an alternate side before any motion.",
    "CAUTION": "Hold position. Re-observe the corridor edge; the obstacle is within estimate uncertainty.",
    "UNKNOWN": "Hold position. Gather more observation (rotate the camera view or wait for confirmed tracks).",
    "CLEAR": "No detected obstacle in the observed corridor. Any motion still needs the rover's safety supervisor and range gate.",
}


def scene_facts(state: dict) -> list:
    facts = []
    a = state.get("assessment") or {}
    facts.append({"id": "assessment", "t": state.get("t"), "source": "camera_mapping.assess",
                  "text": f"Forward corridor {a.get('status')}: " + "; ".join(a.get("reasons") or [])})
    for r in state.get("objects") or []:
        d = r.get("filtered_distance")
        dist = (f"~{d['distance_m']:.2f} m ±{2 * d['sigma_m']:.2f} m ({(r.get('distance') or {}).get('label')})"
                if d else f"range UNKNOWN ({((r.get('distance') or {}).get('reason'))})")
        facts.append({"id": f"track-{r['track_id']}", "t": r["timestamp"], "source": r["data_source"],
                      "text": f"{r['object_class']} #{r['track_id']} score {r['detection_confidence']:.2f}, "
                              f"{dist}, {r['corridor_position']}, {r['validity']}"})
    rt = state.get("route") or {}
    facts.append({"id": "route", "t": state.get("t"), "source": "camera_mapping.assess.suggest_route",
                  "text": f"Route suggestion {rt.get('status')} side={rt.get('side')} (advisory, not validated for driving)"})
    facts.append({"id": "calibration", "t": state.get("t"), "source": "config",
                  "text": f"Distance calibration {state.get('calibration_status')}; mount measured="
                          f"{(state.get('mount') or {}).get('measured')}"})
    return facts


def deterministic_summary(state: dict) -> dict:
    a = (state.get("assessment") or {}).get("status", "UNKNOWN")
    persons = [r for r in state.get("objects") or [] if r["category"] == "PERSON" and r["validity"] != "TENTATIVE"]
    obst = [r for r in state.get("objects") or [] if r["category"] == "OBSTACLE" and r["validity"] != "TENTATIVE"]
    lines = []
    if persons:
        p = persons[0]
        d = p.get("filtered_distance")
        lines.append(f"Potential person (camera detection, UNCONFIRMED) {'~%.1f m away' % d['distance_m'] if d else 'at unknown range'}"
                     f", {p['corridor_position'].replace('_', ' ').lower()}. Priority: operator review of the image.")
    else:
        lines.append("No person detected in the current view.")
    if obst:
        lines.append("Obstacles: " + ", ".join(
            f"{o['object_class']}" + (f" ~{o['filtered_distance']['distance_m']:.1f} m" if o.get("filtered_distance") else " (range unknown)")
            for o in obst[:4]) + ".")
    lines.append(f"Forward path: {a}. " + RECON_ACTIONS.get(a, RECON_ACTIONS["UNKNOWN"]))
    rt = state.get("route") or {}
    if rt.get("status") == "ALTERNATE_ROUTE_OBSERVED_FREE":
        lines.append(f"An alternate route to the {rt.get('side', '').lower()} crosses only observed-free cells (advisory).")
    elif rt.get("status") == "ROUTE_THROUGH_UNOBSERVED_SPACE":
        lines.append(f"A {rt.get('side', '').lower()} detour exists only through unobserved space: observe it first.")
    return {"source": "DETERMINISTIC", "summary": " ".join(lines),
            "priorities": (["Review potential person image"] if persons else []) +
                          (["Assess blocking obstacle"] if a == "BLOCKED" else []),
            "recommended_action": RECON_ACTIONS.get(a, RECON_ACTIONS["UNKNOWN"])}


def person_sighting(state: dict) -> Optional[dict]:
    """Shape the strongest person record for rescue_qwen's evidence packet."""
    persons = [r for r in state.get("objects") or [] if r["category"] == "PERSON" and r["validity"] == "VALID"]
    if not persons:
        return None
    p = max(persons, key=lambda r: r["detection_confidence"])
    return {"obs_id": f"cam-track-{p['track_id']}-{int(state['t'])}", "source_mode": state.get("source_mode"),
            "platform": "ROBOT", "platform_type": "UGV_GROUND_ROBOT", "viewpoint": "GROUND_LEVEL",
            "sensor": "rgb", "kind": "PERSON_VISUAL", "how": "BEARING_ONLY", "cell": None,
            "obs_time": p["timestamp"], "confidence": None,
            "evidence": {"bbox": p["bbox"], "detector": "torchvision_frcnn_r50_fpn_v2_coco",
                         "detector_family": "PERSON_DETECTOR", "detector_score": p["detection_confidence"],
                         "detector_score_kind": "frcnn_class_score",
                         "count_in_frame": sum(1 for r in persons),
                         "camera": state.get("camera") or {}}}


def http_qwen(url: str, timeout_s: float = 10.0) -> Callable[[dict], dict]:
    def call(body: dict) -> dict:
        req = urllib.request.Request(url.rstrip("/") + "/advisory", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read())
    return call


def advise(state: dict, qwen: Optional[Callable[[dict], dict]] = None, question: Optional[str] = None) -> dict:
    det = deterministic_summary(state)
    facts = scene_facts(state)
    out = {"schema": "team15.camera_rescue_advisory/1", "advisory_only": True, "authority": "NONE",
           "generated_at": round(time.time(), 3), "state_t": state.get("t"),
           "deterministic": det, "evidence": facts, "qwen": None, "qwen_status": "NOT_CONFIGURED"}
    if qwen is None:
        return out
    body = {"sighting": person_sighting(state),
            "context": {"scene_notes": [f"[{f['id']} t={f['t']}] {f['text']}" for f in facts],
                        "question": question or "Summarise the scene, rescue priority and next reconnaissance step.",
                        "robot_motion": "STOPPED", "platform_type": "UGV_GROUND_ROBOT",
                        "viewpoint": "GROUND_LEVEL",
                        "camera_calibration": {"pose_measured": bool((state.get("mount") or {}).get("measured"))},
                        "now": time.time()}}
    t0 = time.perf_counter()
    try:
        rec = qwen(body)
    except Exception as e:  # noqa: BLE001 - Qwen is optional; any failure -> deterministic only
        out["qwen_status"] = f"UNAVAILABLE ({type(e).__name__})"
        return out
    out["qwen_latency_ms"] = int((time.perf_counter() - t0) * 1000)
    if not isinstance(rec, dict):
        out["qwen_status"] = "INVALID_RESPONSE"
        return out
    text = " ".join(str(rec.get(k) or "") for k in ("explanation", "recommended_action", "suggested_next_observation"))
    if MOTOR_PATTERN.search(text):
        out["qwen_status"] = "DISCARDED_MOTOR_COMMAND_PATTERN"
        return out
    keep = ("person_evidence", "possible_artifacts", "recommended_action", "explanation", "source_references",
            "suggested_next_observation", "uncertainty", "hazards", "missing_evidence", "config", "model_id",
            "inference_latency_ms", "guard", "evidence_freshness")
    out["qwen"] = {k: rec.get(k) for k in keep}
    g = rec.get("guard") if isinstance(rec.get("guard"), dict) else {}
    out["qwen_status"] = "QWEN_FELL_BACK_TO_DETERMINISTIC" if g.get("fell_back_to_deterministic") else (
        "DETERMINISTIC_SERVICE" if rec.get("config") == "A_DETERMINISTIC" else "QWEN_GUARDED")
    return out

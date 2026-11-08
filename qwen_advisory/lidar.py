"""Qwen LiDAR advisory contract for Team-15 (rescue-lidar-advisory/0.1): schema, deterministic reference policy, guard.

Stdlib only (Python 3.11). Ported from the Team-15-Qwen workspace (rescue_qwen/lidar_policy.py); parity with the
original is tested there on 314 SIMULATED cases. Consumes the LiDAR agent's team15.lidar_advisory_context/1
(PR #11, draft). The advisory is display-only: it has NO authority over motors, gripper or e-stop.

Input LiDAR facts come ONLY from the LiDAR agent's `to_advisory_context()` (team15.lidar_advisory_context/1,
DRAFT). We never recompute sectors. Sensor fusion is LEVEL A only: camera and LiDAR are reported separately and
`association` is always NOT_ESTABLISHED (no camera-LiDAR extrinsic calibration exists). Level B (bounded
association) is NOT implemented and must not be implied.

Recommendations about motion are recommendations to the operator / deterministic controller, never commands.
"""
from __future__ import annotations

import re

SCHEMA_VERSION = "rescue-lidar-advisory/0.1"
SECTORS = ["FRONT", "FRONT_LEFT", "LEFT", "REAR_LEFT", "REAR", "REAR_RIGHT", "RIGHT", "FRONT_RIGHT"]
MOTION_REC = ["REQUEST_DETERMINISTIC_STOP",           # robot moving/commanded and front blocked/unknown/sensor bad
              "DO_NOT_REQUEST_MOTION",                # stationary; evidence does not support any motion request
              "OPERATOR_MAY_CONSIDER_BOUNDED_MOVE"]   # FRONT CLEAR, fresh, aligned, SCANNING; operator still decides
NEXT_OBS = ["NONE", "LIDAR_RESCAN", "CHECK_LIDAR_CONNECTION", "VERIFY_LIDAR_MOUNT", "CAMERA_RECHECK",
            "OPERATOR_VISUAL_CHECK", "SECOND_VIEWPOINT"]
ACTIONS = ["REQUEST_OPERATOR_REVIEW", "REQUEST_FOLLOW_UP_OBSERVATION", "ESCALATE_SENSOR_FAULT",
           "REFUSE_UNSAFE_REQUEST", "ABSTAIN_INSUFFICIENT_EVIDENCE", "NO_FURTHER_ACTION"]
PERSON = ["POSSIBLE_PERSON", "UNCERTAIN", "NOT_DISCERNIBLE"]

MODEL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["person_evidence", "lidar_status", "association", "forward_motion_recommendation",
                 "recommended_action", "next_observation", "missing_evidence", "explanation", "source_references"],
    "properties": {
        "person_evidence": {"enum": PERSON},
        "lidar_status": {"enum": ["USABLE", "STALE", "DISCONNECTED_OR_FAULT", "UNALIGNED", "PARTIAL", "NOT_PROVIDED"]},
        "association": {"enum": ["NOT_ESTABLISHED"]},
        "forward_motion_recommendation": {"enum": MOTION_REC},
        "recommended_action": {"enum": ACTIONS},
        "next_observation": {"enum": NEXT_OBS},
        "missing_evidence": {"type": "array", "items": {"type": "string", "maxLength": 160}, "maxItems": 6},
        "explanation": {"type": "string", "minLength": 1, "maxLength": 900},
        "source_references": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
}


def schema_errors(obj) -> list[str]:
    """Stdlib validator for MODEL_SCHEMA (required, no extra keys, enums, string/array types and limits)."""
    if not isinstance(obj, dict):
        return ["not an object"]
    errs = [f"'{k}' is a required property" for k in MODEL_SCHEMA["required"] if k not in obj]
    errs += [f"unexpected key '{k}'" for k in obj if k not in MODEL_SCHEMA["properties"]]
    for k, rule in MODEL_SCHEMA["properties"].items():
        if k not in obj:
            continue
        v = obj[k]
        if "enum" in rule and (not isinstance(v, str) or v not in rule["enum"]):
            errs.append(f"{k}: {v!r} is not one of {rule['enum']}")
        if rule.get("type") == "string":
            if not isinstance(v, str):
                errs.append(f"{k}: not a string")
            elif not rule.get("minLength", 0) <= len(v) <= rule.get("maxLength", 10**9):
                errs.append(f"{k}: length out of range")
        if rule.get("type") == "array":
            if not isinstance(v, list):
                errs.append(f"{k}: not an array")
            else:
                if len(v) > rule.get("maxItems", 10**9):
                    errs.append(f"{k}: too many items")
                it = rule.get("items", {})
                for x in v:
                    if not isinstance(x, str) or len(x) > it.get("maxLength", 10**9):
                        errs.append(f"{k}: invalid item")
                        break
    return errs


_NEGATION = re.compile(r"\b(no|not|never|nobody|none|neither|nor|without|isn't|is not|has not|hasn't)\b[^.;]{0,25}$", re.I)


def affirmative_search(rx, text: str):
    """First match of rx that is not negated in the same clause ('No person is confirmed' is allowed)."""
    for m in rx.finditer(text or ""):
        if not _NEGATION.search(text[max(0, m.start() - 40):m.start()]):
            return m
    return None

UNSAFE_REQ = re.compile(r"\b(drive|move|go|advance|roll|steer|turn|rotate|strafe|back up|reverse|approach)\b[^.?!]{0,40}"
                        r"\b(forward|ahead|toward|towards|closer|left|right|now|to the person)\b|"
                        r"\b(release|drop) (the )?(package|supply)|\bconfirm (the |this )?(person|candidate)\b|"
                        r"\b(ignore|bypass|reset|override) (the )?(e-?stop|emergency stop|lidar|safety)", re.I)


QUESTION = re.compile(r"^\s*(is|are|can|could|should|would|may|might|do|does|did|what|how|why|when|where|which|who)\b", re.I)
PLANE_HAZARD = re.compile(r"\b(curb|below the (lidar|scan) plane|low (obstacle|debris|curb)|incline|slope|ramp|stairs?|hole|drop-?off|"
                          r"glass|mirror|reflect\w*|transparent)\b", re.I)


def is_unsafe_request(q: str) -> bool:
    """An imperative asking the assistant to act. Questions ('Is it safe to move closer?') are answered, not refused."""
    return bool(q) and not QUESTION.search(q) and bool(UNSAFE_REQ.search(q))


def lidar_facts(lidar: dict | None, now: float | None = None) -> dict:
    """Summarise the LiDAR agent's advisory context; malformed input is treated as unusable."""
    if not lidar:
        return {"status": "NOT_PROVIDED", "front": "UNKNOWN", "sectors": {}, "closest_cm": None, "valid": False,
                "reason": "no LiDAR context"}
    try:
        assert lidar.get("schema") == "team15.lidar_advisory_context/1"
        sectors = {s["facing"]: s for s in lidar["sectors"]}
        assert set(sectors) == set(SECTORS)
        for s in sectors.values():
            assert s["status"] in ("CLEAR", "CAUTION", "BLOCKED", "UNKNOWN")
            assert s["min_range_cm"] is None or (isinstance(s["min_range_cm"], (int, float)) and 0 < s["min_range_cm"] < 1300)
        assert lidar.get("association") == "NOT_ESTABLISHED" and lidar.get("person_distance_cm") is None
    except (AssertionError, KeyError, TypeError) as e:
        return {"status": "DISCONNECTED_OR_FAULT", "front": "UNKNOWN", "sectors": {}, "closest_cm": None,
                "valid": False, "reason": f"malformed LiDAR context ({type(e).__name__})"}
    conn = lidar.get("connection")
    if conn != "SCANNING":
        st = "DISCONNECTED_OR_FAULT" if conn in ("DISCONNECTED", "TIMEOUT", "HEALTH_ERROR", "GATE_LOCKED", "CONNECTING") \
            else ("STALE" if conn == "STALE" else "PARTIAL")
    elif lidar.get("stale"):
        st = "STALE"
    elif not lidar.get("alignment_verified") or lidar.get("orientation_monitor") == "FAILED":
        st = "UNALIGNED"   # contract dd58b80: orientation_monitor FAILED -> treat like unverified mount
    else:
        st = "USABLE"
    if st != "USABLE":
        sec = {k: dict(v, status="UNKNOWN", min_range_cm=None) for k, v in sectors.items()}
    else:
        sec = sectors
    corr = lidar.get("forward_corridor") if isinstance(lidar.get("forward_corridor"), dict) else None
    corridor = (corr or {}).get("status") if st == "USABLE" else ("UNKNOWN" if corr else None)
    return {"status": st, "front": sec["FRONT"]["status"], "corridor": corridor,
            "corridor_reason": (corr or {}).get("reason"), "sectors": {k: (v["status"], v["min_range_cm"]) for k, v in sec.items()},
            "closest_cm": lidar.get("closest_cm") if st == "USABLE" else None, "valid": st == "USABLE",
            "source_mode": lidar.get("source_mode"), "reason": st}


def reference_policy(ctx: dict) -> dict:
    """Deterministic labels for the LiDAR advisory. First matching rule wins (LIDAR_DATASET_CARD.md)."""
    lf = lidar_facts(ctx.get("lidar"))
    cam = ctx.get("camera") or {}
    moving = ctx.get("robot_motion") in ("MOVING", "COMMANDED_FORWARD")
    q = ctx.get("question") or ""
    has_person = bool(cam.get("person_candidate"))
    notes = " ".join(ctx.get("scene_notes") or [])
    missing, reasons = [], []
    pe = "NOT_DISCERNIBLE" if not cam.get("available", True) or not has_person else (
        "UNCERTAIN" if re.search(r"glass|window|reflect|mirror|poster|mannequin|dark|blur", notes, re.I) or
        (cam.get("score") or 0) < 0.6 else "POSSIBLE_PERSON")
    if has_person:
        missing.append("camera-LiDAR association (no extrinsic calibration): LiDAR range is not the person's distance")
    if not cam.get("available", True):
        missing.append("camera observation unavailable")
    if lf["status"] != "USABLE":
        missing.append({"NOT_PROVIDED": "LiDAR scan", "STALE": "fresh LiDAR scan (current one is stale)",
                        "DISCONNECTED_OR_FAULT": "working LiDAR connection / valid scan",
                        "UNALIGNED": "verified LiDAR mount alignment (sectors cannot be mapped to the robot)",
                        "PARTIAL": "complete LiDAR revolution"}[lf["status"]])
    elif lf["front"] in ("UNKNOWN",):
        missing.append("LiDAR coverage of the FRONT sector")
    # motion recommendation
    corridor_bad = lf.get("corridor") is not None and lf["corridor"] != "CLEAR"
    if corridor_bad:
        missing.append(f"forward corridor {lf['corridor']} (robot-width, bumper-referenced)")
    if lf["status"] != "USABLE" or lf["front"] in ("BLOCKED", "UNKNOWN") or corridor_bad or ctx.get("estop_engaged") or ctx.get("link") == "LOST":
        motion = "REQUEST_DETERMINISTIC_STOP" if moving else "DO_NOT_REQUEST_MOTION"
    elif lf["front"] == "CAUTION":
        motion = "REQUEST_DETERMINISTIC_STOP" if moving else "DO_NOT_REQUEST_MOTION"
    else:
        motion = ("OPERATOR_MAY_CONSIDER_BOUNDED_MOVE" if ctx.get("operator_asks_motion") and not moving
                  and not PLANE_HAZARD.search(" ".join(ctx.get("scene_notes") or [])) else "DO_NOT_REQUEST_MOTION")
    # action
    plane_hazard = PLANE_HAZARD.search(notes)
    if plane_hazard:
        missing.append("LiDAR cannot see obstacles outside its single scan plane or through glass/mirrors: "
                       "camera or operator check needed")
    review = ctx.get("operator_review") or "UNREVIEWED"
    if is_unsafe_request(q):
        action, nxt = "REFUSE_UNSAFE_REQUEST", "NONE"
        reasons.append("The request asks the assistant to move the robot, release a package, confirm a person or bypass "
                       "safety; only the operator and the deterministic controller can do that.")
    elif ctx.get("estop_engaged") or ctx.get("link") == "LOST":
        action, nxt = "ESCALATE_SENSOR_FAULT", "NONE"
        reasons.append("Emergency stop engaged or link lost: nothing is requested except operator attention.")
    elif lf["status"] in ("DISCONNECTED_OR_FAULT", "STALE", "PARTIAL"):
        action = "ESCALATE_SENSOR_FAULT" if lf["status"] == "DISCONNECTED_OR_FAULT" else "REQUEST_FOLLOW_UP_OBSERVATION"
        nxt = "CHECK_LIDAR_CONNECTION" if lf["status"] == "DISCONNECTED_OR_FAULT" else "LIDAR_RESCAN"
        reasons.append(f"LiDAR is {lf['status']}: every direction is UNKNOWN, never clear.")
    elif lf["status"] == "UNALIGNED":
        action, nxt = "REQUEST_FOLLOW_UP_OBSERVATION", "VERIFY_LIDAR_MOUNT"
        reasons.append("LiDAR mount alignment is not verified, so sectors cannot be mapped to the robot frame.")
    elif lf["status"] == "NOT_PROVIDED" and not has_person:
        action, nxt = "ABSTAIN_INSUFFICIENT_EVIDENCE", "NONE"
        reasons.append("No LiDAR scan and no camera candidate: nothing to assess.")
    elif has_person and review == "CONFIRMED_BY_OPERATOR":
        action, nxt = "NO_FURTHER_ACTION", "NONE"
        reasons.append("The operator already confirmed this candidate. Any supply placement is decided by the deterministic "
                       "delivery policy and the operator in the control service, not by this advisory.")
    elif has_person and review == "REJECTED_BY_OPERATOR":
        action, nxt = "NO_FURTHER_ACTION", "NONE"
        reasons.append("The operator rejected this candidate.")
    elif plane_hazard:
        action, nxt = "REQUEST_FOLLOW_UP_OBSERVATION", "CAMERA_RECHECK"
        reasons.append("A hazard the 2D LiDAR may not see (outside the scan plane, glass or mirror) is reported; "
                       "a CLEAR sector does not rule it out.")
    elif has_person:
        action = "REQUEST_OPERATOR_REVIEW"
        nxt = "SECOND_VIEWPOINT" if pe == "UNCERTAIN" else "OPERATOR_VISUAL_CHECK"
        reasons.append("Possible person: UNCONFIRMED until the operator decides.")
    elif lf["front"] in ("UNKNOWN", "BLOCKED", "CAUTION") or corridor_bad:
        action, nxt = "REQUEST_FOLLOW_UP_OBSERVATION", ("LIDAR_RESCAN" if "UNKNOWN" in (lf["front"], lf.get("corridor")) else "CAMERA_RECHECK")
        reasons.append(f"FRONT is {lf['front']}." if not corridor_bad else
                       f"FRONT is {lf['front']}; forward corridor {lf['corridor']} ({lf.get('corridor_reason')}).")
    else:
        action, nxt = "NO_FURTHER_ACTION", "NONE"
        reasons.append("No person candidate; FRONT sector reports CLEAR (a sector status, not a guaranteed safe path).")
    if lf["valid"]:
        occ = [f"{k} {s} at {r} cm" for k, (s, r) in lf["sectors"].items() if s in ("BLOCKED", "CAUTION") and r is not None]
        if occ:
            reasons.append("LiDAR (sensor-relative, robot-frame sectors): " + "; ".join(occ) +
                           ". These are reflecting surfaces, not identified objects.")
    expl = " ".join(reasons)
    return {"person_evidence": pe, "lidar_status": lf["status"], "association": "NOT_ESTABLISHED",
            "forward_motion_recommendation": motion, "recommended_action": action, "next_observation": nxt,
            "missing_evidence": list(dict.fromkeys(missing))[:6], "explanation": expl[:900], "source_references": []}


# ---------------------------------------------------------------- guard
FORBID = [
    (re.compile(r"\b(person|subject|human|target|survivor|victim|candidate|he|she|they)\b[^.;]{0,40}?\b(is|are|was|stands?|sits?|lies?|located|appears?)\b[^.;]{0,20}?\d+(?:\.\d+)?\s?(cm|m|meters?|metres?)\b", re.I), "person_distance"),
    (re.compile(r"\b(path|route|way|front|left|right|area|corridor|doorway|sector)\b[^.;]{0,25}?\b(is|are|looks|appears)\s+(safe|clear to (drive|move|proceed)|traversable|passable)\b", re.I), "clearance_claim"),
    (re.compile(r"\b(x|y)\s*=\s*-?\d|\b(lat|lon|coordinates?|world position|map position)\b", re.I), "coordinates"),
    (re.compile(r"\b(drive|move|rotate|turn|go)\s+(forward|ahead|left|right|toward)\b", re.I), "motion_command"),
    (re.compile(r"\b(injur\w*|bleed\w*|unconscious|fractur\w*|diagnos\w*)\b", re.I), "medical"),
    (re.compile(r"(?<!not )(?<!un)\b(person|candidate) (is )?(confirmed|verified)\b", re.I), "confirmation"),
    (re.compile(r"\b(calibrat\w+ (shows|confirms)|associated with the person|LiDAR (sees|detects|measures) the person)\b", re.I), "invented_association"),
]
_DIST = re.compile(r"(\d+(?:\.\d+)?)\s*(cm|m|meters?|metres?)\b", re.I)


def guard(out, ctx: dict, retrieved_ids: set[str]) -> dict:
    if not isinstance(out, dict):
        return {"critical": ["unparseable_output"], "corrected": [], "output": None}
    errs = schema_errors(out)
    if errs:
        return {"critical": [f"schema: {e}" for e in errs[:4]], "corrected": [], "output": None}
    o = dict(out)
    crit, corr = [], []
    text = " ".join([o["explanation"]] + o["missing_evidence"])
    for rx, code in FORBID:
        m = affirmative_search(rx, text) if code in ("confirmation", "clearance_claim") else rx.search(text)
        if m:
            crit.append(f"{code}: {m.group(0)!r}")
    lf = lidar_facts(ctx.get("lidar"))
    allowed = {round(r, 1) for _, (s, r) in lf["sectors"].items() if r is not None} if lf["valid"] else set()
    if lf.get("closest_cm") is not None:
        allowed.add(round(lf["closest_cm"], 1))
    fc = (ctx.get("lidar") or {}).get("forward_corridor")
    if lf["valid"] and isinstance(fc, dict) and fc.get("min_clearance_cm") is not None:
        allowed.add(round(fc["min_clearance_cm"], 1))
    for m in _DIST.finditer(text):
        v = float(m.group(1)) * (1 if m.group(2).lower() == "cm" else 100)
        # documented constants only: BLOCKED 0.35 m, CAUTION 0.75 m (placeholders), valid range 0.08-8.0 m
        if not any(abs(v - a) <= max(2.0, 0.03 * a) for a in allowed) and v not in (35.0, 75.0, 8.0, 800.0):
            crit.append(f"unsupported_distance: {m.group(0)!r}")
    ref = reference_policy(ctx)
    # never more permissive than the reference on motion
    rank = {"REQUEST_DETERMINISTIC_STOP": 0, "DO_NOT_REQUEST_MOTION": 1, "OPERATOR_MAY_CONSIDER_BOUNDED_MOVE": 2}
    if rank[o["forward_motion_recommendation"]] > rank[ref["forward_motion_recommendation"]]:
        crit.append(f"unsafe_motion_recommendation: {o['forward_motion_recommendation']} (allowed at most "
                    f"{ref['forward_motion_recommendation']})")
    if is_unsafe_request(ctx.get("question") or "") and o["recommended_action"] != "REFUSE_UNSAFE_REQUEST":
        corr.append("unsafe_request_not_refused")
        o["recommended_action"] = "REFUSE_UNSAFE_REQUEST"
    if o["lidar_status"] != ref["lidar_status"]:
        corr.append(f"lidar_status_corrected {o['lidar_status']} -> {ref['lidar_status']}")
        o["lidar_status"] = ref["lidar_status"]
    bad = [r for r in o["source_references"] if r not in retrieved_ids]
    if bad:
        o["source_references"] = [r for r in o["source_references"] if r in retrieved_ids]
        corr.append(f"citation_not_retrieved: {bad[:3]}")
    return {"critical": list(dict.fromkeys(crit)), "corrected": corr, "output": o}

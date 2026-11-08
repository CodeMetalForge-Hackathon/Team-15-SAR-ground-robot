"""Camera veto for rover motion. Pure function of one camera-perception state: no I/O, no motor access.

The camera can only ever say NO (stop or hold). It never grants motion: the supervisor's own gates
(range reading, power, driver health, operator approval) still decide whether anything moves, and the camera
is not a range sensor (camera_mapping/rover_adapter.py refuses to build a RangeReading from it).

Decision loop, in order (first match wins):
  1. no state / wrong schema / camera says it has motion authority      -> HOLD    (no motion of any kind)
  2. stale (dashboard rx age > max_age_s) or not LIVE-HW when required  -> HOLD    (no motion of any kind)
  3. a PERSON in the forward corridor (bearing or position)             -> STOP    (forward vetoed)
  4. corridor BLOCKED                                                   -> STOP    (forward vetoed)
  5. corridor CAUTION / UNKNOWN                                         -> HOLD    (forward vetoed)
  6. corridor CLEAR but camera not CALIBRATED                           -> HOLD    (forward vetoed)
  7. corridor CLEAR, calibrated, fresh, live                            -> NO_CAMERA_OBJECTION
For 3-5, the candidate paths (camera_mapping/candidates.py) are attached: if one is OBSERVED_CLEAR the
action becomes OPERATOR_REVIEW with that suggestion; otherwise OPERATOR_INTERVENTION (no clearance can be
established). Neither is executed automatically: autonomous avoidance stays disabled.

An empty detection list is never evidence of clearance: CLEAR comes only from the pipeline's corridor
assessment, which requires every corridor cell to be observed FREE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SCHEMA = "team15.camera_perception/1"
STOP, HOLD, NO_OBJECTION = "STOP", "HOLD", "NO_CAMERA_OBJECTION"
OPERATOR_REVIEW, OPERATOR_INTERVENTION = "OPERATOR_REVIEW", "OPERATOR_INTERVENTION"


@dataclass(frozen=True)
class CameraVerdict:
    action: str                        # STOP | HOLD | NO_CAMERA_OBJECTION
    forward_ok: bool                   # camera does not object to forward motion
    any_motion_ok: bool                # camera feed is fresh and live enough to allow any motion at all
    reason: str
    assessment: str = "UNKNOWN"
    source_mode: Optional[str] = None
    age_s: Optional[float] = None
    persons_ahead: tuple = ()
    operator: Optional[str] = None     # OPERATOR_REVIEW | OPERATOR_INTERVENTION | None
    suggestion: Optional[str] = None   # e.g. "RIGHT" (observed clear); advisory only
    candidates: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"action": self.action, "forward_ok": self.forward_ok, "any_motion_ok": self.any_motion_ok,
                "reason": self.reason, "assessment": self.assessment, "source_mode": self.source_mode,
                "age_s": self.age_s, "persons_ahead": list(self.persons_ahead), "operator": self.operator,
                "suggestion": self.suggestion, "candidates": [dict(c) for c in self.candidates],
                "authority": "VETO_ONLY"}


def _hold(reason: str, **kw) -> CameraVerdict:
    return CameraVerdict(HOLD, False, False, reason, **kw)


def evaluate(state: Optional[dict], now: float, max_age_s: float = 1.0, require_live: bool = True) -> CameraVerdict:
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        return _hold("no camera perception data")
    if state.get("motion_authority") != "NONE" or state.get("data_source") != "CAMERA_ESTIMATE":
        return _hold("perception state claims motion authority or is not a camera estimate: refused")
    mode = state.get("source_mode")
    t = state.get("rx_time") if isinstance(state.get("rx_time"), (int, float)) else state.get("t")
    if not isinstance(t, (int, float)):
        return _hold("perception state has no timestamp", source_mode=mode)
    age = round(now - t, 3)
    if age > max_age_s or age < -max_age_s:
        return _hold(f"camera data stale ({age:.2f} s old > {max_age_s:.2f} s)", source_mode=mode, age_s=age)
    if require_live and mode != "LIVE-HW":
        return _hold(f"camera source is {mode}, not LIVE-HW", source_mode=mode, age_s=age)

    a = state.get("assessment") or {}
    status = a.get("status") or "UNKNOWN"
    cands = tuple(c for c in (state.get("candidates") or []) if isinstance(c, dict))
    persons = tuple(p.get("track_id") for p in (state.get("persons") or [])
                    if p.get("validity") in ("VALID", "COASTING")
                    and str(p.get("corridor_position") or "").startswith("IN_CORRIDOR"))
    common = dict(assessment=status, source_mode=mode, age_s=age, persons_ahead=persons, candidates=cands)

    def blocked(action: str, why: str) -> CameraVerdict:
        side = [c for c in cands if c.get("name") in ("LEFT", "RIGHT") and c.get("status") == "OBSERVED_CLEAR"]
        if side:
            return CameraVerdict(action, False, True, why + f"; {side[0]['name']} path observed clear: operator review",
                                 operator=OPERATOR_REVIEW, suggestion=side[0]["name"], **common)
        return CameraVerdict(action, False, True, why + "; no candidate path has observed clearance: operator "
                             "intervention required", operator=OPERATOR_INTERVENTION, **common)

    if persons:
        return blocked(STOP, f"person ahead (track {', '.join(map(str, persons))})")
    if status == "BLOCKED":
        return blocked(STOP, "forward corridor BLOCKED: " + "; ".join(a.get("reasons") or [])[:200])
    if status != "CLEAR":
        return blocked(HOLD, f"forward corridor {status}: " + "; ".join(a.get("reasons") or [])[:200])
    if state.get("calibration_status") != "CALIBRATED":
        return CameraVerdict(HOLD, False, True, f"corridor CLEAR but camera {state.get('calibration_status')}: "
                             "clearance not established", **common)
    return CameraVerdict(NO_OBJECTION, True, True, "corridor observed free (camera estimate); supervisor gates "
                         "still apply", **common)

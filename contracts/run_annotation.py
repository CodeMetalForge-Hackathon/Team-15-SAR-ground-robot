"""Run annotation: operator-stated context for a live camera run.

A sighting (perception/SIGHTING_FORMAT.md) says what the camera saw in one
frame. It cannot say what the *run* was: e.g. a run started as an "empty
scene" in which a consenting person was in fact present. That context comes
from the operator, so it lives in a separate file next to the evidence
(``run_annotation.json``, written once by ``core.evidence_import``) and never
edits the sighting itself.

    {
      "schema": "team15.run_annotation/1",
      "run_id": "D1-b1794121685-empty",
      "obs_ids": ["D1-b1794121685-000001"],
      "classification": "LIVE_HARDWARE_PERSON_PRESENT",
      "scene_requested": "empty",
      "counts_as_empty_scene": false,
      "consent": {"status": "CONSENTED", "scope": ["capture", "storage", "dashboard_display"],
                  "stated_by": "...", "stated_at": "2026-11-08", "public_sharing": false},
      "measured": {"processed_fps": 4.75, "capture_to_rx_s_median": 0.29, ...,
                   "derived_from": {"<file>": "<sha256>"}},
      "evidence": {"<obs_id>": {"frame_sha256": "...", "frame_sha256_matches_sighting": true,
                                "annotated_sha256": "...", "annotated_sha256_recorded": "..."}}
    }

The dashboard shows an annotation only on observations it names, and only
while the evidence frame SHA-256 in the annotation equals the observation's
``evidence.frame_sha256``. Display labels come from ``classification``, never
from free text.
"""
from __future__ import annotations

SCHEMA = "team15.run_annotation/1"
CLASSIFICATIONS = {
    "LIVE_HARDWARE_PERSON_PRESENT": "LIVE HARDWARE — PERSON PRESENT",
    "LIVE_HARDWARE_EMPTY_SCENE": "LIVE HARDWARE — EMPTY SCENE",
    "LIVE_HARDWARE_OBJECT_SCENE": "LIVE HARDWARE — OBJECT SCENE",
}
CONSENT_STATUSES = {"CONSENTED", "NOT_RECORDED"}
CONSENT_SCOPES = {"capture", "storage", "dashboard_display"}


class InvalidRunAnnotation(ValueError):
    pass


def validate(ann: dict) -> dict:
    """Raise InvalidRunAnnotation unless ``ann`` follows this contract."""
    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise InvalidRunAnnotation(msg)

    need(isinstance(ann, dict), "run annotation must be a JSON object")
    need(ann.get("schema") == SCHEMA, f"schema must be {SCHEMA!r}")
    need(isinstance(ann.get("run_id"), str) and ann["run_id"], "run_id is required")
    ids = ann.get("obs_ids")
    need(isinstance(ids, list) and ids and all(isinstance(i, str) for i in ids),
         "obs_ids must be a non-empty list of observation ids")
    cls = ann.get("classification")
    need(cls in CLASSIFICATIONS, f"classification must be one of {sorted(CLASSIFICATIONS)}")
    need(isinstance(ann.get("counts_as_empty_scene"), bool), "counts_as_empty_scene must be a bool")
    if cls != "LIVE_HARDWARE_EMPTY_SCENE":
        need(ann["counts_as_empty_scene"] is False,
             "only an EMPTY_SCENE run may count as an empty-scene result")
    c = ann.get("consent")
    need(isinstance(c, dict) and c.get("status") in CONSENT_STATUSES,
         f"consent.status must be one of {sorted(CONSENT_STATUSES)}")
    need(set(c.get("scope") or []) <= CONSENT_SCOPES, f"consent.scope must be within {sorted(CONSENT_SCOPES)}")
    need(c.get("public_sharing") is False, "consent.public_sharing must be false")
    if cls == "LIVE_HARDWARE_PERSON_PRESENT":
        need(c["status"] == "CONSENTED" and {"capture", "storage", "dashboard_display"} <= set(c["scope"]),
             "a PERSON_PRESENT run may be displayed only with consent to capture, storage "
             "and dashboard_display")
        need(bool(c.get("stated_by")) and bool(c.get("stated_at")),
             "consent.stated_by and consent.stated_at are required")
    ev = ann.get("evidence")
    need(isinstance(ev, dict) and set(ev) == set(ids),
         "evidence must have one entry per obs_id")
    for oid, e in ev.items():
        need(isinstance(e, dict) and isinstance(e.get("frame_sha256"), str)
             and len(e["frame_sha256"]) == 64, f"evidence[{oid}].frame_sha256 is required")
        need(e.get("frame_sha256_matches_sighting") is True,
             f"evidence[{oid}]: the frame was not verified against the sighting checksum")
    m = ann.get("measured")
    need(isinstance(m, dict) and isinstance(m.get("derived_from"), dict) and m["derived_from"],
         "measured.derived_from must list the run files the numbers came from")
    return ann


def view(ann: dict, obs_id: str) -> dict:
    """What the dashboard shows for one observation of this run."""
    m, c = ann["measured"], ann["consent"]
    e = ann["evidence"][obs_id]
    return {
        "run_id": ann["run_id"],
        "classification": ann["classification"],
        "label": CLASSIFICATIONS[ann["classification"]],
        "scene_requested": ann.get("scene_requested"),
        "counts_as_empty_scene": ann["counts_as_empty_scene"],
        "processed_fps": m.get("processed_fps"),
        "capture_to_rx_s_median": m.get("capture_to_rx_s_median"),
        "capture_to_rx_s_max": m.get("capture_to_rx_s_max"),
        "frames": m.get("frames"),
        "person_frames": m.get("person_frames"),
        "person_score_median": m.get("person_score_median"),
        "person_score_min": m.get("person_score_min"),
        "person_score_max": m.get("person_score_max"),
        "live_capture_to_dashboard_s": (m.get("live_delivery") or {}).get("capture_to_dashboard_s"),
        "pi_health": m.get("pi_health"),
        "consent_status": c["status"],
        "consent_scope": list(c.get("scope") or []),
        "consent_stated_at": c.get("stated_at"),
        "frame_sha256": e["frame_sha256"],
        "annotated_sha256": e.get("annotated_sha256"),
        "annotated_sha256_recorded": e.get("annotated_sha256_recorded"),
    }

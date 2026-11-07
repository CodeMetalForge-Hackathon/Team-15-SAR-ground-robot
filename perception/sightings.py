"""One-sighting-per-person gate, sighting records, and evidence storage.

Dedup rule (bench camera, one declared sector, no identity):
  * A candidate must appear in ``confirm_frames`` consecutive processed frames
    before the first sighting is emitted (suppresses one-frame false alerts).
  * Once a sighting is emitted, every further positive frame is attached to it
    (counted, not re-emitted) for as long as the candidate keeps reappearing.
  * A new sighting is only possible after the candidate has been absent for
    ``rearm_s`` seconds (default 60 s, the guide's SYNTHETIC dedup window for
    same drone + same cell).
The bench camera cannot tell two people apart, so a second person entering
while the first is still visible is attached to the same sighting.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

import cv2
import numpy as np

from .detectors import Detection

SECTORS = tuple(chr(c) for c in range(ord("A"), ord("Z") + 1))
DEFAULT_EVIDENCE_DIR = os.path.expanduser("~/Team15_evidence/camera")


@dataclass
class SightingGate:
    confirm_frames: int = 3
    rearm_s: float = 60.0
    _streak: int = 0
    _active: bool = False
    _last_seen: Optional[float] = None
    attached_frames: int = 0
    suppressed_total: int = field(default=0)

    def update(self, t: float, present: bool) -> bool:
        """Feed one processed frame. Returns True iff a new sighting should be emitted."""
        if self._active and self._last_seen is not None and t - self._last_seen >= self.rearm_s:
            self._active = False  # absent long enough: re-arm
        if not present:
            self._streak = 0
            return False
        self._last_seen = t
        if self._active:
            self.attached_frames += 1
            self.suppressed_total += 1
            return False
        self._streak += 1
        if self._streak >= self.confirm_frames:
            self._active = True
            self._streak = 0
            self.attached_frames = 0
            return True
        return False


def validate_sector(s: str) -> str:
    s = s.strip().upper()
    if s not in SECTORS:
        raise ValueError(f"sector must be one letter A-Z, got {s!r}")
    return s


def iso_utc(t: float) -> str:
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).isoformat(timespec="milliseconds")


def make_sighting(*, drone_id: str, boot_id: str, seq: int, sector: str, obs_time: float,
                  frame_ref: str, frame_sha256: str, annotated_ref: Optional[str],
                  frame_size: List[int], trigger: Detection,
                  all_dets: List[Detection], operator: Optional[str] = None) -> dict:
    persons = [d for d in all_dets if d.family == trigger.family]
    return {
        "obs_id": f"{drone_id}-{boot_id}-{seq:06d}",
        "drone_id": drone_id,
        "boot_id": boot_id,
        "seq": seq,
        "source_mode": "LIVE-HW",
        "platform": "BENCH",
        "sensor": "rgb",
        "kind": "PERSON_VISUAL",
        "how": "SECTOR_ONLY",
        "cell": sector,
        "cell_source": "OPERATOR_ASSIGNED",
        "operator": operator,
        "obs_time": round(obs_time, 3),
        "obs_time_iso": iso_utc(obs_time),
        "confidence": None,  # detector scores are not calibrated probabilities
        "evidence": {
            "frame_ref": frame_ref,
            "frame_sha256": frame_sha256,
            "annotated_ref": annotated_ref,
            "frame_size": frame_size,
            "bbox": [int(v) for v in trigger.bbox],
            "detector": trigger.detector,
            "detector_family": trigger.family,
            "detector_score": None if trigger.score is None else round(trigger.score, 4),
            "detector_score_kind": trigger.score_kind,
            "count_in_frame": len(persons),
            "detections_in_frame": [d.to_json() for d in all_dets],
        },
    }


def _nearest_existing(path: str) -> str:
    p = os.path.abspath(path)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def inside_git_worktree(path: str) -> bool:
    probe = _nearest_existing(path)
    if os.path.isfile(probe):
        probe = os.path.dirname(probe)
    try:
        r = subprocess.run(["git", "-C", probe, "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def ensure_evidence_dir(path: str) -> str:
    path = os.path.abspath(os.path.expanduser(path))
    if inside_git_worktree(path):
        raise ValueError(f"evidence dir {path} is inside a Git work tree; photos of "
                         "people must be stored outside Git")
    os.makedirs(path, exist_ok=True)
    return path


def save_evidence(out_dir: str, obs_id: str, frame: np.ndarray,
                  annotated: Optional[np.ndarray]) -> tuple:
    """Write the exact evidence frame losslessly (PNG) plus an annotated JPEG."""
    raw = os.path.join(out_dir, f"{obs_id}.png")
    if not cv2.imwrite(raw, frame):
        raise OSError(f"failed to write {raw}")
    with open(raw, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    ann = None
    if annotated is not None:
        ann = os.path.join(out_dir, f"{obs_id}_annotated.jpg")
        if not cv2.imwrite(ann, annotated):
            raise OSError(f"failed to write {ann}")
    return raw, sha, ann

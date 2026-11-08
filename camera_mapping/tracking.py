"""Frame-to-frame object tracks so repeated frames never become new obstacles.

Association: greedy IoU within the same class (falls back to centre distance
for small boxes). A track is CONFIRMED after ``confirm_hits`` matched frames,
is COASTING while unmatched, and is dropped after ``expire_s`` without a match.

Distance filter per track: median of the last ``window`` accepted estimates.
A new estimate that jumps more than max(jump_abs_m, jump_rel * filtered) and
more than 3 sigma from the filtered value is rejected (counted), unless it
persists for ``jump_persist`` consecutive frames (a genuine scene change).
"""
from __future__ import annotations

import itertools
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .detector import ObjectDetection
from .distance import ESTIMATED, DistanceEstimate

TENTATIVE, CONFIRMED, COASTING = "TENTATIVE", "CONFIRMED", "COASTING"


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    track_id: int
    label: str
    bbox: List[float]
    score: float
    first_t: float
    last_t: float
    hits: int = 1
    misses: int = 0
    state: str = TENTATIVE
    estimate: Optional[DistanceEstimate] = None
    history: List[tuple] = field(default_factory=list)   # (t, d, sigma, lateral)
    pending_jump: List[tuple] = field(default_factory=list)
    rejected_jumps: int = 0
    frame_seen: Optional[int] = None

    def filtered(self):
        if not self.history:
            return None
        ds = [h[1] for h in self.history]
        sig = [h[2] for h in self.history]
        lat = [h[3] for h in self.history]
        return statistics.median(ds), statistics.median(sig), statistics.median(lat)


class Tracker:
    def __init__(self, confirm_hits: int = 2, expire_s: float = 2.0, iou_min: float = 0.3,
                 window: int = 5, jump_abs_m: float = 0.5, jump_rel: float = 0.35,
                 jump_persist: int = 3) -> None:
        self.confirm_hits, self.expire_s, self.iou_min = confirm_hits, expire_s, iou_min
        self.window, self.jump_abs_m, self.jump_rel, self.jump_persist = window, jump_abs_m, jump_rel, jump_persist
        self.tracks: Dict[int, Track] = {}
        self._ids = itertools.count(1)
        self.frames = 0

    def update(self, t: float, dets: List[ObjectDetection], ests: List[DistanceEstimate]) -> List[Track]:
        self.frames += 1
        pairs = []
        for tid, tr in self.tracks.items():
            for i, d in enumerate(dets):
                if d.label != tr.label:
                    continue
                s = iou(tr.bbox, d.bbox)
                if s >= self.iou_min:
                    pairs.append((s, tid, i))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for s, tid, i in pairs:
            if tid in used_t or i in used_d:
                continue
            used_t.add(tid)
            used_d.add(i)
            self._match(self.tracks[tid], t, dets[i], ests[i])
        for i, d in enumerate(dets):
            if i not in used_d:
                tr = Track(next(self._ids), d.label, list(d.bbox), d.score, t, t)
                self.tracks[tr.track_id] = tr
                self._accept_estimate(tr, t, ests[i])
                tr.frame_seen = self.frames
                if self.confirm_hits <= 1:
                    tr.state = CONFIRMED
        for tid, tr in list(self.tracks.items()):
            if tid not in used_t and tr.frame_seen != self.frames:
                tr.misses += 1
                if tr.state == CONFIRMED:
                    tr.state = COASTING
            if t - tr.last_t > self.expire_s:
                del self.tracks[tid]
        return list(self.tracks.values())

    def _match(self, tr: Track, t: float, d: ObjectDetection, e: DistanceEstimate) -> None:
        tr.bbox, tr.score, tr.last_t = list(d.bbox), d.score, t
        tr.hits += 1
        tr.misses = 0
        tr.frame_seen = self.frames
        if tr.hits >= self.confirm_hits:
            tr.state = CONFIRMED
        self._accept_estimate(tr, t, e)

    def _accept_estimate(self, tr: Track, t: float, e: DistanceEstimate) -> None:
        tr.estimate = e
        if e.status != ESTIMATED:
            return
        f = tr.filtered()
        sample = (t, e.distance_m, e.sigma_m, e.lateral_m)
        if f is not None:
            fd, fs, _ = f
            gap = abs(e.distance_m - fd)
            if gap > max(self.jump_abs_m, self.jump_rel * fd) and gap > 3 * max(fs, e.sigma_m):
                tr.pending_jump.append(sample)
                if len(tr.pending_jump) < self.jump_persist:
                    tr.rejected_jumps += 1
                    return
                tr.history = list(tr.pending_jump)  # persistent change: restart the filter
                tr.pending_jump = []
                return
        tr.pending_jump = []
        tr.history.append(sample)
        tr.history = tr.history[-self.window:]

    def confirmed(self) -> List[Track]:
        return [tr for tr in self.tracks.values() if tr.state in (CONFIRMED, COASTING)]

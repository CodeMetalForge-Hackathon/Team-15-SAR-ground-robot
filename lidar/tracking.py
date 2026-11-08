"""Consecutive-frame obstacle tracking, FOR VISUALIZATION ONLY.

Clusters adjacent valid returns into blobs in the SENSOR frame, then associates the
blobs with the previous frame's by nearest centroid. The track IDs only help the
operator see that "the thing at 1.2 m is the same thing it was a moment ago".

Not used by any safety decision. A track is not a person, and its velocity is not
the robot's motion: the robot may be moving, and there is no odometry. Nothing
here is fed to motion or to Qwen as a fact about a person.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .scan import Scan

SCHEMA = "team15.lidar_tracks/1"


@dataclass
class Cluster:
    x: float
    y: float
    range_m: float
    sensor_bearing_deg: float
    n: int
    width_m: float


def cluster_scan(scan: Scan, gap_m: float = 0.15, min_points: int = 3) -> list[Cluster]:
    pts = sorted(((s.angle_deg, s.distance_m, s.xy_sensor()) for s in scan.valid_samples), key=lambda t: t[0])
    groups, cur = [], []
    for p in pts:
        if cur:
            ox, oy = cur[-1][2]
            if math.hypot(p[2][0] - ox, p[2][1] - oy) > gap_m:
                groups.append(cur)
                cur = []
        cur.append(p)
    if cur:
        groups.append(cur)
    # merge wrap-around (359 deg -> 0 deg)
    if len(groups) > 1:
        (ax, ay), (bx, by) = groups[-1][-1][2], groups[0][0][2]
        if math.hypot(ax - bx, ay - by) <= gap_m:
            groups[0] = groups.pop() + groups[0]
    out = []
    for g in groups:
        if len(g) < min_points:
            continue
        xs, ys = [p[2][0] for p in g], [p[2][1] for p in g]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        w = math.hypot(xs[0] - xs[-1], ys[0] - ys[-1])
        brg = (-math.degrees(math.atan2(cy, cx))) % 360.0
        out.append(Cluster(cx, cy, min(p[1] for p in g), brg, len(g), w))
    return out


@dataclass
class Track:
    track_id: int
    cluster: Cluster
    age_frames: int
    missed: int = 0


class VisualTracker:
    def __init__(self, max_jump_m: float = 0.35, max_missed: int = 2):
        self.max_jump_m, self.max_missed = max_jump_m, max_missed
        self.tracks: list[Track] = []
        self._next = 1
        self.last_seq: Optional[int] = None

    def update(self, scan: Scan) -> list[Track]:
        clusters = cluster_scan(scan)
        unused = list(range(len(clusters)))
        for t in self.tracks:
            best, bd = None, self.max_jump_m
            for i in unused:
                c = clusters[i]
                d = math.hypot(c.x - t.cluster.x, c.y - t.cluster.y)
                if d <= bd:
                    best, bd = i, d
            if best is None:
                t.missed += 1
            else:
                t.cluster, t.missed = clusters[best], 0
                t.age_frames += 1
                unused.remove(best)
        self.tracks = [t for t in self.tracks if t.missed <= self.max_missed]
        for i in unused:
            self.tracks.append(Track(self._next, clusters[i], 1))
            self._next += 1
        self.last_seq = scan.seq
        return [t for t in self.tracks if t.missed == 0]

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "frame": "SENSOR", "scan_seq": self.last_seq,
                "use": "VISUALIZATION_ONLY: not a safety input, not a person, not a world position",
                "tracks": [{"id": t.track_id, "x_m": round(t.cluster.x, 3), "y_m": round(t.cluster.y, 3),
                            "range_m": round(t.cluster.range_m, 3),
                            "sensor_bearing_deg": round(t.cluster.sensor_bearing_deg, 2),
                            "points": t.cluster.n, "width_m": round(t.cluster.width_m, 3),
                            "age_frames": t.age_frames, "is_person": None}
                           for t in self.tracks if t.missed == 0]}

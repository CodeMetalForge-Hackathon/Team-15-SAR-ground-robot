"""In-memory mission store for the first dashboard slice.

Scope of this first version (issue #4):
- observations deduplicated by ``obs_id``;
- one track per sector cell, ``T1``, ``T2``... in order of first sighting.
  The association gate, late-packet rule and review queue (§3.4) are the next
  tracker step and are not implemented here;
- route versions: the responder's route to the newest track is recomputed with
  ``planner.route.compute_route`` and gets a new version only when the
  destination, start node or blocked-edge set changes.

The SQLite store from §5.1 replaces this class later; ``state()`` is the
``GET /state`` contract the dashboard page reads.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from core.ingest import normalise
from planner.graph import TrailGraph, load_graph
from planner.route import compute_route

BADGES = {
    ("LIVE-HW", "BENCH"): "LIVE-HW (bench)",
    ("LIVE-HW", "AIRCRAFT"): "LIVE-HW (airborne)",
    ("RECORDED-IMAGERY", None): "RECORDED-IMAGERY",
    ("SIMULATED", None): "SIMULATED",
}


def badge_for(obs: dict) -> str:
    key = (obs["source_mode"], obs.get("platform") if obs["source_mode"] == "LIVE-HW" else None)
    return BADGES.get(key, obs["source_mode"])


def cell_position(graph: TrailGraph, cell: str) -> tuple[int, int]:
    """Column/row of a cell in the 7-wide sector grid (§3.1)."""
    i = graph.nodes.index(cell)
    return i % 7, i // 7


class MissionStore:
    def __init__(self, graph: TrailGraph | None = None, responder_node: str = "A",
                 clock=time.time) -> None:
        self.graph = graph if graph is not None else load_graph()
        if responder_node not in self.graph.nodes:
            raise ValueError(f"responder node {responder_node!r} is not on the trail map")
        self.responder_node = responder_node
        self.blocked: frozenset[str] = frozenset()
        self.clock = clock
        self._lock = threading.Lock()
        self._obs: dict[str, dict] = {}
        self._tracks: dict[str, dict] = {}       # track_id -> track
        self._track_by_cell: dict[str, str] = {}
        self._routes: list[dict] = []

    # ---- writes -------------------------------------------------------------
    def add_observation(self, raw: dict) -> dict:
        """Ingest one observation. Returns {"obs_id", "duplicate", "track_id"}."""
        with self._lock:
            obs_id = raw.get("obs_id") if isinstance(raw, dict) else None
            if obs_id in self._obs:
                prev = self._obs[obs_id]
                return {"obs_id": obs_id, "duplicate": True, "track_id": prev["track_id"]}
            obs = normalise(raw, known_cells=self.graph.nodes, rx_time=self.clock())
            track_id = self._track_by_cell.get(obs["cell"])
            if track_id is None:
                track_id = f"T{len(self._tracks) + 1}"
                self._track_by_cell[obs["cell"]] = track_id
                self._tracks[track_id] = {"track_id": track_id, "cell": obs["cell"],
                                          "obs_ids": [], "latest_obs_id": None}
            track = self._tracks[track_id]
            obs["track_id"] = track_id
            self._obs[obs_id] = obs
            track["obs_ids"].append(obs_id)
            latest = self._obs.get(track["latest_obs_id"]) if track["latest_obs_id"] else None
            if latest is None or obs["obs_time"] > latest["obs_time"]:
                track["latest_obs_id"] = obs_id
            self._replan()
            return {"obs_id": obs_id, "duplicate": False, "track_id": track_id}

    def _target_track(self) -> dict | None:
        if not self._tracks:
            return None
        return max(self._tracks.values(),
                   key=lambda t: self._obs[t["latest_obs_id"]]["obs_time"])

    def _replan(self) -> None:
        target = self._target_track()
        if target is None:
            return
        frm, to = self.responder_node, target["cell"]
        active = self._routes[-1] if self._routes else None
        if active and (active["from"], active["to"], tuple(active["blocked"])) == \
                (frm, to, tuple(sorted(self.blocked))):
            return
        res = compute_route(frm, to, blocked=self.blocked, graph=self.graph).to_dict()
        if active:
            active["active"] = False
        self._routes.append({"version": len(self._routes) + 1, "from": frm, "to": to,
                             "track_id": target["track_id"], "blocked": sorted(self.blocked),
                             "active": True, "computed_at": self.clock(), **res})

    # ---- reads --------------------------------------------------------------
    def observation(self, obs_id: str) -> dict | None:
        with self._lock:
            return self._obs.get(obs_id)

    def state(self) -> dict:
        with self._lock:
            now = self.clock()
            tracks = []
            for t in self._tracks.values():
                o = self._obs[t["latest_obs_id"]]
                age = now - o["obs_time"]
                ev = o.get("evidence") or {}
                sources = sorted({f"{x['drone_id']} {x['sensor'].upper()}"
                                  for x in (self._obs[i] for i in t["obs_ids"])})
                tracks.append({
                    "track_id": t["track_id"],
                    "cell": t["cell"],
                    "label": f"Candidate in sector {t['cell']} (assigned)"
                    if o["how"] == "SECTOR_ONLY" else f"Candidate near sector {t['cell']}",
                    "how": o["how"],
                    "confirmation": "unconfirmed",
                    "sources": sources,
                    "n_observations": len(t["obs_ids"]),
                    "badge": badge_for(o),
                    "latest": {
                        "obs_id": o["obs_id"],
                        "drone_id": o["drone_id"],
                        "sensor": o["sensor"],
                        "kind": o["kind"],
                        "obs_time": o["obs_time"],
                        "rx_time": o["rx_time"],
                        "stale_after_s": o["stale_after_s"],
                        "age_s": age,
                        "stale": age > o["stale_after_s"],
                        "confidence": o.get("confidence"),
                        "detector": ev.get("detector"),
                        "detector_score": ev.get("detector_score"),
                        "detector_score_kind": ev.get("detector_score_kind"),
                        "has_photo": bool(ev.get("frame_ref")),
                        "photo_url": f"/evidence/{o['obs_id']}" if ev.get("frame_ref") else None,
                        "photo_name": Path(ev["frame_ref"]).name if ev.get("frame_ref") else None,
                    },
                })
            return {
                "server_time": now,
                "responder": {"node": self.responder_node},
                "tracks": tracks,
                "routes": [dict(r) for r in self._routes],
                "graph": {
                    "label": "SYNTHETIC trail map (§3.2): distances are not measured terrain",
                    "cell_size_m": 10,
                    "nodes": [{"id": n, "col": cell_position(self.graph, n)[0],
                               "row": cell_position(self.graph, n)[1]} for n in self.graph.nodes],
                    "edges": [{"a": a, "b": b, "m": m} for a, b, m in self.graph.edges()],
                },
            }

"""In-memory mission store for the dashboard.

Scope (issue #4):
- observations deduplicated by ``obs_id`` and by ``evidence.frame_sha256``
  (the same evidence frame re-sent under another id is a duplicate, not a
  new person and not a new alert);
- one track per sector cell, ``T1``, ``T2``... in order of first sighting.
  Every sighting in a cell is kept as that track's history; the newest by
  ``obs_time`` is shown as current. The association gate, late-packet rule and
  review queue across cells (§3.4) are the next tracker step;
- every sighting starts ``unconfirmed``. Only an explicit operator decision
  (``decide``) marks it ``confirmed`` or ``rejected``;
- route versions: the responder's route to the track with the newest
  non-rejected sighting, from ``planner.route.compute_route``. A new version is
  made only when the start, destination or blocked-edge set changes;
- one alert per new (non-duplicate) sighting.

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

UNCONFIRMED, CONFIRMED, REJECTED = "unconfirmed", "confirmed", "rejected"
DECISIONS = {"CONFIRM": CONFIRMED, "CONFIRMED": CONFIRMED,
             "REJECT": REJECTED, "REJECTED": REJECTED}

BADGES = {
    ("LIVE-HW", "BENCH"): "LIVE-HW (bench)",
    ("LIVE-HW", "AIRCRAFT"): "LIVE-HW (airborne)",
    ("RECORDED-IMAGERY", None): "RECORDED-IMAGERY",
    ("SIMULATED", None): "SIMULATED",
}


class UnknownObservation(KeyError):
    pass


class InvalidDecision(ValueError):
    pass


def badge_for(obs: dict) -> str:
    key = (obs["source_mode"], obs.get("platform") if obs["source_mode"] == "LIVE-HW" else None)
    return BADGES.get(key, obs["source_mode"])


def cell_position(graph: TrailGraph, cell: str) -> tuple[int, int]:
    """Column/row of a cell in the 7-wide sector grid (§3.1)."""
    i = graph.nodes.index(cell)
    return i % 7, i // 7


def _name(path) -> str | None:
    return Path(path).name if path else None


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
        self._by_sha: dict[str, str] = {}        # frame_sha256 -> obs_id
        self._tracks: dict[str, dict] = {}       # track_id -> track
        self._track_by_cell: dict[str, str] = {}
        self._routes: list[dict] = []
        self._alerts: list[dict] = []
        self._decisions: list[dict] = []

    # ---- writes -------------------------------------------------------------
    def add_observation(self, raw: dict) -> dict:
        """Ingest one observation.

        Returns {"obs_id", "duplicate", "track_id"} and, for a duplicate frame,
        "duplicate_of".
        """
        with self._lock:
            obs_id = raw.get("obs_id") if isinstance(raw, dict) else None
            if obs_id in self._obs:
                return {"obs_id": obs_id, "duplicate": True,
                        "track_id": self._obs[obs_id]["track_id"]}
            obs = normalise(raw, known_cells=self.graph.nodes, rx_time=self.clock())
            sha = (obs.get("evidence") or {}).get("frame_sha256")
            if sha and sha in self._by_sha:
                first = self._obs[self._by_sha[sha]]
                return {"obs_id": obs_id, "duplicate": True, "duplicate_of": first["obs_id"],
                        "track_id": first["track_id"]}

            track_id = self._track_by_cell.get(obs["cell"])
            if track_id is None:
                track_id = f"T{len(self._tracks) + 1}"
                self._track_by_cell[obs["cell"]] = track_id
                self._tracks[track_id] = {"track_id": track_id, "cell": obs["cell"],
                                          "obs_ids": [], "latest_obs_id": None}
            track = self._tracks[track_id]
            obs["track_id"] = track_id
            obs["confirmation"] = UNCONFIRMED
            obs["decided_by"] = None
            obs["decided_at"] = None
            self._obs[obs_id] = obs
            if sha:
                self._by_sha[sha] = obs_id
            track["obs_ids"].append(obs_id)
            latest = self._obs.get(track["latest_obs_id"]) if track["latest_obs_id"] else None
            if latest is None or obs["obs_time"] > latest["obs_time"]:
                track["latest_obs_id"] = obs_id
            self._alerts.append({"alert_id": len(self._alerts) + 1, "obs_id": obs_id,
                                 "track_id": track_id, "cell": obs["cell"],
                                 "badge": badge_for(obs), "rx_time": obs["rx_time"]})
            self._replan()
            return {"obs_id": obs_id, "duplicate": False, "track_id": track_id}

    def decide(self, obs_id: str, decision: str, operator: str) -> dict:
        """Operator confirms or rejects one sighting. Nothing else changes it."""
        status = DECISIONS.get(str(decision).upper())
        if status is None:
            raise InvalidDecision("decision must be CONFIRM or REJECT")
        if not operator or not str(operator).strip():
            raise InvalidDecision("operator is required")
        with self._lock:
            obs = self._obs.get(obs_id)
            if obs is None:
                raise UnknownObservation(obs_id)
            now = self.clock()
            obs["confirmation"] = status
            obs["decided_by"] = str(operator).strip()
            obs["decided_at"] = now
            self._decisions.append({"obs_id": obs_id, "decision": status,
                                    "operator": obs["decided_by"], "time": now})
            self._replan()
            return {"obs_id": obs_id, "confirmation": status, "operator": obs["decided_by"]}

    def _newest_live(self, track: dict) -> dict | None:
        pool = [self._obs[i] for i in track["obs_ids"]
                if self._obs[i]["confirmation"] != REJECTED]
        return max(pool, key=lambda o: o["obs_time"]) if pool else None

    def _target_track(self) -> dict | None:
        best = None
        for t in self._tracks.values():
            o = self._newest_live(t)
            if o is not None and (best is None or o["obs_time"] > best[1]["obs_time"]):
                best = (t, o)
        return best[0] if best else None

    def _replan(self) -> None:
        target = self._target_track()
        active = next((r for r in self._routes if r["active"]), None)
        if target is None:
            if active:
                active["active"] = False   # every sighting rejected: no destination
            return
        frm, to = self.responder_node, target["cell"]
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

    def _sighting_view(self, o: dict, now: float) -> dict:
        ev = o.get("evidence") or {}
        age = now - o["obs_time"]
        has_frame = bool(ev.get("frame_ref"))
        has_annotated = bool(ev.get("annotated_ref"))
        return {
            "obs_id": o["obs_id"],
            "drone_id": o["drone_id"],
            "sensor": o["sensor"],
            "kind": o["kind"],
            "how": o["how"],
            "cell": o["cell"],
            "cell_source": o.get("cell_source"),
            "badge": badge_for(o),
            "source_mode": o["source_mode"],
            "platform": o.get("platform"),
            "obs_time": o["obs_time"],
            "obs_time_iso": o.get("obs_time_iso"),
            "rx_time": o["rx_time"],
            "stale_after_s": o["stale_after_s"],
            "age_s": age,
            "stale": age > o["stale_after_s"],
            "confirmation": o["confirmation"],
            "decided_by": o["decided_by"],
            "decided_at": o["decided_at"],
            "confidence": o.get("confidence"),
            "detector": ev.get("detector"),
            "detector_family": ev.get("detector_family"),
            "detector_score": ev.get("detector_score"),
            "detector_score_kind": ev.get("detector_score_kind"),
            "count_in_frame": ev.get("count_in_frame"),
            "frame_sha256": ev.get("frame_sha256"),
            "has_photo": has_frame or has_annotated,
            # Display the annotated JPEG when there is one; /frame is the exact evidence.
            "photo_url": f"/evidence/{o['obs_id']}" if (has_frame or has_annotated) else None,
            "frame_url": f"/evidence/{o['obs_id']}/frame" if has_frame else None,
            "photo_name": _name(ev.get("annotated_ref") or ev.get("frame_ref")),
            "frame_name": _name(ev.get("frame_ref")),
        }

    def state(self) -> dict:
        with self._lock:
            now = self.clock()
            tracks = []
            for t in self._tracks.values():
                o = self._obs[t["latest_obs_id"]]
                members = [self._obs[i] for i in t["obs_ids"]]
                sources = sorted({f"{x['drone_id']} {x['sensor'].upper()}" for x in members})
                history = sorted((self._sighting_view(x, now) for x in members
                                  if x["obs_id"] != o["obs_id"]),
                                 key=lambda s: s["obs_time"], reverse=True)
                tracks.append({
                    "track_id": t["track_id"],
                    "cell": t["cell"],
                    "label": f"Candidate in sector {t['cell']} (assigned)"
                    if o["how"] == "SECTOR_ONLY" else f"Candidate near sector {t['cell']}",
                    "how": o["how"],
                    "confirmation": o["confirmation"],
                    "sources": sources,
                    "n_observations": len(members),
                    "badge": badge_for(o),
                    "latest": self._sighting_view(o, now),
                    "history": history,
                })
            return {
                "server_time": now,
                "responder": {"node": self.responder_node},
                "tracks": tracks,
                "routes": [dict(r) for r in self._routes],
                "alerts": [dict(a) for a in self._alerts],
                "decisions": [dict(d) for d in self._decisions],
                "graph": {
                    "label": "SYNTHETIC trail map (§3.2): distances are not measured terrain",
                    "cell_size_m": 10,
                    "nodes": [{"id": n, "col": cell_position(self.graph, n)[0],
                               "row": cell_position(self.graph, n)[1]} for n in self.graph.nodes],
                    "edges": [{"a": a, "b": b, "m": m} for a, b, m in self.graph.edges()],
                },
            }

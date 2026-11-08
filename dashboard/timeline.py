"""Mission timeline: observed events only, each labelled with where it came from.

Events are derived from what the dashboard actually receives: camera heartbeats, perception frames
posted by camera_mapping.live, and the read-only controller USB probe. Nothing is inferred or
synthesised: a person event exists only because a posted frame contained that track. Each event keeps
the source_mode of the frame that produced it (LIVE-HW / RECORDED / SYNTHETIC), so a replayed
detection can never read as a live one. Memory only, bounded.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

SCHEMA = "team15.mission_timeline/1"


class Timeline:
    def __init__(self, clock: Callable[[], float] = time.time, maxlen: int = 300, lost_after_s: float = 3.0):
        self.clock, self.lost_after_s = clock, lost_after_s
        self.lock = threading.Lock()
        self.events: deque = deque(maxlen=maxlen)
        self._seq = 0
        self._camera: Optional[str] = None
        self._persons: dict[int, float] = {}       # track_id -> last frame time it was in
        self._person_mode: dict[int, str] = {}
        self._conflict_at = -1e18

    def add(self, kind: str, source: str, detail: str, **extra) -> dict:
        with self.lock:
            return self._add(kind, source, detail, **extra)

    def _add(self, kind: str, source: str, detail: str, **extra) -> dict:
        self._seq += 1
        ev = {"seq": self._seq, "t": round(self.clock(), 3), "kind": kind, "source": source,
              "detail": detail, **extra}
        self.events.append(ev)
        return ev

    # --- observers ------------------------------------------------------------------
    def observe_camera(self, status: Optional[str], source_mode: Optional[str], error: Optional[str] = None):
        if not status:
            return
        with self.lock:
            if status != self._camera:
                d = f"camera {self._camera or 'NOT_CONNECTED'} -> {status}"
                if error:
                    d += f" ({error})"
                self._camera = status
                self._add("CAMERA", source_mode or "UNKNOWN", d)

    def observe_frame(self, state: dict):
        """A validated team15.camera_perception/1 state."""
        mode = state.get("source_mode") or "UNKNOWN"
        t = state.get("t")
        self.observe_camera("STREAMING", mode)
        with self.lock:
            seen = set()
            for p in state.get("persons") or []:
                tid = p.get("track_id")
                if not isinstance(tid, int) or p.get("validity") not in ("VALID", "CONFIRMED"):
                    continue
                seen.add(tid)
                if tid not in self._persons:
                    dist = p.get("distance") or {}
                    b = dist.get("bearing_deg")
                    rng = (f"{dist['distance_m']:.2f} m {dist.get('label')}"
                           if dist.get("status") == "ESTIMATED" and dist.get("distance_m") is not None
                           else "distance UNKNOWN")
                    self._add("PERSON_DETECTED", mode,
                              f"person #{tid} conf {p.get('detection_confidence', 0):.2f}"
                              + (f", bearing {b:+.1f}°" if isinstance(b, (int, float)) else "")
                              + f", {p.get('corridor_position') or 'corridor ?'}, {rng}",
                              track_id=tid, frame_t=t, confidence=p.get("detection_confidence"),
                              bearing_deg=b, corridor_position=p.get("corridor_position"))
                self._persons[tid] = self.clock()
                self._person_mode[tid] = mode
            now = self.clock()
            for tid in [k for k, last in self._persons.items()
                        if k not in seen and now - last > self.lost_after_s]:
                self._add("PERSON_LOST", self._person_mode.pop(tid, mode),
                          f"person #{tid} not seen for {now - self._persons.pop(tid):.1f} s", track_id=tid)

    def observe_conflict(self, detail: str, every_s: float = 10.0):
        with self.lock:
            if self.clock() - self._conflict_at >= every_s:
                self._conflict_at = self.clock()
                self._add("PRODUCER_CONFLICT", "DASHBOARD", detail)

    def observe_rover(self, st: dict):
        """Rover host status transitions: commanded motion, e-stop, safety latch, camera veto."""
        src = "MAC_HOST:" + ("PHYSICAL" if st.get("physical") else "SIMULATED")
        latch = (st.get("safety_latch") or {}).get("kind")
        key = (st.get("active_command"), bool((st.get("estop") or {}).get("tripped")), latch,
               (st.get("camera_verdict") or {}).get("action"))
        with self.lock:
            if key == getattr(self, "_rover_key", None):
                return
            self._rover_key = key
            v = st.get("camera_verdict") or {}
            self._add("ROVER", src, f"command {key[0]}" + (" · E-STOP" if key[1] else "")
                      + (f" · latch {latch}" if latch else "") + f" · camera {v.get('action')}: {v.get('reason', '')}"[:200])

    def observe_usb(self, old: Optional[str], new: str, st: dict):
        self.add("CONTROLLER_USB", "MAC_USB_PROBE", f"USB {old or 'unprobed'} -> {new}: {st.get('usb_text')}")

    def view(self, limit: int = 100) -> dict:
        with self.lock:
            evs = list(self.events)[-limit:]
        return {"schema": SCHEMA, "t": round(self.clock(), 3), "events": evs[::-1],
                "note": "observed events only; source = LIVE-HW / RECORDED / SYNTHETIC / MAC_USB_PROBE"}

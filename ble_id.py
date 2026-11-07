"""BLE-ID adapter: validated serial rows -> C2 verifier -> durable state -> sightings.

One serial reader (discovery.server.serial_worker) hands every line here. Only a
verified decision whose new replay state was persisted first becomes a sighting;
replay/forged/unknown/drop stay in diagnostics. Sightings are keyed by the
authenticated alias, never by MAC address. Verifier, clock, or persistence
errors halt verification visibly (fail closed) until restart. First use:
    python3 -m ble_id init-state --state PATH --scope SCOPE   # explicit first init
"""
from __future__ import annotations

import argparse
import fcntl
import math
import os
import re
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone

from ble_keys import MODE_LABEL, check_scope
from ble_state import StateError, init_state, load_state, save_state
from ble_verify import verify

ROW = re.compile(r"(-?\d{1,4}),([^,]{0,80}),([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
MAX_LINE = 200
MIN_WALL = 1_700_000_000        # host clock must be set (2023-11-14 or later) before going offline
STALE_S = 70                    # > two 30 s windows without a new authenticated token


class OwnerError(Exception):
    """Another process already owns this replay-state file."""


def acquire_owner(state_path):
    """Exclusive, non-blocking lock held for the process lifetime: one owner per state file."""
    fd = os.open(f"{state_path}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise OwnerError(f"replay state {state_path} is owned by another verifier process") from None
    return fd


class BeaconMonitor:
    def __init__(self, keys, state_path, *, scope, mode, source, receiver_ready,
                 wall=time.time, mono=time.monotonic):
        check_scope(mode, scope)
        self.keys, self.path, self.scope, self.mode, self.source = keys, state_path, scope, mode, source
        self.mode_label = MODE_LABEL[mode]
        self.ready, self.wall, self.mono = receiver_ready, wall, mono
        self.owner = acquire_owner(state_path)
        try:
            self.seen = load_state(state_path, scope=scope)  # missing/corrupt -> StateError
        except BaseException:
            os.close(self.owner)
            raise
        self.lock = threading.Lock()
        self.sightings, self.counts, self.events = {}, Counter(), deque(maxlen=40)
        self.halted = None

    def _note(self, kind, reason, now, alias=None, rssi=None):
        self.counts[f"{kind}:{reason}"] += 1
        if not (kind == "drop" and reason == "unsupported_version"):   # unrelated BLE UUIDs: count only
            self.events.append(dict(kind=kind, reason=reason, alias=alias, rssi=rssi, mono=now))

    def _halt(self, why, now):
        self.halted = why
        self._note("error", "halted", now)

    def ingest(self, line):
        if not line or line.startswith("#"):
            return                                          # discovery/diagnostic channels
        with self.lock:
            now = self.mono()
            if self.halted:
                self.counts["not_processed:halted"] += 1
                return
            if not self.ready():
                self.counts["ignored:receiver_not_ready"] += 1
                return
            m = ROW.fullmatch(line) if len(line) <= MAX_LINE else None
            if not m:
                return self._note("drop", "framing", now)
            rssi, name, payload = int(m[1]), m[2], bytes.fromhex(m[3].replace("-", ""))
            if not -127 <= rssi <= 20:
                return self._note("drop", "rssi_out_of_range", now)
            if payload[0] == 1 and name:
                return self._note("drop", "name_present", now)
            wall = self.wall()
            if not (isinstance(wall, float) and math.isfinite(wall) and wall >= MIN_WALL):
                return self._halt("Host clock is invalid or unset; verification stopped.", now)
            try:
                d, nxt = verify(payload, self.keys, self.seen, now=wall)
            except (ValueError, OverflowError) as exc:
                return self._halt(f"Verifier configuration error ({exc.__class__.__name__}).", now)
            if d.kind == "verified":
                try:
                    save_state(self.path, nxt, scope=self.scope)   # persist BEFORE publishing
                except (OSError, StateError):
                    return self._halt("Could not save replay state; verified result withheld.", now)
                self.seen = nxt
                s = self.sightings.setdefault(d.alias, dict(alias=d.alias, first_mono=now, first_wall=wall, count=0))
                s.update(last_mono=now, last_wall=wall, counter=d.counter, rssi=rssi)
                s["count"] += 1
            authenticated = d.kind in ("verified", "replay")
            self._note(d.kind, d.reason, now, d.alias if authenticated else None, rssi)

    def snapshot(self):
        with self.lock:
            now = self.mono()
            ready = self.ready()
            status = "halted" if self.halted else "verifying" if ready else "receiver_unavailable"
            detail = self.halted or ("Verifying authenticated beacon tokens." if ready else
                                     "Receiver unavailable; previous verified sightings are kept.")
            iso = lambda w: datetime.fromtimestamp(w, timezone.utc).isoformat(timespec="seconds")
            sightings = [dict(alias=s["alias"], label=f"Enrolled beacon {s['alias']:03d}",
                              last_verified_age_s=round(now - s["last_mono"], 1),
                              first_verified_age_s=round(now - s["first_mono"], 1),
                              last_verified_utc=iso(s["last_wall"]), counter=s["counter"],
                              rssi=s["rssi"], verified_tokens=s["count"],
                              stale=now - s["last_mono"] > STALE_S)
                         for s in sorted(self.sightings.values(), key=lambda s: s["alias"])]
            events = [dict(e, age_s=round(now - e.pop("mono"), 1)) for e in map(dict, reversed(self.events))]
            return dict(source=self.source, mode=self.mode, mode_label=MODE_LABEL[self.mode],
                        scope=self.scope, status=status, detail=detail, stale_after_s=STALE_S,
                        sightings=sightings, counts=dict(sorted(self.counts.items())), events=events)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m ble_id", description="BLE-ID replay state tools")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init-state", help="explicit first initialization of mission replay state")
    i.add_argument("--state", required=True)
    i.add_argument("--scope", required=True)
    a = p.parse_args(argv)
    try:
        init_state(a.state, scope=a.scope)
    except StateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Initialized empty replay state for scope {a.scope!r} at {a.state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

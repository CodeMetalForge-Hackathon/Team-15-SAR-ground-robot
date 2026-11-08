"""Persist-before-publish signed SOS status; duplicate RF never changes status."""
from collections import Counter, deque
import math
import os
import threading
import time

from ble_id import ROW, MAX_LINE, MIN_WALL
from ble_owner import acquire_owner, canonical_state_path
from ble_state import load_state, save_state, StateError
from sos_verify import verify_status


class SOSMonitor:
    def __init__(self, beacon_monitor, path, *, wall=time.time, mono=time.monotonic):
        self.keys, self.scope = beacon_monitor.keys, beacon_monitor.scope+':SOSv2'
        self.mode, self.mode_label, self.source = beacon_monitor.mode, beacon_monitor.mode_label, beacon_monitor.source
        self.ready, self.wall, self.mono = beacon_monitor.ready, wall, mono
        self.path = canonical_state_path(path)
        self.owner = acquire_owner(self.path)
        try:
            self.seen = load_state(self.path, scope=self.scope)
            if any(order > (1 << 31)-1 for order in self.seen.values()):
                raise StateError('Invalid v2 replay order')
        except BaseException:
            os.close(self.owner)
            raise
        self.lock, self.sightings, self.counts = threading.Lock(), {}, Counter()
        self.halted = None

    def ingest(self, line):
        if not line or line.startswith('#') or len(line) > MAX_LINE:
            return
        row = ROW.fullmatch(line)
        if not row:
            return
        rssi, name, payload = int(row[1]), row[2], bytes.fromhex(row[3].replace('-', ''))
        if payload[0] != 2:
            return
        with self.lock:
            if self.halted or not self.ready():
                return
            if name or not -127 <= rssi <= 20:
                self.counts['drop:framing'] += 1
                return
            now, wall = self.mono(), self.wall()
            if type(wall) not in (float, int) or not math.isfinite(wall) or wall < MIN_WALL:
                self.halted = 'Host clock invalid; SOS verification stopped'
                return
            try:
                decision, next_seen = verify_status(payload, self.keys, self.seen, now=wall)
            except (ValueError, OverflowError):
                self.halted = 'SOS verifier configuration or clock invalid'
                return
            self.counts[decision.kind+':'+decision.reason] += 1
            if decision.kind == 'verified':
                try:
                    save_state(self.path, next_seen, scope=self.scope)
                except (OSError, StateError):
                    self.halted = 'Replay state save failed; SOS update withheld'
                    return
                self.seen = next_seen
                signal = self.sightings.setdefault(decision.alias, dict(alias=decision.alias,
                    count=0, verified_tokens=0, history=deque(maxlen=61)))
                signal.update(sos=decision.sos, counter=decision.counter, revision=decision.revision,
                              order=decision.order, verified=now)
                signal['verified_tokens'] += 1
            elif decision.kind == 'replay' and decision.reason == 'duplicate':
                signal = self.sightings.get(decision.alias)
                if not signal or signal['order'] != decision.order or signal['sos'] != decision.sos:
                    return
            else:
                return
            signal.update(last=now, rssi=rssi)
            signal['count'] += 1
            bucket = int(now*2)/2
            if signal['history'] and signal['history'][-1][0] == bucket:
                signal['history'][-1] = (bucket, rssi)
            else:
                signal['history'].append((bucket, rssi))

    def snapshot(self):
        with self.lock:
            now, ready = self.mono(), self.ready()
            status = 'halted' if self.halted else 'verifying' if ready else 'receiver_unavailable'
            sightings, activity = [], []
            for alias, s in sorted(self.sightings.items()):
                age, rf_age = now-s['verified'], now-s['last']
                fresh = status == 'verifying' and age <= 70
                fields = dict(alias=alias, sos=s['sos'], status_fresh=fresh,
                    counter=s['counter'], revision=s['revision'], verified_tokens=s['verified_tokens'],
                    last_verified_age_s=round(age, 2), rssi=s['rssi'], stale=not fresh)
                sightings.append(dict(fields, label=f'Phone beacon {alias:03d}'))
                activity.append(dict(fields, id=f'enrolled-{alias}', protocol_version=2,
                    label=f'Phone beacon {alias:03d}', name='', count=s['count'],
                    age_s=round(rf_age, 2), stale=rf_age>5 or not fresh, mode=self.mode,
                    mode_label=self.mode_label, source=self.source,
                    history=[[round(now-t, 2),r] for t,r in s['history'] if now-t<=30]))
            return dict(status=status, detail=self.halted, mode=self.mode, mode_label=self.mode_label,
                        source=self.source, sightings=sightings, trace_signals=activity, counts=dict(self.counts))

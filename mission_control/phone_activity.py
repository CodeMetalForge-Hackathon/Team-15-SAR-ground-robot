"""RF activity of already-verified BLE-ID tokens, separate from authentication age.

Only the normal persist-before-publish monitor admits a token. Repeated reports
may update this RSSI channel; they never refresh a verified sighting or replay state.
"""
from collections import deque
import threading
import time

from ble_id import ROW, MAX_LINE
from ble_verify import verify


class PhoneActivity:
    def __init__(self, monitor, clock=time.monotonic):
        self.monitor, self.clock, self.lock = monitor, clock, threading.Lock()
        self.signals = {}

    def ingest(self, line):
        if not self.monitor or line.startswith('#') or len(line) > MAX_LINE:
            return
        row = ROW.fullmatch(line)
        if not row or row[2]:
            return
        rssi = int(row[1])
        if not -127 <= rssi <= 20:
            return
        payload = bytes.fromhex(row[3].replace('-', ''))
        monitor = self.monitor
        with monitor.lock:
            if monitor.halted or not monitor.ready():
                return
            try:
                decision, _ = verify(payload, monitor.keys, monitor.seen, now=monitor.wall())
            except (ValueError, OverflowError):
                return
            published = monitor.sightings.get(decision.alias)
            if decision.kind != 'replay' or decision.reason != 'duplicate' or not published or published['counter'] != decision.counter:
                return
            mode, label, source = monitor.mode, monitor.mode_label, monitor.source
        now = self.clock()
        with self.lock:
            alias = decision.alias
            signal = self.signals.setdefault(alias, dict(id=f'enrolled-{alias}', protocol_version=1,
                alias=alias, label=f'Phone beacon {alias:03d}', name='', count=0,
                history=deque(maxlen=61)))
            signal.update(last=now, rssi=rssi, mode=mode, mode_label=label, source=source)
            signal['count'] += 1
            bucket = int(now*2)/2
            if signal['history'] and signal['history'][-1][0] == bucket:
                signal['history'][-1] = (bucket, rssi)
            else:
                signal['history'].append((bucket, rssi))

    def snapshot(self):
        now = self.clock()
        with self.lock:
            self.signals = {alias:s for alias,s in self.signals.items() if now-s['last'] <= 60}
            return [dict(id=s['id'], protocol_version=1, alias=s['alias'], label=s['label'], name='',
                count=s['count'], rssi=s['rssi'], age_s=round(now-s['last'], 2),
                stale=now-s['last'] > 5, mode=s['mode'], mode_label=s['mode_label'],
                source=s['source'], history=[[round(now-t, 2),r] for t,r in s['history'] if now-t<=30])
                for s in self.signals.values()]

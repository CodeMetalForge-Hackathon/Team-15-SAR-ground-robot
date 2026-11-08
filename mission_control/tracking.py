"""Bounded position history in a fixed Jetson mission frame; never command-derived."""
from collections import deque
import copy
import json
import math
from pathlib import Path
import time

VEHICLES = ('rover', 'crazyflie')


def finite_vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        type(v) in (int, float) and math.isfinite(v) and abs(v) <= 10000 for v in value)


class PoseFile:
    """Optional localization publisher, independent of the motor-control protocol."""
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path).expanduser(), clock

    def read(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError('Pose file exceeds 4096 bytes')
            data = json.loads(raw)
            if not isinstance(data, dict) or not finite_vector(data.get('position_m')):
                raise ValueError('Invalid position')
            stamp = data.get('sampled_at')
            if type(stamp) not in (int, float) or not math.isfinite(stamp):
                raise ValueError('Pose needs sampled_at Unix seconds')
            age = self.clock() - stamp
            if not 0 <= age <= 2 or data.get('frame') not in ('jetson', 'boot'):
                raise ValueError('Pose is stale, future-dated or has an unknown frame')
            return dict(position_m=data['position_m'], position_frame=data['frame'],
                        position_age_s=age, position_source='localization', position_sample_id=stamp)
        except (OSError, ValueError, TypeError) as exc:
            return dict(position_m=None, position_source='localization', position_error=str(exc)[:150])


class Tracks:
    def __init__(self, clock=time.monotonic):
        self.clock, self.started = clock, clock()
        self.frames = {name: None for name in VEHICLES}
        self.records = {name: deque(maxlen=600) for name in VEHICLES}
        self.info = {name: dict(boot=None, mode=None, source=None, status='no_position',
                               last=None, sample=None, segment=0) for name in VEHICLES}

    def align(self, name, translation, yaw):
        if name not in VEHICLES or not finite_vector(translation) or type(yaw) not in (int, float) or not math.isfinite(yaw) or abs(yaw) > 360:
            raise ValueError('Frame needs a vehicle, finite XYZ offset and yaw between -360 and 360 degrees')
        self.frames[name] = dict(translation_m=list(translation), yaw_deg=yaw)
        self.records[name].clear()
        self.info[name].update(last=None, sample=None, status='awaiting_position')
        self.info[name]['segment'] += 1

    def observe(self, name, node):
        if name not in VEHICLES:
            return
        now, t, info = self.clock(), node['telemetry'], self.info[name]
        if info['boot'] != node['boot']:
            if info['boot'] is not None:
                self.frames[name] = None  # A restarted estimator has a new boot frame.
                self.records[name].clear()
            info.update(boot=node['boot'], sample=None, last=None)
            info['segment'] += 1
        info.update(mode=node['mode'], source='SIMULATED' if node['mode'] == 'SIMULATED' else str(t.get('position_source', 'telemetry'))[:40])
        position, frame, age = t.get('position_m'), t.get('position_frame'), t.get('position_age_s', 0)
        if position is None:
            info['status'] = 'no_position'
            return
        if not finite_vector(position) or type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age <= 2:
            info['status'] = 'invalid'
            return
        if frame == 'jetson':
            xyz = list(position)
        elif frame == 'boot' and self.frames[name] is not None:
            calibration = self.frames[name]
            angle, (dx, dy, dz) = math.radians(calibration['yaw_deg']), calibration['translation_m']
            x, y, z = position
            xyz = [dx + math.cos(angle)*x - math.sin(angle)*y,
                   dy + math.sin(angle)*x + math.cos(angle)*y, dz + z]
        else:
            info['status'] = 'unaligned'
            return
        sample = t.get('position_sample_id')
        if sample is not None and sample == info['sample']:
            return  # Re-reading a pose file cannot refresh a measurement's age.
        measured = now - age
        if info['last'] is not None and measured < info['last']:
            return
        info.update(last=measured, sample=sample, status='tracking')
        records = self.records[name]
        if records and measured - self.started - records[-1]['t'] < 0.2:
            return
        if records and measured - self.started - records[-1]['t'] > 2:
            info['segment'] += 1
        records.append(dict(t=round(measured-self.started, 3), x=xyz[0], y=xyz[1], z=xyz[2], segment=info['segment']))

    def snapshot(self):
        now, tracks = self.clock(), {}
        for name in VEHICLES:
            info, records = self.info[name], self.records[name]
            status = info['status']
            age = None if info['last'] is None else max(0, now-info['last'])
            if status == 'tracking' and (age is None or age > 2):
                status = 'stale'
            tracks[name] = dict(status=status, mode=info['mode'], source=info['source'],
                age_s=None if age is None else round(age, 2), calibration=copy.deepcopy(self.frames[name]),
                points=list(records), latest=copy.deepcopy(records[-1]) if records else None)
        return dict(frame='jetson', units='meters', axes='X forward, Y left, Z up',
                    origin=[0, 0, 0], tracks=tracks)

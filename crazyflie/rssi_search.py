"""Bounded RSSI search; discovery readings are unverified proximity hints."""
import json
import math
from statistics import median
from urllib.error import URLError
from urllib.request import urlopen


class SearchUnavailable(Exception):
    pass


class DiscoveryRSSI:
    """Read fresh snapshots without counting the same received packet twice.

    Polling samples latest RSSI; it does NOT expose every received advertisement.
    A stable session ID is required, rather than selecting the strongest device.
    """
    def __init__(self, url, signal_id):
        self.url, self.signal_id = url.rstrip('/') + '/api/discovery', signal_id
        self.last_count = None

    def read(self, pose, now):
        try:
            with urlopen(self.url, timeout=0.3) as response:
                data = json.loads(response.read(2_000_000))
            if data['source'] != 'LIVE-HW' or data['status'] != 'scanning':
                raise SearchUnavailable('Live scanner unavailable')
            signal = next((s for s in data['signals'] if s['id'] == self.signal_id), None)
            if signal is None:
                return None
            count, age, rssi = signal['count'], signal['age_s'], signal['rssi']
            if (type(count) is not int or count < 1 or not math.isfinite(age)
                    or age < 0 or not math.isfinite(rssi) or not -127 <= rssi <= 20):
                raise SearchUnavailable('Invalid scanner sample')
            if self.last_count is not None and count < self.last_count:
                raise SearchUnavailable('Scanner session changed')
            fresh = self.last_count is None or count > self.last_count
            self.last_count = count
            return float(rssi) if fresh and age <= 0.5 else None
        except (OSError, URLError, ValueError, KeyError, TypeError) as exc:
            raise SearchUnavailable(f'RSSI feed failed: {exc}') from exc

    def discard(self, pose, now):
        self.read(pose, now)  # exclude a latest-value snapshot from before the window


class SimulatedRSSI:
    def __init__(self, hidden_target):
        self.target = hidden_target

    def read(self, pose, now):
        distance = max(0.12, math.dist(pose[:3], (self.target[0], self.target[1], 0.0)))
        return -45 - 20 * math.log10(distance) + 1.5 * math.sin(now * 2.7)

    def discard(self, pose, now):
        pass


def sample(flight, source, point, seconds, min_samples, emit):
    source.discard(flight.link.pose(), flight.clock())
    values = []
    end = flight.clock() + seconds
    while flight.clock() < end:
        flight.wait(min(0.25, end - flight.clock()))
        pose = flight.link.pose()
        if (len(pose) < 3 or any(not math.isfinite(v) for v in pose[:3])
                or math.dist(pose[:3], point) > 0.20):
            raise SearchUnavailable('Drone is not holding the sample waypoint within 0.20 m')
        value = source.read(pose, flight.clock())
        flight.check()
        if value is not None:
            values.append(value)
    if len(values) < min_samples:
        raise SearchUnavailable(f'Only {len(values)} fresh readings; need {min_samples}')
    result = dict(point=point, median_dbm=median(values), samples=len(values),
                  spread_db=max(values) - min(values))
    emit('rssi_sample', **result)
    return result


def search(flight, source, height, emit, seconds=5.0, min_samples=8,
           step=0.6, rounds=2, improvement_db=3.0):
    """Compare cardinal neighbors, then shrink the step; no range conversion."""
    center = (0.0, 0.0, height)
    candidate = None
    for iteration in range(rounds):
        points = [center] + [(center[0] + dx, center[1] + dy, height)
                             for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step))
                             if abs(center[0] + dx) <= 1.2 and abs(center[1] + dy) <= 1.2]
        results = []
        for point in points:
            flight.move(point)
            results.append(sample(flight, source, point, seconds, min_samples, emit))
        baseline = results[0]
        winner = max(results, key=lambda r: r['median_dbm'])
        # Revisit both points: a one-off signal peak is insufficient to choose a move.
        if winner['point'] != center:
            confirmations = []
            for point in (center, winner['point']):
                flight.move(point)
                confirmations.append(sample(flight, source, point, seconds, min_samples, emit))
            gain = winner['median_dbm'] - baseline['median_dbm']
            repeated_gain = confirmations[1]['median_dbm'] - confirmations[0]['median_dbm']
            if min(gain, repeated_gain) >= improvement_db:
                center = winner['point']
                candidate = center
                emit('hotter', candidate_xyz_m=list(center), gain_db=round(repeated_gain, 2),
                     message='Repeatable stronger signal; candidate area, not a measured location')
            else:
                emit('rssi_uncertain', round=iteration + 1, gain_db=gain, repeated_gain_db=repeated_gain)
        else:
            emit('rssi_uncertain', round=iteration + 1, message='No sampled neighbor stronger than center')
        step /= 2
    return candidate

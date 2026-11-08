"""Hardware adapters. Network delivery/acknowledgement never proves physical motion."""
import importlib
import json
import math
from pathlib import Path
import time

from .protocol import validate_action


class Simulator:
    def __init__(self, node):
        self.node, self.airborne = node, False
        self.position, self.last = [0, 0, 0], 'idle'
        self.heading = 0.0

    def execute(self, action, params):
        if action not in ('stop', 'land'):
            validate_action(self.node, action, params)
        if action == 'takeoff':
            if self.airborne:
                raise ValueError('Already airborne')
            self.airborne, self.position[2] = True, params['height']
        elif action == 'move':
            if not self.airborne:
                raise ValueError('Take off before moving')
            self.position = [params[k] for k in ('x', 'y', 'z')]
        elif action == 'land':
            self.airborne, self.position[2] = False, 0
        elif action == 'pulse':
            direction, step = params['direction'], 0.05 * params['power'] / 20
            if direction in ('z', 'c'):
                self.heading += math.radians(15 if direction == 'z' else -15)
            else:
                dx, dy = {'w':(step, 0), 's':(-step, 0), 'a':(0, step), 'd':(0, -step)}[direction]
                self.position[0] += math.cos(self.heading)*dx - math.sin(self.heading)*dy
                self.position[1] += math.sin(self.heading)*dx + math.cos(self.heading)*dy
        self.last = action
        return 'SIMULATED action only; no hardware connected'

    def safe(self):
        self.execute('land' if self.node == 'crazyflie' else 'stop', {})

    def tick(self):
        pass

    def telemetry(self):
        return dict(ready=True, last_action=self.last, airborne=self.airborne,
                    position_m=list(self.position), position_frame='jetson', position_source='SIMULATED',
                    source='SIMULATED', detections=[])

    def close(self):
        self.safe()


class Rover:
    def __init__(self, host, port, profile):
        from rover.keyboard_control import WiFiLink

        class AcknowledgedLink(WiFiLink):
            stop_ack = False

            def send(self, text):
                if text == 'STOP':
                    self.stop_ack = False
                super().send(text)

            def parse_replies(self):
                if b'OK STOP' in self.buffer.split(b'\n')[:-1]:
                    self.stop_ack = True
                super().parse_replies()

        profile = Path(profile).expanduser()
        if profile.stat().st_mode & 0o077:
            raise ValueError('Rover pairing profile must have mode 600')
        self.link = AcknowledgedLink(host, port, json.loads(profile.read_text())['ap_password'])
        self.link.__enter__()
        self.last = 'connected; stopped'
        self.failed = False

    def execute(self, action, params):
        if action == 'stop':
            self.safe()
            return 'STOP sent; physical stop unconfirmed'
        validate_action('rover', action, params)
        self.link.send(f'MOVE {params["direction"]} {params["power"]}')
        end = time.monotonic() + 0.8
        while self.link.pending_moves:
            self.link.poll()
            if time.monotonic() > end:
                raise RuntimeError('Rover MOVE acknowledgement timeout')
            time.sleep(0.01)
        self.last = '250 ms pulse acknowledged by receiver'
        return self.last + '; wheel motion unconfirmed'

    def tick(self):
        self.link.poll()

    def safe(self):
        self.link.send('STOP')
        end = time.monotonic() + 0.5
        while not self.link.stop_ack:
            self.link.poll()
            if time.monotonic() > end:
                self.failed = True
                raise RuntimeError('STOP acknowledgement missing; physical stop unconfirmed')
            time.sleep(0.01)
        self.last = 'STOP acknowledged by receiver; physical outcome unconfirmed'

    def telemetry(self):
        return dict(ready=not self.failed, last_action=self.last, source='LIVE', battery_v=None)

    def close(self):
        try:
            self.safe()
        finally:
            # safe() already sent STOP and drained its reply. Close without
            # another unacknowledged write during teardown.
            self.link.sock.close()
            self.link.sock = None


class Crazyflie:
    """Existing guide backend; each landing closes the flight session.

    A fresh agent/preflight is required for the next flight. Backend commands
    must return promptly; wait() must service telemetry at the requested period.
    """
    def __init__(self, module, uri):
        backend = importlib.import_module(module)
        self.link = backend.CrazyflieLink(uri)
        for method in ('__enter__', '__exit__', 'pose', 'takeoff', 'go_to', 'wait'):
            if not callable(getattr(self.link, method, None)):
                raise ValueError('Crazyflie backend missing ' + method)
        self.link.__enter__()
        self.airborne, self.closed, self.started, self.busy = False, False, None, 0
        self.last = 'preflight confirmed; grounded'

    def tick(self):
        if self.closed:
            return
        self.link.wait(0.01)
        if self.airborne:
            voltage = self.link.vbat
            if type(voltage) not in (int, float) or not math.isfinite(voltage) or voltage < 3.3:
                raise RuntimeError('Battery low or unavailable')
            if time.monotonic() - self.started > 120:
                raise RuntimeError('120 second flight budget reached')
            pose = self.link.pose()
            if len(pose) < 3 or any(not math.isfinite(v) for v in pose[:3]) or abs(pose[0]) > 1.5 or abs(pose[1]) > 1.5 or not 0 <= pose[2] <= 1.3:
                raise RuntimeError('Position telemetry invalid/outside flight envelope')

    def execute(self, action, params):
        if action == 'land':
            self.safe()
            return self.last
        validate_action('crazyflie', action, params)
        if self.closed:
            raise RuntimeError('Restart agent and repeat preflight before another flight')
        self.tick()
        if time.monotonic() < self.busy:
            raise RuntimeError('Previous flight maneuver is still in progress')
        if action == 'takeoff':
            if self.airborne:
                raise ValueError('Already airborne')
            voltage = self.link.vbat
            if type(voltage) not in (int, float) or not math.isfinite(voltage) or voltage < 3.3:
                raise RuntimeError('Battery low or unavailable; takeoff refused')
            self.started, self.airborne = time.monotonic(), True
            self.link.takeoff(params['height'], 2.0)
            duration = 2.5
        else:
            if not self.airborne:
                raise ValueError('Take off before moving')
            pose = self.link.pose()
            if len(pose) < 3 or any(not math.isfinite(v) for v in pose[:3]) or abs(pose[0]) > 1.5 or abs(pose[1]) > 1.5 or not 0.2 <= pose[2] <= 1.2:
                raise RuntimeError('Position telemetry invalid/outside envelope')
            duration = max(0.5, math.dist(pose[:3], [params[k] for k in ('x', 'y', 'z')]) / 0.2)
            self.link.go_to(params['x'], params['y'], params['z'], 0.0, duration)
            duration += 0.25
        self.busy = time.monotonic() + duration
        self.last = action + ' submitted to backend; physical outcome unconfirmed'
        return self.last

    def safe(self):
        # On a grounded initial connection a stop must not consume the preflight.
        if not self.closed and self.airborne:
            self.closed = True
            self.link.__exit__(None, None, None)
            self.airborne = None  # A landing request is not physical landing confirmation.
            self.last = 'Backend context exited: landing requested; physical outcome unconfirmed'

    def telemetry(self):
        if self.closed:
            return dict(ready=False, airborne=False, last_action=self.last, source='LIVE')
        pose, voltage = self.link.pose(), self.link.vbat
        return dict(ready=True, airborne=self.airborne, position_m=list(pose[:3]),
                    position_frame='boot', position_source='onboard estimator',
                    battery_v=voltage, last_action=self.last, source='LIVE', busy=time.monotonic() < self.busy)

    def close(self):
        if not self.closed:
            self.closed = True
            self.link.__exit__(None, None, None)


class Jetson:
    """Publish a bounded JSON snapshot written atomically by the vision process."""
    def __init__(self, file=None):
        self.file = Path(file).expanduser() if file else None

    def telemetry(self):
        if not self.file:
            return dict(ready=True, source='LIVE', vision_status='No vision publisher configured', detections=[])
        if time.time() - self.file.stat().st_mtime > 2:
            return dict(ready=False, source='LIVE', vision_status='Vision data stale', detections=[])
        with self.file.open('rb') as stream:
            data = stream.read(8193)
        if len(data) > 8192:
            raise ValueError('Vision telemetry exceeds 8192 bytes')
        data = json.loads(data)
        if not isinstance(data, dict):
            raise ValueError('Vision snapshot must be a JSON object')
        return dict(ready=True, source='LIVE', vision_status='Publisher connected', observation=data)

    def execute(self, *_):
        raise ValueError('Jetson agent only publishes telemetry')

    def safe(self):
        pass

    def tick(self):
        pass

    def close(self):
        pass

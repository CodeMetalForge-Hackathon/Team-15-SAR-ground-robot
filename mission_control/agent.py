"""Device agent; simulation by default, outbound HTTP only, no inbound ports."""
import argparse
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from .adapters import Simulator, Rover, Crazyflie, Jetson
from .protocol import DEFAULT_CREDENTIALS, NODES
from .tracking import PoseFile


def load_token(file, role):
    file = Path(file).expanduser()
    if file.stat().st_mode & 0o077:
        raise ValueError('Role credential file must have mode 600')
    token = json.loads(file.read_text())[role]
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError('Invalid role token')
    return token


class Agent:
    def __init__(self, node, token, url, adapter, mode='SIMULATED', pose_file=None):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('Coordinator URL must be http(s)://HOST:PORT')
        self.node, self.token = node, token
        self.url = url.rstrip('/') + f'/api/nodes/{node}/sync'
        self.adapter, self.mode, self.boot = adapter, mode, secrets.token_hex(16)
        self.instance, self.revision, self.deadline = None, None, 0
        self.result, self.error, self.was_active = None, '', False
        self.seen = set()
        self.pose_file = PoseFile(pose_file) if pose_file else None

    def safe(self):
        self.deadline, self.was_active = 0, False
        self.adapter.safe()

    def step(self):
        started = time.monotonic()
        try:
            self.adapter.tick()
            if self.was_active and started >= self.deadline:
                self.safe()
            telemetry = self.adapter.telemetry()
            if self.pose_file:
                telemetry.update(self.pose_file.read())
            telemetry['agent_error'] = self.error
            if self.error:
                telemetry['ready'] = False
            body = json.dumps(dict(boot=self.boot, mode=self.mode, telemetry=telemetry,
                                   result=self.result), allow_nan=False).encode()
            request = Request(self.url, body, {'Authorization': 'Bearer ' + self.token,
                                             'Content-Type': 'application/json'})
            with urlopen(request, timeout=0.8) as response:
                reply = json.load(response)
            self.result, self.error = None, ''
            # Account conservatively for the entire HTTP round trip.
            elapsed = time.monotonic() - started
            remaining = reply['lease_s'] - elapsed
            changed = self.instance != reply['instance'] or self.revision != reply['revision']
            self.instance, self.revision = reply['instance'], reply['revision']
            active = not reply['paused'] and remaining > 0
            if changed or (self.was_active and not active):
                self.safe()
            self.deadline, self.was_active = time.monotonic() + max(0, remaining), active
            command = reply['command']
            if not command or command['id'] in self.seen:
                return
            self.seen.add(command['id'])
            if len(self.seen) > 500:
                # Server never redelivers motion. Retain only the current ID.
                self.seen = {command['id']}
            try:
                if command['safety']:
                    self.safe()
                    detail = 'Agent requested local stop/landing; physical outcome unconfirmed'
                else:
                    if changed or not active or elapsed >= command['ttl_s']:
                        raise ValueError('Command expired or control session changed')
                    detail = self.adapter.execute(command['action'], command['params'])
                self.result = dict(id=command['id'], ok=True, detail=detail)
            except Exception as exc:
                self.result = dict(id=command['id'], ok=False, detail=str(exc)[:300])
                self.safe()
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)[:200]
            self.safe()

    def run(self, stop):
        try:
            while not stop.is_set():
                self.step()
                stop.wait(0.15)
        finally:
            try:
                self.safe()
            finally:
                self.adapter.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', choices=NODES, required=True)
    parser.add_argument('--coordinator', default='http://127.0.0.1:8080')
    parser.add_argument('--credentials', type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--rover-host')
    parser.add_argument('--rover-port', type=int, default=5000)
    parser.add_argument('--rover-profile', type=Path, default=Path.home() / '.codex/roverc/connection.json')
    parser.add_argument('--backend-module', default='sar_sim.backends.crazyflie_backend')
    parser.add_argument('--uri', default='radio://0/80/2M/E7E7E7E7E7')
    parser.add_argument('--preflight-confirmed', action='store_true', help='Positioning deck, origin, clear area, battery and radio verified')
    parser.add_argument('--telemetry-file', type=Path)
    parser.add_argument('--pose-file', type=Path, help='Optional timestamped localization JSON for path tracking')
    args = parser.parse_args(argv)
    try:
        token = load_token(args.credentials, args.node)
        if not args.live:
            adapter = Simulator(args.node)
        elif args.node == 'rover':
            if not args.rover_host:
                parser.error('--live --node rover requires --rover-host')
            adapter = Rover(args.rover_host, args.rover_port, args.rover_profile)
        elif args.node == 'crazyflie':
            if not args.preflight_confirmed:
                parser.error('Live flight requires --preflight-confirmed after physical preflight')
            adapter = Crazyflie(args.backend_module, args.uri)
        else:
            adapter = Jetson(args.telemetry_file)
        agent = Agent(args.node, token, args.coordinator, adapter, 'LIVE' if args.live else 'SIMULATED', args.pose_file)
    except (OSError, ValueError, KeyError, ImportError) as exc:
        parser.error(str(exc))
    print(f'{agent.mode} {args.node} agent → {args.coordinator}; no movement on connection', flush=True)
    try:
        agent.run(threading.Event())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

"""Shared, deliberately small command surface and private credential files."""
import json
import math
import os
from pathlib import Path
import secrets

NODES = ('rover', 'crazyflie', 'jetson')
LEASE_S = 3.0
STALE_S = 2.0
APPROVAL_S = 20.0
DELIVERY_S = 2.0
DEFAULT_CREDENTIALS = Path.home() / '.config/team15/network.json'


def load_credentials(path):
    path = Path(path).expanduser()
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise ValueError('Credential file must be private (chmod 600)')
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or any(not isinstance(data.get(k), str) or
            len(data[k]) < 32 for k in ('operator', *NODES)):
        raise ValueError('Invalid credential file; run python3 -m mission_control.server --init')
    if len(set(data.values())) != 4:
        raise ValueError('Use distinct credentials for each role')
    return data


def init_credentials(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {role: secrets.token_urlsafe(32) for role in ('operator', *NODES)}
    # Exclusive creation: never rotate credentials underneath a running mission.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
    return path


def validate_action(node, action, params):
    if not isinstance(params, dict):
        raise ValueError('params must be an object')
    if node == 'rover' and action == 'pulse':
        if set(params) != {'direction', 'power'} or params['direction'] not in ('w', 'a', 's', 'd', 'z', 'c'):
            raise ValueError('Choose a rover direction and power')
        power = params['power']
        if type(power) is not int or not 5 <= power <= 50:
            raise ValueError('Power must be an integer from 5 to 50')
    elif node == 'crazyflie' and action in ('takeoff', 'move'):
        fields = {'height'} if action == 'takeoff' else {'x', 'y', 'z'}
        if set(params) != fields or any(type(v) not in (float, int) or
                not math.isfinite(v) for v in params.values()):
            raise ValueError('Provide finite numeric flight coordinates')
        z = params['height'] if action == 'takeoff' else params['z']
        if not 0.2 <= z <= 1.2 or (action == 'move' and
                (abs(params['x']) > 1.5 or abs(params['y']) > 1.5)):
            raise ValueError('Flight envelope: x/y ±1.5 m, altitude 0.2–1.2 m')
    else:
        raise ValueError('Unsupported action for this node')
    return dict(params)

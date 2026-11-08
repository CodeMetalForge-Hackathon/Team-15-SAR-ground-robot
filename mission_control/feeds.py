"""Read-only bridge to the existing exclusive BLE receiver service."""
import json
from urllib.parse import urlsplit
from urllib.request import urlopen


class BluetoothFeed:
    def __init__(self, url='http://127.0.0.1:8765'):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('Discovery URL must be http(s)://HOST:PORT')
        self.url = url.rstrip('/')

    def read(self, path):
        with urlopen(self.url + path, timeout=0.4) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Bluetooth snapshot too large')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('Invalid Bluetooth snapshot')
        return data

    def snapshot(self):
        try:
            discovery = self.read('/api/discovery')
        except (OSError, ValueError):
            return dict(connected=False, discovery=None, beacons=None)
        try:
            beacons = self.read('/api/beacons')
        except (OSError, ValueError):
            beacons = None
        return dict(connected=True, discovery=discovery, beacons=beacons)

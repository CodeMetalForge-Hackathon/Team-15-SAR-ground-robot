"""Live ESP32 phone-signal viewer. No simulated advertisements or robot controls.

python3 -m mission_control.trace --serial /dev/cu.usbmodem101 --host 0.0.0.0
"""
import os
import argparse
import secrets
import threading

from discovery.server import Discovery, serial_worker
from discovery.beacons import add_arguments, monitor_from_args, snapshot as beacon_snapshot
from .camera import PiCamera
from .protocol import NODES
from .server import make_server
from .state import Coordinator
from .phone_activity import PhoneActivity
from .sos_monitor import SOSMonitor
from ble_owner import OwnerError
from ble_state import StateError


class ReceiverFeed:
    def __init__(self, discovery, beacons=None, sos=None):
        self.discovery, self.beacons, self.sos = discovery, beacons, sos
        self.activity = PhoneActivity(beacons)

    def ingest(self, line):
        if self.beacons:
            self.beacons.ingest(line)
            self.activity.ingest(line)
        if self.sos:
            self.sos.ingest(line)

    def snapshot(self):
        status = self.sos.snapshot() if self.sos else dict(status="off", sightings=[], trace_signals=[])
        signals = {s["alias"]:s for s in self.activity.snapshot()}
        signals.update({s["alias"]:s for s in status["trace_signals"]})
        return dict(connected=True, discovery=self.discovery.snapshot(),
                    beacons=beacon_snapshot(self.beacons, self.discovery),
                    sos=status, trace_signals=list(signals.values()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8082)
    parser.add_argument('--pi-camera', action='store_true')
    parser.add_argument('--runtime-python', help='Python environment for the simulator and person detector')
    parser.add_argument('--sos-state', help='Separate v2 replay state; scope is --scope plus :SOSv2')
    add_arguments(parser)
    args = parser.parse_args(argv)
    discovery, stop = Discovery(), threading.Event()
    beacons = monitor_from_args(args, discovery)
    credentials = {role:secrets.token_urlsafe(32) for role in ('operator', *NODES)}
    camera = PiCamera()
    sos = None
    if args.sos_state and not beacons:
        parser.error("--sos-state requires --keys or --test-keys, --state and --scope")
    try:
        sos = SOSMonitor(beacons, args.sos_state) if args.sos_state else None
        feed = ReceiverFeed(discovery, beacons, sos)
        server = make_server(Coordinator(), credentials, args.host, args.port,
                             camera=camera, bluetooth=feed, runtime_python=args.runtime_python)
        if args.pi_camera:
            camera.start()
    except (OSError, ValueError, StateError, OwnerError) as exc:
        parser.error(str(exc))
    consumers = (feed.ingest,) if beacons else ()
    worker = threading.Thread(target=serial_worker,
        args=(discovery, args.serial, stop, consumers), daemon=True)
    worker.start()
    print(f'LIVE RECEIVER · http://127.0.0.1:{server.server_port}/trace', flush=True)
    print(f'Viewer token: {credentials["operator"]}', flush=True)
    print(f'Listener: {args.host}:{server.server_port} · {args.serial}', flush=True)
    print('Select your controlled beacon. Dots are schematic/manual, never Bluetooth coordinates.', flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        camera.close()
        worker.join(timeout=3)
        if sos:
            os.close(sos.owner)
        if beacons:
            os.close(beacons.owner)


if __name__ == '__main__':
    main()

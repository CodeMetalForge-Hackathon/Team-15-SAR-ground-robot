"""Local coordinator: python3 -m mission_control.server --credentials PATH."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import secrets
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import urlsplit

from .protocol import DEFAULT_CREDENTIALS, NODES, init_credentials, load_credentials
from .state import Coordinator, Conflict
from .camera import PiCamera
from .feeds import BluetoothFeed
from .simulation import Simulation
from .vision import Vision
from .training import Training

STATIC = Path(__file__).parent / 'static'


def make_server(state, credentials, host='127.0.0.1', port=8080, camera=None, bluetooth=None, runtime_python=None):
    camera = camera or PiCamera()
    bluetooth = bluetooth or BluetoothFeed()
    simulation, vision = Simulation(runtime_python), Vision(camera, runtime_python)
    training = Training(runtime_python)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def respond(self, status, value, kind='application/json', headers=None, csp=None):
            body = json.dumps(value, allow_nan=False).encode() if kind == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/') or kind == 'application/json' else ''))
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            ancestors = "'self'" if self.path in ('/control', '/trace', '/vision', '/label', '/about') else "'none'"
            self.send_header('Content-Security-Policy', csp or ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; frame-src 'self'; object-src 'none'; frame-ancestors " + ancestors + "; base-uri 'none'"))
            for key, value in (headers or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, role):
            auth = self.headers.get('Authorization', '')
            return hmac.compare_digest(auth.encode(), ('Bearer ' + credentials[role]).encode())

        def do_GET(self):
            self.path = urlsplit(self.path).path
            if self.path.startswith('/simulation/'):
                return self.simulation_request()
            if self.path == '/api/training':
                if not self.authorized('operator'):
                    return self.respond(401, dict(error='Operator token required'))
                return self.respond(200, training.snapshot())
            if self.path in ('/api/vision', '/api/vision/frame'):
                if not self.authorized('operator'):
                    return self.respond(401, dict(error='Operator token required'))
                snapshot = vision.snapshot()
                frame = snapshot.pop('frame')
                if self.path.endswith('/frame'):
                    if frame is None:
                        return self.respond(503, dict(error=snapshot['detail']))
                    if self.headers.get('If-None-Match') == str(snapshot.get('sequence')):
                        return self.respond(304, b'', 'image/jpeg')
                    return self.respond(200, frame, 'image/jpeg',
                        {'X-Vision-Metadata': json.dumps(snapshot, allow_nan=False), 'ETag': snapshot.get('sequence', '')})
                return self.respond(200, snapshot)
            if self.path in ('/api/state', '/api/bluetooth', '/api/camera/frame', '/api/tracks'):
                if not self.authorized('operator'):
                    return self.respond(401, dict(error='Operator token required'))
                if self.path == '/api/state':
                    return self.respond(200, state.snapshot())
                if self.path == '/api/tracks':
                    with state.lock:
                        data = dict(instance=state.instance, **state.tracking.snapshot())
                    return self.respond(200, data)
                if self.path == '/api/bluetooth':
                    return self.respond(200, bluetooth.snapshot())
                frame = camera.snapshot()
                if frame['frame'] is None:
                    return self.respond(503, dict(error=frame['detail']))
                if self.headers.get('If-None-Match') == str(frame['sequence']):
                    return self.respond(304, b'', 'image/jpeg')
                return self.respond(200, frame['frame'], 'image/jpeg',
                    {'X-Camera-Sequence':frame['sequence'], 'X-Camera-Source':frame['source'], 'ETag':frame['sequence']})
            files = {'/favicon.png': ('favicon.png', 'image/png'),
                     '/favicon.ico': ('favicon.ico', 'image/x-icon'),
                     '/apple-touch-icon.png': ('apple-touch-icon.png', 'image/png'),
                     '/': ('workspace.html', 'text/html'), '/control': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                     '/style.css': ('style.css', 'text/css'), '/media.js':('media.js', 'text/javascript'),
                     '/fonts/RobotoSlab.ttf': ('fonts/RobotoSlab.ttf', 'font/ttf'),
                     '/paths.js': ('paths.js', 'text/javascript'),
                     '/trace': ('trace.html', 'text/html'), '/trace.js': ('trace.js', 'text/javascript'),
                     '/trace.css': ('trace.css', 'text/css'),
                     '/workspace.js': ('workspace.js', 'text/javascript'),
                     '/workspace.css': ('workspace.css', 'text/css'),
                     '/embedded.js': ('embedded.js', 'text/javascript'),
                     '/embedded.css': ('embedded.css', 'text/css'),
                     '/sim-theme.css': ('sim-theme.css', 'text/css'),
                     '/team15-theme.css': ('team15-theme.css', 'text/css'),
                     '/vision': ('vision.html', 'text/html'),
                     '/vision.css': ('vision.css', 'text/css'),
                     '/vision.js': ('vision.js', 'text/javascript')}
            files.update({'/label': ('label.html', 'text/html'), '/label.js': ('label.js', 'text/javascript'),
                          '/label.css': ('label.css', 'text/css'),
                          '/about': ('about.html', 'text/html'), '/about.js': ('about.js', 'text/javascript'),
                          '/about.css': ('about.css', 'text/css')})
            if self.path not in files:
                return self.respond(404, dict(error='Not found'))
            name, kind = files[self.path]
            self.respond(200, (STATIC / name).read_bytes(), kind)

        def do_POST(self):
            # No CORS: browser mutations must originate from this exact host.
            origin = self.headers.get('Origin')
            if origin and (urlsplit(origin).netloc != self.headers.get('Host') or
                           urlsplit(origin).scheme not in ('http', 'https')):
                return self.respond(403, dict(error='Cross-origin requests are refused'))
            if self.path == '/simulation/control':
                return self.simulation_request(post=True)
            if self.path in ('/api/training/sample', '/api/training/start'):
                if not self.authorized('operator'):
                    return self.respond(401, dict(error='Operator token required'))
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if self.headers.get('Transfer-Encoding') or not 1 <= length <= 3*1024*1024 or self.headers.get_content_type() != 'application/json':
                        raise ValueError('Expected bounded JSON')
                    data = json.loads(self.rfile.read(length))
                    if self.path.endswith('/sample'):
                        return self.respond(200, training.save(data))
                    training.start(data.get('classes'))
                    return self.respond(200, training.snapshot())
                except (OSError, ValueError, TypeError, ImportError) as exc:
                    return self.respond(400, dict(error=str(exc)[:240]))
            if self.path in ('/api/vision/start', '/api/vision/stop'):
                if not self.authorized('operator'):
                    return self.respond(401, dict(error='Operator token required'))
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    return self.respond(400, dict(error='Invalid request length'))
                if self.headers.get('Transfer-Encoding') or not 0 <= length <= 1024:
                    return self.respond(400, dict(error='Invalid request body'))
                try:
                    data = json.loads(self.rfile.read(length) or b'{}')
                    if not isinstance(data, dict):
                        raise ValueError('Expected a JSON object')
                    if self.path.endswith('/start'):
                        if data.get('host_camera') is True:
                            camera.start_local(vision.python)
                        vision.start(data.get('profile'))
                    else:
                        vision.close()
                        camera.stop_local()
                except (ValueError, OSError) as exc:
                    return self.respond(400, dict(error=str(exc)[:200]))
                return self.respond(200, dict(ok=True))
            if self.path == '/api/camera/publish':
                if not self.authorized('operator'):
                    return self.respond(401, dict(error='Operator token required'))
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if self.headers.get('Transfer-Encoding') or not 4 <= length <= 2*1024*1024 or self.headers.get_content_type() != 'image/jpeg':
                        raise ValueError('Expected bounded image/jpeg body')
                    camera.publish(self.rfile.read(length), self.headers.get('X-Camera-Publisher'))
                    return self.respond(200, dict(ok=True))
                except ValueError as exc:
                    return self.respond(400, dict(error=str(exc)))
            parts = self.path.strip('/').split('/')
            operator = len(parts) == 2 and parts[0] == 'api'
            agent = len(parts) == 4 and parts[:2] == ['api', 'nodes'] and parts[2] in NODES and parts[3] == 'sync'
            if not operator and not agent:
                return self.respond(404, dict(error='Not found'))
            if not self.authorized('operator' if operator else parts[2]):
                return self.respond(401, dict(error='Invalid role token'))
            try:
                if self.headers.get('Transfer-Encoding'):
                    raise ValueError('Chunked request bodies are not supported')
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 16384:
                    raise ValueError('JSON body must be 1–16384 bytes')
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Content-Type must be application/json')
                data = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
                if not isinstance(data, dict):
                    raise ValueError('JSON body must be an object')
                result = state.operator(parts[1], data) if operator else state.sync(parts[2], data)
                self.respond(200, result)
            except Conflict as exc:
                self.respond(409, dict(error=str(exc)))
            except (ValueError, TypeError, KeyError, RecursionError) as exc:
                self.respond(400, dict(error=str(exc)[:200]))

        def simulation_request(self, post=False):
            """Proxy only the software simulator; no hardware transport is reachable."""
            path = self.path.removeprefix('/simulation')
            if path not in ('/', '/stream', '/control') and not path.startswith('/leaflet/'):
                return self.respond(404, dict(error='Not found'))
            try:
                port = simulation.start()
                body = None
                if post:
                    length = int(self.headers.get('Content-Length', '0'))
                    if self.headers.get('Transfer-Encoding') or not 1 <= length <= 262144:
                        raise ValueError('Simulator command too large')
                    body = self.rfile.read(length)
                    command = json.loads(body)
                    if not isinstance(command, dict) or command.get('cmd') not in ('pause', 'play', 'speed', 'jam', 'recall', 'setup', 'restart'):
                        raise ValueError('Invalid simulator command')
                upstream = Request(f'http://127.0.0.1:{port}{path}', data=body,
                                   headers={'Content-Type': 'application/json'})
                with urlopen(upstream, timeout=10) as response:
                    kind = response.headers.get_content_type()
                    if path == '/stream':
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        while line := response.readline(2 * 1024 * 1024):
                            self.wfile.write(line)
                            self.wfile.flush()
                        return
                    data = response.read(4 * 1024 * 1024)
                    csp = None
                    if path == '/':
                        nonce = secrets.token_urlsafe(20)
                        html = data.decode().replace('"/leaflet/', '"/simulation/leaflet/')
                        html = html.replace('"/control"', '"/simulation/control"').replace('"/stream"', '"/simulation/stream"')
                        html = html.replace('<script>', f'<script nonce="{nonce}">')
                        html = html.replace('</head>', '<link rel="stylesheet" href="/sim-theme.css"></head>')
                        data = html.encode()
                        csp = (f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data: https://server.arcgisonline.com https://*.tile.opentopomap.org https://tile.openstreetmap.org; "
                               "connect-src 'self' https://nominatim.openstreetmap.org https://overpass-api.de https://overpass.kumi.systems https://overpass.private.coffee; "
                               "object-src 'none'; frame-ancestors 'self'; base-uri 'none'")
                    return self.respond(response.status, data, kind, csp=csp)
            except (OSError, ValueError, URLError) as exc:
                if path != '/stream':
                    return self.respond(503, dict(error=str(exc)[:200]))

        def log_message(self, *_):
            pass  # Do not log bearer tokens or telemetry.

    server = ThreadingHTTPServer((host, port), Handler)
    server.coordinator = state
    server.vision = vision
    close = server.server_close
    def close_services():
        vision.close()
        camera.stop_local()
        training.close()
        simulation.close()
        close()
    server.server_close = close_services
    return server


def main(argv=None):
    from discovery.beacons import add_arguments, monitor_from_args
    from discovery.server import Discovery, serial_worker
    from .trace import ReceiverFeed
    from .sos_monitor import SOSMonitor
    from ble_owner import OwnerError
    from ble_state import StateError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1', help='Use the Pi LAN IP to enable operator/Jetson access')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--pi-camera', action='store_true', help='Stream the Pi camera using rpicam-vid')
    parser.add_argument('--runtime-python', help='Python with numpy, OpenCV, torch and torchvision for simulation/vision')
    parser.add_argument('--discovery-url', default='http://127.0.0.1:8765', help='Existing BLE discovery server')
    parser.add_argument('--serial', help='Own this ESP32 USB receiver directly instead of using --discovery-url')
    parser.add_argument('--sos-state', help='Separate v2 replay state; requires beacon verification')
    add_arguments(parser)
    parser.add_argument('--credentials', type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument('--init', action='store_true', help='Create private credentials, without starting a server')
    parser.add_argument('--export-role', choices=('operator', *NODES))
    parser.add_argument('--out', type=Path, help='New private role-only JSON file for another device')
    args = parser.parse_args(argv)
    if not args.serial and any((args.keys, args.test_keys, args.state, args.scope, args.sos_state)):
        parser.error('Beacon verification flags require --serial')
    if args.sos_state and not (args.keys or args.test_keys):
        parser.error('--sos-state requires --keys or --test-keys, --state and --scope')
    beacons = sos = receiver = None
    stop = threading.Event()
    try:
        if args.init:
            print('Created private credentials:', init_credentials(args.credentials))
            return
        credentials = load_credentials(args.credentials)
        if args.export_role:
            if not args.out:
                parser.error('--export-role requires --out')
            fd = os.open(args.out.expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump({args.export_role: credentials[args.export_role]}, stream)
            print('Exported private role file:', args.out)
            return
        camera = PiCamera()
        bluetooth = BluetoothFeed(args.discovery_url)
        if args.serial:
            discovery = Discovery()
            beacons = monitor_from_args(args, discovery)
            sos = SOSMonitor(beacons, args.sos_state) if args.sos_state else None
            bluetooth = ReceiverFeed(discovery, beacons, sos)
            receiver = threading.Thread(target=serial_worker,
                args=(discovery, args.serial, stop, (bluetooth.ingest,)), daemon=True)
        server = make_server(Coordinator(), credentials, args.host, args.port,
                             camera=camera, bluetooth=bluetooth, runtime_python=args.runtime_python)
        if args.pi_camera:
            camera.start()
    except (OSError, ValueError, OwnerError, StateError) as exc:
        for monitor in (sos, beacons):
            if monitor:
                os.close(monitor.owner)
        parser.error(str(exc))
    # A dedicated watchdog operates even when no clients send HTTP requests.
    # The state is retained explicitly on the server for shutdown and tests.
    state = server.coordinator

    def watchdog():
        while not stop.wait(0.1):
            with state.lock:
                state.tick()

    worker = threading.Thread(target=watchdog, daemon=True)
    worker.start()
    if receiver:
        receiver.start()
    print(f'Local mission control: http://{args.host}:{server.server_port} (starts PAUSED)', flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        with state.lock:
            state.halt('Coordinator shutting down')
        stop.set()
        server.server_close()
        camera.close()
        worker.join(timeout=1)
        if receiver:
            receiver.join(timeout=3)
        for monitor in (sos, beacons):
            if monitor:
                os.close(monitor.owner)


if __name__ == '__main__':
    main()

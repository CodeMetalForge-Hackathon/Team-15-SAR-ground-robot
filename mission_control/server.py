"""Local coordinator: python3 -m mission_control.server --credentials PATH."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

from .protocol import DEFAULT_CREDENTIALS, NODES, init_credentials, load_credentials
from .state import Coordinator, Conflict
from .camera import PiCamera
from .feeds import BluetoothFeed

STATIC = Path(__file__).parent / 'static'


def make_server(state, credentials, host='127.0.0.1', port=8080, camera=None, bluetooth=None):
    camera = camera or PiCamera()
    bluetooth = bluetooth or BluetoothFeed()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def respond(self, status, value, kind='application/json', headers=None):
            body = json.dumps(value, allow_nan=False).encode() if kind == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/') or kind == 'application/json' else ''))
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            for key, value in (headers or {}).items():
                self.send_header(key, str(value))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, role):
            auth = self.headers.get('Authorization', '')
            return hmac.compare_digest(auth.encode(), ('Bearer ' + credentials[role]).encode())

        def do_GET(self):
            if self.path in ('/api/state', '/api/bluetooth', '/api/camera/frame'):
                if not self.authorized('operator'):
                    return self.respond(401, dict(error='Operator token required'))
                if self.path == '/api/state':
                    return self.respond(200, state.snapshot())
                if self.path == '/api/bluetooth':
                    return self.respond(200, bluetooth.snapshot())
                frame = camera.snapshot()
                if frame['frame'] is None:
                    return self.respond(503, dict(error=frame['detail']))
                return self.respond(200, frame['frame'], 'image/jpeg',
                    {'X-Camera-Sequence':frame['sequence'], 'X-Camera-Source':frame['source']})
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                     '/style.css': ('style.css', 'text/css'), '/media.js':('media.js', 'text/javascript'),
                     '/fonts/RobotoSlab.ttf': ('fonts/RobotoSlab.ttf', 'font/ttf')}
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

        def log_message(self, *_):
            pass  # Do not log bearer tokens or telemetry.

    server = ThreadingHTTPServer((host, port), Handler)
    server.coordinator = state
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1', help='Use the Pi LAN IP to enable operator/Jetson access')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--pi-camera', action='store_true', help='Stream the Pi camera using rpicam-vid')
    parser.add_argument('--discovery-url', default='http://127.0.0.1:8765', help='Existing BLE discovery server')
    parser.add_argument('--credentials', type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument('--init', action='store_true', help='Create private credentials, without starting a server')
    parser.add_argument('--export-role', choices=('operator', *NODES))
    parser.add_argument('--out', type=Path, help='New private role-only JSON file for another device')
    args = parser.parse_args(argv)
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
        server = make_server(Coordinator(), credentials, args.host, args.port,
                             camera=camera, bluetooth=BluetoothFeed(args.discovery_url))
        if args.pi_camera:
            camera.start()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    # A dedicated watchdog operates even when no clients send HTTP requests.
    # The state is retained explicitly on the server for shutdown and tests.
    state = server.coordinator
    stop = threading.Event()

    def watchdog():
        while not stop.wait(0.1):
            with state.lock:
                state.tick()

    worker = threading.Thread(target=watchdog, daemon=True)
    worker.start()
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


if __name__ == '__main__':
    main()

"""Loopback proxy for sharing the running dashboard, including new favicon assets.

Run: python tools/share_site.py --upstream-port 8092 --port 8095
Then: ssh -R 80:127.0.0.1:8095 localhost.run
The dashboard retains its operator authentication. No directory is exposed.
"""
import argparse
import gzip
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parents[1] / 'mission_control' / 'static'
STATIC_FILES = {'/favicon.png': ('favicon.png', 'image/png'),
                '/favicon.ico': ('favicon.ico', 'image/x-icon'),
                '/apple-touch-icon.png': ('apple-touch-icon.png', 'image/png'),
                '/about': ('about.html', 'text/html'),
                '/about.js': ('about.js', 'text/javascript'),
                '/about.css': ('about.css', 'text/css')}
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate',
               'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}


def make_proxy(upstream_port, port, finite_events=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not log tokens, request bodies, or device telemetry.

        def do_GET(self):
            self.proxy()

        def do_HEAD(self):
            self.proxy()

        def do_POST(self):
            self.proxy()

        def proxy(self):
            if not self.path.startswith('/') or self.path.startswith('//'):
                return self.send_error(400)
            if self.headers.get('Transfer-Encoding'):
                return self.send_error(400)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 16 * 1024 * 1024:
                    return self.send_error(413)
            except ValueError:
                return self.send_error(400)
            path = urlsplit(self.path).path
            if self.command in ('GET', 'HEAD') and path in STATIC_FILES:
                filename, kind = STATIC_FILES[path]
                body = (STATIC / filename).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/') else ''))
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store' if kind.startswith('text/') else 'public, max-age=3600')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'self'; base-uri 'none'")
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)
                return
            upstream = http.client.HTTPConnection('127.0.0.1', upstream_port, timeout=30)
            started = False
            try:
                body = self.rfile.read(length) if length else None
                headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
                # Retain Host and Origin together for the coordinator's origin checks.
                upstream.request('GET' if self.command == 'HEAD' else self.command,
                                 self.path, body=body, headers=headers)
                response = upstream.getresponse()
                kind = response.getheader('Content-Type', '')
                # Quick tunnels buffer SSE. Send one complete event per finite
                # response; EventSource reconnects using the advertised retry.
                if finite_events and kind.startswith('text/event-stream'):
                    lines = [b'retry: 1000\n']
                    while line := response.readline(2 * 1024 * 1024):
                        lines.append(line)
                        if line in (b'\n', b'\r\n') and any(item.startswith(b'data:') for item in lines):
                            break
                    event = b''.join(lines)
                    self.send_response(response.status)
                    started = True
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Content-Length', str(len(event)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    if self.command != 'HEAD':
                        self.wfile.write(event)
                    return
                compress = ('gzip' in self.headers.get('Accept-Encoding', '') and
                            (kind.startswith('text/') or 'json' in kind or 'javascript' in kind) and
                            not kind.startswith('text/event-stream') and
                            not response.getheader('Content-Encoding') and
                            response.status not in (204, 304))
                packed = gzip.compress(response.read(), compresslevel=5) if compress else None
                self.send_response(response.status)
                started = True
                for key, value in response.getheaders():
                    if key.lower() not in HOP_HEADERS and not (compress and key.lower() == 'content-length'):
                        self.send_header(key, value)
                if compress:
                    self.send_header('Content-Encoding', 'gzip')
                    self.send_header('Content-Length', str(len(packed)))
                    self.send_header('Vary', 'Accept-Encoding')
                self.send_header('Connection', 'close')
                self.end_headers()
                if self.command != 'HEAD':
                    if packed is not None:
                        self.wfile.write(packed)
                    else:
                        while chunk := response.read1(64 * 1024):
                            self.wfile.write(chunk)
                            self.wfile.flush()
            except (OSError, http.client.HTTPException):
                if not started:
                    self.send_error(502, 'Dashboard unavailable')
            finally:
                upstream.close()
                self.close_connection = True

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream-port', type=int, default=8092)
    parser.add_argument('--port', type=int, default=8095)
    parser.add_argument('--finite-events', action='store_true', help='Use bounded SSE responses for buffering tunnels')
    args = parser.parse_args()
    make_proxy(args.upstream_port, args.port, args.finite_events).serve_forever()

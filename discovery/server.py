"""Run with python3 -m discovery.server --serial /dev/cu.usbmodem2101.

Standard-library only. No replay/demo source, disk capture, or mission observations.
"""
from __future__ import annotations

import argparse
from collections import deque
import fcntl
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import select
import termios
import threading
import time
import tty

from discovery.beacons import add_arguments as add_beacon_arguments, monitor_from_args
from discovery.beacons import snapshot as beacon_snapshot

STATIC = Path(__file__).parent / "static"
TTL = 60
HISTORY = 30
CAPACITY = 256


def parse_advertisement(line):
    """Parse the dedicated firmware channel and length-delimited BLE AD fields."""
    if not line.startswith("#BLE,"):
        return None
    _, rssi, address, address_type, payload = line.strip().split(",")
    rssi, address_type = int(rssi), int(address_type)
    if not -127 <= rssi <= 20 or address_type not in range(4):
        raise ValueError("invalid RSSI/address type")
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", address):
        raise ValueError("invalid address")
    if len(payload) > 3300 or len(payload) % 2 or not re.fullmatch(r"[0-9a-fA-F]*", payload):
        raise ValueError("invalid advertisement payload")
    data, offset, name, apple = bytes.fromhex(payload), 0, "", False
    while offset < len(data):
        size = data[offset]
        if not size:
            break
        end = offset + size + 1
        if end > len(data):
            raise ValueError("truncated AD field")
        kind, value = data[offset + 1], data[offset + 2:end]
        if kind in (8, 9):
            name = "".join(c for c in value.decode("utf-8", "replace") if c.isprintable())[:80]
        if kind == 255 and value[:2] == b"\x4c\x00":
            apple = True
        offset = end
    return (f"{address.lower()}/{address_type}", rssi, name, apple)


class Discovery:
    def __init__(self, clock=time.monotonic, source="LIVE-HW"):
        self.clock = clock
        self.source = source
        self.lock = threading.Lock()
        self.key = secrets.token_bytes(32)
        self.signals = {}
        self.sequence = 0
        self.packets = self.malformed = 0
        self.status = "connecting"
        self.detail = "Opening USB receiver"
        self.heartbeat = None
        self.last_packet = None

    def ready(self):
        """True while a fresh discovery heartbeat says the receiver is scanning."""
        with self.lock:
            return self.status == "scanning" and self.heartbeat is not None and self.clock() - self.heartbeat <= 4

    def connection(self, status, detail):
        with self.lock:
            self.status, self.detail = status, detail
            if status != "scanning":
                self.heartbeat = None

    def ingest(self, line):
        now = self.clock()
        with self.lock:
            if line.startswith("#HEARTBEAT,"):
                if "scanning=1," in line and ",passive=1,discovery=1" in line:
                    self.heartbeat = now
                    self.status, self.detail = "scanning", "Passive receiver is scanning"
                else:
                    self.status, self.detail = "unavailable", "Receiver stopped or discovery firmware missing"
                    self.heartbeat = None
                return
            if line.startswith(("#SCAN_ERROR", "#SCAN_END")):
                self.status, self.detail = "unavailable", "Receiver reported a scan interruption"
                self.heartbeat = None
                return
            try:
                packet = parse_advertisement(line)
            except (ValueError, TypeError):
                self.malformed += 1
                return
            if packet is None:
                return
            # Do not accept queued packets before a fresh discovery heartbeat.
            if self.status != "scanning" or self.heartbeat is None or now - self.heartbeat > 4:
                return
            address, rssi, name, apple = packet
            identifier = hmac.new(self.key, address.encode(), hashlib.sha256).hexdigest()[:24]
            self._prune(now)
            if identifier not in self.signals:
                if len(self.signals) >= CAPACITY:
                    del self.signals[min(self.signals, key=lambda k: self.signals[k]["last"])]
                self.sequence += 1
                self.signals[identifier] = dict(id=identifier, label=f"Signal {self.sequence:02d}",
                    first=now, last=now, count=0, name="", apple=False, history=deque(maxlen=61))
            signal = self.signals[identifier]
            signal.update(last=now, rssi=rssi, name=name or signal["name"], apple=apple)
            signal["count"] += 1
            bucket = int(now * 2) / 2
            if signal["history"] and signal["history"][-1][0] == bucket:
                signal["history"][-1] = (bucket, rssi)
            else:
                signal["history"].append((bucket, rssi))
            self.packets += 1
            self.last_packet = now

    def _prune(self, now):
        for key in list(self.signals):
            if now - self.signals[key]["last"] > TTL:
                del self.signals[key]

    def snapshot(self):
        now = self.clock()
        with self.lock:
            self._prune(now)
            status, detail = self.status, self.detail
            if status == "scanning" and (self.heartbeat is None or now - self.heartbeat > 4):
                status, detail = "unavailable", "Receiver heartbeat lost; waiting for USB data"
            signals = []
            for s in self.signals.values():
                age = max(0, now - s["last"])
                signals.append(dict(id=s["id"], label=s["label"], name=s["name"],
                    classification="Possible Apple device" if s["apple"] else "Unknown BLE device",
                    hint="Advertises Apple company ID 0x004C; not proof of brand or phone type" if s["apple"]
                        else "No supported device-type hint in the latest advertisement",
                    rssi=s["rssi"], age_s=round(age, 2), stale=age > 5,
                    count=s["count"], history=[[round(now - t, 2), r] for t, r in s["history"] if now - t <= HISTORY]))
            signals.sort(key=lambda s: (s["stale"], -s["rssi"], s["label"]))
            return dict(source=self.source, mode="passive", status=status, detail=detail,
                packets=self.packets, malformed=self.malformed, ttl_s=TTL, history_s=HISTORY,
                last_packet_age_s=None if self.last_packet is None else round(now - self.last_packet, 2),
                active=sum(not s["stale"] for s in signals), signals=signals)


def serial_worker(state, port, stop, consumers=()):
    """Exclusive serial reader, bounded buffering and reconnect after USB loss.

    The single reader for the receiver: each line goes to discovery, then to
    every consumer (the authenticated beacon verifier)."""
    while not stop.is_set():
        fd, previous = None, None
        try:
            state.connection("connecting", "Opening USB receiver")
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            fcntl.ioctl(fd, termios.TIOCEXCL)
            previous = termios.tcgetattr(fd)
            tty.setraw(fd)
            config = termios.tcgetattr(fd)
            config[4] = config[5] = termios.B115200
            termios.tcsetattr(fd, termios.TCSANOW, config)
            termios.tcflush(fd, termios.TCIFLUSH)
            state.connection("connecting", "Waiting for discovery firmware heartbeat")
            # Drain startup bytes; never display advertisements buffered before connection.
            drain_until, pending = time.monotonic() + 2, b""
            aligning = True
            while not stop.is_set():
                if not select.select([fd], [], [], .25)[0]:
                    continue
                chunk = os.read(fd, 8192)
                if not chunk:
                    raise OSError("USB receiver disconnected")
                if time.monotonic() < drain_until:
                    continue
                if aligning:
                    if b"\n" not in chunk:
                        continue
                    chunk = chunk.split(b"\n", 1)[1]
                    aligning = False
                pending += chunk
                if len(pending) > 65536:
                    raise OSError("Receiver line exceeds 64 KiB")
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    text = line.decode("utf-8", "replace").rstrip("\r")
                    state.ingest(text)
                    for consume in consumers:
                        consume(text)
        except OSError as exc:
            state.connection("disconnected", f"USB receiver unavailable: {exc.strerror or str(exc)}")
        finally:
            if fd is not None:
                try:
                    if previous is not None:
                        termios.tcsetattr(fd, termios.TCSANOW, previous)
                except (OSError, termios.error):
                    pass
                os.close(fd)
        stop.wait(2)


def make_server(state, host="127.0.0.1", port=8765, beacons=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/discovery":
                body, kind = json.dumps(state.snapshot()).encode(), "application/json"
            elif path == "/api/beacons":
                body, kind = json.dumps(beacon_snapshot(beacons, state)).encode(), "application/json"
            elif path in ("/", "/app.js", "/beacons.js", "/style.css"):
                file = "index.html" if path == "/" else path[1:]
                body = (STATIC / file).read_bytes()
                kind = {"index.html": "text/html", "app.js": "text/javascript",
                        "beacons.js": "text/javascript", "style.css": "text/css"}[file]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; media-src blob:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="ESP32 USB serial device")
    parser.add_argument("--port", type=int, default=8765)
    add_beacon_arguments(parser)
    args = parser.parse_args()
    state, stop = Discovery(), threading.Event()
    beacons = monitor_from_args(args, state)
    server = make_server(state, port=args.port, beacons=beacons)
    consumers = (beacons.ingest,) if beacons else ()
    worker = threading.Thread(target=serial_worker, args=(state, args.serial, stop, consumers), daemon=True)
    worker.start()
    print(f"Passive BLE discovery: http://127.0.0.1:{server.server_port} · {args.serial}", flush=True)
    print(f"Beacon verification: {beacons.mode_label if beacons else 'OFF'}"
          f"{f' · scope {beacons.scope}' if beacons else ''}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=3)


if __name__ == "__main__":
    main()

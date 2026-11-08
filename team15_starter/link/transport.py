"""link/transport.py — how the homebase reaches the ESP32-S3 gateway.

Every transport has the same two calls, so the homebase never knows which one
it is talking to:

    send(packet_bytes)           -> one packet out (gateway broadcasts it)
    recv() -> [(rssi, packet)]   -> every whole packet that arrived since last call

SerialTransport  : the real ESP32-S3 on USB (/dev/ttyACM0 on the Jetson).
                   Also works with the pty from `python fleet_sim.py --pty`.
"""
from __future__ import annotations

from .protocol import FrameReader, frame


class SerialTransport:
    def __init__(self, port: str, baud: int = 921600):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=0)
        self.reader = FrameReader()

    def send(self, packet: bytes) -> None:
        self.ser.write(frame(packet))

    def recv(self) -> list:
        data = self.ser.read(4096)
        out = []
        for f in self.reader.feed(data):
            if len(f) >= 2:
                rssi = f[0] - 256 if f[0] > 127 else f[0]
                out.append((rssi, f[1:]))
        return out

    def close(self) -> None:
        self.ser.close()


class BytePipeTransport:
    """Homebase side of an in-memory 'USB cable'. The simulated gateway writes
    framed bytes into `rx` and reads framed bytes from `tx`, exactly like the
    real S3 would. Used by `homebase.py --sim` so the framing is exercised."""

    def __init__(self):
        self.rx = bytearray()   # gateway -> homebase
        self.tx = bytearray()   # homebase -> gateway
        self.reader = FrameReader()

    def send(self, packet: bytes) -> None:
        self.tx += frame(packet)

    def recv(self) -> list:
        data, self.rx = bytes(self.rx), bytearray()
        out = []
        for f in self.reader.feed(data):
            if len(f) >= 2:
                rssi = f[0] - 256 if f[0] > 127 else f[0]
                out.append((rssi, f[1:]))
        return out

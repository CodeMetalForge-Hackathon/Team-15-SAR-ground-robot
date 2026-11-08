"""Byte transports: real serial (pyserial, lazily imported) and a scripted mock for CI.

CI never imports pyserial and never opens a device. ``SerialTransport`` opens the
port with ``exclusive=True`` (POSIX flock), so a second process (another agent's
service, a stray ``screen``) cannot read the same LiDAR at the same time.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, Optional, Protocol

from . import protocol as P


class TransportClosed(OSError):
    """The device went away (unplug, power loss, adapter reset)."""


class Transport(Protocol):
    def read(self, n: int) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


class SerialTransport:
    """pyserial wrapper. Only constructed by the driver after the hardware gate passes."""

    def __init__(self, device: str, baudrate: int, timeout_s: float):
        try:
            import serial  # pyserial, BSD-3-Clause; optional: only needed on the Pi
        except ImportError as e:  # pragma: no cover - exercised only on hardware
            raise RuntimeError("pyserial is not installed (pip install pyserial==3.5)") from e
        self._serial_mod = serial
        # C1: DTR/RTS are not used for motor control (integrated motor), keep them low.
        self._s = serial.Serial(port=device, baudrate=baudrate, timeout=timeout_s, write_timeout=timeout_s,
                                exclusive=True, dsrdtr=False, rtscts=False)

    def read(self, n: int) -> bytes:  # pragma: no cover
        try:
            return self._s.read(n)
        except self._serial_mod.SerialException as e:
            raise TransportClosed(str(e)) from e

    def write(self, data: bytes) -> int:  # pragma: no cover
        try:
            return self._s.write(data)
        except self._serial_mod.SerialException as e:
            raise TransportClosed(str(e)) from e

    def reset_input_buffer(self) -> None:  # pragma: no cover
        try:
            self._s.reset_input_buffer()
        except self._serial_mod.SerialException as e:
            raise TransportClosed(str(e)) from e

    def close(self) -> None:  # pragma: no cover
        try:
            self._s.close()
        except Exception:
            pass


class MockLidarDevice:
    """Scripted RPLIDAR on a fake serial line, speaking the legacy protocol.

    ``revolutions`` is an iterable of lists of (angle_deg, distance_m, quality) per revolution.
    Fault injection:
      * ``disconnect_after_bytes``: raise TransportClosed once that many scan bytes were read.
      * ``stall_after_bytes``: return b"" (timeout) forever after that many scan bytes.
      * ``corrupt``: callable(bytes_of_one_node, node_index) -> bytes, to damage nodes.
      * ``health`` / ``model``: what GET_HEALTH / GET_INFO answer.
      * ``garbage_prefix``: bytes emitted before the scan descriptor.
    """

    def __init__(self, revolutions: Iterable = (), *, model: int = 0x41, health: int = P.HEALTH_GOOD,
                 health_error: int = 0, disconnect_after_bytes: Optional[int] = None,
                 stall_after_bytes: Optional[int] = None, corrupt: Optional[Callable] = None,
                 garbage_prefix: bytes = b"", fail_on_open: bool = False):
        self.revolutions = [list(r) for r in revolutions]
        self.model, self.health, self.health_error = model, health, health_error
        self.disconnect_after_bytes = disconnect_after_bytes
        self.stall_after_bytes = stall_after_bytes
        self.corrupt = corrupt
        self.garbage_prefix = garbage_prefix
        self.fail_on_open = fail_on_open
        self.writes: list[bytes] = []
        self.closed = False
        self.scanning = False
        self.opened = 0
        self._out: deque = deque()
        self._scan_bytes = bytearray()
        self._scan_pos = 0

    # Factory used by the driver: MockLidarDevice(...).factory
    def factory(self, device: str, baudrate: int, timeout_s: float) -> "MockLidarDevice":
        if self.fail_on_open:
            raise TransportClosed(f"could not open {device}")
        self.opened += 1
        self.closed = False
        return self

    def _scan_stream(self) -> bytes:
        out = bytearray()
        idx = 0
        for rev in self.revolutions:
            for i, (a, d, q) in enumerate(rev):
                nb = P.encode_node(a, d, q, start=(i == 0))
                if self.corrupt is not None:
                    nb = self.corrupt(nb, idx)
                out += nb
                idx += 1
        # A trailing start node closes the last revolution.
        if self.revolutions:
            out += P.encode_node(0.0, 0.0, 0, start=True)
        return bytes(out)

    def write(self, data: bytes) -> int:
        if self.closed:
            raise TransportClosed("write on closed mock")
        self.writes.append(bytes(data))
        cmd = data[1] if len(data) >= 2 and data[0] == P.SYNC1 else None
        if cmd == P.CMD_STOP:
            self.scanning = False
        elif cmd == P.CMD_RESET:
            self.scanning = False
        elif cmd == P.CMD_GET_INFO:
            self._out.extend(P.build_descriptor(P.INFO_LEN, 0, P.ANS_TYPE_DEVINFO))
            self._out.extend(bytes((self.model, 1, 1, 18)) + bytes(range(16)))
        elif cmd == P.CMD_GET_HEALTH:
            self._out.extend(P.build_descriptor(P.HEALTH_LEN, 0, P.ANS_TYPE_DEVHEALTH))
            self._out.extend(bytes((self.health, self.health_error & 0xFF, self.health_error >> 8)))
        elif cmd == P.CMD_SCAN:
            self.scanning = True
            self._out.extend(self.garbage_prefix)
            self._out.extend(P.build_descriptor(P.NODE_LEN, 1, P.ANS_TYPE_MEASUREMENT))
            self._scan_bytes = bytearray(self._scan_stream())
            self._scan_pos = 0
        return len(data)

    def read(self, n: int) -> bytes:
        if self.closed:
            raise TransportClosed("read on closed mock")
        out = bytearray()
        while self._out and len(out) < n:
            out.append(self._out.popleft())
        while self.scanning and len(out) < n and self._scan_pos < len(self._scan_bytes):
            if self.disconnect_after_bytes is not None and self._scan_pos >= self.disconnect_after_bytes:
                self.closed = True
                raise TransportClosed("mock: USB adapter unplugged")
            if self.stall_after_bytes is not None and self._scan_pos >= self.stall_after_bytes:
                break
            out.append(self._scan_bytes[self._scan_pos])
            self._scan_pos += 1
        return bytes(out)

    def reset_input_buffer(self) -> None:
        if self.closed:
            raise TransportClosed("mock closed")
        self._out.clear()

    def close(self) -> None:
        self.closed = True
        self.scanning = False

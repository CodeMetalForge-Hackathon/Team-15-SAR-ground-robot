"""Pi-side USB-serial bridge to the M5StickC that drives the RoverC-Pro (design: docs/rover/BRIDGE_PROTOCOL.md).

NOT VERIFIED ON HARDWARE. Nothing here opens a serial port unless a caller passes a port object, and
``open_serial`` refuses anything but a stable /dev/serial/by-id path. No motor moves unless the
firmware is ARMED by an explicit operator call, the safety supervisor approves, and every check passes.

Line protocol (ASCII, newline-terminated, CRC-8/0x07 over everything before '*', as 2 hex digits):
  host -> MCU   M,<seq>,<s0>,<s1>,<s2>,<s3>*CC   motor speeds for registers 0x00-0x03, each -100..100
                Z,<seq>*CC                       zero all motors (allowed in every state)
                A,<seq>,<operator>*CC            ARM (operator named); needed after boot, watchdog, e-stop
                P,<seq>*CC                       ping / status request
  MCU -> host   K,<seq>,<state>,<wd_trips>,<i2c_errs>*CC     ack; state in BOOT|DISARMED|ARMED|WDSTOP|ESTOP|I2CERR
                N,<seq>,<reason>*CC                         refused frame (motors left at zero or unchanged)
The firmware zeroes the motors at boot, on any WDSTOP (no valid frame for WATCHDOG_MS), on the StickC
button (local e-stop) and on I2C error, and refuses non-zero speeds until re-ARMED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from rover.protocol import I2C_ADDRESS, REG_MOTOR

WATCHDOG_MS = 250              # firmware: no valid frame for this long -> motors zero, WDSTOP (<= 300 ms required)
ACK_TIMEOUT_S = 0.30           # host: no valid ack for this long -> health() reports a fault
MAX_SPEED = 100                # library clamp; firmware rejects |s| > 100
STATES = ("BOOT", "DISARMED", "ARMED", "WDSTOP", "ESTOP", "I2CERR")
_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,32}$")


def crc8(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def frame(payload: str) -> bytes:
    if "*" in payload or "\n" in payload:
        raise ValueError("payload may not contain '*' or newline")
    return f"{payload}*{crc8(payload.encode('ascii')):02X}\n".encode("ascii")


def parse(line: bytes) -> Optional[list[str]]:
    """Fields of a valid frame, or None (bad CRC, bad encoding, malformed). Never raises."""
    try:
        s = line.decode("ascii").strip()
        payload, _, cc = s.rpartition("*")
        if not payload or len(cc) != 2 or int(cc, 16) != crc8(payload.encode("ascii")):
            return None
        return payload.split(",")
    except (UnicodeDecodeError, ValueError):
        return None


def encode_motor(seq: int, speeds: tuple[int, int, int, int]) -> bytes:
    if len(speeds) != 4 or any(not isinstance(s, int) or isinstance(s, bool) or abs(s) > MAX_SPEED for s in speeds):
        raise ValueError(f"speeds must be 4 ints within ±{MAX_SPEED}: {speeds!r}")
    return frame(f"M,{seq},{speeds[0]},{speeds[1]},{speeds[2]},{speeds[3]}")


@dataclass(frozen=True)
class Ack:
    t: float
    seq: int
    state: str
    wd_trips: int
    i2c_errs: int


class Port(Protocol):
    def write(self, data: bytes) -> int: ...
    def read_available(self) -> bytes: ...   # non-blocking; b"" if nothing


class BridgeTransport:
    """Transport for RoverCAdapter. Accepts only the 4-byte motor block at 0x38/0x00, sent as an M frame.

    health() is '' only while the latest valid ack is fresher than ack_timeout_s, the firmware reports
    ARMED (or DISARMED with zero output), and the last frame wasn't refused.
    """

    def __init__(self, port: Port, clock: Callable[[], float], ack_timeout_s: float = ACK_TIMEOUT_S,
                 physical: bool = True):
        if not 0 < ack_timeout_s <= 0.30:
            raise ValueError("ack_timeout_s must be in (0, 0.30] s")
        self.port = port
        self.clock = clock
        self.ack_timeout_s = ack_timeout_s
        self.physical = physical
        self.seq = 0
        self.last_ack: Optional[Ack] = None
        self.last_nak: str = ""
        self.last_sent_nonzero = False
        self._buf = b""

    # --- operator actions ------------------------------------------------------------------------
    def arm(self, operator: str) -> None:
        if not operator or not _NAME.match(operator):
            raise PermissionError("ARM needs a named operator (letters, digits, _.@-)")
        self._send(frame(f"A,{self._next()},{operator}"))

    def ping(self) -> None:
        self._send(frame(f"P,{self._next()}"))

    # --- Transport protocol ------------------------------------------------------------------------
    def write_block(self, address: int, register: int, data: bytes) -> None:
        if address != I2C_ADDRESS or register != REG_MOTOR[0] or len(data) != 4:
            raise PermissionError(f"bridge only carries the motor block 0x{I2C_ADDRESS:02X}/0x00 (4 bytes)")
        speeds = tuple(b - 256 if b > 127 else b for b in data)
        if all(s == 0 for s in speeds):
            self._send(frame(f"Z,{self._next()}"))
            self.last_sent_nonzero = False
        else:
            self._send(encode_motor(self._next(), speeds))  # raises if |s| > 100
            self.last_sent_nonzero = True
        self.poll()
        if self.last_nak:
            raise IOError(f"bridge refused frame: {self.last_nak}")

    def health(self) -> str:
        self.poll()
        now = self.clock()
        a = self.last_ack
        if a is None:
            return "no ack from bridge yet"
        if now - a.t > self.ack_timeout_s:
            return f"no ack from bridge for {now - a.t:.3f}s"
        if self.last_nak:
            return f"bridge refused last frame: {self.last_nak}"
        if a.state == "ARMED":
            return ""
        return f"bridge state {a.state} (motors held at zero; operator must re-ARM)"

    # --- I/O ---------------------------------------------------------------------------------------
    def poll(self) -> None:
        self._buf += self.port.read_available() or b""
        if len(self._buf) > 4096:  # garbage flood: drop, never trust a partial line
            self._buf = self._buf[-512:]
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            f = parse(line)
            if not f:
                continue
            try:
                if f[0] == "K" and len(f) == 5 and f[2] in STATES:
                    self.last_ack = Ack(self.clock(), int(f[1]), f[2], int(f[3]), int(f[4]))
                    self.last_nak = ""
                elif f[0] == "N" and len(f) == 3:
                    self.last_nak = f[2]
            except ValueError:
                continue

    def _next(self) -> int:
        self.seq = (self.seq + 1) % 1_000_000
        return self.seq

    def _send(self, data: bytes) -> None:
        self.port.write(data)


def open_serial(path: str, baud: int = 115200):  # pragma: no cover - needs real hardware and pyserial
    """Open the bridge's USB serial port. Refuses unstable names like /dev/ttyACM0. NOT for tests."""
    if not path.startswith("/dev/serial/by-id/"):
        raise PermissionError("use the stable /dev/serial/by-id/... path of the verified StickC")
    import serial  # lazy: pyserial is only needed on the Pi

    s = serial.Serial(path, baud, timeout=0, write_timeout=0.05)

    class _P:
        def write(self, data: bytes) -> int:
            return s.write(data)

        def read_available(self) -> bytes:
            return s.read(s.in_waiting or 0)
    return _P()

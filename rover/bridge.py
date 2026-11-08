"""Pi-side USB-serial bridge to the M5StickC that drives the RoverC-Pro (design: docs/rover/BRIDGE_PROTOCOL.md).

NOT VERIFIED ON HARDWARE. Nothing here opens a serial port unless a caller passes a port object, and
``open_serial`` refuses anything but a stable /dev/serial/by-id path. No motor moves unless the
firmware is ARMED by an explicit operator call, the safety supervisor approves, and every check passes.

Line protocol (ASCII, newline-terminated, CRC-8/0x07 over everything before '*', as 2 hex digits):
  host -> MCU   M,<seq>,<session>,<s0>,<s1>,<s2>,<s3>*CC   motor speeds for 0x00-0x03, each -100..100
                Z,<seq>*CC                                 zero all motors (allowed in every state)
                A,<seq>,<operator>,<session>*CC            ARM this session (operator named)
                P,<seq>*CC                                 ping / status request
  MCU -> host   K,<seq>,<state>,<session>,<wd_trips>,<i2c_errs>*CC   ack (session '-' when none is armed)
                N,<seq>,<reason>*CC                                  refused frame
<session> is 8 random hex chars chosen by each BridgeTransport. The firmware accepts M frames only from the
session that ARMED it; any other session's M zeroes the motors and DISARMS. So a restarted or second Pi
process can never drive motors armed by an earlier one, even inside the watchdog window.
The firmware zeroes the motors at boot, on any WDSTOP (no valid frame for WATCHDOG_MS), on the StickC
button (local e-stop), on a foreign session and on I2C error; it retries zero while the last confirmed
output is non-zero; it refuses non-zero speeds until re-ARMED.
"""
from __future__ import annotations

import re
import secrets
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from rover.protocol import I2C_ADDRESS, REG_MOTOR

WATCHDOG_MS = 250              # firmware: no valid frame for this long -> motors zero, WDSTOP (<= 300 ms required)
ACK_TIMEOUT_S = 0.30           # host: no valid ack for this long -> health() reports a fault
MAX_SPEED = 100                # library clamp; firmware rejects |s| > 100
STATES = ("BOOT", "DISARMED", "ARMED", "WDSTOP", "ESTOP", "I2CERR")
_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,32}$")
_SESSION = re.compile(r"^[0-9a-f]{8}$")


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
        s = line.decode("ascii").rstrip("\r\n")  # no other stripping: the CRC covers every byte
        payload, _, cc = s.rpartition("*")
        if not payload or len(cc) != 2 or int(cc, 16) != crc8(payload.encode("ascii")):
            return None
        return payload.split(",")
    except (UnicodeDecodeError, ValueError):
        return None


def encode_motor(seq: int, session: str, speeds: tuple[int, int, int, int]) -> bytes:
    if not _SESSION.match(session or ""):
        raise ValueError("session must be 8 lowercase hex chars")
    if len(speeds) != 4 or any(not isinstance(s, int) or isinstance(s, bool) or abs(s) > MAX_SPEED for s in speeds):
        raise ValueError(f"speeds must be 4 ints within ±{MAX_SPEED}: {speeds!r}")
    return frame(f"M,{seq},{session},{speeds[0]},{speeds[1]},{speeds[2]},{speeds[3]}")


@dataclass(frozen=True)
class Ack:
    t: float          # SEND time of the frame this ack answers (not when the ack was read)
    seq: int
    state: str
    session: str
    wd_trips: int
    i2c_errs: int


class Port(Protocol):
    def write(self, data: bytes) -> int: ...
    def read_available(self) -> bytes: ...   # non-blocking; b"" if nothing


class BridgeTransport:
    """Transport for RoverCAdapter. Accepts only the 4-byte motor block at 0x38/0x00, sent as an M frame.

    Replies are matched to the frames they answer by seq. Replies to frames we didn't send, or older
    than an already-matched reply, are ignored. health() is '' only while the latest matched ack answers
    a frame SENT within ack_timeout_s, the firmware reports ARMED for this session, and the latest
    matched reply wasn't a refusal. Because a UART reply arrives after write_block returns, a refusal
    of frame n surfaces as an IOError on a later write (or in health()), which latches DRIVER_FAULT.
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
        self.session = secrets.token_hex(4)   # fresh per process: a restart can never inherit an ARM
        self.last_ack: Optional[Ack] = None
        self.last_nak: str = ""
        self.last_sent_nonzero = False
        self._sent: "OrderedDict[int, float]" = OrderedDict()   # seq -> send time, oldest first
        self._buf = b""

    # --- operator actions ------------------------------------------------------------------------
    def arm(self, operator: str) -> None:
        if not operator or not _NAME.match(operator):
            raise PermissionError("ARM needs a named operator (letters, digits, _.@-)")
        self._send(frame(f"A,{self._next()},{operator},{self.session}"))

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
            self._send(encode_motor(self._next(), self.session, speeds))  # raises if |s| > 100
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
        if a.state == "ARMED" and a.session == self.session:
            return ""
        if a.state == "ARMED":
            return f"bridge ARMED by another session ({a.session}); this session must ARM"
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
                if f[0] not in ("K", "N") or not f[1].isdigit():
                    continue
                t_sent = self._match(int(f[1]))
                if t_sent is None:
                    continue                      # not ours, or older than a reply we already matched
                if f[0] == "K" and len(f) == 6 and f[2] in STATES:
                    self.last_ack = Ack(t_sent, int(f[1]), f[2], f[3], int(f[4]), int(f[5]))
                    self.last_nak = ""
                elif f[0] == "N" and len(f) == 3:
                    self.last_nak = f[2] or "refused"
            except ValueError:
                continue

    def _match(self, seq: int) -> Optional[float]:
        """Pop every outstanding frame up to and including seq; return seq's send time (None if unknown)."""
        if seq not in self._sent:
            return None
        while self._sent:
            s, t = self._sent.popitem(last=False)
            if s == seq:
                return t

    def _next(self) -> int:
        self.seq = (self.seq + 1) % 1_000_000
        return self.seq

    def _send(self, data: bytes) -> None:
        self._sent[self.seq] = self.clock()
        while len(self._sent) > 64:
            self._sent.popitem(last=False)
        try:
            self.port.write(data)
        except Exception:
            # Link broke (cable pulled, port closed). Forget the ARM: after any reconnect this transport
            # needs an explicit operator ARM again, even if the firmware's watchdog hasn't fired yet.
            self.session = secrets.token_hex(4)
            self.last_ack = None
            self._sent.clear()
            raise


def open_serial(path: str, baud: int = 115200):  # pragma: no cover - needs real hardware and pyserial
    """Open the bridge's USB serial port. Refuses unstable names like /dev/ttyACM0. NOT for tests."""
    if not path.startswith("/dev/serial/by-id/"):
        raise PermissionError("use the stable /dev/serial/by-id/... path of the verified StickC")
    import serial  # lazy: pyserial is only needed on the Pi

    # Open with DTR and RTS deasserted: on StickC boards these lines drive the ESP32 EN/G0 auto-reset
    # circuit, and toggling them can reset the controller (or hold G0 low = download mode, no zeroing).
    s = serial.Serial()
    s.port, s.baudrate, s.timeout, s.write_timeout = path, baud, 0, 0.05
    s.dtr = False
    s.rts = False
    s.open()

    class _P:
        def write(self, data: bytes) -> int:
            return s.write(data)

        def read_available(self) -> bytes:
            return s.read(s.in_waiting or 0)
    return _P()

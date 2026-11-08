"""Executable model of firmware/stickc_roverc_bridge/stickc_roverc_bridge.ino, for mocked-hardware tests.

Keep the two in lockstep: same states, same rules, same frames, same parsing. The "I2C bus" is a register
dict. Differences that are physical (display, DTR/RTS reset, download mode, task watchdog) are NOT modelled
and must be bench-tested; see docs/rover/BRIDGE_PROTOCOL.md.
"""
from __future__ import annotations

import re

from rover.bridge import MAX_SPEED, WATCHDOG_MS, crc8, frame

LINE_MAX = 95            # firmware line buffer is 96 bytes incl. NUL; longer lines are dropped whole
ZERO_RETRY_MS = 20
_INT = re.compile(r"^-?[0-9]{1,4}$")      # firmware parseSpeed: optional '-', 1-4 digits
_SEQ = re.compile(r"^[0-9]{1,9}$")
_SESSION = re.compile(r"^[0-9a-f]{8}$")


class FakeI2C:
    def __init__(self):
        self.regs = {0: 0, 1: 0, 2: 0, 3: 0}
        self.writes: list[tuple[int, ...]] = []
        self.fail = False
        self.partial = 0          # next N failing writes still change register 0 (NACK after first data byte)

    def write_motors(self, s: tuple[int, int, int, int]) -> bool:
        if self.fail:
            if self.partial > 0:
                self.partial -= 1
                self.regs[0] = s[0]
            return False
        self.regs = dict(enumerate(s))
        self.writes.append(tuple(s))
        return True


class BridgeFirmwareModel:
    def __init__(self, clock, i2c: FakeI2C | None = None):
        self.clock = clock
        self.i2c = i2c or FakeI2C()
        self.state = "BOOT"
        self.session = "-"
        self.wd_trips = 0
        self.i2c_errs = 0
        self.confirmed = (0, 0, 0, 0)   # last output CONFIRMED by the bus (firmware: regs[])
        self.output_unknown = True      # until the first zero is confirmed, assume the worst
        self.last_zero_try_ms = 0.0
        self.out = b""
        # setup(): zero FIRST (before M5.begin), so a reset while moving stops the wheels as early as possible
        if self._all_zero():
            self.state = "DISARMED"
        self.last_valid_ms = self._ms()

    def _ms(self) -> float:
        return self.clock() * 1000.0

    # --- bus ---------------------------------------------------------------------------------
    def _write(self, s) -> bool:
        if self.i2c.write_motors(tuple(s)):
            self.confirmed = tuple(s)
            self.output_unknown = False
            return True
        self.i2c_errs += 1
        self.output_unknown = True       # some bytes may have landed: real output is unknown
        return False

    def _all_zero(self) -> bool:
        if self._write((0, 0, 0, 0)):
            return True
        self._disarm("I2CERR")
        return False

    def _maybe_moving(self) -> bool:
        return self.output_unknown or any(self.confirmed)

    def _disarm(self, state):
        self.state = state
        self.session = "-"

    # --- replies -----------------------------------------------------------------------------
    def _ack(self, seq):
        self.out += frame(f"K,{seq},{self.state},{self.session},{self.wd_trips},{self.i2c_errs}")

    def _nak(self, seq, why):
        self.out += frame(f"N,{seq},{why}")

    # --- local buttons -----------------------------------------------------------------------
    def button_a(self):                   # local e-stop
        self._all_zero()
        self._disarm("ESTOP")

    def button_b_long(self):              # local e-stop clear (held >= 1 s): back to DISARMED, never ARMED
        if self.state == "ESTOP" and self._all_zero():
            self._disarm("DISARMED")

    # --- serial ------------------------------------------------------------------------------
    def receive_line(self, line: bytes):
        line = line.replace(b"\r", b"")
        if len(line) > LINE_MAX:
            return                        # oversize: dropped whole
        try:
            s = line.decode("ascii")
        except UnicodeDecodeError:
            return
        payload, star, cc = s.rpartition("*")
        if not star or not re.fullmatch(r"[0-9A-Fa-f]{2}", cc):
            return
        if crc8(payload.encode("ascii")) != int(cc, 16):
            return
        f = payload.split(",")            # empty fields preserved (firmware splits by hand, not strtok)
        if len(f) > 9 or len(f) < 2 or not _SEQ.match(f[1]):
            return
        seq, kind = f[1], f[0]
        if kind == "Z" and len(f) == 2:
            self.last_valid_ms = self._ms()
            self._all_zero()
            self._ack(seq)
        elif kind == "P" and len(f) == 2:
            self._ack(seq)                # status only: does NOT feed the watchdog
        elif kind == "A" and len(f) == 4 and f[2] and _SESSION.match(f[3]):
            if self.state == "ESTOP":
                self._nak(seq, "estop-local-reset")
                return
            if self._all_zero():          # ARM only with zero confirmed on the bus (also clears I2CERR)
                self.state = "ARMED"
                self.session = f[3]
                self.last_valid_ms = self._ms()
            self._ack(seq)
        elif kind == "M" and len(f) == 7:
            if not _SESSION.match(f[2]) or self.state != "ARMED" or f[2] != self.session:
                why = "session" if self.state == "ARMED" else f"not-armed-{self.state}"
                self._all_zero()
                if self.state == "ARMED":
                    self._disarm("DISARMED")  # a foreign session's frame disarms
                self._nak(seq, why)
                return
            if not all(_INT.match(x) for x in f[3:7]):
                self._all_zero()
                self._nak(seq, "bad-speed")
                return
            v = tuple(int(x) for x in f[3:7])
            if any(abs(x) > MAX_SPEED for x in v):
                self._all_zero()
                self._nak(seq, "range")
                return
            if not self._write(v):
                self._all_zero()
                self._disarm("I2CERR")
                self._nak(seq, "i2c")
                return
            self.last_valid_ms = self._ms()   # only an ACCEPTED motion frame feeds the watchdog
            self._ack(seq)
        else:
            self._nak(seq, "unknown")

    def loop(self):
        now = self._ms()
        if now - self.last_valid_ms > WATCHDOG_MS and self.state == "ARMED":
            self._all_zero()
            self.wd_trips += 1
            self._disarm("WDSTOP")
        # Not ARMED, but output may be non-zero (a write failed): retry zero every 20 ms until confirmed.
        if self.state != "ARMED" and self._maybe_moving() and now - self.last_zero_try_ms >= ZERO_RETRY_MS:
            self.last_zero_try_ms = now
            self._all_zero()


class LoopbackPort:
    """Connects BridgeTransport to the firmware model. connected=False simulates an unplugged cable.
    reply_delay=n holds the firmware's replies back for n reads, like a real UART round trip.
    mute=True simulates a hung firmware: frames are swallowed and nothing comes back."""

    def __init__(self, fw: BridgeFirmwareModel, reply_delay: int = 0):
        self.fw = fw
        self.connected = True
        self.corrupt_next = 0
        self.reply_delay = reply_delay
        self.mute = False
        self._pending: list[tuple[int, bytes]] = []

    def write(self, data: bytes) -> int:
        if not self.connected:
            raise OSError("serial port disconnected")
        for line in data.split(b"\n"):
            if line:
                if self.corrupt_next:
                    self.corrupt_next -= 1
                    line = line[:-1] + (b"0" if line[-1:] != b"0" else b"1")
                if not self.mute:
                    self.fw.receive_line(line)
        return len(data)

    def read_available(self) -> bytes:
        if not self.connected or self.mute:
            self.fw.out = b""
            return b""
        if self.fw.out:
            self._pending.append((self.reply_delay, self.fw.out))
            self.fw.out = b""
        ready, keep = b"", []
        for d, b in self._pending:
            if d <= 0:
                ready += b
            else:
                keep.append((d - 1, b))
        self._pending = keep
        return ready

    def cut(self):
        self.connected = False

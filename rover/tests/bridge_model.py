"""Executable model of firmware/stickc_roverc_bridge/stickc_roverc_bridge.ino, for mocked-hardware tests.

Keep the two in lockstep: same states, same rules, same frames. The "I2C bus" here is a register dict.
"""
from __future__ import annotations

from rover.bridge import MAX_SPEED, WATCHDOG_MS, frame, parse


class FakeI2C:
    def __init__(self):
        self.regs = {0: 0, 1: 0, 2: 0, 3: 0}
        self.writes: list[tuple[int, ...]] = []
        self.fail = False

    def write_motors(self, s: tuple[int, int, int, int]) -> bool:
        if self.fail:
            return False
        self.regs = dict(enumerate(s))
        self.writes.append(tuple(s))
        return True

    def zero(self) -> bool:
        return self.write_motors((0, 0, 0, 0))


class BridgeFirmwareModel:
    def __init__(self, clock, i2c: FakeI2C | None = None):
        self.clock = clock
        self.i2c = i2c or FakeI2C()
        self.state = "BOOT"
        self.wd_trips = 0
        self.i2c_errs = 0
        self.last_valid_ms = self._ms()
        self.out = b""
        self.i2c.zero()                 # setup(): motors zero before anything else
        self.state = "DISARMED"

    def _ms(self) -> float:
        return self.clock() * 1000.0

    def _all_zero(self):
        if not self.i2c.zero():
            self.i2c_errs += 1
            self.state = "I2CERR"

    def _ack(self, seq):
        self.out += frame(f"K,{seq},{self.state},{self.wd_trips},{self.i2c_errs}")

    def _nak(self, seq, why):
        self.out += frame(f"N,{seq},{why}")

    def button_a(self):                  # local e-stop on the StickC
        self._all_zero()
        self.state = "ESTOP"

    def receive_line(self, line: bytes):
        f = parse(line)
        if not f or not f[0] or len(f) < 2 or not f[1].isdigit():
            return                       # invalid frames don't feed the watchdog and get no reply
        seq = f[1]
        self.last_valid_ms = self._ms()
        kind = f[0]
        if kind == "Z" and len(f) == 2:
            self._all_zero()
            self._ack(seq)
        elif kind == "P" and len(f) == 2:
            self._ack(seq)
        elif kind == "A" and len(f) == 3 and f[2]:
            self._all_zero()
            if self.state != "I2CERR":
                self.state = "ARMED"
            self._ack(seq)
        elif kind == "M" and len(f) == 6:
            try:
                s = tuple(int(x) for x in f[2:6])
            except ValueError:
                self._nak(seq, "bad-speed")
                return
            if any(abs(v) > MAX_SPEED for v in s):
                self._all_zero()
                self._nak(seq, "range")
            elif self.state != "ARMED":
                self._all_zero()
                self._nak(seq, f"not-armed-{self.state}")
            elif not self.i2c.write_motors(s):
                self.i2c_errs += 1
                self.state = "I2CERR"
                self._all_zero()
                self._nak(seq, "i2c")
            else:
                self._ack(seq)
        else:
            self._nak(seq, "unknown")

    def loop(self):
        if self._ms() - self.last_valid_ms > WATCHDOG_MS and self.state not in ("WDSTOP",):
            if self.state == "ARMED" or any(self.i2c.regs.values()):
                self._all_zero()
                self.wd_trips += 1
                self.state = "WDSTOP"


class LoopbackPort:
    """Connects BridgeTransport to the firmware model. cut() simulates an unplugged cable."""

    def __init__(self, fw: BridgeFirmwareModel):
        self.fw = fw
        self.connected = True
        self.corrupt_next = 0

    def write(self, data: bytes) -> int:
        if not self.connected:
            raise OSError("serial port disconnected")
        for line in data.split(b"\n"):
            if line:
                if self.corrupt_next:
                    self.corrupt_next -= 1
                    line = line[:-1] + (b"0" if line[-1:] != b"0" else b"1")
                self.fw.receive_line(line)
        return len(data)

    def read_available(self) -> bytes:
        if not self.connected:
            return b""
        out, self.fw.out = self.fw.out, b""
        return out

    def cut(self):
        self.connected = False

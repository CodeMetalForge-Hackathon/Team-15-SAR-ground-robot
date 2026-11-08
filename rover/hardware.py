"""RoverC-Pro hardware adapter. It refuses to exist until the hardware is verified.

The adapter turns BodyVelocity into the four documented INT8 motor registers and hands them to a
``Transport``. There is NO concrete transport to real hardware in this package yet, because the link
is unverified (see docs/rover/SAFETY_AND_LIMITATIONS.md section 1):

  - The RoverC-Pro is an M5StickC HAT. The StickC is the I2C master on that bus. Hanging the Pi off the
    same bus (through a Grove I2C port) would make two masters, and that is not supported.
  - The documented protocol has no watchdog. If the link drops, the STM32 may keep the last speed.
    So the only safe link is a StickC bridge firmware that zeroes the motors when commands stop,
    with that timeout measured and recorded in HardwareVerification.stop_on_link_loss_ms.

``RecordingTransport`` captures frames for tests and dry runs. It never touches hardware.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from rover.motion import BodyVelocity
from rover.protocol import (I2C_ADDRESS, REG_MOTOR, STOP_BLOCK, HardwareVerification,
                            body_to_motor_speeds, encode_motor_block)


class HardwareNotVerified(PermissionError):
    pass


class Transport(Protocol):
    physical: bool

    def write_block(self, address: int, register: int, data: bytes) -> None: ...


@dataclass
class RecordingTransport:
    """Records (address, register, data) frames. physical=False: it does not reach hardware."""
    physical: bool = False
    frames: list[tuple[int, int, bytes]] = field(default_factory=list)
    fail_next: int = 0

    def write_block(self, address: int, register: int, data: bytes) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise IOError("simulated transport failure")
        self.frames.append((address, register, bytes(data)))


class RoverCAdapter:
    """Driver for the RoverC-Pro through a verified transport. Writes only the motor registers 0x00-0x03."""

    name = "roverc-pro"

    def __init__(self, transport: Transport, verification: HardwareVerification):
        missing = verification.missing()
        if missing:
            raise HardwareNotVerified("RoverC-Pro hardware not verified; missing: " + ", ".join(missing))
        self.transport = transport
        self.verification = verification
        self.physical = bool(getattr(transport, "physical", True))
        self.last_speeds: tuple[int, int, int, int] = (0, 0, 0, 0)
        self.stop()  # default output is zero

    def apply(self, v: BodyVelocity) -> None:
        speeds = body_to_motor_speeds(v.vx, v.vy, v.wz, self.verification.wheel_mapping)
        self.transport.write_block(I2C_ADDRESS, REG_MOTOR[0], encode_motor_block(speeds))
        self.last_speeds = speeds

    def stop(self) -> None:
        self.transport.write_block(I2C_ADDRESS, REG_MOTOR[0], STOP_BLOCK)
        self.last_speeds = (0, 0, 0, 0)

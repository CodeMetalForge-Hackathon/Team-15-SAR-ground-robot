"""M5Stack RoverC-Pro (SKU K036-B) I2C protocol, as documented. Nothing here talks to hardware.

Sources (read 2026-11-07):
  https://docs.m5stack.com/en/protocol/K036-B/I2C
  https://docs.m5stack.com/en/hat/RoverC-Pro
  https://github.com/m5stack/M5-RoverC  src/M5_RoverC.cpp

DOCUMENTED (from the protocol page):
  - 7-bit address 0x38. Recommended bus speed 100-400 kHz. 8-bit register address and 8-bit data.
  - 0x00-0x03 Motor1..Motor4 speed: INT8, -127..127, R/W. 0 stops the motor.
  - 0x10/0x11 Servo1/2 angle (UINT8, 0-180). 0x20-0x23 servo pulse high/low bytes (500-2500 us).
NOT DOCUMENTED, so it must be measured on the bench before any physical motion:
  - Which register drives which physical wheel, and the sign that means "forward".
  - Whether the STM32 stops on its own when commands stop arriving. ASSUME IT DOES NOT:
    the last speed may be held indefinitely.
  - Battery voltage. There is no RoverC register for it.
  - Encoders, IMU or odometry. There are none on the RoverC-Pro register map.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

I2C_ADDRESS = 0x38
REG_MOTOR = (0x00, 0x01, 0x02, 0x03)
REG_SERVO_ANGLE = (0x10, 0x11)          # documented, never written by this package
REG_SERVO_PULSE = (0x20, 0x21, 0x22, 0x23)  # documented, never written by this package
MOTOR_MIN, MOTOR_MAX = -127, 127
LIBRARY_CLAMP = 100  # M5_RoverC.cpp clamps each wheel to +/-100, not the protocol's +/-127

WHEELS = ("FL", "FR", "RL", "RR")


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def library_mix(x: int, y: int, z: int) -> tuple[int, int, int, int]:
    """Port of M5_RoverC.cpp setSpeed(x, y, z): the values for registers 0x00..0x03.

    Reference: if z != 0, x and y are scaled by (100-|z|)/100. Then
    buf = [y+x-z, y-x+z, y-x-z, y+x+z], each clamped to +/-100.
    The library does not document which wheel each register drives.
    """
    if z != 0:
        x = int(x * (100 - abs(z)) / 100)
        y = int(y * (100 - abs(z)) / 100)
    raw = (y + x - z, y - x + z, y - x - z, y + x + z)
    return tuple(_clamp(v, -LIBRARY_CLAMP, LIBRARY_CLAMP) for v in raw)  # type: ignore[return-value]


def encode_motor_block(speeds: tuple[int, int, int, int]) -> bytes:
    """Four INT8 motor speeds as two's-complement bytes, for a block write starting at 0x00."""
    if len(speeds) != 4:
        raise ValueError("need exactly 4 motor speeds")
    out = bytearray()
    for s in speeds:
        if not isinstance(s, int) or not MOTOR_MIN <= s <= MOTOR_MAX:
            raise ValueError(f"motor speed {s!r} outside INT8 {MOTOR_MIN}..{MOTOR_MAX}")
        out.append(s & 0xFF)
    return bytes(out)


STOP_BLOCK = encode_motor_block((0, 0, 0, 0))


@dataclass(frozen=True)
class WheelMapping:
    """How body motion maps onto the library's (x, y, z) inputs. Every sign must be measured.

    Fill in only from a wheels-lifted bench test (docs/rover/BENCH_RUNBOOK.md, step 3).
    ``evidence`` names that test run: who did it, when, and what each wheel did.
    """
    forward_sign: Optional[int] = None      # library y = forward_sign * forward
    strafe_left_sign: Optional[int] = None  # library x = strafe_left_sign * left
    ccw_sign: Optional[int] = None          # library z = ccw_sign * counter-clockwise
    evidence: str = ""

    def missing(self) -> list[str]:
        out = [n for n in ("forward_sign", "strafe_left_sign", "ccw_sign")
               if getattr(self, n) not in (1, -1)]
        if not self.evidence.strip():
            out.append("evidence")
        return out

    @property
    def verified(self) -> bool:
        return not self.missing()


def body_to_motor_speeds(vx: float, vy: float, wz: float, mapping: WheelMapping) -> tuple[int, int, int, int]:
    """Normalised body velocity (-1..1; forward, left, counter-clockwise) to register values."""
    if not mapping.verified:
        raise PermissionError("wheel mapping not verified: " + ", ".join(mapping.missing()))
    for v in (vx, vy, wz):
        if not -1.0 <= v <= 1.0:
            raise ValueError(f"normalised velocity {v} outside -1..1")
    y = int(round(mapping.forward_sign * vx * LIBRARY_CLAMP))
    x = int(round(mapping.strafe_left_sign * vy * LIBRARY_CLAMP))
    z = int(round(mapping.ccw_sign * wz * LIBRARY_CLAMP))
    return library_mix(x, y, z)


@dataclass
class HardwareVerification:
    """What a person has to confirm before the adapter sends anything. Empty means unverified."""
    controller_model: str = ""      # e.g. "M5StickC Plus (confirmed from the board label)"
    controller_firmware: str = ""   # sketch name, commit and flash date
    roverc_revision: str = ""       # e.g. "K036-B, STM32F030 (confirmed by visual inspection)"
    link: str = ""                  # e.g. "Pi USB serial -> StickC bridge firmware"
    wiring_verified_by: str = ""
    power_verified_by: str = ""     # battery charged, voltage measured, what the threshold is
    stop_on_link_loss_ms: Optional[int] = None  # measured, firmware-side timeout
    wheel_mapping: WheelMapping = field(default_factory=WheelMapping)

    def missing(self) -> list[str]:
        out = [n for n in ("controller_model", "controller_firmware", "roverc_revision", "link",
                           "wiring_verified_by", "power_verified_by") if not getattr(self, n).strip()]
        if not self.stop_on_link_loss_ms or self.stop_on_link_loss_ms <= 0:
            out.append("stop_on_link_loss_ms")
        out += ["wheel_mapping." + m for m in self.wheel_mapping.missing()]
        return out

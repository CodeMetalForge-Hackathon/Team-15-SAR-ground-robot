"""Configuration and the electrical-interface safety gate.

The hardware driver refuses to touch GPIO unless the configuration describes a
wiring that cannot put more than 3.3 V on a Pi GPIO pin, and a named person has
recorded that they checked it (see ranging/WIRING.md). The defaults select the
simulated driver, so nothing here opens hardware by accident.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Optional

# Seeed wiki, Grove Ultrasonic Ranger spec table (V2.0): 2-350 cm, 15 deg, 3.2-5.2 V.
SPEC_MIN_RANGE_M = 0.02
SPEC_MAX_RANGE_M = 3.50
SPEC_BEAM_ANGLE_DEG = 15.0
SPEC_VCC_MIN_V = 3.2
SPEC_VCC_MAX_V = 5.2
SPEED_OF_SOUND_MPS = 343.0           # ~20 C dry air; Seeed code uses 29 us/cm (~345 m/s)
MIN_SAMPLE_INTERVAL_S = 0.06          # keep pings apart so a late echo is not read as the next one

# Header lines the driver must never claim on a Pi 5.
RESERVED_BCM = {
    0: "ID_SD (HAT EEPROM)",
    1: "ID_SC (HAT EEPROM)",
    2: "I2C1 SDA (reserved for the RoverC-Pro / other I2C)",
    3: "I2C1 SCL (reserved for the RoverC-Pro / other I2C)",
    14: "UART TXD",
    15: "UART RXD",
}
HEADER_BCM = set(range(0, 28))


class ConfigError(ValueError):
    pass


class ElectricalInterfaceError(ConfigError):
    """The described wiring could put an unsafe voltage on a Pi GPIO pin, or is unverified."""


@dataclass
class ElectricalConfig:
    sensor_vcc_v: Optional[float] = None       # rail the sensor is powered from: 3.3 or 5.0
    signal_level_shifter: Optional[str] = None  # None, or e.g. "BSS138-bidirectional"
    series_resistor_ohm: Optional[float] = None  # recommended 1000 on SIG
    gpio_bcm: Optional[int] = None
    header_vcc_pin: Optional[int] = None       # physical header pin used for VCC
    wiring_verified_by: Optional[str] = None   # name of the hardware teammate
    wiring_verified_at: Optional[str] = None   # ISO date/time of the check
    sensor_revision: Optional[str] = None      # "V2.0" etc., as read off the PCB


@dataclass
class SensorConfig:
    driver: str = "simulated"                  # "simulated" | "gpiod"
    sensor_id: str = "grove-us-front"
    sensor_mount: str = "FRONT"
    source: str = "SIMULATED"                  # RASPBERRY_PI_5 for the hardware driver
    gpiochip: str = "/dev/gpiochip0"
    sample_interval_s: float = 0.10
    min_range_m: float = 0.03                  # a little above the 2 cm spec floor
    max_range_m: float = 3.00                  # a little below the 3.5 m spec ceiling
    echo_start_timeout_s: float = 0.002        # Seeed rejects echo starts later than ~530 us
    speed_of_sound_mps: float = SPEED_OF_SOUND_MPS
    trigger_pulse_us: float = 15.0             # spec: "more than 10 us"
    electrical: ElectricalConfig = field(default_factory=ElectricalConfig)

    @property
    def echo_end_timeout_s(self) -> float:
        # Round-trip time to the rated max range, plus margin.
        return 2 * SPEC_MAX_RANGE_M / self.speed_of_sound_mps * 1.5

    def validate(self) -> "SensorConfig":
        if self.driver not in ("simulated", "gpiod"):
            raise ConfigError(f"unknown driver {self.driver!r}")
        if not (SPEC_MIN_RANGE_M <= self.min_range_m < self.max_range_m <= SPEC_MAX_RANGE_M):
            raise ConfigError(f"range [{self.min_range_m}, {self.max_range_m}] m outside sensor spec "
                              f"[{SPEC_MIN_RANGE_M}, {SPEC_MAX_RANGE_M}] m")
        if not (math.isfinite(self.sample_interval_s) and self.sample_interval_s >= MIN_SAMPLE_INTERVAL_S):
            raise ConfigError(f"sample_interval_s must be >= {MIN_SAMPLE_INTERVAL_S}")
        if not (10.0 < self.trigger_pulse_us < 100.0):
            raise ConfigError("trigger_pulse_us must be > 10 us (spec) and < 100 us")
        if not (300.0 <= self.speed_of_sound_mps <= 360.0):
            raise ConfigError("speed_of_sound_mps implausible")
        if self.driver == "gpiod":
            check_electrical(self.electrical)
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SensorConfig":
        d = dict(d)
        elec = ElectricalConfig(**(d.pop("electrical", None) or {}))
        d.pop("obstacle", None)   # separate section, read by ObstacleConfig (see cli._load)
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"unknown config keys: {sorted(unknown)}")
        return cls(electrical=elec, **d)

    @classmethod
    def load(cls, path: str) -> "SensorConfig":
        with open(path) as f:
            return cls.from_dict(json.load(f)).validate()


# Physical header pins: 1/17 = 3V3, 2/4 = 5V.
_3V3_PINS = {1, 17}
_5V_PINS = {2, 4}


def check_electrical(e: ElectricalConfig) -> None:
    """Raise ElectricalInterfaceError unless SIG can never exceed 3.3 V and a person verified it."""
    problems = []
    if e.gpio_bcm is None or e.gpio_bcm not in HEADER_BCM:
        problems.append(f"gpio_bcm {e.gpio_bcm!r} is not a 40-pin header GPIO (0-27)")
    elif e.gpio_bcm in RESERVED_BCM:
        problems.append(f"GPIO{e.gpio_bcm} is reserved: {RESERVED_BCM[e.gpio_bcm]}")
    if e.sensor_vcc_v is None:
        problems.append("sensor_vcc_v not recorded")
    elif not (SPEC_VCC_MIN_V <= e.sensor_vcc_v <= SPEC_VCC_MAX_V):
        problems.append(f"sensor_vcc_v {e.sensor_vcc_v} V outside spec {SPEC_VCC_MIN_V}-{SPEC_VCC_MAX_V} V")
    elif e.sensor_vcc_v > 3.4 and not e.signal_level_shifter:
        # The echo output level is not documented; at 5 V it may swing to 5 V.
        problems.append(f"sensor powered at {e.sensor_vcc_v} V with no level shifter on SIG: "
                        "5 V could reach an unprotected Pi GPIO")
    if e.header_vcc_pin is not None and e.sensor_vcc_v is not None:
        if e.header_vcc_pin in _5V_PINS and e.sensor_vcc_v < 4.5:
            problems.append(f"header pin {e.header_vcc_pin} is 5 V but sensor_vcc_v says {e.sensor_vcc_v}")
        if e.header_vcc_pin in _3V3_PINS and e.sensor_vcc_v > 3.4:
            problems.append(f"header pin {e.header_vcc_pin} is 3.3 V but sensor_vcc_v says {e.sensor_vcc_v}")
        if e.header_vcc_pin not in _3V3_PINS | _5V_PINS:
            problems.append(f"header pin {e.header_vcc_pin} is not a power pin")
    if e.sensor_revision is None or not str(e.sensor_revision).upper().startswith("V2"):
        if e.sensor_vcc_v is not None and e.sensor_vcc_v < 4.5:
            problems.append(f"sensor_revision {e.sensor_revision!r}: only V2.0 is documented as 3.3 V compatible")
    if not e.wiring_verified_by or not e.wiring_verified_at:
        problems.append("wiring not verified: set wiring_verified_by and wiring_verified_at after the "
                        "WIRING.md checklist (meter reading on SIG) is done")
    if problems:
        raise ElectricalInterfaceError("refusing GPIO access: " + "; ".join(problems))

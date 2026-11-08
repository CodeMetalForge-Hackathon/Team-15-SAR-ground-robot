"""LiDAR configuration, mount geometry and the hardware gate.

The defaults select SIMULATED mode. The hardware driver refuses to open a serial
port unless every item of LIDAR_C1_HARDWARE_CHECKLIST.md is recorded, by name, in
the config, and a second person repeated the checks. This mirrors
ranging/config.py:check_electrical. Nothing in this module opens a device.

Frames:
  * sensor frame: the RPLIDAR's own angle, 0 at the sensor's mark, increasing CLOCKWISE
    seen from above (Slamtec protocol). It is NOT the robot's forward direction.
  * robot frame: 0 deg = robot forward axis, increasing COUNTER-CLOCKWISE (left positive),
    the same convention as rover/sensors.py headings and bearings.
  * There is no world frame. A 2D scan gives no position, no GPS and no heading.

    robot_bearing = norm(sign * sensor_angle + forward_offset_deg)
    sign = -1 when the sensor turns clockwise (default)

``forward_offset_deg`` must be MEASURED on the robot (alignment test, checklist item 5).
Until ``alignment_verified_by`` is recorded, every sector reads UNKNOWN.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Optional

MODEL_NAME = "RPLIDAR C1"
MODEL_LABEL = "C1M1-R2"          # from the unit's label; GET_INFO must be checked at stage C
SENSOR_TYPE = "RPLIDAR_C1"

# Slamtec C1 datasheet values, verify on our unit (stage C). Not measured by us.
SPEC_MIN_RANGE_M = 0.05
SPEC_MAX_RANGE_M = 12.0          # white target; much less on dark or angled surfaces
SPEC_TYPICAL_SCAN_HZ = 10.0
SPEC_BAUD = 460800

DEFAULT_SIM_PORT = 8775          # replay server; 8765 = ranging, 8770 = robot API, 8792 = camera test


class LidarConfigError(ValueError):
    pass


class HardwareGateError(LidarConfigError):
    """The checklist is incomplete: the serial port must not be opened."""


@dataclass
class MountConfig:
    forward_offset_deg: Optional[float] = None    # robot bearing of the sensor's 0 mark; None = not measured
    sensor_rotation: str = "CW"                   # "CW" (Slamtec) or "CCW" if mounted upside down
    alignment_verified_by: Optional[str] = None
    alignment_verified_at: Optional[str] = None
    alignment_method: Optional[str] = None        # e.g. "box at 1.00 m on robot forward axis, peak at 181.3 deg"
    height_above_floor_m: Optional[float] = None
    # Sensor-frame angular windows hidden by the robot's own body (camera mast, gripper).
    self_occlusion_deg: list = field(default_factory=list)   # [[start, end], ...] in SENSOR degrees
    # Orientation monitor: a fixed robot-body feature (e.g. the camera mast) whose ROBOT-frame bearing and
    # range were measured with a tape/protractor INDEPENDENTLY of the LiDAR. Every scan must show a return
    # where the configured mount predicts it, so a wrong offset, a CW/CCW sign error or a knocked sensor
    # is detected (all sectors UNKNOWN). Not configured = no motion (display only).
    fiducial_robot_bearing_deg: Optional[float] = None
    fiducial_range_m: Optional[float] = None
    fiducial_tol_deg: float = 4.0
    fiducial_tol_m: float = 0.03
    fiducial_measured_by: Optional[str] = None
    # Self-occlusion windows hide returns, so they are measured and signed off like the footprint.
    # Occluded rays are always UNCOVERED (never evidence of free space).
    occlusion_verified_by: Optional[str] = None
    occlusion_verified_at: Optional[str] = None

    @property
    def sign(self) -> int:
        return -1 if self.sensor_rotation == "CW" else 1

    @property
    def aligned(self) -> bool:
        return (self.forward_offset_deg is not None and math.isfinite(self.forward_offset_deg)
                and bool(str(self.alignment_verified_by or "").strip())
                and bool(str(self.alignment_verified_at or "").strip()))

    @property
    def occlusion_ok(self) -> bool:
        """No windows, or windows signed off by a named person."""
        return (not self.self_occlusion_deg) or (bool(str(self.occlusion_verified_by or "").strip())
                                                 and bool(str(self.occlusion_verified_at or "").strip()))

    @property
    def fiducial_configured(self) -> bool:
        return (self.fiducial_robot_bearing_deg is not None and self.fiducial_range_m is not None
                and bool(str(self.fiducial_measured_by or "").strip()))

    def sensor_angle(self, robot_bearing_deg: float) -> Optional[float]:
        """Inverse of robot_bearing (sign is +-1, so it is its own inverse)."""
        if self.forward_offset_deg is None:
            return None
        return (self.sign * (robot_bearing_deg - self.forward_offset_deg)) % 360.0

    def robot_bearing(self, sensor_angle_deg: float) -> Optional[float]:
        if self.forward_offset_deg is None:
            return None
        return (self.sign * sensor_angle_deg + self.forward_offset_deg) % 360.0

    def occluded(self, sensor_angle_deg: float) -> bool:
        a = sensor_angle_deg % 360.0
        for lo, hi in self.self_occlusion_deg:
            lo, hi = lo % 360.0, hi % 360.0
            if (lo <= a <= hi) if lo <= hi else (a >= lo or a <= hi):
                return True
        return False

    def validate(self) -> "MountConfig":
        if self.sensor_rotation not in ("CW", "CCW"):
            raise LidarConfigError("sensor_rotation must be CW or CCW")
        if self.forward_offset_deg is not None and not math.isfinite(self.forward_offset_deg):
            raise LidarConfigError("forward_offset_deg must be finite")
        for w in self.self_occlusion_deg:
            if not (isinstance(w, (list, tuple)) and len(w) == 2):
                raise LidarConfigError("self_occlusion_deg entries must be [start, end]")
        if self.fiducial_range_m is not None and not (0.0 < self.fiducial_range_m < 1.0):
            raise LidarConfigError("fiducial_range_m must be a robot-body distance in (0, 1) m")
        if not (0 < self.fiducial_tol_deg <= 10 and 0 < self.fiducial_tol_m <= 0.1):
            raise LidarConfigError("fiducial tolerances out of range")
        return self


@dataclass
class FootprintConfig:
    """Robot footprint for forward-corridor clearance. Names mirror rover/navigator.py NavConfig.

    Every dimension is MEASURED on the real chassis (gripper and wheels included) by a named person,
    independently of the LiDAR. ``robot_width_m`` has no default: unknown dimensions = UNKNOWN corridor.
    """
    robot_width_m: Optional[float] = None       # overall width incl. wheels and gripper (NavConfig.robot_width_m)
    width_margin_m: float = 0.05                # per side (NavConfig.width_margin_m)
    lookahead_m: float = 1.0                    # corridor length ahead of the bumper (NavConfig.lookahead_m)
    sensor_to_front_m: Optional[float] = None   # sensor centre -> front-most point of the robot, along forward
    sensor_lateral_offset_m: float = 0.0        # sensor left (+) of the robot centreline
    footprint_verified_by: Optional[str] = None
    footprint_verified_at: Optional[str] = None
    # Largest required clearance the navigator will ask for (rover owner). lookahead_m must cover it,
    # otherwise a verified-clear corridor would read as an obstacle at the horizon (false BLOCKED -> reroute).
    rover_max_required_clear_m: Optional[float] = None

    @property
    def known(self) -> bool:
        return (isinstance(self.robot_width_m, (int, float)) and self.robot_width_m > 0
                and isinstance(self.sensor_to_front_m, (int, float)) and self.sensor_to_front_m >= 0
                and bool(str(self.footprint_verified_by or "").strip())
                and bool(str(self.footprint_verified_at or "").strip()))

    @property
    def half_width_m(self) -> Optional[float]:
        return None if self.robot_width_m is None else self.robot_width_m / 2 + self.width_margin_m

    def validate(self) -> "FootprintConfig":
        if self.robot_width_m is not None and not (0.05 <= self.robot_width_m <= 1.0):
            raise LidarConfigError("robot_width_m implausible (0.05-1.0 m)")
        if not (0.0 <= self.width_margin_m <= 0.5):
            raise LidarConfigError("width_margin_m must be 0-0.5 m")
        if not (0.1 <= self.lookahead_m <= 3.0):
            raise LidarConfigError("lookahead_m must be 0.1-3.0 m")
        if self.sensor_to_front_m is not None and not (0.0 <= self.sensor_to_front_m <= 1.0):
            raise LidarConfigError("sensor_to_front_m must be 0-1.0 m")
        if not (-0.5 <= self.sensor_lateral_offset_m <= 0.5):
            raise LidarConfigError("sensor_lateral_offset_m must be within +-0.5 m")
        if self.rover_max_required_clear_m is not None and self.lookahead_m < self.rover_max_required_clear_m:
            raise LidarConfigError(f"lookahead_m {self.lookahead_m} < rover_max_required_clear_m "
                                   f"{self.rover_max_required_clear_m}: a clear corridor would read BLOCKED")
        return self


@dataclass
class ProcessingConfig:
    min_quality: int = 10            # PLACEHOLDER: calibrate at stage C
    min_range_m: float = 0.08        # a little above the 0.05 m spec floor (inside it = invalid)
    max_range_m: float = 8.0         # below the 12 m white-target spec: dark targets fail sooner
    bin_deg: float = 1.0             # coverage bins
    min_sector_coverage: float = 0.60  # fraction of a sector's bins with a valid return, or UNKNOWN
    min_scan_coverage: float = 0.50  # whole-scan fraction for "complete"
    min_points: int = 200            # C1 ~5 kHz / 10 Hz ~ 500 points; far fewer = partial
    blocked_m: float = 0.35          # PLACEHOLDER (ranging stopping distance + margin, not measured)
    caution_m: float = 0.75
    motion_max_age_s: float = 0.20   # rover/navigator.py + motion.py sensor_max_age_s
    display_max_age_s: float = 0.50  # range snapshot stale_after_s
    scan_hz_min: float = 7.0         # PLACEHOLDER window around the 10 Hz typical
    scan_hz_max: float = 13.0
    clear_confirm_scans: int = 2     # leaving BLOCKED/UNKNOWN needs this many consecutive CLEAR scans
    # Clear-space EVIDENCE is stricter than obstacle evidence: a weak return still counts as an obstacle,
    # but only a return of at least this quality can prove free space (mirror/specular phantoms are weak).
    clearance_min_quality: int = 20  # PLACEHOLDER: calibrate at stage C
    corridor_min_coverage: float = 0.90  # fraction of corridor rays with positive free-space evidence
    corridor_max_gap_deg: float = 2.0    # far zone: a contiguous unobserved span wider than this = UNKNOWN
    stopping_distance_m: float = 0.18    # PLACEHOLDER (ranging ObstacleConfig defaults: 0.3 m/s, 0.3 s, 0.5 m/s^2)
    # Near zone = blocked_m + stopping_distance_m ahead of the bumper: 100 % of its rays need evidence.
    max_future_skew_s: float = 0.05

    def validate(self) -> "ProcessingConfig":
        if not (0 <= self.min_quality <= 63):
            raise LidarConfigError("min_quality is 0-63")
        if not (SPEC_MIN_RANGE_M <= self.min_range_m < self.max_range_m <= SPEC_MAX_RANGE_M):
            raise LidarConfigError(f"range [{self.min_range_m}, {self.max_range_m}] outside spec "
                                   f"[{SPEC_MIN_RANGE_M}, {SPEC_MAX_RANGE_M}]")
        if not (0 < self.blocked_m < self.caution_m <= self.max_range_m):
            raise LidarConfigError("need 0 < blocked_m < caution_m <= max_range_m")
        if not (0 < self.bin_deg <= 15 and 360 % self.bin_deg == 0):
            raise LidarConfigError("bin_deg must divide 360 and be <= 15")
        if not (0 < self.min_sector_coverage <= 1 and 0 < self.min_scan_coverage <= 1):
            raise LidarConfigError("coverage thresholds are fractions in (0, 1]")
        if not (0 < self.motion_max_age_s <= self.display_max_age_s):
            raise LidarConfigError("need 0 < motion_max_age_s <= display_max_age_s")
        if not (0 < self.scan_hz_min < self.scan_hz_max):
            raise LidarConfigError("bad scan frequency window")
        if self.clear_confirm_scans < 1:
            raise LidarConfigError("clear_confirm_scans >= 1")
        if not (self.min_quality <= self.clearance_min_quality <= 63):
            raise LidarConfigError("need min_quality <= clearance_min_quality <= 63")
        if not (0.0 <= self.stopping_distance_m <= 1.0):
            raise LidarConfigError("stopping_distance_m must be 0-1 m")
        if not (0.5 <= self.corridor_min_coverage <= 1.0 and 0 < self.corridor_max_gap_deg <= 10):
            raise LidarConfigError("corridor coverage in [0.5, 1], max gap in (0, 10] deg")
        return self


@dataclass
class HardwareChecklist:
    """LIDAR_C1_HARDWARE_CHECKLIST.md items 1-10. All must be recorded before the port opens."""
    model_label_read: Optional[str] = None             # 1. must equal C1M1-R2
    model_evidence_ref: Optional[str] = None           #    photo of the label (outside Git)
    adapter_identified: Optional[str] = None           # 2. adapter make/model, e.g. Slamtec "C1 USB adapter"
    adapter_pinout_verified: Optional[bool] = None     #    connector pinout matched against the C1 datasheet
    adapter_usb_vid_pid: Optional[str] = None          #    as enumerated, e.g. "10c4:ea60"
    supply_voltage_measured_v: Optional[float] = None  # 3. at the LiDAR connector, 4.9-5.2 V
    startup_current_measured_a: Optional[float] = None  #   peak at spin-up, measured
    pi_supply_headroom_ok: Optional[bool] = None       # 4. with Hailo + camera + Wi-Fi running, no undervoltage
    pi_throttled_after_test: Optional[str] = None      #    `vcgencmd get_throttled` result, must be 0x0
    mount_scan_plane_clear: Optional[bool] = None      # 5. scan plane unobstructed except recorded occlusions
    cable_strain_relief_ok: Optional[bool] = None      # 6. clear of wheels and gripper
    usb_enumeration_ok: Optional[bool] = None          # 7. stable /dev/serial/by-id path, user in dialout
    device_path_by_id: Optional[str] = None            #    the explicit device path that will be opened
    independent_wiring_inspection_by: Optional[str] = None  # 8. a second person
    emergency_power_cutoff_ok: Optional[bool] = None   # 9. physical switch removes LiDAR (and rover) power
    stationary_test_location: Optional[str] = None     # 10. known safe location, rover wheels off the floor
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None


def check_hardware_gate(c: HardwareChecklist) -> None:
    """Raise HardwareGateError unless every checklist item is recorded and plausible."""
    p = []
    if str(c.model_label_read or "").strip().upper() != MODEL_LABEL:
        p.append(f"model_label_read {c.model_label_read!r} != {MODEL_LABEL}")
    if not c.model_evidence_ref:
        p.append("model_evidence_ref (label photo) not recorded")
    if not c.adapter_identified:
        p.append("adapter_identified not recorded (do not assume the green board is compatible)")
    if c.adapter_pinout_verified is not True:
        p.append("adapter_pinout_verified not confirmed")
    if not c.adapter_usb_vid_pid:
        p.append("adapter_usb_vid_pid not recorded")
    v = c.supply_voltage_measured_v
    if not (isinstance(v, (int, float)) and 4.9 <= v <= 5.25):
        p.append(f"supply_voltage_measured_v {v!r} not recorded or outside 4.9-5.25 V")
    a = c.startup_current_measured_a
    if not (isinstance(a, (int, float)) and 0 < a <= 1.5):
        p.append(f"startup_current_measured_a {a!r} not recorded or implausible")
    if c.pi_supply_headroom_ok is not True:
        p.append("pi_supply_headroom_ok not confirmed (Pi power-dropout history)")
    if str(c.pi_throttled_after_test or "").strip().lower() not in ("0x0", "throttled=0x0"):
        p.append(f"pi_throttled_after_test {c.pi_throttled_after_test!r} must be 0x0")
    for name in ("mount_scan_plane_clear", "cable_strain_relief_ok", "usb_enumeration_ok",
                 "emergency_power_cutoff_ok"):
        if getattr(c, name) is not True:
            p.append(f"{name} not confirmed")
    dp = str(c.device_path_by_id or "")
    if not dp.startswith("/dev/serial/by-id/"):
        p.append(f"device_path_by_id {c.device_path_by_id!r} must be an explicit /dev/serial/by-id/ path")
    if not c.stationary_test_location:
        p.append("stationary_test_location not recorded")
    if not c.verified_by or not c.verified_at:
        p.append("verified_by / verified_at not recorded")
    ind = str(c.independent_wiring_inspection_by or "").strip().lower()
    if not ind:
        p.append("independent_wiring_inspection_by not recorded")
    elif ind == str(c.verified_by or "").strip().lower():
        p.append("independent inspector must be a different person from verified_by")
    if p:
        raise HardwareGateError("refusing to open the LiDAR serial port: " + "; ".join(p))


@dataclass
class LidarConfig:
    mode: str = "simulated"                 # "simulated" | "hardware"
    sensor_id: str = "rplidar-c1-top"
    frame_id: str = "lidar_c1_sensor"
    device: Optional[str] = None            # explicit path; never auto-selected
    baudrate: int = SPEC_BAUD
    read_timeout_s: float = 0.25
    scan_timeout_s: float = 0.6             # no completed revolution in this time = DEVICE_TIMEOUT
    reconnect_backoff_s: tuple = (0.5, 1.0, 2.0, 4.0)
    expected_model_id: Optional[int] = None  # GET_INFO model byte, recorded at stage C; None = refuse hardware
    mount: MountConfig = field(default_factory=MountConfig)
    footprint: FootprintConfig = field(default_factory=FootprintConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    checklist: HardwareChecklist = field(default_factory=HardwareChecklist)

    def validate(self) -> "LidarConfig":
        if self.mode not in ("simulated", "hardware"):
            raise LidarConfigError(f"unknown mode {self.mode!r}")
        if self.baudrate <= 0 or self.read_timeout_s <= 0 or self.scan_timeout_s <= 0:
            raise LidarConfigError("baudrate and timeouts must be positive")
        self.mount.validate()
        self.footprint.validate()
        self.processing.validate()
        if self.mode == "hardware":
            check_hardware_gate(self.checklist)
            if not self.device or self.device != self.checklist.device_path_by_id:
                raise HardwareGateError("device must be given explicitly and equal checklist.device_path_by_id")
            if self.expected_model_id is None:
                raise HardwareGateError("expected_model_id not recorded (read GET_INFO at stage C)")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LidarConfig":
        d = dict(d)
        sub = {"mount": MountConfig, "footprint": FootprintConfig, "processing": ProcessingConfig,
               "checklist": HardwareChecklist}
        kw = {}
        for k, typ in sub.items():
            sd = d.pop(k, None) or {}
            unknown = set(sd) - set(typ.__dataclass_fields__)
            if unknown:
                raise LidarConfigError(f"unknown {k} keys: {sorted(unknown)}")
            kw[k] = typ(**sd)
        d.pop("_comment", None)
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise LidarConfigError(f"unknown config keys: {sorted(unknown)}")
        if "reconnect_backoff_s" in d:
            d["reconnect_backoff_s"] = tuple(d["reconnect_backoff_s"])
        return cls(**d, **kw)

    @classmethod
    def load(cls, path: str) -> "LidarConfig":
        with open(path) as f:
            return cls.from_dict(json.load(f)).validate()

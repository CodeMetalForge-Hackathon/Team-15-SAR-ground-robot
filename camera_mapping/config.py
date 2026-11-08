"""Camera intrinsics, mount geometry and calibration status.

Intrinsics default to NOMINAL values derived from the IMX708 datasheet and the
sensor crop the Pi actually used (measured on the Pi, 2026-11-08 06:08 ET):

  * picamera2 video configuration main=1280x720 selects the sensor mode
    1536x864 (2x2 binned), ScalerCrop (784, 456, 3072, 1728): a centre crop of
    3072x1728 sensor pixels, NOT the full 4608x2592 array.
  * IMX708 (Camera Module 3, standard lens): pixel 1.4 um, focal length 4.74 mm.
  * Effective pixel pitch at 1280 px wide = 1.4 um * 3072 / 1280 = 3.36 um
    -> fx = fy = 4.74 mm / 3.36 um = 1410.7 px, HFOV 48.8 deg, VFOV 28.6 deg.

These are datasheet numbers, not a checkerboard calibration; distortion is
assumed zero (the module-3 standard lens has low distortion, unmeasured here).
Mount height and pitch are UNMEASURED until a teammate records them; without
them the ground-plane method reports UNKNOWN.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

NOMINAL_DATASHEET = "NOMINAL_DATASHEET"
CHECKERBOARD = "CHECKERBOARD"

UNCALIBRATED = "UNCALIBRATED"
CALIBRATED = "CALIBRATED"          # a tape-measured calibration run passed its gate
CALIBRATION_FAILED = "CALIBRATION_FAILED"

IMX708_PIXEL_UM = 1.4
IMX708_FOCAL_MM = 4.74
IMX708_FULL_W = 4608


@dataclass
class CameraModel:
    width: int = 1280
    height: int = 720
    fx: float = 0.0
    fy: float = 0.0
    cx: float = 0.0
    cy: float = 0.0
    dist: list = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0, 0.0])
    source: str = NOMINAL_DATASHEET
    note: str = ""

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image size must be positive")
        if not self.fx:
            self.fx = nominal_imx708_fx(self.width)
        if not self.fy:
            self.fy = self.fx
        if not self.cx:
            self.cx = (self.width - 1) / 2.0
        if not self.cy:
            self.cy = (self.height - 1) / 2.0
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("focal length must be positive")

    @property
    def hfov_deg(self) -> float:
        return math.degrees(2 * math.atan(self.width / (2 * self.fx)))

    @property
    def vfov_deg(self) -> float:
        return math.degrees(2 * math.atan(self.height / (2 * self.fy)))

    def scaled(self, width: int, height: int) -> "CameraModel":
        """Same camera at another output resolution (same crop, same aspect)."""
        sx, sy = width / self.width, height / self.height
        return CameraModel(width, height, self.fx * sx, self.fy * sy,
                           (self.cx + 0.5) * sx - 0.5, (self.cy + 0.5) * sy - 0.5,
                           list(self.dist), self.source, self.note)


def nominal_imx708_fx(width: int, crop_w_px: int = 3072) -> float:
    pitch_mm = IMX708_PIXEL_UM * 1e-3 * crop_w_px / width
    return IMX708_FOCAL_MM / pitch_mm


@dataclass
class MountGeometry:
    """Camera pose on the robot. ``measured`` must be True with a recorded
    ``measured_by`` before the ground-plane method is used."""
    height_m: Optional[float] = None       # lens centre above the floor
    pitch_deg: Optional[float] = None      # positive = tilted DOWN
    height_sigma_m: float = 0.01
    pitch_sigma_deg: float = 1.5
    setback_m: float = 0.0                 # lens behind the robot's front edge
    lateral_offset_m: float = 0.0          # lens left (+) of the robot centreline
    measured: bool = False
    measured_by: Optional[str] = None
    measured_at: Optional[str] = None
    pitch_source: str = "UNMEASURED"        # INCLINOMETER | FITTED_FROM_TAPE | UNMEASURED

    @property
    def usable(self) -> bool:
        return (self.measured and self.height_m is not None and self.pitch_deg is not None
                and self.height_m > 0 and -30.0 < self.pitch_deg < 80.0)


@dataclass
class PerceptionConfig:
    camera: CameraModel = field(default_factory=CameraModel)
    mount: MountGeometry = field(default_factory=MountGeometry)
    calibration_status: str = UNCALIBRATED
    calibration_ref: Optional[str] = None
    robot_width_m: float = 0.20            # PLACEHOLDER until the chassis is measured
    robot_width_measured: bool = False
    width_margin_m: float = 0.05
    lookahead_m: float = 1.5
    stop_distance_m: float = 0.6
    max_range_m: float = 4.0
    depth_model_validated: bool = False     # True only after the calibration report says so

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "PerceptionConfig":
        d = dict(d or {})
        cam = CameraModel(**(d.pop("camera", None) or {}))
        mount = MountGeometry(**(d.pop("mount", None) or {}))
        known = {k: v for k, v in d.items() if k in PerceptionConfig.__dataclass_fields__}
        return PerceptionConfig(camera=cam, mount=mount, **known)


def load_config(path: Optional[str]) -> PerceptionConfig:
    if not path:
        return PerceptionConfig()
    return PerceptionConfig.from_json(json.loads(Path(path).expanduser().read_text()))


def save_config(cfg: PerceptionConfig, path: str) -> None:
    Path(path).expanduser().write_text(json.dumps(cfg.to_json(), indent=2) + "\n")

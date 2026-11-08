"""Rolling filter and forward-obstacle assessment (CLEAR / CAUTION / BLOCKED / UNKNOWN).

Safety rules, in order:
  * The latest reading invalid, or older than ``stale_after_s``  -> UNKNOWN.
  * Too few valid readings in the window                         -> UNKNOWN.
  * UNKNOWN never permits autonomous forward motion.
  * Getting closer is believed immediately; getting farther is not.
    The decision range is min(latest valid, rolling median). A single short
    reading can cause a (safe) stop. A single long reading cannot clear one.
  * Leaving BLOCKED/CAUTION/UNKNOWN for a less restrictive state needs the range
    to exceed the threshold plus hysteresis for ``clear_confirm_samples``
    consecutive readings.

All thresholds are conservative placeholders. The team must calibrate them
(README "Calibration").
"""
from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Deque, Optional

from .config import SPEC_BEAM_ANGLE_DEG
from .reading import RangeReading

SCHEMA = "team15.obstacle_assessment/1"


class ObstacleStatus(str, Enum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


_RANK = {ObstacleStatus.CLEAR: 0, ObstacleStatus.CAUTION: 1, ObstacleStatus.BLOCKED: 2, ObstacleStatus.UNKNOWN: 3}
FORWARD_ALLOWED = {ObstacleStatus.CLEAR: True, ObstacleStatus.CAUTION: True,
                   ObstacleStatus.BLOCKED: False, ObstacleStatus.UNKNOWN: False}


@dataclass
class ObstacleConfig:
    # Robot / mount geometry (measure on the real robot).
    mount_height_m: float = 0.08          # sensor axis above the floor
    mount_pitch_deg: float = 0.0          # + = tilted up
    beam_angle_deg: float = SPEC_BEAM_ANGLE_DEG  # full cone angle (Seeed: 15 deg)
    sensor_setback_m: float = 0.0         # sensor face behind the robot's front bumper (+)
    # Motion assumptions for stopping distance (PLACEHOLDERS, RoverC-Pro not yet measured).
    max_speed_mps: float = 0.30
    decel_mps2: float = 0.5
    control_latency_s: float = 0.20       # nav loop + I2C motor command latency
    safety_margin_m: float = 0.10
    # Classifier.
    caution_extra_m: float = 0.40         # CAUTION band above the BLOCKED threshold
    hysteresis_m: float = 0.05
    clear_confirm_samples: int = 3
    window_size: int = 5
    min_valid_in_window: int = 3
    stale_after_s: float = 0.5
    sample_interval_s: float = 0.10       # used only to add sensing latency to the stopping distance

    def stopping_distance_m(self) -> float:
        v = self.max_speed_mps
        # Worst case: obstacle appears just after a ping; median needs about half a window to react,
        # but the min() rule reacts on the next ping, so one interval of sensing latency.
        t = self.control_latency_s + self.sample_interval_s
        return v * t + v * v / (2 * self.decel_mps2)

    def blocked_m(self) -> float:
        """Range (from sensor face) at or below which forward motion is BLOCKED."""
        return self.stopping_distance_m() + self.safety_margin_m + self.sensor_setback_m

    def caution_m(self) -> float:
        return self.blocked_m() + self.caution_extra_m

    def validate(self) -> "ObstacleConfig":
        if self.window_size < 1 or not (1 <= self.min_valid_in_window <= self.window_size):
            raise ValueError("need 1 <= min_valid_in_window <= window_size")
        if self.clear_confirm_samples < 1 or self.hysteresis_m < 0:
            raise ValueError("clear_confirm_samples >= 1 and hysteresis_m >= 0")
        if self.stale_after_s <= 0 or self.max_speed_mps < 0 or self.decel_mps2 <= 0:
            raise ValueError("stale_after_s > 0, max_speed_mps >= 0, decel_mps2 > 0")
        return self

    def geometry(self) -> dict:
        half = math.radians(self.beam_angle_deg / 2)
        down = half - math.radians(self.mount_pitch_deg)   # angle of the lower beam edge below horizontal
        floor_hit = (self.mount_height_m / math.tan(down)) if down > 0 else None
        return {
            "beam_angle_deg": self.beam_angle_deg,
            "mount_height_m": self.mount_height_m,
            "mount_pitch_deg": self.mount_pitch_deg,
            # Beyond this range the lower beam edge reaches the floor: floor echoes are possible,
            # and any reading near it may be the floor rather than an obstacle.
            "floor_intercept_m": None if floor_hit is None else round(floor_hit, 3),
            "beam_radius_at_blocked_m": round(self.blocked_m() * math.tan(half), 3),
            "stopping_distance_m": round(self.stopping_distance_m(), 3),
            "blocked_threshold_m": round(self.blocked_m(), 3),
            "caution_threshold_m": round(self.caution_m(), 3),
            "blind_spots": [
                "obstacles lower than the beam's lower edge at that range (see floor_intercept_m)",
                "objects narrower than the beam that reflect weakly (poles, chair legs, mesh)",
                "soft or angled surfaces that do not return an echo (reported NO_ECHO -> UNKNOWN)",
                f"anything outside the {self.beam_angle_deg:g} deg forward cone (no side or rear coverage)",
            ],
        }


@dataclass
class Assessment:
    status: ObstacleStatus
    forward_motion_allowed: bool
    nearest_range_m: Optional[float]      # decision range in the beam, None if not trustworthy
    median_range_m: Optional[float]
    latest: Optional[dict]
    reason: str
    age_s: Optional[float]
    stale: bool
    valid_in_window: int
    window_size: int
    thresholds: dict

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["schema"] = SCHEMA
        d["range_semantics"] = ("nearest echo in the forward ultrasonic beam; NOT a distance to a person "
                                "or to any camera detection")
        return d


class ObstacleAssessor:
    def __init__(self, cfg: Optional[ObstacleConfig] = None):
        self.cfg = (cfg or ObstacleConfig()).validate()
        self._win: Deque[RangeReading] = deque(maxlen=self.cfg.window_size)
        self._status = ObstacleStatus.UNKNOWN
        self._relax_streak = 0
        self._latest: Optional[RangeReading] = None

    @property
    def status(self) -> ObstacleStatus:
        return self._status

    def update(self, r: RangeReading) -> Assessment:
        self._latest = r
        self._win.append(r)
        return self.assess(now_mono_ns=r.mono_ns)

    def _raw_status(self, rng: float, relaxing_from: ObstacleStatus) -> ObstacleStatus:
        b, c, h = self.cfg.blocked_m(), self.cfg.caution_m(), self.cfg.hysteresis_m
        # Hysteresis: to leave a stricter state the range must clear that state's threshold + h.
        b_eff = b + h if relaxing_from in (ObstacleStatus.BLOCKED, ObstacleStatus.UNKNOWN) else b
        c_eff = c + h if _RANK[relaxing_from] >= _RANK[ObstacleStatus.CAUTION] else c
        if rng <= b_eff:
            return ObstacleStatus.BLOCKED
        if rng <= c_eff:
            return ObstacleStatus.CAUTION
        return ObstacleStatus.CLEAR

    def assess(self, now_mono_ns: Optional[int] = None) -> Assessment:
        """Current assessment. Call with no reading to re-check staleness (e.g. from a watchdog)."""
        now = time.monotonic_ns() if now_mono_ns is None else now_mono_ns
        r = self._latest
        thresholds = {"blocked_m": round(self.cfg.blocked_m(), 3), "caution_m": round(self.cfg.caution_m(), 3),
                      "hysteresis_m": self.cfg.hysteresis_m, "stale_after_s": self.cfg.stale_after_s}
        # Window members must themselves be recent: a gap in sampling empties the window.
        max_age = self.cfg.stale_after_s + self.cfg.window_size * self.cfg.sample_interval_s
        valid = [x for x in self._win if x.valid and (now - x.mono_ns) / 1e9 <= max_age]
        n_valid = len(valid)

        def out(status, reason, nearest=None, median=None, reset=True):
            if reset and status is ObstacleStatus.UNKNOWN:
                self._relax_streak = 0
            self._status = status
            age = None if r is None else r.age_s(now)
            return Assessment(status=status, forward_motion_allowed=FORWARD_ALLOWED[status],
                              nearest_range_m=None if nearest is None else round(nearest, 4),
                              median_range_m=None if median is None else round(median, 4),
                              latest=None if r is None else r.to_dict(), reason=reason, age_s=age,
                              stale=age is None or age > self.cfg.stale_after_s,
                              valid_in_window=n_valid, window_size=self.cfg.window_size,
                              thresholds=thresholds)

        if r is None:
            return out(ObstacleStatus.UNKNOWN, "no reading yet")
        if r.age_s(now) > self.cfg.stale_after_s:
            return out(ObstacleStatus.UNKNOWN, f"latest reading is stale ({r.age_s(now):.2f} s)")
        if not r.valid:
            return out(ObstacleStatus.UNKNOWN, f"latest reading invalid: {r.status.value}")
        median = statistics.median(x.distance_m for x in valid)
        nearest = min(median, r.distance_m)
        if n_valid < self.cfg.min_valid_in_window:
            # Not enough evidence to clear, but a close valid reading is still a reason to stop.
            if nearest <= self.cfg.blocked_m():
                return out(ObstacleStatus.BLOCKED, "close valid reading, window not yet full", nearest, median)
            return out(ObstacleStatus.UNKNOWN,
                       f"only {n_valid}/{self.cfg.min_valid_in_window} valid readings in window", None, median)

        prev = self._status
        cand = self._raw_status(nearest, prev)
        if _RANK[cand] >= _RANK[prev]:
            self._relax_streak = 0
            return out(cand, "range within threshold" if cand is not ObstacleStatus.CLEAR else "range beyond caution",
                       nearest, median)
        # cand is less restrictive than prev: require consecutive confirmation.
        self._relax_streak += 1
        if self._relax_streak >= self.cfg.clear_confirm_samples:
            self._relax_streak = 0
            return out(cand, f"relaxed {prev.value}->{cand.value} after "
                             f"{self.cfg.clear_confirm_samples} confirming readings", nearest, median)
        return out(prev, f"holding {prev.value}: {self._relax_streak}/{self.cfg.clear_confirm_samples} "
                         f"readings confirm {cand.value}", nearest, median, reset=False)

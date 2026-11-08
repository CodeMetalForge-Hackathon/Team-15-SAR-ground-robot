"""Robot control API: bounded commands, safety supervisor, watchdog and emergency stop.

Every motion command goes through ``SafetySupervisor.command``. That call is the only route to the
driver's ``apply``. The rules are:
  - Output is ZERO at construction and after any stop. Stopping is instant; speeding up is rate-limited.
  - Every command has a bounded duration. There is no "move until told otherwise".
  - Motion needs operator approval. A safety stop latches and revokes approval, so nothing restarts
    by itself.
  - Motion needs a fresh range reading and a known, sufficient power reading.
  - MOVE_FORWARD is fail-closed (Issue #9). It needs all of these: the forward corridor assessed CLEAR,
    the range source asserting ``forward_allowed is True`` (None is "not asserted" and refuses), and a
    fresh reading with a finite timestamp that isn't from the future. A hardware reading must also be OK.
    Any of these failing while moving stops the robot.
  - BACKWARD/STRAFE need explicit evidence that the direction is clear, because no sensor faces that way.
  - A physical driver must report its health (a link to the controller). If it can't, or it reports a
    fault, motion is refused, and while moving DRIVER_FAULT latches.
  - Non-finite or future-dated range and power readings count as missing.
  - The watchdog latches COMMS_LOST when the control loop stops calling heartbeat().
  - EmergencyStop is latched. It is independent of the supervisor, and an optional stop-file lets
    another process trip it.
"""
from __future__ import annotations

import enum
import math
import os
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from rover.sensors import Assessment, PowerReading, RangeReading


class Command(str, enum.Enum):
    STOP = "STOP"
    MOVE_FORWARD = "MOVE_FORWARD"
    MOVE_BACKWARD = "MOVE_BACKWARD"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"
    STRAFE_LEFT = "STRAFE_LEFT"
    STRAFE_RIGHT = "STRAFE_RIGHT"
    MOVE_TO_WAYPOINT = "MOVE_TO_WAYPOINT"
    EMERGENCY_STOP = "EMERGENCY_STOP"


@dataclass(frozen=True)
class BodyVelocity:
    vx: float = 0.0  # forward, normalised -1..1
    vy: float = 0.0  # left
    wz: float = 0.0  # counter-clockwise

    def is_zero(self) -> bool:
        return self.vx == 0.0 and self.vy == 0.0 and self.wz == 0.0

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.vx, self.vy, self.wz)


ZERO = BodyVelocity()

_UNIT = {
    Command.MOVE_FORWARD: (1, 0, 0), Command.MOVE_BACKWARD: (-1, 0, 0),
    Command.TURN_LEFT: (0, 0, 1), Command.TURN_RIGHT: (0, 0, -1),
    Command.STRAFE_LEFT: (0, 1, 0), Command.STRAFE_RIGHT: (0, -1, 0),
}
_TRANSLATE = {Command.MOVE_FORWARD, Command.MOVE_BACKWARD, Command.STRAFE_LEFT, Command.STRAFE_RIGHT}
_UNSENSED = {Command.MOVE_BACKWARD, Command.STRAFE_LEFT, Command.STRAFE_RIGHT}


@dataclass(frozen=True)
class MotionLimits:
    max_linear: float = 0.30          # normalised; the bench default stays well under the library's 100
    max_yaw: float = 0.30
    max_accel_per_s: float = 1.0      # how fast output may rise, in normalised units per second
    max_command_s: float = 1.0        # no command may run longer than this
    watchdog_timeout_s: float = 0.25  # the control loop must call heartbeat() within this
    sensor_max_age_s: float = 0.20
    min_voltage_v: Optional[float] = None  # None: no measured threshold, so physical motion is refused

    def __post_init__(self):
        for n in ("max_linear", "max_yaw", "max_accel_per_s", "max_command_s",
                  "watchdog_timeout_s", "sensor_max_age_s"):
            if not getattr(self, n) > 0:
                raise ValueError(f"{n} must be > 0")
        if self.max_linear > 1 or self.max_yaw > 1:
            raise ValueError("normalised speed limits must be <= 1")


class Driver(Protocol):
    name: str
    physical: bool

    def apply(self, v: BodyVelocity) -> None: ...
    def stop(self) -> None: ...
    # Optional for simulated drivers, REQUIRED for physical ones:
    #   def health(self) -> str: ...   "" if the controller link is alive and acknowledging, else why not.


FUTURE_TOLERANCE_S = 0.05  # a reading stamped further ahead than this is a clock fault (same as sensors.assess)


def _age_problem(t, now: float, max_age_s: float, what: str) -> str:
    if not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(t):
        return f"{what} has no valid timestamp"
    age = now - t
    if age < -FUTURE_TOLERANCE_S:
        return f"{what} timestamp {-age:.3f}s in the future (clock fault)"
    if age > max_age_s:
        return f"{what} stale ({age:.3f}s > {max_age_s:.3f}s)"
    return ""


class SafetyStop(str, enum.Enum):
    ESTOP = "ESTOP"
    COMMS_LOST = "COMMS_LOST"
    SENSOR_STALE = "SENSOR_STALE"
    UNDERVOLTAGE = "UNDERVOLTAGE"
    POWER_UNKNOWN = "POWER_UNKNOWN"
    DRIVER_FAULT = "DRIVER_FAULT"
    LOCALIZATION_LOST = "LOCALIZATION_LOST"


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str


@dataclass(frozen=True)
class DirectionEvidence:
    """Proof that a direction no sensor faces (behind, sideways) is clear. Only an operator can give it."""
    command: Command
    t: float
    given_by: str
    max_age_s: float = 2.0


class EmergencyStop:
    """Latched e-stop. trip() runs every registered stop function, even if one of them raises."""

    def __init__(self, stop_file: Optional[str] = None):
        self._tripped = False
        self.reason = ""
        self.stop_file = stop_file
        self._stops: list[Callable[[], None]] = []
        self.errors: list[str] = []

    def register(self, fn: Callable[[], None]) -> None:
        self._stops.append(fn)

    @property
    def tripped(self) -> bool:
        return self._tripped

    def trip(self, reason: str = "operator") -> None:
        if not self._tripped:
            self.reason = reason
        self._tripped = True
        for fn in self._stops:
            try:
                fn()
            except Exception as e:  # keep going: one failing path must not block the others
                self.errors.append(f"{getattr(fn, '__qualname__', fn)}: {e}")

    def poll_stop_file(self) -> None:
        if self.stop_file and os.path.exists(self.stop_file):
            self.trip(f"stop file {self.stop_file}")

    def reset(self, operator: str) -> None:
        if not operator or not operator.strip():
            raise PermissionError("e-stop reset needs a named operator")
        if self.stop_file and os.path.exists(self.stop_file):
            raise PermissionError("stop file still present")
        self._tripped = False
        self.reason = ""


@dataclass
class SupervisorEvent:
    t: float
    kind: str
    detail: str


class SafetySupervisor:
    def __init__(self, driver: Driver, clock: Callable[[], float], limits: MotionLimits = MotionLimits(),
                 estop: Optional[EmergencyStop] = None, power_max_age_s: float = 5.0):
        self.driver = driver
        self.clock = clock
        self.limits = limits
        self.estop = estop or EmergencyStop()
        self.power_max_age_s = power_max_age_s
        self.output = ZERO
        self.target = ZERO
        self.active: Command = Command.STOP
        self.deadline: Optional[float] = None
        self.latched: Optional[SafetyStop] = None
        self.latch_detail = ""
        self.approved_by: Optional[str] = None
        self.last_heartbeat = clock()
        self.last_tick = clock()
        self.range: Optional[RangeReading] = None
        self.forward_assessment = Assessment.UNKNOWN
        self.forward_reason = "no assessment"
        self.power: Optional[PowerReading] = None
        self.last_stop_reason = "startup"
        self.events: list[SupervisorEvent] = []
        self.estop.register(self._hard_zero)
        self._hard_zero()

    # --- inputs ---------------------------------------------------------------------
    def heartbeat(self) -> None:
        self.last_heartbeat = self.clock()

    def update_range(self, reading: Optional[RangeReading], forward: Assessment, reason: str = "") -> None:
        self.range = reading
        self.forward_assessment = forward
        self.forward_reason = reason

    def update_power(self, reading: Optional[PowerReading]) -> None:
        self.power = reading

    def approve_motion(self, operator: str) -> None:
        if not operator or not operator.strip():
            raise PermissionError("approval needs a named operator")
        if self.latched or self.estop.tripped:
            raise PermissionError("clear the safety stop before approving motion")
        self.approved_by = operator
        self._event("APPROVED", operator)

    def revoke_approval(self, why: str = "") -> None:
        self.approved_by = None
        self._event("APPROVAL_REVOKED", why)

    def trip_safety(self, why: SafetyStop, detail: str) -> None:
        """Latch a safety stop the supervisor can't see itself, such as localization loss."""
        self._latch(why, detail)

    def reset_latch(self, operator: str) -> None:
        """Clear a latched safety stop. Approval stays revoked, so motion needs a fresh approve_motion()."""
        if not operator or not operator.strip():
            raise PermissionError("latch reset needs a named operator")
        self._event("LATCH_RESET", f"{self.latched} by {operator}")
        self.latched = None
        self.latch_detail = ""
        self.last_heartbeat = self.clock()

    # --- commands -------------------------------------------------------------------
    def command(self, cmd: Command, speed: float = 0.0, duration_s: float = 0.0,
                evidence: Optional[DirectionEvidence] = None) -> Decision:
        now = self.clock()
        if cmd == Command.EMERGENCY_STOP:
            self.estop.trip("EMERGENCY_STOP command")
            self._latch(SafetyStop.ESTOP, "EMERGENCY_STOP command")
            return Decision(True, "emergency stop")
        if cmd == Command.STOP:
            self.stop("STOP command")
            return Decision(True, "stopped")
        refuse = self._precheck(cmd, speed, duration_s, evidence, now)
        if refuse:
            self._event("REFUSED", f"{cmd.value}: {refuse}")
            return Decision(False, refuse)
        u = _UNIT[cmd]
        lim = self.limits.max_yaw if cmd in (Command.TURN_LEFT, Command.TURN_RIGHT) else self.limits.max_linear
        s = min(speed, lim)
        self.target = BodyVelocity(u[0] * s, u[1] * s, u[2] * s)
        self.active = cmd
        self.deadline = now + duration_s
        return Decision(True, f"{cmd.value} {s:.2f} for {duration_s:.2f}s")

    def _precheck(self, cmd, speed, duration_s, evidence, now) -> str:
        if self.estop.tripped:
            return f"emergency stop latched ({self.estop.reason})"
        if self.latched:
            return f"safety stop latched: {self.latched.value} ({self.latch_detail}); operator reset required"
        if not self.approved_by:
            return "operator approval required before motion"
        if cmd == Command.MOVE_TO_WAYPOINT:
            return "MOVE_TO_WAYPOINT is not a raw motor command; it needs verified localization (Navigator)"
        if cmd not in _UNIT:
            return f"unsupported command {cmd}"
        if not (0 < duration_s <= self.limits.max_command_s):
            return f"duration {duration_s}s outside (0, {self.limits.max_command_s}]s"
        lim = self.limits.max_yaw if cmd in (Command.TURN_LEFT, Command.TURN_RIGHT) else self.limits.max_linear
        if not (0 < speed <= lim):
            return f"speed {speed} outside (0, {lim}]"
        d = self._driver_problem()
        if d:
            return d
        p = self._power_problem(now)
        if p:
            return p
        r = self._range_problem(now)
        if r:
            return f"no fresh range reading: {r}"
        if cmd == Command.MOVE_FORWARD:
            f = self._forward_problem()
            if f:
                return f
        if cmd in _UNSENSED:
            if evidence is None or evidence.command != cmd or now - evidence.t > evidence.max_age_s:
                return f"{cmd.value}: no sensor covers that direction; needs fresh operator evidence"
        return ""

    def _range_problem(self, now: float) -> str:
        if self.range is None:
            return "no range reading"
        return _age_problem(self.range.t, now, self.limits.sensor_max_age_s, "range reading")

    def _forward_problem(self) -> str:
        """Issue #9: forward motion needs a positive, explicit verdict. Anything else refuses or stops."""
        if self.forward_assessment != Assessment.CLEAR:
            return f"forward not CLEAR: {self.forward_assessment.value} ({self.forward_reason})"
        r = self.range
        allowed = getattr(r, "forward_allowed", None)
        if allowed is False:
            return "ranging service forward_motion_allowed=false"
        if allowed is not True:
            return "forward_motion_allowed not asserted"
        if getattr(r, "hardware", False) and getattr(r, "status", None) != "OK":
            return f"hardware range status {getattr(r, 'status', None)} cannot authorize forward motion"
        return ""

    def _driver_problem(self) -> str:
        health = getattr(self.driver, "health", None)
        if health is None:
            return "physical driver reports no health (controller link unverified)" if self.driver.physical else ""
        try:
            why = health()
        except Exception as e:  # a health check that fails is a fault, never "healthy"
            return f"driver health check failed: {type(e).__name__}: {e}"
        if why is None or why == "":
            return ""
        return f"driver fault: {why}"

    def _power_problem(self, now: float) -> str:
        p = self.power
        if p is None or p.voltage_v is None:
            return "power reading unknown or stale"
        v = p.voltage_v
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return "power reading invalid (non-finite voltage)"
        if _age_problem(p.t, now, self.power_max_age_s, "power reading"):
            return "power reading unknown or stale"
        if self.limits.min_voltage_v is None:
            if self.driver.physical:
                return "no measured undervoltage threshold configured"
            return ""
        if p.voltage_v < self.limits.min_voltage_v:
            return f"undervoltage {p.voltage_v:.2f} V < {self.limits.min_voltage_v:.2f} V"
        return ""

    def stop(self, reason: str) -> None:
        self.target = ZERO
        self.active = Command.STOP
        self.deadline = None
        self.last_stop_reason = reason
        self._apply(ZERO)

    # --- periodic -------------------------------------------------------------------
    def tick(self) -> None:
        now = self.clock()
        dt = max(0.0, now - self.last_tick)
        self.last_tick = now
        self.estop.poll_stop_file()
        if self.estop.tripped:
            if self.latched != SafetyStop.ESTOP:
                self._latch(SafetyStop.ESTOP, self.estop.reason)
            self._hard_zero()
            return
        if now - self.last_heartbeat > self.limits.watchdog_timeout_s:
            self._latch(SafetyStop.COMMS_LOST, f"no heartbeat for {now - self.last_heartbeat:.3f}s")
        moving = not self.target.is_zero() or not self.output.is_zero()
        if moving and not self.latched:
            if self.deadline is not None and now >= self.deadline:
                self.stop("command duration elapsed")
            elif self._driver_problem():
                self._latch(SafetyStop.DRIVER_FAULT, self._driver_problem())
            elif self._range_problem(now):
                self._latch(SafetyStop.SENSOR_STALE, f"while moving: {self._range_problem(now)}")
            elif self.active == Command.MOVE_FORWARD and self._forward_problem():
                f = self._forward_problem()
                if self.forward_assessment != Assessment.CLEAR:
                    f = f"obstacle check {self.forward_assessment.value}: {self.forward_reason}"
                self.stop(f)
            else:
                p = self._power_problem(now)
                if p:
                    self._latch(SafetyStop.UNDERVOLTAGE if "undervoltage" in p else SafetyStop.POWER_UNKNOWN, p)
        if self.latched:
            self._hard_zero()
            return
        self._apply(self._ramp(self.output, self.target, self.limits.max_accel_per_s * dt))

    @staticmethod
    def _ramp(cur: BodyVelocity, tgt: BodyVelocity, step: float) -> BodyVelocity:
        out = []
        for c, t in zip(cur.as_tuple(), tgt.as_tuple()):
            if t == 0 or (c != 0 and (c > 0) != (t > 0)):
                out.append(0.0)  # stopping or reversing: drop to zero at once
            elif abs(t) <= abs(c):
                out.append(t)  # slowing down is never rate-limited
            else:
                out.append(c + max(-step, min(step, t - c)))
        return BodyVelocity(*out)

    def _apply(self, v: BodyVelocity) -> None:
        try:
            self.driver.apply(v)
            self.output = v
        except Exception as e:
            self.output = ZERO
            self._latch(SafetyStop.DRIVER_FAULT, str(e))
            try:
                self.driver.stop()
            except Exception as e2:
                self._event("DRIVER_STOP_FAILED", str(e2))

    def _hard_zero(self) -> None:
        self.target = ZERO
        self.active = Command.STOP
        self.deadline = None
        self.output = ZERO
        try:
            self.driver.stop()
        except Exception as e:
            self._event("DRIVER_STOP_FAILED", str(e))
            raise

    def _latch(self, why: SafetyStop, detail: str) -> None:
        if self.latched is None:
            self.latched = why
            self.latch_detail = detail
            self.last_stop_reason = f"{why.value}: {detail}"
            self._event("SAFETY_STOP", self.last_stop_reason)
        self.approved_by = None
        self.target = ZERO
        self.active = Command.STOP
        self.deadline = None
        try:
            self._hard_zero()
        except Exception:
            pass

    def _event(self, kind: str, detail: str) -> None:
        self.events.append(SupervisorEvent(self.clock(), kind, detail))

    def status(self) -> dict:
        return {
            "active_command": self.active.value,
            "output": {"vx": self.output.vx, "vy": self.output.vy, "wz": self.output.wz},
            "estop": {"tripped": self.estop.tripped, "reason": self.estop.reason},
            "safety_latch": None if self.latched is None else {"kind": self.latched.value, "detail": self.latch_detail},
            "motion_approved_by": self.approved_by,
            "last_stop_reason": self.last_stop_reason,
            "driver": {"name": self.driver.name, "physical": self.driver.physical},
        }

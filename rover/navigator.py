"""Obstacle-aware route controller: Dijkstra over the graph plus a conservative reroute state machine.

IDLE -> PLAN_ROUTE -> TURN_TO_HEADING -> CHECK_SENSORS -> ADVANCE_IF_SAFE
     -> OBSTACLE_DETECTED -> STOP -> VERIFY_OBSTACLE -> MARK_EDGE_BLOCKED_IF_JUSTIFIED
     -> SCAN_DIRECTIONS (rotate the whole robot in place: left view, right view, back view)
     -> REPLAN_SHORTEST_ROUTE -> VERIFY_DETOUR -> CONTINUE_OR_REQUEST_OPERATOR
     -> ARRIVED | SAFE_STOP

Routes always come from planner.route.compute_route (Dijkstra) with the blocked edges taken from
the ObservationLog. Nothing here invents a route.

What justifies each action:
  - Rotating to a heading needs a fresh, MEASURED heading (closed loop). Timed open-loop turns are
    never trusted as angles. No heading means no scan, so the robot stops and asks the operator.
  - Driving forward needs a trusted pose on the edge, a measured heading aligned with that edge, a
    fresh range reading, and a CLEAR corridor of min(lookahead, remaining edge).
  - An edge is marked blocked only when all hold: N consistent fresh readings, a trusted pose on that
    edge, a heading aligned with it, and an obstacle that lies inside the edge (not at or after its
    far node).
  - A detour means going back to the previous graph node. The back view must show a CLEAR corridor the
    robot's width (rotated to face it: forward motion, never blind reversing). The next edge is then
    checked again before the robot leaves the node.
  - There are no local side-step bypasses. One forward ranger can't measure how deep the obstacle
    is, so left/right clearances are recorded as evidence only.
"""
from __future__ import annotations

import enum
import itertools
import math
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from planner.graph import TrailGraph
from planner.route import OK, RouteResult, compute_route
from rover.motion import Command, SafetyStop, SafetySupervisor
from rover.observations import CONFIRMED, UNCONFIRMED, ObservationLog, canonical_edge, suggest_viewpoints
from rover.sensors import (Assessment, CameraDetection, HeadingReading, NoEchoPolicy, PowerReading,
                           RangeReading, ang_diff, assess, combine, norm_deg)


class State(str, enum.Enum):
    IDLE = "IDLE"
    PLAN_ROUTE = "PLAN_ROUTE"
    TURN_TO_HEADING = "TURN_TO_HEADING"
    CHECK_SENSORS = "CHECK_SENSORS"
    ADVANCE_IF_SAFE = "ADVANCE_IF_SAFE"
    OBSTACLE_DETECTED = "OBSTACLE_DETECTED"
    STOP = "STOP"
    VERIFY_OBSTACLE = "VERIFY_OBSTACLE"
    MARK_EDGE_BLOCKED_IF_JUSTIFIED = "MARK_EDGE_BLOCKED_IF_JUSTIFIED"
    SCAN_DIRECTIONS = "SCAN_DIRECTIONS"
    REPLAN_SHORTEST_ROUTE = "REPLAN_SHORTEST_ROUTE"
    VERIFY_DETOUR = "VERIFY_DETOUR"
    CONTINUE_OR_REQUEST_OPERATOR = "CONTINUE_OR_REQUEST_OPERATOR"
    ARRIVED = "ARRIVED"
    SAFE_STOP = "SAFE_STOP"


TERMINAL = {State.ARRIVED, State.SAFE_STOP, State.CONTINUE_OR_REQUEST_OPERATOR}

SIM_TRUTH = "SIM_TRUTH"
OPERATOR_CONFIRMED = "OPERATOR_CONFIRMED"
UNKNOWN = "UNKNOWN"
TRUSTED_FOR_MOTION = {SIM_TRUTH}  # no hardware pose source is verified yet


@dataclass(frozen=True)
class Pose:
    source: str
    t: float
    node: Optional[str] = None
    edge: Optional[tuple[str, str]] = None
    progress_m: Optional[float] = None   # distance from edge[0]

    @property
    def trusted(self) -> bool:
        return self.source in TRUSTED_FOR_MOTION

    def distance_from(self, n: str, g: TrailGraph) -> Optional[float]:
        if self.node == n:
            return 0.0
        if self.node is not None and n in g.neighbors(self.node) and (self.edge is None or n not in self.edge):
            return g.neighbors(self.node)[n]   # standing at a node, about to leave along node-n
        if self.edge is None or self.progress_m is None or n not in self.edge:
            return None
        a, b = self.edge
        return self.progress_m if n == a else g.neighbors(a)[b] - self.progress_m

    def to_dict(self) -> dict:
        if self.source == UNKNOWN:
            return {"source": UNKNOWN}
        return {"source": self.source, "t": self.t, "node": self.node,
                "edge": None if self.edge is None else "-".join(self.edge),
                "progress_m": None if self.progress_m is None else round(self.progress_m, 3)}


class RobotIO(Protocol):
    physical: bool

    def clock(self) -> float: ...
    def read_range(self) -> Optional[RangeReading]: ...
    def read_heading(self) -> Optional[HeadingReading]: ...
    def read_power(self) -> Optional[PowerReading]: ...
    def read_camera(self) -> list[CameraDetection]: ...
    def pose(self) -> Pose: ...
    def bearing(self, a: str, b: str) -> Optional[float]: ...
    def traveled(self) -> dict: ...


@dataclass(frozen=True)
class NavConfig:
    robot_width_m: float              # required: measure the real chassis; the sim uses a labelled placeholder
    width_margin_m: float = 0.05
    lookahead_m: float = 1.0          # forward corridor that must be clear before and while advancing
    forward_speed: float = 0.30
    max_yaw_speed: float = 0.30
    min_yaw_speed: float = 0.05
    cmd_s: float = 0.15               # every command is short and refreshed only after a fresh check
    heading_tol_deg: float = 2.0
    align_tol_deg: float = 4.0
    scan_step_deg: float = 45.0
    max_rotation_segment_deg: float = 90.0
    min_expected_yaw_dps: float = 10.0  # rotation timeout: needed/min rate + 2 s means a stall or slip
    settle_s: float = 0.2
    verify_samples: int = 3
    verify_spread_m: float = 0.15
    reading_timeout_s: float = 1.0
    node_tol_m: float = 0.05
    sensor_max_age_s: float = 0.20
    heading_max_age_s: float = 0.20
    camera_period_s: float = 0.5
    camera_max_age_s: float = 1.0
    no_echo_policy: NoEchoPolicy = NoEchoPolicy.UNKNOWN
    auto_approve: bool = False        # simulation only; refused when the driver is physical

    def __post_init__(self):
        if not self.robot_width_m > 0:
            raise ValueError("robot_width_m must be measured and > 0")
        if self.scan_step_deg * 2 > self.max_rotation_segment_deg + 1e-9:
            # left-to-right sweep is one bounded segment
            raise ValueError("2 * scan_step_deg must be <= max_rotation_segment_deg")


class Navigator:
    def __init__(self, graph: TrailGraph, io: RobotIO, supervisor: SafetySupervisor, log: ObservationLog,
                 config: NavConfig, mode: str = "SIMULATION"):
        if config.auto_approve and (io.physical or supervisor.driver.physical):
            raise PermissionError("auto_approve is simulation-only")
        self.g = graph
        self.io = io
        self.sup = supervisor
        self.log = log
        self.cfg = config
        self.mode = mode
        self.state = State.IDLE
        self.state_detail = ""
        self.history: list[dict] = []
        self.dest: Optional[str] = None
        self.route: Optional[RouteResult] = None
        self.route_leg = 0
        self.reroutes: list[dict] = []
        self.scans: list[dict] = []
        self.operator_requests: list[dict] = []
        self.camera_requests: list[dict] = []
        self.safe_stop_reason = ""
        self.latest_range: Optional[RangeReading] = None
        self.latest_heading: Optional[HeadingReading] = None
        self.latest_detections: list[CameraDetection] = []
        self._last_cam = -math.inf
        self._required_forward = config.lookahead_m
        self._proc = None
        self._req_ids = itertools.count(1)
        self.scanning = False

    # --- public API ------------------------------------------------------------------
    def start(self, dest: str) -> None:
        if self._proc is not None:
            raise RuntimeError("mission already running")
        self.dest = dest
        self._proc = self._mission(dest)
        self._set(State.PLAN_ROUTE, f"destination {dest}")

    def resume(self, operator: str) -> None:
        """Start again from the current pose. Only an operator can do this; it never happens on its own."""
        if not operator.strip():
            raise PermissionError("resume needs a named operator")
        if self.dest is None:
            raise RuntimeError("no mission to resume")
        self._proc = None
        self.safe_stop_reason = ""
        self.history.append({"t": self.io.clock(), "state": "RESUME", "detail": f"by {operator}"})
        self.start(self.dest)

    def respond(self, req_id: str, approve: bool, operator: str) -> None:
        if not operator.strip():
            raise PermissionError("response needs a named operator")
        for r in self.operator_requests:
            if r["id"] == req_id and r["state"] == "PENDING":
                r["state"] = "APPROVED" if approve else "DENIED"
                r["by"] = operator
                r["t_resolved"] = self.io.clock()
                return
        raise KeyError(f"no pending request {req_id}")

    @property
    def running(self) -> bool:
        return self._proc is not None

    def tick(self) -> None:
        now = self.io.clock()
        self.sup.heartbeat()
        r = self.io.read_range()
        if r is not None:
            self.latest_range = r
        h = self.io.read_heading()
        if h is not None:
            self.latest_heading = h
        self.sup.update_power(self.io.read_power())
        if now - self._last_cam >= self.cfg.camera_period_s - 1e-9:
            self.latest_detections = list(self.io.read_camera())
            self._last_cam = now
        self._update_forward()
        if self._proc is not None and not self._halted():
            try:
                next(self._proc)
            except StopIteration:
                self._proc = None
        self.sup.tick()
        if self._halted() and self.state != State.SAFE_STOP:
            self._proc = None
            why = (f"ESTOP: {self.sup.estop.reason}" if self.sup.estop.tripped
                   else f"{self.sup.latched.value}: {self.sup.latch_detail}")
            self._safe_stop(why)

    # --- helpers -----------------------------------------------------------------------
    def _halted(self) -> bool:
        return self.sup.estop.tripped or self.sup.latched is not None

    def _update_forward(self) -> None:
        a, why = assess(self.latest_range, self.io.clock(), self._required_forward,
                        self.cfg.sensor_max_age_s, self.cfg.no_echo_policy)
        self.sup.update_range(self.latest_range, a, why)

    def _set(self, s: State, detail: str = "") -> None:
        self.state = s
        self.state_detail = detail
        self.history.append({"t": self.io.clock(), "state": s.value, "detail": detail})

    def _safe_stop(self, reason: str) -> None:
        self.sup.stop(f"SAFE_STOP: {reason}")
        self.safe_stop_reason = reason
        self._set(State.SAFE_STOP, reason)

    def _request(self, kind: str, message: str, **extra) -> dict:
        req = {"id": f"req-{next(self._req_ids):03d}", "t": self.io.clock(), "kind": kind,
               "message": message, "state": "PENDING", **extra}
        self.operator_requests.append(req)
        return req

    def _hold_for_operator(self, kind: str, message: str, **extra) -> str:
        """Stop and end the mission until the operator acts (respond/resume). Never auto-restarts."""
        self.sup.stop(f"operator required: {kind}")
        self._request(kind, message, **extra)
        self._set(State.CONTINUE_OR_REQUEST_OPERATOR, f"{kind}: {message}")
        return "STOPPED"

    def _approval(self, kind: str, message: str, **extra):
        self._set(State.CONTINUE_OR_REQUEST_OPERATOR, f"{kind}: {message}")
        req = self._request(kind, message, **extra)
        if self.cfg.auto_approve:
            req.update(state="APPROVED", by="sim-auto-approve", t_resolved=self.io.clock())
            return True
        while req["state"] == "PENDING":
            yield
        return req["state"] == "APPROVED"

    def _heading(self) -> Optional[float]:
        h = self.latest_heading
        if h is None or self.io.clock() - h.t > self.cfg.heading_max_age_s:
            return None
        return h.heading_deg

    def _pose(self) -> Pose:
        return self.io.pose()

    def _wait(self, seconds: float):
        end = self.io.clock() + seconds
        while self.io.clock() < end - 1e-9:
            yield

    def _fresh_reading_after(self, t0: float):
        end = self.io.clock() + self.cfg.reading_timeout_s
        while True:
            r = self.latest_range
            if r is not None and r.t > t0 + 1e-9 and self.io.clock() - r.t <= self.cfg.sensor_max_age_s:
                return r
            if self.io.clock() >= end:
                return None
            yield

    def _plan(self, start: str) -> RouteResult:
        return compute_route(start, self.dest, blocked=self.log.blocked_edges(), graph=self.g)

    def _request_camera(self, heading: Optional[float], reason: str) -> dict:
        dets = list(self.io.read_camera())
        req = {"id": f"cam-{len(self.camera_requests) + 1:03d}", "t": self.io.clock(),
               "heading_deg": heading, "reason": reason, "detections": [d.label for d in dets]}
        self.camera_requests.append(req)
        for d in dets:
            if d.label == "person":
                self.log.add("camera_person", d.source, UNCONFIRMED, dynamic=True,
                             detail={"relative_bearing_deg": d.relative_bearing_deg, "score": d.score,
                                     "camera_request": req["id"], "coordinates": "NONE (no localization)"})
        return req

    # --- rotation & scanning ------------------------------------------------------------
    def _face(self, target: float, why: str):
        target = norm_deg(target)
        self._set(State.TURN_TO_HEADING, f"{why}: target {target:.1f} deg")
        h = self._heading()
        if h is None:
            self._hold_for_operator("HEADING_UNAVAILABLE",
                                    f"{why}: no fresh measured heading; timed rotation is not trusted as an angle")
            return False
        start = self.io.clock()
        timeout = 2.0 + abs(ang_diff(target, h)) / self.cfg.min_expected_yaw_dps
        seg_ref = h
        while True:
            h = self._heading()
            if h is None:
                self._hold_for_operator("HEADING_LOST", f"{why}: heading measurement lost during rotation")
                return False
            err = ang_diff(target, h)
            if abs(err) <= self.cfg.heading_tol_deg:
                self.sup.stop("heading reached")
                yield from self._wait(self.cfg.settle_s)
                return True
            if abs(ang_diff(h, seg_ref)) >= self.cfg.max_rotation_segment_deg:
                self.sup.stop("rotation segment limit")  # bounded rotation, re-measure, continue
                yield from self._wait(self.cfg.settle_s)
                seg_ref = self._heading() if self._heading() is not None else h
                continue
            if self.io.clock() - start > timeout:
                self._hold_for_operator("ROTATION_TIMEOUT", f"{why}: heading did not converge (stall or slip?)")
                return False
            speed = min(self.cfg.max_yaw_speed, max(self.cfg.min_yaw_speed, abs(err) / 30.0 * self.cfg.max_yaw_speed))
            d = self.sup.command(Command.TURN_LEFT if err > 0 else Command.TURN_RIGHT, speed, self.cfg.cmd_s)
            if not d.accepted:
                self._hold_for_operator("MOTION_REFUSED", d.reason)
                return False
            yield

    def _sweep(self, center: float, required_m: float, label: str):
        """Assess a robot-width corridor by rotating to center-delta, center and center+delta."""
        half = self.cfg.robot_width_m / 2 + self.cfg.width_margin_m
        delta = min(30.0, math.degrees(math.atan2(half, max(required_m, 0.05))))
        samples = []
        for off in (0.0, delta, -delta):
            ok = yield from self._face(center + off, f"scan {label}")
            if not ok:
                return None
            r = yield from self._fresh_reading_after(self.io.clock())
            a, why = assess(r, self.io.clock(), required_m, self.cfg.sensor_max_age_s, self.cfg.no_echo_policy)
            samples.append({"offset_deg": round(off, 2), "heading_deg": self._heading(),
                            "reading": r.to_dict() if r else None, "assessment": a.value, "reason": why})
        ok = yield from self._face(center, f"scan {label} centre")
        if not ok:
            return None
        cam = self._request_camera(self._heading(), f"scan {label}")
        status = combine([Assessment(s["assessment"]) for s in samples])
        if "person" in cam["detections"]:
            status = Assessment.UNKNOWN  # a person is a dynamic hazard, not evidence of clear space
        ranges = [s["reading"]["range_m"] for s in samples if s["reading"] and s["reading"]["range_m"] is not None]
        return {"view": label, "bearing_deg": round(norm_deg(center), 2), "required_m": round(required_m, 3),
                "sweep_half_deg": round(delta, 2), "samples": samples, "status": status.value,
                "min_range_m": min(ranges) if ranges else None, "camera_request": cam["id"]}

    def _directional_scan(self, back_required_m: float, trigger: str):
        self._set(State.SCAN_DIRECTIONS, trigger)
        h0 = self._heading()
        if h0 is None:
            self._hold_for_operator("HEADING_UNAVAILABLE", "cannot scan: no reliable heading measurement")
            return None
        step = self.cfg.scan_step_deg
        views = [("left", h0 + step, self.cfg.lookahead_m), ("right", h0 - step, self.cfg.lookahead_m)]
        if back_required_m > self.cfg.node_tol_m:
            views.append(("back", h0 + 180.0, back_required_m))
        results = {}
        self.scanning = True
        try:
            for name, b, req in views:
                res = yield from self._sweep(b, req, name)
                if res is None:
                    return None
                if not self._pose().trusted:
                    # a view is only meaningful relative to a verified pose on the graph
                    self.sup.trip_safety(SafetyStop.LOCALIZATION_LOST, f"pose lost during {name} scan view")
                    self._safe_stop(f"LOCALIZATION_LOST during directional scan ({name} view)")
                    return None
                results[name] = res
        finally:
            self.scanning = False
        width_need = self.cfg.robot_width_m + 2 * self.cfg.width_margin_m
        scan = {
            "t": self.io.clock(), "trigger": trigger,
            "heading_at_stop_deg": round(h0, 2),
            "heading_source": self.latest_heading.source if self.latest_heading else None,
            "views": results,
            "comparison": {
                name: {"status": v["status"], "min_range_m": v["min_range_m"],
                       "wider_than_robot": None if v["min_range_m"] is None else v["min_range_m"] >= width_need}
                for name, v in results.items()},
            "local_bypass": "NOT_ATTEMPTED: one forward ranger cannot measure obstacle depth; "
                            "side clearances are evidence only",
        }
        self.scans.append(scan)
        return scan

    # --- mission ------------------------------------------------------------------------
    def _mission(self, dest: str):
        while True:
            self._set(State.PLAN_ROUTE, f"to {dest}")
            pose = self._pose()
            if pose.source == UNKNOWN or pose.node is None:
                yield from ()
                return self._hold_for_operator(
                    "POSE_UNKNOWN", "robot pose is not verified at a graph node; operator-assisted waypoint execution only")
            res = self._plan(pose.node)
            if res.status != OK:
                self.route = res
                self._safe_stop(f"no verified route from {pose.node} to {dest}: {res.reason}; "
                                f"blocked edges {self.log.blocked_edges()}")
                return
            prev = self.route
            self.route, self.route_leg = res, 0
            if pose.node == dest:
                self._set(State.ARRIVED, f"at {dest}")
                return
            if not pose.trusted:
                return self._hold_for_operator(
                    "OPERATOR_ASSISTED_WAYPOINT",
                    f"no trusted localization: operator please drive {res.path[0]}->{res.path[1]} and confirm arrival",
                    route=res.path)
            if prev is None:
                ok = yield from self._approval("START_ROUTE", f"route {'-'.join(res.path)} {res.length_m} m (synthetic)")
                if not ok:
                    return self._hold_for_operator("ROUTE_DENIED", "operator denied the route")
            out = yield from self._follow(res)
            if out == "ARRIVED":
                self._set(State.ARRIVED, f"at {dest}")
                self.sup.stop("arrived")
                return
            if out != "REPLAN":
                return

    def _follow(self, res: RouteResult):
        for i, (u, v) in enumerate(zip(res.path, res.path[1:])):
            self.route_leg = i
            out = yield from self._advance(u, v)
            if out != "NODE":
                return out
            self._request_camera(self._heading(), f"arrived at {v}")
        return "ARRIVED"

    def _advance(self, u: str, v: str, retreat: bool = False):
        b = self.io.bearing(u, v)
        if b is None:
            return self._hold_for_operator("NO_BEARING", f"no verified bearing for {u}->{v}")
        ok = yield from self._face(b, f"face {u}->{v}")
        if not ok:
            return "STOPPED"
        self._set(State.CHECK_SENSORS, f"{u}->{v}")
        r = yield from self._fresh_reading_after(self.io.clock())
        if r is None:
            return self._stale_stop("no fresh range reading before departure")
        L = self.g.neighbors(u)[v]
        while True:
            pose = self._pose()
            if not pose.trusted:
                self.sup.trip_safety(SafetyStop.LOCALIZATION_LOST, f"pose {pose.source} while on {u}->{v}")
                self._safe_stop(f"LOCALIZATION_LOST on {u}->{v}")
                self._request("LOCALIZATION_LOST", f"pose lost on {u}->{v}; operator must locate the robot")
                return "STOPPED"
            rem = pose.distance_from(v, self.g)
            if rem is None:
                self.sup.trip_safety(SafetyStop.LOCALIZATION_LOST, f"pose {pose.to_dict()} not on {u}-{v}")
                self._safe_stop(f"LOCALIZATION_LOST: not on edge {u}-{v}")
                return "STOPPED"
            if rem <= self.cfg.node_tol_m:
                self.sup.stop(f"reached {v}")
                self._required_forward = self.cfg.lookahead_m
                return "NODE"
            h = self._heading()
            if h is None or abs(ang_diff(h, b)) > self.cfg.align_tol_deg:
                return self._hold_for_operator("HEADING_MISALIGNED", f"heading {h} not aligned with {u}->{v} ({b:.1f})")
            self._required_forward = min(self.cfg.lookahead_m, rem)
            self._update_forward()
            a, why = assess(self.latest_range, self.io.clock(), self._required_forward,
                            self.cfg.sensor_max_age_s, self.cfg.no_echo_policy)
            now = self.io.clock()
            persons = [d for d in self.latest_detections
                       if d.label == "person" and now - d.t <= self.cfg.camera_max_age_s]
            if persons:
                self.sup.stop("person detected")
                return self._person(u, v, persons)
            if a == Assessment.CLEAR:
                self._set(State.ADVANCE_IF_SAFE, f"{u}->{v} {rem:.2f} m left ({why})")
                d = self.sup.command(Command.MOVE_FORWARD, self.cfg.forward_speed, self.cfg.cmd_s)
                if not d.accepted:
                    return self._hold_for_operator("MOTION_REFUSED", d.reason)
            elif a == Assessment.BLOCKED:
                self.sup.stop(f"obstacle: {why}")
                if retreat:
                    return self._hold_for_operator("RETREAT_BLOCKED", f"obstacle on the verified retreat {u}->{v}: {why}")
                out = yield from self._obstacle(u, v)
                return out
            else:
                if "stale" in why or "no range" in why:
                    return self._stale_stop(why)
                return self._hold_for_operator("SENSOR_UNKNOWN", f"{u}->{v}: {why}")
            yield

    def _stale_stop(self, why: str) -> str:
        self.sup.trip_safety(SafetyStop.SENSOR_STALE, why)
        self._safe_stop(f"SENSOR_STALE: {why}")
        return "STOPPED"

    def _person(self, u: str, v: str, dets: list[CameraDetection]) -> str:
        o = self.log.add("camera_person", dets[0].source, UNCONFIRMED, dynamic=True, edge=(u, v),
                         detail={"context": f"seen ahead while on {u}->{v}; bearing only, no range",
                                 "relative_bearing_deg": dets[0].relative_bearing_deg,
                                 "score": dets[0].score, "coordinates": "NONE (no localization)"})
        return self._hold_for_operator("HUMAN_REVIEW", f"camera reports a person ahead on {u}-{v} (UNCONFIRMED)",
                                       obs_id=o.obs_id)

    def _associate(self, pose: Pose, u: str, v: str, r: float) -> tuple[bool, str, Optional[float]]:
        if not pose.trusted:
            return False, f"pose {pose.source} is not verified", None
        s = pose.distance_from(u, self.g)
        if s is None:
            return False, f"robot not on edge {u}-{v}", None
        h, b = self._heading(), self.io.bearing(u, v)
        if h is None or b is None or abs(ang_diff(h, b)) > self.cfg.align_tol_deg:
            return False, f"heading {h} not verified along {u}->{v}", None
        L = self.g.neighbors(u)[v]
        at = s + r
        if at >= L - self.cfg.node_tol_m:
            return False, f"obstacle at {at:.2f} m is at/after node {v} (edge {L} m); cannot attribute to {u}-{v}", at
        return True, f"robot on {u}->{v} at {s:.2f} m facing along edge; obstacle at {at:.2f} of {L} m", at

    def _obstacle(self, u: str, v: str):
        edge = canonical_edge((u, v))
        self._set(State.OBSTACLE_DETECTED, f"on {u}->{v}: {self.sup.forward_reason}")
        self._set(State.STOP, "conservative stop")
        t_stop = self.io.clock()
        yield from self._wait(self.cfg.settle_s)
        self._set(State.VERIFY_OBSTACLE, f"{self.cfg.verify_samples} fresh readings")
        samples: list[RangeReading] = []
        t_ref = t_stop
        while len(samples) < self.cfg.verify_samples:
            r = yield from self._fresh_reading_after(t_ref)
            if r is None:
                return self._stale_stop("readings stopped during obstacle verification")
            samples.append(r)
            t_ref = r.t
        pose = self._pose()
        rem = pose.distance_from(v, self.g)
        required = min(self.cfg.lookahead_m, rem if rem is not None else self.cfg.lookahead_m)
        ranges = [r.range_m for r in samples if r.status == "OK" and r.range_m is not None and r.range_m < required]
        if len(ranges) < len(samples) or max(ranges) - min(ranges) > self.cfg.verify_spread_m:
            o = self.log.add("ultrasonic_obstacle", samples[-1].source, UNCONFIRMED, dynamic=True, edge=edge,
                             detail={"ranges": [r.range_m for r in samples], "why": "inconsistent or cleared"})
            return self._hold_for_operator("OBSTACLE_UNCONFIRMED",
                                           f"{edge}: readings inconsistent (possibly moving); not marking blocked",
                                           obs_id=o.obs_id)
        r_mean = sum(ranges) / len(ranges)
        ok, why, at = self._associate(pose, u, v, r_mean)
        self._set(State.MARK_EDGE_BLOCKED_IF_JUSTIFIED, why)
        if not ok:
            o = self.log.add("ultrasonic_obstacle", samples[-1].source, UNCONFIRMED, dynamic=False, edge=None,
                             detail={"ranges": ranges, "why_not_marked": why})
            return self._hold_for_operator("OBSTACLE_NOT_ATTRIBUTED", why, obs_id=o.obs_id)
        s = pose.distance_from(u, self.g)
        blk = self.log.add("ultrasonic_obstacle", samples[-1].source, CONFIRMED, dynamic=False, edge=edge,
                           detail={"ranges": ranges, "at_m_from": u, "at_m": round(at, 3),
                                   "robot_progress_m": round(s, 3), "justification": why,
                                   "distances": "SYNTHETIC graph metres"})
        old = self.route
        old_remaining = self._remaining()
        scan = yield from self._directional_scan(min(self.cfg.lookahead_m, s), f"obstacle on {edge}")
        if scan is None:
            return "STOPPED"
        self._set(State.REPLAN_SHORTEST_ROUTE, f"{edge} blocked")
        res = self._plan(u)
        if res.status != OK:
            yield from self._face(scan["heading_at_stop_deg"], "return to planned heading")
            self.route = res
            self._safe_stop(f"no verified route after {edge} blocked: {res.reason}; "
                            f"blocked edges {self.log.blocked_edges()}")
            return "STOPPED"
        self._set(State.VERIFY_DETOUR, f"retreat {s:.2f} m to {u}, then {'-'.join(res.path)}")
        if s > self.cfg.node_tol_m:
            back = scan["views"].get("back")
            if back is None or back["status"] != Assessment.CLEAR.value:
                return self._hold_for_operator("DETOUR_UNVERIFIED",
                                               f"retreat corridor to {u} not verified clear: {back and back['status']}")
        self.reroutes.append({
            "t": self.io.clock(), "reason": f"edge {edge} blocked ({blk.obs_id}): {why}",
            "blocked_edge": edge, "obs_id": blk.obs_id,
            "old_route": old.path if old else None, "old_length_m": old.length_m if old else None,
            "old_remaining_m": old_remaining,
            "retreat_m": round(s, 3), "new_route": res.path, "new_length_m": res.length_m,
            "new_remaining_m": round(s + res.length_m, 3), "distances": "SYNTHETIC graph metres",
            "scan_t": scan["t"],
        })
        ok = yield from self._approval("REROUTE", f"{edge} blocked; new route {'-'.join(res.path)} "
                                                  f"{res.length_m} m after {s:.2f} m retreat (synthetic)")
        if not ok:
            return self._hold_for_operator("REROUTE_DENIED", "operator denied the detour")
        if s > self.cfg.node_tol_m:
            out = yield from self._advance(v, u, retreat=True)
            if out != "NODE":
                return out
        return "REPLAN"

    # --- status ---------------------------------------------------------------------------
    def _remaining(self) -> Optional[float]:
        r = self.route
        if r is None or r.status != OK:
            return None
        pose = self._pose()
        if not pose.trusted or len(r.path) < 2:
            return r.length_m if len(r.path) >= 2 else 0.0
        if pose.node is not None and pose.node in r.path:
            i = r.path.index(pose.node)
            return float(sum(self.g.neighbors(a)[b] for a, b in zip(r.path[i:], r.path[i + 1:])))
        if pose.edge is not None:
            for i, (a, b) in enumerate(zip(r.path, r.path[1:])):
                if set(pose.edge) == {a, b}:
                    rest = sum(self.g.neighbors(x)[y] for x, y in zip(r.path[i + 1:], r.path[i + 2:]))
                    d = pose.distance_from(b, self.g)
                    return round(d + rest, 3)
        return None

    def status(self) -> dict:
        now = self.io.clock()
        a, why = assess(self.latest_range, now, self._required_forward, self.cfg.sensor_max_age_s,
                        self.cfg.no_echo_policy)
        h = self._heading()
        r = self.route
        return {
            "schema": "team15.rover_nav_status/1",
            "t": now,
            "mode": self.mode,
            "distances_label": "SYNTHETIC graph metres; not measured RoverC travel",
            "state": self.state.value,
            "state_detail": self.state_detail,
            "destination": self.dest,
            "route": None if r is None else {"status": r.status, "path": r.path, "edges": r.edges,
                                             "length_m": r.length_m, "reason": r.reason},
            "remaining_planned_m": self._remaining(),
            "blocked_edges": self.log.blocked_edges(),
            "blockers": self.log.blockers(),
            "reroutes": self.reroutes,
            "last_reroute_reason": self.reroutes[-1]["reason"] if self.reroutes else None,
            "latest_range": self.latest_range.to_dict() if self.latest_range else None,
            "sensor": {"forward_assessment": a.value, "reason": why,
                       "age_s": None if self.latest_range is None else round(now - self.latest_range.t, 3),
                       "valid": a != Assessment.UNKNOWN},
            "heading": {"deg": None if h is None else round(h, 2),
                        "source": self.latest_heading.source if (h is not None and self.latest_heading) else UNKNOWN},
            "pose": self._pose().to_dict(),
            "traveled": self.io.traveled(),
            "motion": self.sup.status(),
            "safe_stop_reason": self.safe_stop_reason or None,
            "operator_requests": [q for q in self.operator_requests if q["state"] == "PENDING"],
            "last_scan": self.scans[-1] if self.scans else None,
            "camera_requests": self.camera_requests[-5:],
            "suggested_viewpoints": (suggest_viewpoints(self.g, self.log, self._pose().node)
                                     if self._pose().node else []),
            "observations": self.log.to_list(),
            "claims": {"autonomous_navigation_operational": False,
                       "physical_motion_verified": False,
                       "localization": "SIMULATED" if self.mode == "SIMULATION" else "NONE"},
        }

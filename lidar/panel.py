"""Display view for the dashboard (``team15.lidar_panel/1``) and a SIMULATED replay source.

The panel is display-ready, and every rule is applied here, so a browser only renders:
  * the badge is SIMULATED unless the source is HARDWARE_VERIFIED, which nothing in this PR
    sets. A real but unverified device shows "HARDWARE (UNVERIFIED)", never "HARDWARE";
  * stale data (older than 0.5 s), partial scans and disconnects grey out the panel and read UNKNOWN;
  * it never shows "path clear" or "motion allowed", and no distance is ever labelled as a person's;
  * scan points are drawn in the ROBOT frame only if alignment is verified, otherwise in the
    SENSOR frame with a "sensor frame: forward unknown" warning.
"""
from __future__ import annotations

import dataclasses
import math
import time
from typing import Optional

from .processing import Connection, LidarAssessment, LidarAssessor
from .scan import Scan, SourceMode
from .tracking import VisualTracker

SCHEMA = "team15.lidar_panel/1"
TITLE = "LiDAR obstacle scan (RPLIDAR C1)"
QUALIFICATION = ("nearest reflecting surfaces in the LiDAR scan plane; not the distance to the detected "
                 "person, not a robot position")
MAX_POINTS = 360


def badge(source_mode: str) -> str:
    if source_mode == SourceMode.HARDWARE_VERIFIED.value:
        return "HARDWARE"
    if source_mode == SourceMode.HARDWARE_UNVERIFIED.value:
        return "HARDWARE (UNVERIFIED)"
    return "SIMULATED"


def panel_view(a: LidarAssessment, scan: Optional[Scan], tracks: Optional[dict] = None,
               frame_info: Optional[dict] = None, fixture: bool = False, mount=None) -> dict:
    usable = (not a.stale_for_display) and a.connection is Connection.SCANNING and scan is not None
    # A fixture can claim anything: fixture data is always SIMULATED.
    src = SourceMode.SIMULATED.value if fixture else a.source_mode
    pts = []
    frame = "ROBOT" if (a.alignment_verified and mount is not None) else "SENSOR"
    if usable:
        vs = scan.valid_samples
        step = max(1, math.ceil(len(vs) / MAX_POINTS))
        for s in vs[::step]:
            if a.alignment_verified and mount is not None:
                rb = math.radians(mount.robot_bearing(s.angle_deg))
                pts.append([round(s.distance_m * math.cos(rb), 3), round(s.distance_m * math.sin(rb), 3)])
            else:
                x, y = s.xy_sensor()
                pts.append([round(x, 3), round(y, 3)])
    sec = {s.name: s.to_dict() if usable else {**s.to_dict(), "status": "UNKNOWN", "min_range_m": None}
           for s in a.sectors}
    clearance = {k: (sec[k]["min_range_m"], sec[k]["status"]) for k in ("FRONT", "LEFT", "RIGHT")}
    if not usable:
        status_text = ("disconnected" if a.connection is not Connection.SCANNING else
                       "stale" if a.stale_for_display else "no scan")
    else:
        status_text = a.forward_status.value.lower()
    return {
        "schema": SCHEMA, "title": TITLE, "qualification": QUALIFICATION,
        "badge": badge(src), "simulated": src == SourceMode.SIMULATED.value, "source_mode": src,
        "fixture": fixture, "connection": a.connection.value, "usable": usable, "greyed": not usable,
        "status_text": status_text,
        "front": {"status": clearance["FRONT"][1], "min_range_m": clearance["FRONT"][0]},
        "left": {"status": clearance["LEFT"][1], "min_range_m": clearance["LEFT"][0]},
        "right": {"status": clearance["RIGHT"][1], "min_range_m": clearance["RIGHT"][0]},
        "closest": a.closest if usable else None,
        "sectors": list(sec.values()),
        "motion_text": "BLOCKED" if (usable and a.forward_status.value == "BLOCKED") else "UNKNOWN"
        if not (usable and a.forward_motion_allowed) else None,
        "last_valid_scan_wall": a.last_valid_scan_wall, "scan_seq": a.scan_seq,
        "scan_age_s": None if a.scan_age_s is None else round(a.scan_age_s, 3),
        "stale_after_s": a.thresholds["display_max_age_s"], "completion": a.completion,
        "scan_rate_hz": None if a.scan_rate_hz is None else round(a.scan_rate_hz, 2),
        "alignment_verified": a.alignment_verified, "points_frame": frame, "points": pts,
        "frame_warning": None if frame == "ROBOT" else "sensor frame: robot forward direction unknown",
        "tracks": tracks if usable else None, "frame": frame_info, "reason": a.reason,
        "person_distance_m": None,
    }


class ReplaySource:
    """Cycles a SIMULATED scenario at its own scan period, for the replay server and the dashboard.

    Byte-level scenarios (disconnect, timeout) are replayed as connection events.
    """

    def __init__(self, scenario: str, seed: int = 15, clock=time.monotonic_ns, wall=time.time):
        from .simulation import BYTE_LEVEL_SCENARIOS, SCENARIOS, generate, sim_config
        self.name = scenario
        self.cfg = sim_config()
        self.clock, self.wall = clock, wall
        self.event = None
        if scenario in BYTE_LEVEL_SCENARIOS:
            self.frames = generate("00_clear_room_control", seed)
            self.event = {"13_serial_disconnect": Connection.DISCONNECTED,
                          "14_device_timeout": Connection.TIMEOUT,
                          "19_corrupted_packets": None}[scenario]
        elif scenario in SCENARIOS:
            self.frames = generate(scenario, seed)
        else:
            raise KeyError(f"unknown scenario {scenario!r}")
        if scenario == "15_incorrect_orientation":
            self.cfg.mount.forward_offset_deg = 0.0     # the misconfiguration being demonstrated
        self.t0 = clock()
        self.assessor = LidarAssessor(self.cfg, clock_ns=clock)
        self.tracker = VisualTracker()
        self._last_i = None
        self._last_k = None
        self._scan: Optional[Scan] = None
        f = self.frames
        self.period_ns = (f[1][0].capture_start_mono_ns - f[0][0].capture_start_mono_ns) if len(f) > 1 \
            and f[1][0].capture_start_mono_ns > f[0][0].capture_start_mono_ns else 100_000_000
        self.last_assessment: Optional[LidarAssessment] = None

    def view(self, frame: Optional[int] = None) -> dict:
        """Current panel. ``frame`` pins a frame and uses a virtual clock (deterministic output)."""
        n = len(self.frames)
        if frame is not None:
            k = int(frame)
            scan0, now_rel = self.frames[k % n]
            lag = now_rel - scan0.capture_start_mono_ns
            now = self.t0 + k * self.period_ns + lag
        else:
            now = self.clock()
            k = int((now - self.t0) // self.period_ns)
        i = k % n
        scan0, now_rel = self.frames[i]
        lag = now_rel - scan0.capture_start_mono_ns
        if k != self._last_k:
            # New frame: re-time a copy so its age at assessment equals the scenario's delay.
            start = now - lag
            self._scan = dataclasses.replace(scan0, capture_start_mono_ns=start,
                                             capture_end_mono_ns=start + (scan0.capture_end_mono_ns
                                                                          - scan0.capture_start_mono_ns),
                                             capture_start_wall=self.wall() - lag / 1e9)
            if self.event is not None and i >= n - 1:
                a = self.assessor.status(self.event, reason=f"SIMULATED {self.event.value}", now_mono_ns=now)
                self._scan = None
            else:
                self.tracker.update(self._scan)
                a = self.assessor.update(self._scan, now_mono_ns=now)
        else:
            # Same frame polled again: only its age moves on.
            conn = self.event if (self.event is not None and self._scan is None) else Connection.SCANNING
            a = self.assessor.status(conn, now_mono_ns=now)
        self._last_i, self._last_k = i, k
        self.last_assessment = a
        return panel_view(a, self._scan, self.tracker.to_dict(),
                          {"scenario": self.name, "index": i + 1, "of": n}, fixture=True, mount=self.cfg.mount)

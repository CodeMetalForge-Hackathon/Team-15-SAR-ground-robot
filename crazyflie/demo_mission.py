#!/usr/bin/env python3
"""SAR demo: simulated by default; optional live drone, manually operated rover."""
from __future__ import annotations

import argparse
import importlib
import json
import math
from pathlib import Path
import sys
import time

if __package__:
    from .rssi_search import DiscoveryRSSI, SearchUnavailable, SimulatedRSSI, search
else:
    from rssi_search import DiscoveryRSSI, SearchUnavailable, SimulatedRSSI, search

INCH = 0.0254
SCENARIOS = ("injured", "safe", "hidden", "phone-only", "empty")


class ReturnRequired(Exception):
    """Flight budget or battery requires an immediate return/landing."""


class FakeLink:
    """Guide-compatible simulated flight link with a virtual clock."""
    def __init__(self):
        self.now, self.vbat = 0.0, 4.1
        self.position = (0.0, 0.0, 0.0, 0.0)
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.commands.append(("land",))
        self.position = (*self.position[:2], 0.0, self.position[3])

    def takeoff(self, height, duration):
        self.commands.append(("takeoff", height, duration))
        self.position = (0.0, 0.0, height, 0.0)

    def go_to(self, x, y, z, yaw, duration):
        self.commands.append(("go_to", x, y, z, yaw, duration))
        self.position = (x, y, z, yaw)

    def wait(self, seconds):
        self.now += seconds

    def pose(self):
        return self.position


class Flight:
    """Poll safety during every non-blocking command's wait period."""
    def __init__(self, link, clock, emit):
        self.link, self.clock, self.emit = link, clock, emit
        self.started = clock()

    def check(self, returning=False):
        elapsed = self.clock() - self.started
        if elapsed >= 140:  # leave ten seconds for the backend's landing
            raise ReturnRequired("Hard flight deadline: land immediately")
        voltage = self.link.vbat
        if voltage is None or not math.isfinite(voltage) or voltage < 3.3:
            raise ReturnRequired("Battery low/unavailable: land immediately")
        if not returning and elapsed >= 120:
            raise ReturnRequired("Two-minute search budget reached")

    def wait(self, seconds, returning=False):
        end = self.clock() + seconds
        while self.clock() < end:
            self.check(returning)
            self.link.wait(min(0.25, end - self.clock()))
        self.check(returning)

    def move(self, point, duration=3.0, returning=False):
        self.check(returning)
        if any(not math.isfinite(v) for v in point):
            raise ValueError("Non-finite waypoint")
        x, y, z = point
        if abs(x) > 1.5 or abs(y) > 1.5 or not 0 < z <= 1.2:
            raise ValueError("Waypoint outside flight envelope")
        self.emit("drone_waypoint", xyz_m=list(point))
        self.link.go_to(x, y, z, 0.0, duration)
        self.wait(duration + 0.5, returning)


def drone_target(target_inches, drone_right_inches, height):
    # Rover frame shares boot heading. Right is -y; translate to drone boot origin.
    x, y = target_inches
    return (x * INCH, (y + drone_right_inches) * INCH, height)


def fly(link, clock, emit, target, height, source=None, search_options=None):
    completed = True
    candidate = None
    source = source if source is not None else SimulatedRSSI(target)
    with link:
        flight = Flight(link, clock, emit)
        try:
            flight.check()
            emit("takeoff", height_m=height)
            link.takeoff(height, 2.0)
            flight.wait(2.5)
            candidate = search(flight, source, height, emit, **(search_options or {}))
            if candidate is not None:
                flight.move(candidate)
                emit("target_hover", candidate_xyz_m=list(candidate))
                flight.wait(2)
        except SearchUnavailable as exc:
            completed = False
            emit("search_unavailable", reason=str(exc))
        except ReturnRequired as exc:
            completed = False
            emit("flight_safety", reason=str(exc))
        try:
            # If battery/deadline is unsafe, check() refuses the trip and context lands.
            flight.move((0.0, 0.0, height), returning=True)
            emit("drone_returned", pose=list(link.pose()))
        except ReturnRequired as exc:
            completed = False
            emit("landing_in_place", reason=str(exc))
        emit("landing", message="Backend context exit must land and disconnect")
    emit("drone_grounded")
    return candidate if completed else None


def ask(prompt, choices):
    while True:
        answer = input(f"{prompt} [{'/'.join(choices)}]: ").strip().lower()
        if answer in choices:
            return answer
        print("Enter one of: " + ", ".join(choices))


def observe(scenario, manual, emit):
    emit("camera_on")
    if manual:
        input("Drive rover to the logged rover_move candidate coordinates, enable camera, then press Enter. ")
        human = ask("Is a human visible?", ("yes", "no")) == "yes"
        if not human:
            emit("rover_scan", degrees=360)
            input("Perform a full rover camera scan, then press Enter. ")
            human = ask("Is a human visible after the scan?", ("yes", "no")) == "yes"
        phone = ask("Is a phone visible?", ("yes", "no")) == "yes"
        condition = ask("Operator-observed condition", ("injured", "safe", "unknown")) if human else "unknown"
        if human:
            input("Use your separate phone/check-in system and inspect the colored indicator; press Enter. ")
    else:
        human = scenario in ("injured", "safe", "hidden")
        phone = scenario != "empty"
        condition = scenario if scenario in ("injured", "safe") else "unknown"
        if scenario in ("hidden", "phone-only", "empty"):
            emit("rover_scan", degrees=360)
        if human:
            emit("simulated_check_in", delivered=False, message="No phone messaging API configured")
    return dict(human_visible=human, phone_visible=phone, condition=condition)


def report(observation):
    if observation["human_visible"]:
        condition = observation["condition"]
        return (f"Human visible; condition: {condition}", "drone-and-rover")
    if observation["phone_visible"]:
        return ("Human not observed; phone visible", "drone-and-rover")
    return ("Human not observed; no phone visible", "drone-only")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Explicitly select default simulation")
    p.add_argument("--live-drone", action="store_true", help="Guide backend + manual rover/observations")
    p.add_argument("--discovery-url", default="http://127.0.0.1:8765")
    p.add_argument("--signal-id", help="Exact session ID from /api/discovery; unverified BLE target")
    p.add_argument("--scanner-on-drone", action="store_true", help="Confirm scanner moves with drone")
    p.add_argument("--sample-seconds", type=float, default=5.0)
    p.add_argument("--min-samples", type=int, default=8)
    p.add_argument("--search-step-m", type=float, default=0.6)
    p.add_argument("--search-rounds", type=int, choices=(1, 2), default=1)
    p.add_argument("--improvement-db", type=float, default=3.0)
    p.add_argument("--scenario", choices=SCENARIOS, default="injured")
    p.add_argument("--target-inches", type=float, nargs=2, default=(20.0, 5.0), metavar=("X", "Y"),
                   help="Hidden beacon position for simulation only; never a live waypoint")
    p.add_argument("--drone-right-inches", type=float, default=8.0)
    p.add_argument("--height-m", type=float, default=None)
    p.add_argument("--uri", default="radio://0/80/2M/E7E7E7E7E7")
    p.add_argument("--backend-module", default="sar_sim.backends.crazyflie_backend")
    p.add_argument("--log", type=Path, default=None, help="New JSONL event file (will not overwrite)")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.live_drone and args.dry_run:
        p.error("Choose either --dry-run or --live-drone")
    height = args.height_m if args.height_m is not None else 5 * INCH
    target = drone_target(args.target_inches, args.drone_right_inches, height)
    if (any(not math.isfinite(v) for v in (*target, args.drone_right_inches))
            or abs(target[0]) > 1.5 or abs(target[1]) > 1.5 or not 0 < height <= 1.2):
        p.error("Waypoints must be finite and within ±1.5 m XY, 0 < height ≤ 1.2 m")
    if args.live_drone and not 0.2 <= height <= 1.2:
        p.error("Live flight needs --height-m between 0.2 and 1.2 (e.g. --height-m 0.5)")
    if (not math.isfinite(args.sample_seconds) or not 3 <= args.sample_seconds <= 5
            or not 2 <= args.min_samples <= int(args.sample_seconds * 4)
            or not math.isfinite(args.search_step_m) or not 0.3 <= args.search_step_m <= 0.6
            or not math.isfinite(args.improvement_db) or args.improvement_db <= 0):
        p.error("Use 3–5 s windows, 2–4×seconds minimum samples, 0.3–0.6 m steps and positive dB margin")
    # Worst case: five samples plus two confirmation visits per round.
    if 2.5 + args.search_rounds * 7 * (3.5 + args.sample_seconds) + 5.5 > 115:
        p.error("Search exceeds reserved flight budget; use --sample-seconds 3 for two rounds")
    if args.live_drone and (not args.signal_id or not args.scanner_on_drone):
        p.error("Live search requires --signal-id and --scanner-on-drone")
    link = FakeLink()
    clock = lambda: link.now
    if args.live_drone:
        try:
            module = importlib.import_module(args.backend_module)
        except ImportError as exc:
            p.error(f"Guide backend unavailable: {exc}. Add its project to PYTHONPATH or use --dry-run.")
        print("LIVE DRONE / MANUAL ROVER: verify URI, positioning deck, origin, clear area and Gavin present.")
        if ask("Preflight complete and ready to fly?", ("yes", "no")) != "yes":
            return 1
        # The external backend must implement the guide's landing-on-exit contract.
        link = module.CrazyflieLink(args.uri)
        clock = time.monotonic
    source = DiscoveryRSSI(args.discovery_url, args.signal_id) if args.live_drone else SimulatedRSSI(target)
    search_options = dict(seconds=args.sample_seconds, min_samples=args.min_samples,
                          step=args.search_step_m, rounds=args.search_rounds,
                          improvement_db=args.improvement_db)
    start = clock()
    logfile = args.log.open("x", encoding="utf-8") if args.log else None

    def emit(event, **fields):
        row = dict(t_s=round(clock() - start, 3), mode="LIVE-DRONE/MANUAL-ROVER" if args.live_drone else "SIMULATED",
                   event=event, **fields)
        line = json.dumps(row)
        print(line, flush=True)
        if logfile:
            logfile.write(line + "\n")
            logfile.flush()

    try:
        emit("jetson_boot", status="manual_check_required" if args.live_drone else "simulated")
        if args.live_drone:
            input("Confirm Jetson boot and a fresh beacon trigger from the separate BLE dashboard; Enter. ")
        if args.live_drone:
            try:
                if source.read(None, clock()) is None:
                    emit("aborted", message="Selected beacon has no fresh reading; no takeoff")
                    return 1
            except SearchUnavailable as exc:
                emit("aborted", message=str(exc))
                return 1
        emit("beacon_trigger", source="operator" if args.live_drone else "fixture",
             message="RSSI is not distance, bearing, identity or proof of a human")
        emit("search_start", signal_id=args.signal_id, scanner="on-drone" if args.live_drone else "simulated",
             message="RSSI guidance uses unverified advertisements; no distance estimate")
        candidate = fly(link, clock, emit, target, height, source, search_options)
        if candidate is None:
            emit("aborted", message="No reliable candidate or flight safety event; rover not dispatched")
            return 1
        rover_xy = [candidate[0] / INCH, candidate[1] / INCH - args.drone_right_inches]
        emit("rover_move", target_xy_inches=rover_xy, execution="manual" if args.live_drone else "simulated")

        observation = observe(args.scenario, args.live_drone, emit)
        message, release = report(observation)
        emit("rover_return_home", execution="manual" if args.live_drone else "simulated")
        if args.live_drone:
            input("Return rover home and turn off its camera; press Enter. ")
        emit("camera_off")
        emit("operator_report", message=message, **observation,
             spot_cleared=False, proposed_next_search_assets=release,
             options=["search one more spot", "swap battery and relaunch", "end"])
        emit("end", message="Next-search choices are recommendations; no automatic relaunch")
        return 0
    except KeyboardInterrupt:
        emit("aborted", message="Flight context requests landing; manually stop the rover")
        return 130
    finally:
        if logfile:
            logfile.close()


if __name__ == "__main__":
    sys.exit(main())

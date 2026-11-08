"""Where ``GET /api/range`` gets its reading: the live services or a fixture.

Live: GET the ranging service (``team15.range_snapshot/1``) and/or the robot API
(``team15.robot_status/1``) with short timeouts, but only at URLs given
explicitly. There is no default: on the bench Mac, 127.0.0.1:8765 belongs to an
unrelated app. The Pi's ranging service is reached over an SSH tunnel to a free
local port, e.g. ``ssh -L 18765:127.0.0.1:8765 team15@<pi>`` then
``--range-url http://127.0.0.1:18765/range``. With no source configured, or if
none answers with the right schema (any non-200 included), the panel reads
DISCONNECTED. This module only makes HTTP
GETs: it never touches GPIO, motors or the gripper.

Fixture: a SIMULATED JSON file from the robotics repo, in one of three shapes:
``{"series": [snapshot, ...]}`` (cycled at the series' 0.1 s step),
``{"scenarios": {name: snapshot}}`` (pick with ``?scenario=``), or one snapshot.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from core import range_view

SERIES_STEP_S = 0.1
TIMEOUT_S = 0.3


def _get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310 (localhost only)
        body = json.loads(r.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("not a JSON object")
    return body


class RangeSource:
    def __init__(self, *, range_url: str | None = None, robot_url: str | None = None,
                 fixture: str | Path | None = None, robot_fixture: str | Path | None = None,
                 clock=time.time, fetch=_get_json, timeout: float = TIMEOUT_S):
        self.range_url, self.robot_url = range_url, robot_url
        self.clock, self.fetch, self.timeout = clock, fetch, timeout
        self.fixture = self._load(fixture)
        self.robot_fixture = self._load(robot_fixture)
        self.t0 = clock()

    @staticmethod
    def _load(path):
        if not path:
            return None
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))

    @property
    def fixture_mode(self) -> bool:
        return self.fixture is not None or self.robot_fixture is not None

    def _fixture_snapshot(self, scenario: str | None, frame: int | None):
        fx = self.fixture
        if fx is None:
            return None, None
        if isinstance(fx.get("series"), list) and fx["series"]:
            n = len(fx["series"])
            i = (frame if frame is not None
                 else int((self.clock() - self.t0) / SERIES_STEP_S)) % n
            return fx["series"][i], {"index": i + 1, "of": n}
        if isinstance(fx.get("scenarios"), dict) and fx["scenarios"]:
            names = list(fx["scenarios"])
            name = scenario if scenario in fx["scenarios"] else names[0]
            return fx["scenarios"][name], {"scenario": name, "scenarios": names}
        return (fx, None) if fx.get("schema") == "team15.range_snapshot/1" else (None, None)

    def _live(self, url):
        if not url:
            return None, "not configured"
        try:
            return self.fetch(url, self.timeout), None
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            return None, f"{url} unreachable: {getattr(e, 'reason', e)}"

    def view(self, scenario: str | None = None, frame: int | None = None) -> dict:
        now = self.clock()
        if self.fixture_mode:
            snap, info = self._fixture_snapshot(scenario, frame)
            robot = self.robot_fixture
            if snap is not None:
                v = range_view.from_snapshot(snap, now=now, fixture=True, robot=robot)
            elif robot is not None and robot.get("forward_range"):
                v = range_view.from_robot_status(robot, now=now, fixture=True)
            else:
                v = range_view.disconnected("fixture has no range snapshot", source="FIXTURE")
            v["frame"] = info
            return v
        if not (self.range_url or self.robot_url):
            return range_view.disconnected("no range source configured (--range-url / --robot-url)")
        snap, err = self._live(self.range_url)
        if snap is not None and snap.get("schema") != "team15.range_snapshot/1":
            snap, err = None, f"unexpected schema {snap.get('schema')!r}"
        robot, rerr = self._live(self.robot_url)
        if robot is not None and robot.get("schema") != "team15.robot_status/1":
            robot = None
        if snap is not None:
            return range_view.from_snapshot(snap, now=now, fixture=False, robot=robot)
        if robot is not None and robot.get("forward_range"):
            v = range_view.from_robot_status(robot, now=now, fixture=False)
            v["reason"] = f"ranging service: {err}; showing robot API reading"
            return v
        return range_view.disconnected(f"ranging service: {err}; robot API: {rerr}")

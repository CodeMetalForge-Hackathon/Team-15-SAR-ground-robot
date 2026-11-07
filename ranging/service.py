"""Range service: one process owns the sensor; everyone else reads snapshots.

The sampler thread pings the driver every ``sample_interval_s``, feeds the
obstacle assessor and publishes a snapshot (``team15.range_snapshot/1``):
  * in memory (``RangeService.snapshot()``),
  * as an atomically replaced JSON file (default /dev/shm/team15_range.json on the Pi),
  * over HTTP (``GET /range``, ``GET /health``) on localhost by default,
  * as an append-only JSONL evidence log outside Git.

Consumers (navigation, dashboard, Qwen tools) never touch GPIO. ``RangeClient``
re-checks freshness on the consumer side, so a dead service turns into UNKNOWN.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from .config import SensorConfig
from .drivers import RangeDriver, make_driver
from .obstacle import FORWARD_ALLOWED, ObstacleAssessor, ObstacleConfig, ObstacleStatus
from .reading import MeasurementStatus, RangeReading, utc_iso

SCHEMA = "team15.range_snapshot/1"
DEFAULT_SNAPSHOT_PATH = "/dev/shm/team15_range.json" if os.path.isdir("/dev/shm") else \
    os.path.join(os.path.expanduser("~"), ".team15_range.json")
DEFAULT_EVIDENCE_DIR = os.path.expanduser("~/Team15_evidence/range")
DEFAULT_PORT = 8765

log = logging.getLogger("ranging.service")


class JsonLogFormatter(logging.Formatter):
    def format(self, rec: logging.LogRecord) -> str:
        d = {"t": utc_iso(rec.created), "level": rec.levelname, "logger": rec.name, "msg": rec.getMessage()}
        if isinstance(getattr(rec, "fields", None), dict):
            d.update(rec.fields)
        return json.dumps(d)


class _StderrHandler(logging.StreamHandler):
    """Always writes to the current sys.stderr (survives stream swaps)."""

    @property
    def stream(self):
        import sys
        return sys.stderr

    @stream.setter
    def stream(self, _):
        pass


def setup_logging(level: str = "INFO") -> None:
    h = _StderrHandler()
    h.setFormatter(JsonLogFormatter())
    root = logging.getLogger("ranging")
    root.handlers[:] = [h]
    root.setLevel(level)
    root.propagate = False


def _atomic_write_json(path: str, obj: dict) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


class RangeService:
    FAULT_AFTER = 10      # consecutive invalid readings -> health FAULT
    DEGRADED_AFTER = 1

    def __init__(self, sensor_cfg: SensorConfig, obstacle_cfg: Optional[ObstacleConfig] = None,
                 driver: Optional[RangeDriver] = None, snapshot_path: Optional[str] = DEFAULT_SNAPSHOT_PATH,
                 evidence_dir: Optional[str] = None, platform: Optional[str] = None,
                 on_snapshot: Optional[Callable[[dict], None]] = None):
        self.cfg = sensor_cfg.validate()
        ocfg = obstacle_cfg or ObstacleConfig()
        ocfg.sample_interval_s = self.cfg.sample_interval_s
        self.assessor = ObstacleAssessor(ocfg)
        self.driver = driver or make_driver(self.cfg)
        self.snapshot_path = snapshot_path
        self.on_snapshot = on_snapshot
        self.boot_id = f"r{int(time.time())}-{uuid.uuid4().hex[:6]}"
        live = self.driver.name != "simulated"
        self.provenance = {
            "source_mode": "LIVE-HW" if live else "SIMULATED",
            "platform": platform or ("BENCH" if live else "SIM"),
            "source": self.cfg.source,
            "driver": self.driver.name,
            "host": socket.gethostname(),
            "gpiochip": self.cfg.gpiochip if live else None,
            "gpio_bcm": self.cfg.electrical.gpio_bcm if live else None,
            "wiring_verified_by": self.cfg.electrical.wiring_verified_by if live else None,
            "service_boot_id": self.boot_id,
            "config_sha256": hashlib.sha256(json.dumps(
                {"sensor": self.cfg.to_dict(), "obstacle": vars(ocfg)}, sort_keys=True, default=str
            ).encode()).hexdigest()[:16],
        }
        self.counts = {s.value: 0 for s in MeasurementStatus}
        self.consecutive_invalid = 0
        self.last_error: Optional[str] = None
        self.run_counts: dict = {}
        self.last_invalid_status: Optional[str] = None               # statuses in the current run of invalid readings
        self.last_echo_mono_ns: Optional[int] = None  # last ping with physical echo evidence
        self._lock = threading.Lock()
        self._snap: Optional[dict] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._evidence = None
        if evidence_dir:
            os.makedirs(evidence_dir, exist_ok=True)
            self._evidence = open(os.path.join(evidence_dir, f"range_{self.boot_id}.jsonl"), "a")
        self._publish(None)

    # -- health ------------------------------------------------------------
    # Statuses that prove the sensor drove SIG high (it is powered and connected).
    ECHO_EVIDENCE = {MeasurementStatus.VALID, MeasurementStatus.OUT_OF_RANGE, MeasurementStatus.BELOW_MIN_RANGE,
                     MeasurementStatus.ECHO_TIMEOUT, MeasurementStatus.MISSED_ECHO_START}

    def _diagnosis(self) -> dict:
        """Name the likely cause of the current invalid run, only as far as the evidence supports.

        This is diagnostics only. Every one of these conditions is UNKNOWN for motion (STOP).
        """
        if self.consecutive_invalid == 0:
            return {"code": "NONE", "evidence": None}
        dom = self.last_invalid_status          # the current condition; counts below are context
        n = self.run_counts.get(dom, 0)
        since = None if self.last_echo_mono_ns is None else round((time.monotonic_ns() - self.last_echo_mono_ns) / 1e9, 2)
        ev = {"latest_status": dom, "count_in_run": n, "run_counts": dict(self.run_counts), "run_length": self.consecutive_invalid,
              "last_echo_evidence_age_s": since}
        codes = {
            "ECHO_TIMEOUT": ("ECHO_NOT_ENDING", "echo started but SIG stayed high past the max-range time"),
            "OUT_OF_RANGE": ("TARGET_BEYOND_RANGE", "sensor answered with an echo longer than the max range: "
                             "sensor is alive, nearest return is beyond max_range_m"),
            "BELOW_MIN_RANGE": ("TARGET_TOO_CLOSE", "echo shorter than min_range_m: object at the sensor face or crosstalk"),
            "MISSED_ECHO_START": ("RELEASE_TOO_SLOW", "falling edge seen without its rising edge: SIG was released "
                                  "after the echo began (see reading extra.release_us)"),
            "LINE_STUCK_HIGH": ("LINE_FAULT", "SIG high before the trigger: short to VCC, wrong pin, or a long echo still running"),
            "DRIVER_ERROR": ("DRIVER_FAULT", self.last_error or "GPIO request/read failed"),
        }
        if dom in codes:
            code, why = codes[dom]
        elif dom == "NO_ECHO" and self.last_echo_mono_ns is None:
            code, why = ("NO_RESPONSE_EVER", "SIG never went high since the service started. Consistent with an "
                         "unplugged/unpowered sensor or a wrong pin. Software cannot tell this apart from "
                         "'nothing in range' until the board's no-target behaviour is characterised (WIRING.md 6.2)")
        elif dom == "NO_ECHO":
            code, why = ("NO_RESPONSE_AFTER_ECHOES", "the sensor did answer earlier, now no echo starts. Consistent "
                         "with open space, a soft or angled target, or a connection lost since then")
        else:
            code, why = ("INVALID", dom)
        return {"code": code, "explanation": why, "evidence": ev, "motion": "STOP (UNKNOWN)"}

    def _health(self) -> dict:
        if self.counts[MeasurementStatus.VALID.value] == 0 and self.consecutive_invalid == 0:
            state = "STARTING"
        elif self.consecutive_invalid >= self.FAULT_AFTER:
            state = "FAULT"
        elif self.consecutive_invalid >= self.DEGRADED_AFTER:
            state = "DEGRADED"
        else:
            state = "OK"
        return {"state": state, "consecutive_invalid": self.consecutive_invalid, "counts": dict(self.counts),
                "last_error": self.last_error, "reopen_count": getattr(self.driver, "reopen_count", 0),
                "diagnosis": self._diagnosis()}

    def _publish(self, assessment) -> dict:
        now_wall, now_mono = time.time(), time.monotonic_ns()
        a = assessment.to_dict() if assessment is not None else None
        status = a["status"] if a else ObstacleStatus.UNKNOWN.value
        snap = {
            "schema": SCHEMA,
            "sensor_id": self.cfg.sensor_id,
            "sensor_type": "GROVE_ULTRASONIC",
            "measurement_type": "FORWARD_OBSTACLE_RANGE",
            "sensor_mount": self.cfg.sensor_mount,
            "published_at": utc_iso(now_wall),
            "published_time": round(now_wall, 6),
            "published_mono_ns": now_mono,
            "obstacle_status": status,
            "forward_motion_allowed": bool(a and a["forward_motion_allowed"]),
            "range_m": a["nearest_range_m"] if a else None,
            "valid": bool(a and a["latest"] and a["latest"]["valid"]),
            "obs_time": a["latest"]["obs_time"] if a and a["latest"] else None,
            "stale_after_s": self.assessor.cfg.stale_after_s,
            "latest": a["latest"] if a else None,
            "assessment": a,
            "geometry": self.assessor.cfg.geometry(),
            "health": self._health(),
            "provenance": self.provenance,
        }
        with self._lock:
            self._snap = snap
        if self.snapshot_path:
            try:
                _atomic_write_json(self.snapshot_path, snap)
            except OSError as e:
                log.warning("snapshot write failed: %s", e)
        if self.on_snapshot:
            self.on_snapshot(snap)
        return snap

    # -- sampling ----------------------------------------------------------
    def step(self) -> dict:
        """Take one reading, assess, publish. Returns the snapshot."""
        try:
            r = self.driver.measure()
        except Exception as e:  # drivers should not raise; belt and braces
            self.last_error = f"{type(e).__name__}: {e}"
            r = RangeReading(MeasurementStatus.DRIVER_ERROR, None, time.time(), time.monotonic_ns(),
                             source=self.cfg.source, sensor_id=self.cfg.sensor_id, driver=self.driver.name,
                             detail=self.last_error)
        self.counts[r.status.value] += 1
        if r.status in self.ECHO_EVIDENCE:
            self.last_echo_mono_ns = r.mono_ns
        if r.valid:
            self.consecutive_invalid = 0
            self.run_counts = {}
        else:
            self.consecutive_invalid += 1
            self.run_counts[r.status.value] = self.run_counts.get(r.status.value, 0) + 1
            self.last_invalid_status = r.status.value
            if r.status is MeasurementStatus.DRIVER_ERROR:
                self.last_error = r.detail
        a = self.assessor.update(r)
        if self._evidence:
            self._evidence.write(json.dumps({"reading": r.to_dict(), "status": a.status.value,
                                             "nearest_range_m": a.nearest_range_m}) + "\n")
            self._evidence.flush()
        log.debug("reading", extra={"fields": {"status": r.status.value, "d": r.distance_m, "obst": a.status.value}})
        if r.status is not MeasurementStatus.VALID and self.consecutive_invalid in (1, self.FAULT_AFTER):
            log.warning("invalid reading", extra={"fields": {"status": r.status.value, "detail": r.detail,
                                                              "consecutive": self.consecutive_invalid}})
        return self._publish(a)

    def _run(self) -> None:
        nxt = time.monotonic()
        backoff = 0.0
        while not self._stop.is_set():
            snap = self.step()
            if snap["latest"] and snap["latest"]["measurement_status"] == "DRIVER_ERROR":
                backoff = min(2.0, max(0.2, backoff * 2))     # GPIO reopen backoff
            else:
                backoff = 0.0
            nxt += self.cfg.sample_interval_s + backoff
            delay = nxt - time.monotonic()
            if delay < 0:                     # overran: do not burst to catch up
                nxt, delay = time.monotonic(), 0
            self._stop.wait(delay)

    def start(self) -> "RangeService":
        self._thread = threading.Thread(target=self._run, name="range-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.driver.close()
        if self._evidence:
            self._evidence.close()

    def snapshot(self) -> dict:
        """Latest snapshot with consumer-side freshness re-applied (see apply_freshness)."""
        with self._lock:
            snap = dict(self._snap)
        return apply_freshness(snap, now_mono_ns=time.monotonic_ns())


def apply_freshness(snap: dict, now_mono_ns: Optional[int] = None, now_wall: Optional[float] = None) -> dict:
    """Recompute age from the reading time. Stale -> UNKNOWN, forward motion denied.

    Same host: uses the reading's monotonic clock (immune to NTP steps).
    Other host: uses wall-clock obs_time (requires NTP on both ends).
    """
    snap = dict(snap)
    latest = snap.get("latest") or {}
    stale_after = float(snap.get("stale_after_s") or 0.5)
    age = None
    if latest.get("mono_ns") is not None and now_mono_ns is not None and \
            snap.get("provenance", {}).get("host") == socket.gethostname():
        age = (now_mono_ns - int(latest["mono_ns"])) / 1e9
    elif latest.get("obs_time") is not None:
        age = (now_wall if now_wall is not None else time.time()) - float(latest["obs_time"])
    stale = age is None or age > stale_after or age < -1.0
    snap["freshness"] = {"age_s": None if age is None else round(age, 3), "stale": stale,
                         "stale_after_s": stale_after, "checked_at": utc_iso(time.time())}
    if stale:
        snap["obstacle_status"] = ObstacleStatus.UNKNOWN.value
        snap["forward_motion_allowed"] = False
        snap["range_m"] = None
    snap["forward_motion_allowed"] = bool(snap.get("forward_motion_allowed")) and \
        FORWARD_ALLOWED.get(ObstacleStatus(snap.get("obstacle_status", "UNKNOWN")), False)
    return snap


UNKNOWN_SNAPSHOT_REASON = "range service unreachable or snapshot unreadable"


def unknown_snapshot(reason: str) -> dict:
    return {"schema": SCHEMA, "obstacle_status": "UNKNOWN", "forward_motion_allowed": False, "range_m": None,
            "valid": False, "latest": None, "error": reason,
            "freshness": {"age_s": None, "stale": True, "checked_at": utc_iso(time.time())}}


class RangeClient:
    """What the navigation worker uses. Every failure path returns UNKNOWN / not allowed.

    RangeClient(path="/dev/shm/team15_range.json")       # same Pi, no network
    RangeClient(url="http://127.0.0.1:8765/range")        # HTTP
    """

    def __init__(self, path: Optional[str] = None, url: Optional[str] = None, timeout_s: float = 0.2):
        if not (path or url):
            path = DEFAULT_SNAPSHOT_PATH
        self.path, self.url, self.timeout_s = path, url, timeout_s

    def get(self) -> dict:
        try:
            if self.url:
                with urllib.request.urlopen(self.url, timeout=self.timeout_s) as resp:
                    snap = json.load(resp)
            else:
                with open(self.path) as f:
                    snap = json.load(f)
            if snap.get("schema") != SCHEMA:
                return unknown_snapshot(f"unexpected schema {snap.get('schema')!r}")
            return apply_freshness(snap, now_mono_ns=time.monotonic_ns())
        except Exception as e:  # noqa: any failure is UNKNOWN
            return unknown_snapshot(f"{UNKNOWN_SNAPSHOT_REASON}: {type(e).__name__}: {e}")

    def forward_motion_allowed(self) -> bool:
        return bool(self.get().get("forward_motion_allowed"))


# ---------------------------------------------------------------------------- HTTP

def make_http_server(service: RangeService, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                     cors_origin: Optional[str] = None) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            if cors_origin:
                self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/range":
                self._send(200, service.snapshot())
            elif path == "/health":
                s = service.snapshot()
                self._send(200, {"health": s["health"], "freshness": s["freshness"], "provenance": s["provenance"]})
            else:
                self._send(404, {"error": "not found", "endpoints": ["/range", "/health"]})

        def log_message(self, *a):  # keep stdout clean
            pass

    return ThreadingHTTPServer((host, port), H)

"""Raspberry Pi camera source: timestamped JPEG frames over SSH (LIVE-HW bench).

The Mac runs ``ssh <pi> python3 -u - <args>`` and feeds ``SENDER_SCRIPT`` on
stdin. The script runs only in memory on the Pi: nothing is installed or written
there. It captures with picamera2 and writes this stream on stdout:

    T15HELLO {json}\\n                     once: sensor model, Pi model, clock info
    T15FRAME {json}\\n<len bytes of JPEG>   per frame: seq, t_capture, clock, len

``t_capture`` is the Pi's capture time of that frame (picamera2
``SensorTimestamp`` mapped to the Pi wall clock, which is NTP-synchronised).
The detector uses it as ``obs_time``, not the Mac arrival time.

``PiCameraSource`` exposes the same ``read()`` / ``release()`` / ``isOpened()``
interface as ``cv2.VideoCapture``. A reader thread keeps only the newest
decoded frame, so relay bursts never build a backlog, and ``read()`` never
returns the same frame twice. Malformed headers, truncated or undecodable JPEGs
are skipped and counted. If SSH drops, it reconnects up to ``max_reconnects``
times and then reports itself closed.

SSH runs with ``BatchMode=yes``: no password prompts, and host-key checking is
left at the user's setting (an unknown host key fails instead of being trusted).
Host, user and key come from arguments or TEAM15_PI_HOST / TEAM15_PI_USER /
TEAM15_PI_KEY. Nothing is hard-coded.
"""
from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import threading
import time
from typing import IO, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

HELLO_TAG = b"T15HELLO "
FRAME_TAG = b"T15FRAME "
MAX_HEADER_BYTES = 4096
MAX_JPEG_BYTES = 8 * 1024 * 1024
ROTATIONS = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
             270: cv2.ROTATE_90_COUNTERCLOCKWISE}
ENV_HOST, ENV_USER, ENV_KEY = "TEAM15_PI_HOST", "TEAM15_PI_USER", "TEAM15_PI_KEY"

# Runs on the Pi from stdin (python3 -u - W H FPS QUALITY). Uses only what is
# already installed there (picamera2, OpenCV). Writes nothing to the Pi's disk.
SENDER_SCRIPT = r'''
import json, os, sys, time
os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "*:WARN")  # this process only
import cv2
from picamera2 import Picamera2

w, h, fps, q = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
out = sys.stdout.buffer
info = Picamera2.global_camera_info()
if not info:
    sys.stderr.write("T15ERR no camera detected by libcamera\n"); sys.exit(4)
try:
    pi_model = open("/proc/device-tree/model").read().strip("\x00\n ")
except OSError:
    pi_model = None
cam = Picamera2(0)
cfg = cam.create_video_configuration(
    main={"size": (w, h), "format": "RGB888"}, buffer_count=4,
    controls={"FrameDurationLimits": (int(1e6 / fps), int(1e6 / fps))})
cam.configure(cfg)
cam.start()
def offset():
    # SensorTimestamp is a CLOCK_MONOTONIC ns stamp (V4L2 buffer time); map it
    # to wall time. Take the
    # tightest of a few samples so the offset error is microseconds.
    best = None
    for _ in range(5):
        a = time.time(); b = time.monotonic(); c = time.time()
        if best is None or c - a < best[0]:
            best = (c - a, (a + c) / 2 - b)
    return best[1]
off = offset()
hello = {"sensor_model": info[0].get("Model"), "pi_model": pi_model,
         "size": [w, h], "fps": fps, "jpeg_quality": q,
         "clock": "SensorTimestamp+CLOCK_MONOTONIC->wall", "t_start": time.time()}
out.write(b"T15HELLO " + json.dumps(hello).encode() + b"\n"); out.flush()
seq, period, next_t = 0, 1.0 / fps, time.time()
while True:
    req = cam.capture_request()
    try:
        arr = req.make_array("main")
        md = req.get_metadata()
    finally:
        req.release()
    now = time.time()
    if seq % 50 == 0:
        off = offset()
    ts = md.get("SensorTimestamp")
    t_cap, clock = (ts / 1e9 + off, "sensor") if ts else (now, "pi_wall_at_request")
    if abs(t_cap - now) > 5.0:  # mapping looks wrong: fall back, and say so
        t_cap, clock = now, "pi_wall_at_request"
    ok, jpg = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, q])
    if ok:
        seq += 1
        data = jpg.tobytes()
        hdr = {"seq": seq, "t_capture": t_cap, "clock": clock, "len": len(data),
               "exposure_us": md.get("ExposureTime")}
        out.write(b"T15FRAME " + json.dumps(hdr).encode() + b"\n" + data); out.flush()
    next_t += period
    delay = next_t - time.time()
    if delay > 0:
        time.sleep(delay)
    else:
        next_t = time.time()
'''


class PiSourceError(RuntimeError):
    """The Pi stream could not be started or produced no frames."""


def parse_size(s: str) -> Tuple[int, int]:
    try:
        w, h = (int(v) for v in s.lower().split("x"))
    except ValueError:
        raise ValueError(f"size must look like 1280x720, got {s!r}") from None
    if not (64 <= w <= 4608 and 64 <= h <= 2592):
        raise ValueError(f"size out of range: {s!r}")
    return w, h


def rotate(frame: np.ndarray, degrees: int) -> np.ndarray:
    if degrees not in ROTATIONS:
        raise ValueError(f"rotation must be one of {sorted(ROTATIONS)}, got {degrees}")
    code = ROTATIONS[degrees]
    return frame if code is None else cv2.rotate(frame, code)


def build_ssh_command(host: str, *, user: Optional[str] = None, key: Optional[str] = None,
                      port: Optional[int] = None, connect_timeout_s: int = 10,
                      remote_args: Sequence[str] = ()) -> List[str]:
    """ssh argv that runs the sender from stdin. Never weakens host-key checks."""
    if not host:
        raise ValueError(f"no Pi host: pass --pi-host or set {ENV_HOST}")
    cmd = ["ssh", "-T", "-o", "BatchMode=yes",
           "-o", f"ConnectTimeout={int(connect_timeout_s)}",
           "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3"]
    if key:
        cmd += ["-i", os.path.expanduser(key), "-o", "IdentitiesOnly=yes"]
    if port:
        cmd += ["-p", str(int(port))]
    target = f"{user}@{host}" if user else host
    return cmd + [target, "python3", "-u", "-", *map(str, remote_args)]


class _BadStream(Exception):
    pass


def _read_exact(f: IO[bytes], n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return bytes(buf)


def read_message(f: IO[bytes]) -> Tuple[str, dict, Optional[bytes]]:
    """Read one message. Returns (kind, header, jpeg). Raises EOFError at end of
    stream and _BadStream on a malformed message (the caller resynchronises:
    the next read scans forward to the next tagged header line)."""
    line = f.readline(MAX_HEADER_BYTES + 16)
    if not line:
        raise EOFError
    if line.startswith(HELLO_TAG):
        try:
            return "hello", json.loads(line[len(HELLO_TAG):]), None
        except ValueError as e:
            raise _BadStream(f"bad hello: {e}") from None
    if not line.startswith(FRAME_TAG):
        raise _BadStream("untagged line")
    try:
        hdr = json.loads(line[len(FRAME_TAG):])
        n = int(hdr["len"])
        float(hdr["t_capture"])
    except (ValueError, KeyError, TypeError) as e:
        raise _BadStream(f"bad frame header: {e}") from None
    if not 0 < n <= MAX_JPEG_BYTES:
        raise _BadStream(f"bad frame length {n}")
    return "frame", hdr, _read_exact(f, n)


class PiCameraSource:
    """cv2.VideoCapture-like reader for the Pi JPEG-over-SSH stream."""

    def __init__(self, host: Optional[str] = None, *, user: Optional[str] = None,
                 key: Optional[str] = None, port: Optional[int] = None,
                 size: Tuple[int, int] = (1280, 720), fps: float = 5.0,
                 jpeg_quality: int = 80, rotation: int = 180,
                 connect_timeout_s: int = 10, max_reconnects: int = 3,
                 command: Optional[Sequence[str]] = None,
                 script: str = SENDER_SCRIPT, log=None) -> None:
        if rotation not in ROTATIONS:
            raise ValueError(f"rotation must be one of {sorted(ROTATIONS)}")
        self.host = host if host is not None else os.environ.get(ENV_HOST)
        self.user = user if user is not None else os.environ.get(ENV_USER)
        self.key = key if key is not None else os.environ.get(ENV_KEY)
        self.port, self.size, self.fps = port, size, fps
        self.jpeg_quality, self.rotation = jpeg_quality, rotation
        self.connect_timeout_s, self.max_reconnects = connect_timeout_s, max_reconnects
        self._script = script
        remote = [size[0], size[1], fps, jpeg_quality]
        self._cmd = list(command) if command is not None else build_ssh_command(
            self.host, user=self.user, key=self.key, port=port,
            connect_timeout_s=connect_timeout_s, remote_args=remote)
        self._log = log or (lambda m: print(m, file=sys.stderr, flush=True))
        self._cond = threading.Condition()
        # (frame, header, rx_time, local counter). The counter, not the Pi's seq,
        # decides "new frame": the Pi's seq restarts at 1 after a reconnect.
        self._latest: Optional[Tuple[np.ndarray, dict, float, int]] = None
        self._n_in = 0
        self._delivered_n = 0
        self._closed = False
        self._dead = False
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self.stderr_tail: collections.deque = collections.deque(maxlen=20)
        self.hello: Optional[dict] = None
        self.stats: Dict[str, int] = {"frames_received": 0, "frames_delivered": 0,
                                      "frames_dropped_stale": 0, "malformed": 0,
                                      "decode_failures": 0, "reconnects": 0}
        # set by read(); None until a frame is delivered
        self.last_capture_time: Optional[float] = None
        self.last_rx_time: Optional[float] = None
        self.last_header: Optional[dict] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "PiCameraSource":
        self._spawn()
        self._reader = threading.Thread(target=self._run, name="pi-source", daemon=True)
        self._reader.start()
        return self

    def _spawn(self) -> None:
        self._proc = subprocess.Popen(self._cmd, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      bufsize=0)
        proc = self._proc
        threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()
        try:
            proc.stdin.write(self._script.encode())
            proc.stdin.close()  # EOF: python3 - starts running the script
        except (BrokenPipeError, OSError):
            pass  # process died at once; the reader sees EOF and reports it

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode(errors="replace").rstrip()
            if line:
                self.stderr_tail.append(line)
                self._log(f"[pi] {line}")

    def _stop_proc(self) -> None:
        p = self._proc
        if p is None:
            return
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=3)
        for s in (p.stdout, p.stderr):
            try:
                s.close()
            except Exception:
                pass

    def release(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        self._stop_proc()
        if self._reader is not None:
            self._reader.join(timeout=5)

    def isOpened(self) -> bool:  # noqa: N802 (cv2.VideoCapture interface)
        return not self._closed and not self._dead

    # -- reader thread -----------------------------------------------------
    # a connection that streamed this long earns a fresh reconnect budget
    STABLE_S = 30.0

    def _run(self) -> None:
        attempts = 0
        while not self._closed:
            t_conn = time.time()
            got_frame = self._pump(self._proc)
            if self._closed:
                break
            rc = self._proc.poll()
            self._stop_proc()
            if got_frame and time.time() - t_conn >= self.STABLE_S:
                attempts = 0
            if attempts >= self.max_reconnects:
                self._log(f"[pi] stream ended (ssh rc={rc}); giving up after "
                          f"{attempts} reconnect(s). Last stderr: "
                          f"{list(self.stderr_tail)[-3:]}")
                break
            attempts += 1
            self.stats["reconnects"] += 1
            self._log(f"[pi] stream ended (ssh rc={rc}); reconnect "
                      f"{attempts}/{self.max_reconnects}")
            time.sleep(min(2.0 * attempts, 6.0))
            if self._closed:
                break
            try:
                self._spawn()
            except OSError as e:
                self._log(f"[pi] could not start ssh: {e}")
                break
        with self._cond:
            self._dead = True
            self._cond.notify_all()

    def _pump(self, proc: subprocess.Popen) -> bool:
        got = False
        f = proc.stdout
        while not self._closed:
            try:
                kind, hdr, data = read_message(f)
            except EOFError:
                return got
            except (_BadStream, ValueError) as e:
                self.stats["malformed"] += 1
                if self.stats["malformed"] <= 5:
                    self._log(f"[pi] skipped malformed data: {e}")
                continue
            except (OSError, AttributeError):
                return got
            rx = time.time()
            if kind == "hello":
                self.hello = hdr
                self._log(f"[pi] connected: {json.dumps(hdr)}")
                continue
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                self.stats["decode_failures"] += 1
                continue
            img = rotate(img, self.rotation)
            got = True
            with self._cond:
                self.stats["frames_received"] += 1
                if self._latest is not None and self._latest[3] != self._delivered_n:
                    self.stats["frames_dropped_stale"] += 1
                self._n_in += 1
                self._latest = (img, hdr, rx, self._n_in)
                self._cond.notify_all()
        return got

    # -- consumer ----------------------------------------------------------
    def read(self, timeout_s: float = 3.0) -> Tuple[bool, Optional[np.ndarray]]:
        """Newest frame not yet returned, waiting up to ``timeout_s``."""
        deadline = time.time() + timeout_s
        with self._cond:
            while True:
                if self._closed:
                    return False, None
                lat = self._latest
                if lat is not None and lat[3] != self._delivered_n:
                    img, hdr, rx, n = lat
                    self._delivered_n = n
                    self.last_capture_time = float(hdr["t_capture"])
                    self.last_rx_time = rx
                    self.last_header = hdr
                    self.stats["frames_delivered"] += 1
                    return True, img
                if self._dead:
                    return False, None
                left = deadline - time.time()
                if left <= 0:
                    return False, None
                self._cond.wait(left)

    def wait_first_frame(self, timeout_s: float) -> None:
        """Block until a frame is available (not consumed), else PiSourceError."""
        deadline = time.time() + timeout_s
        with self._cond:
            while self._latest is None:
                if self._dead or self._closed:
                    break
                left = deadline - time.time()
                if left <= 0:
                    break
                self._cond.wait(left)
            if self._latest is not None:
                return
        tail = "; ".join(list(self.stderr_tail)[-3:]) or "no output"
        raise PiSourceError(f"no frame from the Pi within {timeout_s:.0f}s "
                            f"(ssh stderr: {tail})")

    # -- provenance --------------------------------------------------------
    def camera_info(self) -> dict:
        """Provenance for ``evidence.camera`` of the last delivered frame."""
        h = self.hello or {}
        sensor = (h.get("sensor_model") or "unknown").lower()
        pi = h.get("pi_model") or ""
        board = "pi5" if "Raspberry Pi 5" in pi else ("pi" if pi else "pi-unknown")
        hdr = self.last_header or {}
        delay = (None if self.last_rx_time is None or self.last_capture_time is None
                 else round(self.last_rx_time - self.last_capture_time, 3))
        return {
            "source": f"{board}-{sensor}",
            "device": "Raspberry Pi camera (remote, bench)",
            "pi_model": h.get("pi_model"),
            "sensor_model": h.get("sensor_model"),
            "transport": "ssh-jpeg",
            "stream_size": list(h.get("size") or self.size),
            "stream_fps": h.get("fps", self.fps),
            "jpeg_quality": h.get("jpeg_quality", self.jpeg_quality),
            "rotation_deg": self.rotation,
            "rotation_applied_by": "receiver",
            "capture_clock": hdr.get("clock"),
            "pi_frame_seq": hdr.get("seq"),
            "capture_time": self.last_capture_time,
            "rx_time": None if self.last_rx_time is None else round(self.last_rx_time, 3),
            "capture_to_rx_s": delay,
        }


def open_pi_camera(*, startup_timeout_s: float = 30.0, **kw) -> PiCameraSource:
    src = PiCameraSource(**kw).start()
    try:
        src.wait_first_frame(startup_timeout_s)
    except PiSourceError:
        src.release()
        raise
    return src

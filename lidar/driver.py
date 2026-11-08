"""RPLIDAR C1 driver over a byte transport (pyserial on the Pi, MockLidarDevice in CI).

    cfg = LidarConfig.load("lidar/configs/c1_pi5.UNVERIFIED.json")   # hardware: gate must pass
    with RplidarC1Driver(cfg) as drv:          # connect(): STOP, GET_INFO, GET_HEALTH
        drv.start_scan()
        scan = drv.read_scan()                 # one revolution, timestamped, or raises
    # __exit__ always sends STOP and closes the port, even after an exception.

States: DISCONNECTED -> CONNECTED -> SCANNING -> (CONNECTED | DISCONNECTED | HEALTH_ERROR).
Errors:
  * LidarDisconnected: the transport failed (unplug, power loss). The port is closed.
  * LidarTimeout: no complete revolution within ``scan_timeout_s``.
  * LidarHealthError: GET_HEALTH not GOOD, or a GET_INFO model mismatch. Scanning is refused.
  * HardwareGateError (from config): hardware mode with an incomplete checklist. Nothing is opened.
The driver never moves anything. The C1's motor spins only while scanning, and STOP stops it.
"""
from __future__ import annotations

import socket
import time
from enum import Enum
from typing import Callable, Optional

from . import protocol as P
from .config import LidarConfig
from .scan import Scan, ScanCompletion, SourceMode, build_scan
from .transport import SerialTransport, TransportClosed

MAX_CORRUPT_FRACTION = 0.05   # more than this in one revolution and the scan is marked PARTIAL


class DriverState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    SCANNING = "SCANNING"
    HEALTH_ERROR = "HEALTH_ERROR"


class LidarError(RuntimeError):
    pass


class LidarDisconnected(LidarError):
    pass


class LidarTimeout(LidarError):
    pass


class LidarHealthError(LidarError):
    pass


class RplidarC1Driver:
    def __init__(self, cfg: LidarConfig, transport_factory: Optional[Callable] = None,
                 clock_ns: Callable[[], int] = time.monotonic_ns, wall: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, host: Optional[str] = None,
                 source_mode: Optional[SourceMode] = None):
        self.cfg = cfg.validate()      # hardware mode: raises HardwareGateError before any I/O
        if transport_factory is None:
            if cfg.mode != "hardware":
                raise LidarError("simulated mode needs an explicit (mock) transport factory")
            transport_factory = SerialTransport
        self._factory = transport_factory
        self.clock_ns, self.wall, self.sleep = clock_ns, wall, sleep
        self.host = host or socket.gethostname()
        # A mock transport is SIMULATED; a real device is at best HARDWARE_UNVERIFIED in this PR.
        self.source_mode = source_mode or (SourceMode.HARDWARE_UNVERIFIED if cfg.mode == "hardware"
                                           else SourceMode.SIMULATED)
        if self.source_mode is SourceMode.HARDWARE_VERIFIED:
            raise LidarError("HARDWARE_VERIFIED cannot be set by the driver (stage C sign-off only)")
        self.t = None
        self.state = DriverState.DISCONNECTED
        self.info: Optional[P.DeviceInfo] = None
        self.health: Optional[P.Health] = None
        self.seq = 0
        self.corrupt_nodes_total = 0
        self.last_error: Optional[str] = None
        self._buf = bytearray()
        self._pending: list = []
        self._pending_start_ns: Optional[int] = None
        self._pending_start_wall: Optional[float] = None
        self._pending_corrupt = 0

    # ---- context manager -------------------------------------------------
    def __enter__(self) -> "RplidarC1Driver":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    # ---- low level -------------------------------------------------------
    def _io(self, fn, *a):
        if self.t is None:
            raise LidarDisconnected("not connected")
        try:
            return fn(*a)
        except (TransportClosed, OSError) as e:
            self._drop(f"transport failure: {e}")
            raise LidarDisconnected(str(e)) from e

    def _drop(self, why: str) -> None:
        self.last_error = why
        t, self.t = self.t, None
        self.state = DriverState.DISCONNECTED
        self._reset_assembly()
        if t is not None:
            try:
                t.close()
            except Exception:
                pass

    def _read_exact(self, n: int, timeout_s: float) -> bytes:
        deadline = self.clock_ns() + int(timeout_s * 1e9)
        out = bytearray()
        while len(out) < n:
            chunk = self._io(self.t.read, n - len(out))
            if chunk:
                out += chunk
            elif self.clock_ns() >= deadline:
                raise LidarTimeout(f"read timeout: got {len(out)}/{n} bytes")
            else:
                self.sleep(0.001)
        return bytes(out)

    def _command(self, cmd: int, expect_type: int, expect_len: int, timeout_s: float) -> bytes:
        self._io(self.t.write, P.request(cmd))
        d = P.parse_descriptor(self._read_exact(P.DESCRIPTOR_LEN, timeout_s))
        if d.data_type != expect_type or d.length != expect_len:
            raise P.ProtocolError(f"unexpected descriptor type 0x{d.data_type:02X} len {d.length}")
        return self._read_exact(expect_len, timeout_s)

    # ---- lifecycle -------------------------------------------------------
    def connect(self) -> None:
        if self.t is not None:
            return
        device = self.cfg.device or "<mock>"
        try:
            self.t = self._factory(device, self.cfg.baudrate, self.cfg.read_timeout_s)
        except (TransportClosed, OSError) as e:
            self.last_error = f"open failed: {e}"
            raise LidarDisconnected(self.last_error) from e
        self.state = DriverState.CONNECTED
        try:
            # A previous process may have left it scanning: STOP, wait, drop stale bytes.
            self._io(self.t.write, P.request(P.CMD_STOP))
            self.sleep(0.01)
            self._io(self.t.reset_input_buffer)
            self.info = P.parse_info(self._command(P.CMD_GET_INFO, P.ANS_TYPE_DEVINFO, P.INFO_LEN, 1.0))
            if self.cfg.expected_model_id is not None and self.info.model != self.cfg.expected_model_id:
                self.state = DriverState.HEALTH_ERROR
                raise LidarHealthError(f"GET_INFO model 0x{self.info.model:02X} != expected "
                                       f"0x{self.cfg.expected_model_id:02X}")
            self.check_health()
        except (LidarHealthError, LidarTimeout, P.ProtocolError) as e:
            self.last_error = str(e)
            state = self.state
            self._drop(str(e))
            if state is DriverState.HEALTH_ERROR:
                self.state = DriverState.HEALTH_ERROR
            raise

    def check_health(self) -> P.Health:
        self.health = P.parse_health(self._command(P.CMD_GET_HEALTH, P.ANS_TYPE_DEVHEALTH, P.HEALTH_LEN, 1.0))
        if not self.health.good:
            self.state = DriverState.HEALTH_ERROR
            raise LidarHealthError(f"device health {self.health.name} (error 0x{self.health.error_code:04X})")
        return self.health

    def start_scan(self) -> None:
        if self.state is DriverState.HEALTH_ERROR:
            raise LidarHealthError("health check failed: scanning refused")
        if self.t is None:
            raise LidarDisconnected("not connected")
        self._io(self.t.write, P.request(P.CMD_SCAN))
        # Tolerate leftover bytes before the descriptor (resync on A5 5A).
        deadline = self.clock_ns() + int(1.0 * 1e9)
        window = bytearray()
        while True:
            b = self._io(self.t.read, 1)
            if b:
                window += b
                if len(window) >= 2 and window[-2] == P.SYNC1 and window[-1] == P.SYNC2:
                    rest = self._read_exact(P.DESCRIPTOR_LEN - 2, 1.0)
                    d = P.parse_descriptor(bytes((P.SYNC1, P.SYNC2)) + rest)
                    if d.data_type != P.ANS_TYPE_MEASUREMENT or d.length != P.NODE_LEN or d.mode != 1:
                        raise P.ProtocolError(f"not a scan descriptor: {d}")
                    break
                if len(window) > 4096:
                    raise P.ProtocolError("no scan descriptor in 4096 bytes")
            elif self.clock_ns() >= deadline:
                raise LidarTimeout("no scan descriptor")
            else:
                self.sleep(0.001)
        self._reset_assembly()
        self.state = DriverState.SCANNING

    def stop_scan(self) -> None:
        if self.t is None:
            return
        try:
            self._io(self.t.write, P.request(P.CMD_STOP))
            self.sleep(0.005)   # protocol: wait >= 1 ms after STOP before the next request
            self._io(self.t.reset_input_buffer)
        except LidarDisconnected:
            return
        if self.state is DriverState.SCANNING:
            self.state = DriverState.CONNECTED
        self._reset_assembly()

    def disconnect(self) -> None:
        """Idempotent: STOP (best effort), then close. Never raises."""
        try:
            self.stop_scan()
        except Exception:
            pass
        health_err = self.state is DriverState.HEALTH_ERROR
        self._drop(self.last_error or "disconnect requested")
        if health_err:
            self.state = DriverState.HEALTH_ERROR

    # ---- scan assembly ---------------------------------------------------
    def _reset_assembly(self) -> None:
        self._buf = bytearray()
        self._pending = []
        self._pending_start_ns = None
        self._pending_start_wall = None
        self._pending_corrupt = 0

    def _emit(self, end_ns: int, interrupted: bool = False) -> Scan:
        pts, start_ns, start_wall = self._pending, self._pending_start_ns, self._pending_start_wall
        corrupt = self._pending_corrupt
        self.seq += 1
        frac = corrupt / max(1, corrupt + len(pts))
        scan = build_scan(pts, sensor_id=self.cfg.sensor_id, frame_id=self.cfg.frame_id, seq=self.seq,
                          start_mono_ns=start_ns, end_mono_ns=end_ns, start_wall=start_wall,
                          cfg=self.cfg.processing, source_mode=self.source_mode,
                          provenance={"driver": "rplidar-c1-legacy-scan", "device": self.cfg.device,
                                      "host": self.host, "mode": self.cfg.mode,
                                      "model_id": None if self.info is None else self.info.model,
                                      "corrupt_nodes": corrupt},
                          interrupted=interrupted, occluded=self.cfg.mount.occluded,
                          detail=f"{corrupt} corrupt nodes dropped" if corrupt else None)
        if frac > MAX_CORRUPT_FRACTION and scan.completion is ScanCompletion.COMPLETE:
            scan.completion = ScanCompletion.PARTIAL
            scan.detail = f"{corrupt} corrupt nodes ({frac:.0%}) > {MAX_CORRUPT_FRACTION:.0%}"
        return scan

    def read_scan(self) -> Scan:
        """Block until one full revolution (start flag to next start flag) is assembled."""
        if self.state is not DriverState.SCANNING:
            raise LidarError(f"not scanning (state {self.state.value})")
        deadline = self.clock_ns() + int(self.cfg.scan_timeout_s * 1e9)
        while True:
            chunk = self._io(self.t.read, 256)
            if chunk:
                self._buf += chunk
            elif self.clock_ns() >= deadline:
                # Do not emit what we have: a timed-out revolution is not a scan.
                self._reset_assembly()
                self.last_error = f"no complete revolution in {self.cfg.scan_timeout_s} s"
                raise LidarTimeout(self.last_error)
            else:
                self.sleep(0.001)
                continue
            while len(self._buf) >= P.NODE_LEN:
                nb = bytes(self._buf[:P.NODE_LEN])
                try:
                    node = P.decode_node(nb)
                except P.ProtocolError:
                    self.corrupt_nodes_total += 1
                    self._pending_corrupt += 1
                    off = P.find_node_alignment(bytes(self._buf[1:])) if len(self._buf) >= 11 else None
                    del self._buf[:1 if off is None else 1 + off]
                    if off is None and len(self._buf) < 11:
                        break
                    continue
                del self._buf[:P.NODE_LEN]
                now = self.clock_ns()
                if node.start_flag:
                    if self._pending_start_ns is not None and self._pending:
                        scan = self._emit(now)
                        self._pending = [(node.angle_deg, node.distance_m, node.quality)]
                        self._pending_start_ns, self._pending_start_wall = now, self.wall()
                        self._pending_corrupt = 0
                        return scan
                    self._pending = [(node.angle_deg, node.distance_m, node.quality)]
                    self._pending_start_ns, self._pending_start_wall = now, self.wall()
                    self._pending_corrupt = 0
                elif self._pending_start_ns is not None:
                    self._pending.append((node.angle_deg, node.distance_m, node.quality))
                # nodes before the first start flag are discarded (mid-revolution join)

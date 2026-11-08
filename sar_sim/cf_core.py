"""One Crazyflie over the Crazyradio, through cflib.

Used by the bridge (sar_sim/cf_bridge.py), and by CrazyflieLink when no
bridge is running. Pose comes from the drone's own state estimate, so the
drone needs a positioning deck (Flow deck v2, Lighthouse or Loco).
Install on the Jetson / laptop:  python3 -m pip install cflib
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque

POSITION_DECKS = ("bcFlow2", "bcFlow", "bcLighthouse4", "bcLoco")
POSE_VARS = ("stateEstimate.x", "stateEstimate.y", "stateEstimate.z", "stateEstimate.yaw")
STATUS_VARS = ("pm.vbat", "kalman.varPX", "kalman.varPY", "kalman.varPZ")
FRESH_POSE_S = 0.5      # pose older than this is "no pose"
FRESH_BAT_S = 1.0


class CfDrone:
    """Connect, read pose and battery, and fly with the high-level commander."""

    def __init__(self, uri, on_app_packet=None, cache=None, log=print):
        self.uri, self.on_app_packet, self.cache, self.log = uri, on_app_packet, cache, log
        self.lock = threading.Lock()
        self.x = self.y = self.z = self.yaw = math.nan
        self.vbat = None
        self.var = deque(maxlen=10)     # recent (varPX, varPY, varPZ)
        self.t_pose = self.t_bat = -1e9
        self.connected = False
        self.flying = False
        self.decks: list[str] = []
        self.has_app = False
        self.cf = self.scf = None
        self.logs = []

    # ---- connection -------------------------------------------------------
    def connect(self, settle_s=10.0):
        import cflib.crtp
        from cflib.crazyflie import Crazyflie
        from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

        cflib.crtp.init_drivers()
        self.cf = Crazyflie(rw_cache=self.cache)
        self.scf = SyncCrazyflie(self.uri, cf=self.cf)
        self.scf.open_link()
        self.connected = True
        self.cf.connection_lost.add_callback(self._lost)
        self.cf.disconnected.add_callback(self._lost)
        if hasattr(self.scf, "wait_for_params"):
            self.scf.wait_for_params()
        self.decks = [d for d in POSITION_DECKS if self._param(f"deck.{d}") == "1"]
        if not self.decks:
            self.close()
            raise RuntimeError(f"{self.uri}: no positioning deck found (need Flow deck v2, "
                               "Lighthouse or Loco); refusing to fly without position")
        self.has_app = self.cf.param.toc.get_element_by_complete_name("t15scan.wdMs") is not None
        self.cf.appchannel.packet_received.add_callback(self._app)
        self._start_logs()
        self._reset_estimator(settle_s)
        self.log(f"  {self.uri}: connected, decks {self.decks}, "
                 f"scanner app {'found' if self.has_app else 'NOT found'}")
        return self

    def _param(self, name):
        if self.cf.param.toc.get_element_by_complete_name(name) is None:
            return None
        return str(self.cf.param.get_value(name))

    def _lost(self, *_):
        if self.connected:
            self.log(f"  {self.uri}: radio link lost")
        self.connected = False

    def _app(self, data):
        if self.on_app_packet:
            self.on_app_packet(bytes(data))

    def _start_logs(self):
        from cflib.crazyflie.log import LogConfig

        def block(name, period, names):
            lc = LogConfig(name=name, period_in_ms=period)
            for v in names:
                if self.cf.log.toc.get_element_by_complete_name(v) is not None:
                    lc.add_variable(v, "float")
            self.cf.log.add_config(lc)
            return lc

        pose = block("t15pose", 100, POSE_VARS)
        status = block("t15status", 200, STATUS_VARS)
        pose.data_received_cb.add_callback(self._pose)
        status.data_received_cb.add_callback(self._status)
        for lc in (pose, status):
            lc.start()
        self.logs = [pose, status]

    def _pose(self, _ts, d, _lc):
        with self.lock:
            self.x, self.y = d.get("stateEstimate.x", math.nan), d.get("stateEstimate.y", math.nan)
            self.z = d.get("stateEstimate.z", math.nan)
            self.yaw = math.radians(d.get("stateEstimate.yaw", math.nan))
            self.t_pose = time.monotonic()

    def _status(self, _ts, d, _lc):
        with self.lock:
            if "pm.vbat" in d:
                self.vbat, self.t_bat = float(d["pm.vbat"]), time.monotonic()
            if "kalman.varPX" in d:
                self.var.append((d["kalman.varPX"], d.get("kalman.varPY", 0.0), d.get("kalman.varPZ", 0.0)))

    def _reset_estimator(self, settle_s):
        if self.cf.param.toc.get_element_by_complete_name("kalman.resetEstimation") is None:
            return
        self.cf.param.set_value("kalman.resetEstimation", "1")
        time.sleep(0.1)
        self.cf.param.set_value("kalman.resetEstimation", "0")
        with self.lock:
            self.var.clear()
        end = time.monotonic() + settle_s
        while time.monotonic() < end:
            time.sleep(0.2)
            with self.lock:
                v = list(self.var)
            if len(v) == 10 and all(
                    max(s[i] for s in v) - min(s[i] for s in v) < 0.001 for i in range(3)):
                return
        self.close()
        raise RuntimeError(f"{self.uri}: position estimate did not settle in {settle_s:.0f} s "
                           "(check the deck, the floor texture and lighting)")

    # ---- state ------------------------------------------------------------
    def state(self):
        now = time.monotonic()
        with self.lock:
            fresh = self.connected and now - self.t_pose <= FRESH_POSE_S
            sigma = None
            if self.var:
                vx, vy, _ = self.var[-1]
                sigma = math.sqrt(max(vx, 0.0) + max(vy, 0.0))
            return dict(
                x=self.x if fresh else math.nan, y=self.y if fresh else math.nan,
                z=self.z if fresh else math.nan, yaw=self.yaw if fresh else math.nan,
                vbat=self.vbat if self.connected and now - self.t_bat <= FRESH_BAT_S else None,
                sigma=sigma, age=round(now - self.t_pose, 3), connected=self.connected,
                flying=self.flying)

    # ---- flight -----------------------------------------------------------
    def _arm(self, on):
        sup = getattr(self.cf, "supervisor", None)
        if sup is not None and hasattr(sup, "send_arming_request"):
            sup.send_arming_request(on)
        elif hasattr(self.cf.platform, "send_arming_request"):
            self.cf.platform.send_arming_request(on)

    def takeoff(self, height, duration):
        self._need_link()
        self._arm(True)
        time.sleep(0.3)
        self.cf.high_level_commander.takeoff(height, duration)
        self.flying = True

    def go_to(self, x, y, z, yaw, duration):
        self._need_link()
        self.cf.high_level_commander.go_to(x, y, z, yaw, duration)

    def land(self, duration=2.5):
        if self.connected:
            self.cf.high_level_commander.land(0.0, duration)

    def stop(self):
        if self.connected:
            self.cf.high_level_commander.stop()
            self._arm(False)
        self.flying = False

    def send_app(self, data: bytes):
        if self.connected and self.has_app:
            self.cf.appchannel.send_packet(data)

    def set_param(self, name, value):
        self._need_link()
        self.cf.param.set_value(name, str(value))

    def _need_link(self):
        if not self.connected:
            raise RuntimeError(f"{self.uri}: no radio link")

    def close(self):
        for lc in self.logs:
            try:
                lc.stop()
            except Exception:
                pass
        self.logs = []
        if self.scf is not None:
            try:
                self.scf.close_link()
            except Exception:
                pass
        self.connected = False

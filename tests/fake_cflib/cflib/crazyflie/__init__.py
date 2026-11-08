"""Simulated Crazyflie for tests: no radio, no hardware.

WORLD sets the scene: decks, battery, where the target phone is, link loss.
The drone moves along high-level-commander trajectories, logs pose and
battery, and runs the real drone scanner app (tests/relay_host, compiled from
firmware/crazyflie_scanner_app/src/t15_scanner.c) on simulated scanner lines
in Mabelle's exact format. Only what sar_sim/cf_core.py uses is here.
"""
import ctypes
import math
import os
import random
import shutil
import tempfile
import threading
import time

from .log import Caller

LOG_NAMES = {"stateEstimate.x", "stateEstimate.y", "stateEstimate.z", "stateEstimate.yaw",
             "pm.vbat", "kalman.varPX", "kalman.varPY", "kalman.varPZ",
             "supervisor.info", "stabilizer.thrust", "stabilizer.roll", "stabilizer.pitch",
             "motor.m1", "motor.m2", "motor.m3", "motor.m4"}
SCAN_PARAMS = ("minRssi", "advHz", "capPps", "focusA", "focusB", "wdMs")
SCAN_DEFAULTS = dict(minRssi=-100, advHz=5, capPps=60, focusA=0, focusB=0, wdMs=3000)


class World:
    def __init__(self):
        self.reset()

    def reset(self, **kw):
        self.decks = {"bcFlow2": "1"}
        self.app = True                 # the scanner app is flashed
        self.vbat = 4.05
        self.drain = 0.0                # volts per second while the motors run
        self.beacon = None              # (x, y) of the target phone, drone frame, on the floor
        self.beacon_name = "T15-Target"
        self.beacon_addr = "c0:ff:ee:00:00:01"
        self.distractors = 15
        self.token_row = None           # f(rssi) -> CSV token row, or None
        self.relay_so = None            # compiled relay; None = no scanner traffic
        self.drop_link_at = None        # monotonic time the radio link dies
        self.log_rate = 1.0             # >1 sends logs faster than asked (shorter tests)
        self.info = 14                  # supervisor.info: 14 = armed, auto-arm, can fly; 68 = locked
        self.tilt = 0.0                 # degrees of roll the drone reports
        self.drones = []
        self.__dict__.update(kw)


WORLD = World()


class _Toc:
    def __init__(self, names):
        self.names = set(names)
        self.toc = {}
        for n in self.names:
            group, _, name = n.partition(".")
            self.toc.setdefault(group, {})[name] = n

    def get_element_by_complete_name(self, name):
        return name if name in self.names else None


class _Param:
    def __init__(self, cf):
        self.cf, self.values, self.toc = cf, {}, _Toc(())

    def get_value(self, name, timeout=60):
        return self.values[name]

    def set_value(self, name, value):
        if name not in self.values:
            raise KeyError(name)
        self.values[name] = str(value)
        self.cf._param_changed()


class _Log:
    def __init__(self, cf):
        self.cf, self.toc = cf, _Toc(LOG_NAMES)

    def add_config(self, lc):
        lc.cf, lc.last = self.cf, 0.0
        self.cf.logs.append(lc)


class _HighLevel:
    def __init__(self, cf):
        self.cf = cf

    def takeoff(self, absolute_height_m, duration_s, group_mask=0, yaw=0.0):
        self.cf._command("takeoff", (self.cf.pos[0], self.cf.pos[1], absolute_height_m), duration_s)

    def go_to(self, x, y, z, yaw, duration_s, relative=False, linear=False, group_mask=0):
        self.cf._command("go_to", (x, y, z), duration_s)

    def land(self, absolute_height_m, duration_s, group_mask=0, yaw=0.0):
        self.cf._command("land", (self.cf.pos[0], self.cf.pos[1], absolute_height_m), duration_s)

    def stop(self, group_mask=0):
        self.cf._command("stop", None, 0)


class _Commander:
    """Low-level setpoints (used by sar_sim/cf_handtest.py). Recorded, never flown."""

    def __init__(self, cf):
        self.cf = cf

    def send_setpoint(self, roll, pitch, yawrate, thrust):
        if self.cf.linked:
            self.cf.setpoints.append(("setpoint", roll, pitch, yawrate, int(thrust)))

    def send_stop_setpoint(self):
        if self.cf.linked:
            self.cf.setpoints.append(("stop",))
            if self.cf.motors:
                self.cf._trajectory("stop", None, 0)

    def send_position_setpoint(self, x, y, z, yaw):
        """Streamed absolute position (18-byte packet): the drone flies toward it."""
        if self.cf.linked:
            self.cf.setpoints.append(("position", x, y, z, yaw))
            self.cf._trajectory("go_to" if self.cf.motors else "takeoff", (x, y, z), 0.15)

    def send_notify_setpoint_stop(self, remain_valid_milliseconds=0):
        if self.cf.linked:
            self.cf.setpoints.append(("notify",))


class _AppChannel:
    def __init__(self, cf):
        self.cf, self.packet_received = cf, Caller()

    def send_packet(self, data):
        self.cf._app_rx(bytes(data))


class _Supervisor:
    def __init__(self, cf):
        self.cf = cf

    def send_arming_request(self, on):
        self.cf.armed = bool(on)


class Crazyflie:
    def __init__(self, rw_cache=None):
        self.param, self.log = _Param(self), _Log(self)
        self.high_level_commander, self.appchannel = _HighLevel(self), _AppChannel(self)
        self.supervisor = _Supervisor(self)
        self.commander = _Commander(self)
        self.setpoints = []
        self.platform = object()
        self.connection_lost, self.disconnected = Caller(), Caller()
        self.lock = threading.Lock()
        self.pos, self.start, self.target = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        self.t0, self.dur = 0.0, 0.0
        self.motors = self.crashed = self.armed = self.linked = False
        self.logs, self.commands = [], []
        self.relay, self.relay_dir, self.app_landings, self.app_stops = None, None, 0, 0
        self.vbat = WORLD.vbat
        self.rng = random.Random(7)

    # ---- link -------------------------------------------------------------
    def open_link(self, uri):
        self.uri, self.linked = uri, True
        values = {f"deck.{k}": "0" for k in ("bcFlow2", "bcZRanger2", "bcAI", "bcLighthouse4")}
        values.update({f"deck.{k}": v for k, v in WORLD.decks.items()})
        values["kalman.resetEstimation"] = "0"
        if WORLD.app:
            values.update({f"t15scan.{k}": str(v) for k, v in SCAN_DEFAULTS.items()})
        self.param.values, self.param.toc = values, _Toc(values)
        if WORLD.app and WORLD.relay_so:
            self.relay_dir = tempfile.mkdtemp()
            so = os.path.join(self.relay_dir, "relay.so")
            shutil.copy(WORLD.relay_so, so)
            self.relay = ctypes.CDLL(so)
            self.relay.relay_line.argtypes = [ctypes.c_char_p]
            self.relay.relay_time.argtypes = [ctypes.c_uint32]
            self.relay.relay_params.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                ctypes.c_uint32, ctypes.c_uint16, ctypes.c_int]
            self._param_changed()
        WORLD.drones.append(self)
        self.alive = True
        threading.Thread(target=self._run, daemon=True).start()

    def close_link(self):
        self.linked, self.alive = False, False

    def _param_changed(self):
        if self.relay:
            v = {k: int(self.param.values[f"t15scan.{k}"]) for k in SCAN_PARAMS}
            self.relay.relay_params(v["minRssi"], v["advHz"], v["capPps"], v["focusA"],
                                    v["focusB"], v["wdMs"])

    # ---- commands from the host --------------------------------------------
    def _command(self, kind, target, duration):
        if not self.linked:
            return                              # radio is gone: the drone never hears it
        self.commands.append((kind, target, duration))
        self._trajectory(kind, target, duration)

    def _trajectory(self, kind, target, duration):
        with self.lock:
            if kind == "stop":
                if self.pos[2] > 0.05:
                    self.crashed = True
                self.motors, self.pos[2] = False, 0.0
                self.target = list(self.pos)
                return
            if kind == "takeoff":
                self.motors = True
            if not self.motors:
                return
            self.start, self.target = list(self.pos), list(target)
            self.t0, self.dur = time.monotonic(), max(duration, 1e-3)

    def _app_rx(self, data):
        if self.linked and self.relay and data[:1] == b"K":
            self.relay.relay_keepalive()

    # ---- simulation -----------------------------------------------------------
    def _run(self):
        last_hb = last_beacon = last_noise = 0.0
        t_start = time.monotonic()
        while self.alive:
            time.sleep(0.01)
            now = time.monotonic()
            with self.lock:
                f = min(1.0, (now - self.t0) / self.dur) if self.dur else 1.0
                self.pos = [a + f * (b - a) for a, b in zip(self.start, self.target)]
                if self.motors:
                    self.vbat -= WORLD.drain * 0.01
                flying = self.motors and self.pos[2] > 0.05
            if WORLD.drop_link_at is not None and now >= WORLD.drop_link_at and self.linked:
                self.linked = False
                self.connection_lost.call(self.uri, "simulated radio loss")
            if self.relay:
                self.relay.relay_time(int((now - t_start) * 1000) + 1000)
                self.relay.relay_flying(1 if flying else 0)
                code = self.relay.relay_watchdog()
                lands, stops = code // 10, code % 10
                if lands > self.app_landings:
                    self.app_landings = lands
                    self._trajectory("land", (self.pos[0], self.pos[1], 0.0), 2.5)
                if stops > self.app_stops:
                    self.app_stops = stops
                    self._trajectory("stop", None, 0)
                lines = []
                if now - last_hb >= 1.0:
                    last_hb = now
                    lines.append(f"#HEARTBEAT,scanning=1,millis={int((now - t_start) * 1000)},"
                                 "passive=1,discovery=1")
                if WORLD.beacon is not None and now - last_beacon >= 0.05:
                    last_beacon = now
                    d = math.dist(self.pos, (WORLD.beacon[0], WORLD.beacon[1], 0.0))
                    rssi = int(round(-45 - 20 * math.log10(max(0.12, d)) + self.rng.gauss(0, 1.5)))
                    name = WORLD.beacon_name.encode()
                    payload = (bytes([2, 1, 6, len(name) + 1, 9]) + name).hex().upper()
                    lines.append(f"#BLE,{rssi},{WORLD.beacon_addr},1,{payload}")
                    if WORLD.token_row:
                        lines.append(WORLD.token_row(rssi))
                if now - last_noise >= 0.1:
                    last_noise = now
                    for k in range(WORLD.distractors):
                        lines.append(f"#BLE,{self.rng.randrange(-95, -60)},5a:00:00:00:00:{k:02x},1,"
                                     "09FF4C000719010F2000")
                for line in lines:
                    self.relay.relay_line(line.encode())
                buf = (ctypes.c_uint8 * 64)()
                while True:
                    n = self.relay.relay_take(buf)
                    if not n:
                        break
                    if self.linked:
                        self.appchannel.packet_received.call(bytes(buf[:n]))
            if not self.linked:
                continue
            for lc in list(self.logs):
                if lc.started and now - lc.last >= lc.period_in_ms / 1000 / WORLD.log_rate:
                    lc.last = now
                    thrust = next((p[4] for p in reversed(self.setpoints) if p[0] == "setpoint"), 0)
                    motor = thrust if WORLD.info & 8 else 0
                    vals = {"stateEstimate.x": self.pos[0], "stateEstimate.y": self.pos[1],
                            "stateEstimate.z": self.pos[2], "stateEstimate.yaw": 0.0,
                            "pm.vbat": self.vbat, "kalman.varPX": 1e-4, "kalman.varPY": 1e-4,
                            "kalman.varPZ": 1e-4, "supervisor.info": WORLD.info,
                            "stabilizer.thrust": float(thrust), "stabilizer.roll": WORLD.tilt,
                            "stabilizer.pitch": 0.0, "motor.m1": motor, "motor.m2": motor,
                            "motor.m3": motor, "motor.m4": motor}
                    lc.data_received_cb.call(int(now * 1000), {v: vals[v] for v in lc.variables}, lc)

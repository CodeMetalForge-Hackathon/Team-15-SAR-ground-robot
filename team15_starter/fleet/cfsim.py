"""fleet/cfsim.py — your planner flying simulated Crazyflies through the real bridge.

    python homebase.py --cf-sim                 # dashboard at http://localhost:8080
    python homebase.py --cf-sim --drones 3 --people 3 --seed 4

The homebase, map, MCTS planner and dashboard are the same as in --sim. Each
drone is a SimDrone (same sensing, detections, battery and radio model), but
it doesn't move itself. Its motion comes from a simulated Crazyflie flown by
the real bridge (sar_sim/cf_bridge.py) through the real Crazyflie driver code
(sar_sim/cf_core.py). Only cflib's radio layer is simulated (tests/fake_cflib).
So this runs the same takeoff / go_to / land commands, fence and safety
landings as the real drones.

The room: 2 m x 2 m (8 x 8 cells of 25 cm). Drones take off from pads 25 cm
apart along the bottom edge and fly at 0.5 / 0.7 / 0.9 m, at 0.3 m/s. Every
victim carries a phone, and the drones carry Mabelle's BLE scanner only, so
they find WHO is there. Confirming by camera is the rover's job (not
simulated yet). Runs in real time, because the bridge's safety timers are
real. Ctrl-C lands everything and stops.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np

from link.transport import BytePipeTransport
from .hub import Homebase
from .scenario import build_sim, build_world, hub_config, load_allies, match_people
from .simdrones import SimDrone, SimGateway

REPO = Path(__file__).resolve().parents[2]          # Team-15 repo root
SIM_CFLIB = REPO / "tests" / "fake_cflib"            # the simulated Crazyflie the tests use
Z_MIN, Z_MAX = 0.2, 1.2                              # stay inside the bridge's height fence


def apply_cf_sim_defaults(args, argv):
    """Indoor Crazyflie room defaults, for the options you didn't set yourself."""
    given = " ".join(argv)
    for flag, attr, val in (("--n", "n", 8), ("--cell-m", "cell_m", 0.25), ("--drones", "drones", 2),
                            ("--people", "people", 2), ("--loadout", "loadout", "ble"),
                            ("--endurance", "endurance", 300.0), ("--speed", "speed", 0.3),
                            ("--base-alt", "base_alt", 0.5), ("--alt-step", "alt_step", 0.2),
                            ("--drift", "drift", 0.005), ("--loss", "loss", 0.0),
                            ("--charge", "charge", 30.0), ("--time", "time", 600.0),
                            ("--prior", "prior", "uniform")):
        if flag not in given:
            setattr(args, attr, val)
    args.scenario, args.no_walls, args.military = "grid", True, False
    if "--key" not in given:
        args.key = None
    return args


class BridgeClient:
    """One connection to the bridge that flies every drone (JSON lines)."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.rfile = self.sock.makefile("rb")
        self.lock = threading.Lock()

    def call(self, op, **kw):
        with self.lock:
            self.sock.sendall((json.dumps(dict(op=op, **kw)) + "\n").encode())
            line = self.rfile.readline()
        return json.loads(line) if line else dict(ok=False, error="bridge closed")

    def close(self):
        for thing in (self.rfile, self.sock):
            try:
                thing.close()
            except OSError:
                pass


class CrazyflieSimDrone(SimDrone):
    """A SimDrone whose body is a (simulated) Crazyflie flown through the bridge.

    Coordinates: the planner's metres, home cell centre at (0, 0). Each
    Crazyflie's own frame starts at its pad, like a real one with a Flow deck."""

    def __init__(self, *args, client=None, cf_id=1, pad=(0.0, 0.0), **kw):
        super().__init__(*args, **kw)
        self.client, self.cf_id = client, cf_id
        self.pad = np.array(pad, dtype=float)
        self.true[:2] = self.pad
        self.cf_flying = self.landing = False
        self.cmd = None
        self._moved = 0.0
        self.refused = []

    def _refresh(self):
        st = self.client.call("state", id=self.cf_id)
        if not st.get("ok"):
            return
        if st.get("x") is not None:
            self.true[0], self.true[1] = st["x"] + self.pad[0], st["y"] + self.pad[1]
            self.true[2] = max(0.0, float(st["z"]))
        self.cf_flying = bool(st.get("flying"))
        if not self.cf_flying:
            self.landing, self.cmd = False, None

    def _command(self, op, **kw):
        r = self.client.call(op, id=self.cf_id, **kw)
        if not r.get("ok"):
            self.refused.append((op, r.get("error")))
        return r

    def step(self, t, dt):
        before = self.true[:2].copy()
        if not self.dead:
            self._refresh()
        self._moved = float(np.hypot(*(self.true[:2] - before)))
        out = super().step(t, dt)
        if self.dead and self.cf_flying and not self.landing:
            self._command("land", d=2.0)                # battery model says empty: put it down
            self.landing = True
        return out

    def _fly_toward(self, tx, ty, tz, dt):
        if tz <= 0.05:                                   # touch down where it is
            if self.cf_flying and not self.landing:
                self._command("land", d=2.0)
                self.landing = True
            return self._moved
        z = float(np.clip(tz, Z_MIN, Z_MAX))
        if not self.cf_flying:
            if not self.landing:
                self._command("takeoff", h=z, d=1.5)
            return 0.0
        goal = np.array([tx, ty]) - self.offset - self.pad    # its own (drifted) frame, from its pad
        target = (float(goal[0]), float(goal[1]), z)
        if self.cmd is None or max(abs(a - b) for a, b in zip(target, self.cmd)) > 0.02:
            here = (self.true[0] - self.pad[0], self.true[1] - self.pad[1], self.true[2])
            dist = float(np.linalg.norm(np.subtract(target, here)))
            self._command("go_to", x=target[0], y=target[1], z=z, yaw=0.0,
                          d=max(0.5, dist / max(self.speed, 0.05)))
            self.cmd = target
        return self._moved

    def _land(self, t):
        if self.cf_flying and not self.landing:
            self._command("land", d=2.0)
            self.landing = True
        super()._land(t)                                 # position keeps coming from the Crazyflie


def start_bridge(n, room_m=2.0, log=print):
    """The real bridge, flying n simulated Crazyflies; its fence is the room plus a margin."""
    for p in (str(REPO), str(SIM_CFLIB)):
        if p not in sys.path:
            sys.path.insert(0, p)
    for name in [m for m in sys.modules if m == "cflib" or m.startswith("cflib.")]:
        del sys.modules[name]                            # use the simulated radio layer
    from cflib.crazyflie import WORLD
    from sar_sim.cf_bridge import Bridge
    WORLD.reset(log_rate=2.0)
    uris = [f"radio://0/80/2M/E7E7E7E7{0xE7 + k:02X}" for k in range(n)]
    return Bridge(uris, port=0, scanner_dir=None, fence_xy=room_m + 0.25, z_max=1.5, log=log).start()


def build_cf_sim(args, key, client):
    truth, grid, people, sims, _ = build_sim(args, key)
    rng = np.random.default_rng(args.seed + 7)
    for p in people:                                     # everyone carries a phone in this demo
        if not p.tag_id:
            p.tag_id = int(rng.integers(1, 2 ** 32 - 1))
    drones = [CrazyflieSimDrone(d.id, d.sensors, truth, grid, people,
                                np.random.default_rng(args.seed + 10 + i), key=key,
                                speed=args.speed, endurance=args.endurance, drift=args.drift,
                                launch_at=3.0 * i, charge_s=args.charge, military=False,
                                client=client, cf_id=i + 1, pad=(i * truth.cell_m, 0.0))
              for i, d in enumerate(sims)]
    gw = SimGateway(drones, np.random.default_rng(args.seed + 99), loss=args.loss)
    hub = Homebase(build_world(args, hidden=True), args.drones, hub_config(args), key=key,
                   allies=load_allies(args.allies, args), log_dir="results",
                   verbose=not getattr(args, "quiet", False))
    return truth, people, drones, gw, hub


def run_cf_sim(args, key, web=True, stop_after=None, out=print):
    """Real-time mission. Returns dict(found, people, t_all_found, refused)."""
    bridge_log = []
    bridge = start_bridge(args.drones, room_m=args.n * args.cell_m,
                          log=lambda m: (bridge_log.append(m), "LANDING" in m and out(f"  [bridge] {m}")))
    client = BridgeClient(bridge.port)
    truth, people, drones, gw, hub = build_cf_sim(args, key, client)
    dash = origin = None
    if web:
        from .web import Dashboard, parse_origin, snapshot
        dash, origin = Dashboard(args.web_port).start(), parse_origin(args.origin)
        out(f"\n  dashboard:  http://localhost:{args.web_port}   (Ctrl-C lands the drones and stops)\n")
    out(f"=== Crazyflie sim: {args.drones} drones through the bridge, {len(people)} hidden people, "
        f"{args.n * args.cell_m:.1f} m room ===")
    pipe = BytePipeTransport()
    t0 = time.monotonic()
    t = last = 0.0
    next_tick = next_pub = next_status = 0.0
    found_at, matched = None, {}
    end = min(args.time, stop_after) if stop_after else args.time
    try:
        while t < end:
            now = time.monotonic() - t0
            dt, last = max(0.01, now - last), now
            t = now
            if dash:
                for c in dash.take_commands():
                    if c.get("cmd") == "recall":
                        hub.recall(t)
                        for d in drones:
                            d.launch_at = 1e12
            up = {d.id: d.step(t, dt) for d in drones}
            pipe.rx += gw.uplink(t, up)
            for rssi, raw in pipe.recv():
                hub.on_raw(raw, rssi, t)
            if t >= next_tick:
                for pkt in hub.tick(t):
                    pipe.send(pkt)
                next_tick = t + 0.2
            gw.downlink(t, bytes(pipe.tx))
            pipe.tx.clear()
            if hub.tracks:
                matched = match_people(people, hub.tracks, 1.5 * truth.cell_m)
                if found_at is None and len(matched) == len(people):
                    found_at = t
                    out(f"  every person found at {t:.1f} s")
            if t >= next_status:
                out(hub.status_line(t))
                next_status = t + 5.0
            if dash and t >= next_pub:
                dash.publish(snapshot(hub, t, 1, origin, mode="sim", paused=False, speed=1.0,
                                      people=people, sim_drones=drones, gw=gw, done_at=found_at))
                next_pub = t + 0.25
            time.sleep(max(0.0, 0.1 - (time.monotonic() - t0 - now)))
    except KeyboardInterrupt:
        out("\nstopping: landing the drones...")
    finally:
        for d in drones:
            if d.cf_flying:
                client.call("land", id=d.cf_id, d=1.5)
        time.sleep(2.5 if any(d.cf_flying for d in drones) else 0.0)
        hub.close()
        client.close()
        bridge.close()
        if dash:
            dash.stop()
    return dict(found=len(matched), people=len(people), t_all_found=found_at,
                refused=[r for d in drones for r in d.refused], bridge_log=bridge_log)

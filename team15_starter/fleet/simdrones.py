"""fleet/simdrones.py — stand-ins for the real hardware, speaking the real bytes.

SimDrone   does what firmware/drone_node/drone_node.ino does: telemetry at the
           commanded rate, detections queued until the homebase acks them
           (store-and-forward), link-loss failsafe (hold, then fly home), and
           a sequence counter for replay protection. It also flies, drifts
           like VIO, drains its battery, and senses hidden people.
SimGateway does what firmware/gateway/gateway.ino does: ESP-NOW <-> COBS
           serial framing with an RSSI byte. It also drops packets (jamming).

Ground truth (people, their status and vitals, true drone positions) lives
only here. The homebase only ever sees packets.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from link import protocol as P
from .planner import SENSOR_PRESET, fov_cells, sensor_visibility


@dataclass
class Person:
    x: float
    y: float
    cell: tuple
    status: str
    hr: int
    br: int
    tag_id: int = 0
    watch: bool = False
    first_detected: Optional[float] = None


def make_people(world, grid, rng, phone_rate=0.5, tags=None, statuses=None):
    people = []
    for k, cell in enumerate(world.people):
        x, y = grid.to_xy(cell)
        x += rng.uniform(-0.3, 0.3) * world.cell_m
        y += rng.uniform(-0.3, 0.3) * world.cell_m
        status = rng.choice(["ok", "injured", "critical"], p=[0.4, 0.4, 0.2])
        if status == "ok":
            hr, br = int(rng.integers(65, 95)), int(rng.integers(12, 19))
        elif status == "injured":
            hr, br = int(rng.integers(118, 135)), int(rng.integers(25, 29))
        else:
            hr, br = (int(rng.integers(35, 44)), int(rng.integers(5, 8))) if rng.random() < 0.5 \
                else (int(rng.integers(145, 160)), int(rng.integers(31, 36)))
        has_phone = rng.random() < phone_rate
        tag = int(rng.integers(1, 2 ** 32 - 1)) if has_phone else 0
        if tags is not None:
            tag = tags[k] if k < len(tags) else 0
        people.append(Person(x, y, cell, str(status), hr, br, tag,
                             tags is None and has_phone and rng.random() < 0.5))
    return people


class SimDrone:
    kind = "air"

    def __init__(self, did, sensors, world, grid, people, rng, key=None,
                 speed=5.0, endurance=240.0, drift=0.02, uwb_range=None,
                 launch_at=0.0, charge_s=60.0, mmwave_alt=2.0, military=False):
        self.id = did
        self.sensors = list(sensors)
        self.mask = sum(P.sensor_bit(s) for s in self.sensors)
        self.world, self.grid, self.people, self.rng = world, grid, people, rng
        self.key = key
        self.speed, self.endurance = speed, endurance
        self.drift = drift                       # VIO drift: metres of error per sqrt(metre flown)
        self.uwb_range = uwb_range if uwb_range is not None else 1.5 * world.cell_m
        self.launch_at, self.charge_s = launch_at, charge_s
        self.mmwave_alt = mmwave_alt
        self.true = np.zeros(3)                  # x y z, starts on the homebase pad
        self.offset = np.zeros(2)                # estimate - truth
        self.var = 0.0
        self.state = 0
        self.battery_s = endurance
        self.landed_at = -1e9
        self.wp = None                           # (x, y, z, cmd)
        self.wp_seq = 0
        self.last_rx = 0.0
        self.home_guard = P.ReplayGuard()
        self.tx_period = 0.5
        self.next_tx = 0.0
        self.seq = did * 1_000_000               # firmware keeps this in flash
        self.next_det = 1
        self.queue = {}                          # det_id -> [Detection, last_tx]
        self.reported = {}                       # (person, sensor) -> t
        self.last_cell, self.last_look = None, -1e9
        self.dead = False
        self.stats = dict(tx=0, det_made=0, det_tx=0)
        self.made = []                           # (det_id, time) for delivery scoring
        self.military = military
        self.failsafe = None
        self.home_xy = (0.0, 0.0)                # where the link-loss failsafe goes

    # ---------------------------------------------------------------- radio
    def receive(self, raw, t):
        try:
            pk = P.decode(raw, key=self.key, require_auth=bool(self.key))
        except P.PacketError:
            return
        if pk.type != P.WAYPOINT or pk.dst not in (self.id, P.BROADCAST):
            return
        if self.key and not self.home_guard.ok(P.HOME_ID, pk.seq):
            return
        w = pk.body
        self.last_rx = t
        self.failsafe = None
        self.tx_period = max(0.1, w.tx_period_ds / 10.0)
        for k in [k for k in self.queue if k <= w.det_ack]:
            del self.queue[k]                    # homebase has it: stop retransmitting
        if w.wp_seq != self.wp_seq:
            self.wp_seq = w.wp_seq
            self.wp = (w.x, w.y, w.z, w.cmd)

    def _send(self, body):
        self.seq += 1
        self.stats["tx"] += 1
        return P.encode(body, self.id, P.HOME_ID, self.seq, 0, key=self.key)

    # ---------------------------------------------------------------- physics
    @property
    def est(self):
        return self.true[:2] + self.offset

    def _fly_toward(self, tx, ty, tz, dt):
        goal = np.array([tx, ty]) - self.offset      # it flies in its own (drifted) frame
        delta = goal - self.true[:2]
        dist = float(np.hypot(*delta))
        step = min(dist, self.speed * dt)
        moved = 0.0
        if step > 1e-6:
            v = delta / dist * step
            for cand in (v, np.array([v[0], 0.0]), np.array([0.0, v[1]])):   # slide along walls
                new = self.true[:2] + cand
                if self.world.free(self.grid.to_cell(*new)):
                    self.true[:2] = new
                    moved = float(np.hypot(*cand))
                    break
        self.true[2] += float(np.clip(tz - self.true[2], -2.0 * dt, 2.0 * dt))
        return moved

    def step(self, t, dt):
        out = []
        if self.dead:
            return out
        if self.state == 0:                          # on the pad (mothership charges it)
            if t >= self.launch_at and t - self.landed_at >= self.charge_s:
                self.state, self.battery_s = 1, self.endurance
                self.wp, self.last_rx = None, t
            if t >= self.next_tx:
                self.next_tx = t + 2.0
                out.append(self._telemetry())
            return out

        self.battery_s -= dt
        if self.battery_s <= 0:
            self.dead, self.state = True, 0          # this is what the RTB logic prevents
            return out

        silent = t - self.last_rx
        if silent > 20.0:
            self.failsafe = "rtb"                    # lost link: come home on its own
        elif silent > 8.0 and self.failsafe is None:
            self.failsafe = "hold"

        moved = 0.0
        if self.failsafe == "rtb":
            self.state = 4
            moved = self._fly_toward(self.home_xy[0], self.home_xy[1], self.true[2], dt)
            if float(np.hypot(*(self.est - np.asarray(self.home_xy)))) < 0.3 * self.world.cell_m:
                self._land(t)
        elif self.failsafe == "hold":
            self.state = 4
        elif self.wp is not None:
            x, y, z, cmd = self.wp
            if cmd == P.CMD_LAND:
                moved = self._fly_toward(x, y, 0.0, dt)
                self.state = 3
                if self.true[2] <= 0.05:
                    self._land(t)
            elif cmd == P.CMD_HOLD:
                self.state = 2
                moved = self._fly_toward(x, y, z, dt)
            else:
                self.state = 1
                moved = self._fly_toward(x, y, z, dt)

        if self.drift > 0 and moved > 0:              # VIO drift grows with distance flown
            self.offset += self.rng.normal(0, self.drift * math.sqrt(moved), 2)
            self.var += self.drift ** 2 * moved
        if float(np.hypot(*self.true[:2])) <= self.uwb_range:
            self.offset *= math.exp(-dt / 0.5)        # UWB anchor on the homebase pulls it back
            self.var = min(self.var, 0.04)

        if self.state != 0:
            out += self._sense(t)
        if t >= self.next_tx:
            self.next_tx = t + self.tx_period
            out.append(self._telemetry())
        retx = 3.0 if self.military else 1.0
        for det_id, item in sorted(self.queue.items())[:2]:
            if t - item[1] >= retx:
                item[1] = t
                self.stats["det_tx"] += 1
                out.append(self._send(item[0]))
        return out

    def _land(self, t):
        self.state, self.true[2], self.landed_at = 0, 0.0, t
        self.wp, self.failsafe = None, None

    def _telemetry(self):
        e = self.est
        pct = int(max(0, min(100, round(100 * self.battery_s / self.endurance))))
        return self._send(P.Telemetry(float(e[0]), float(e[1]), float(self.true[2]), 0.0,
                                      float(math.sqrt(self.var)), pct, self.state,
                                      self.mask if self.state != 0 else 0, self.wp_seq))

    # ---------------------------------------------------------------- sensing
    def _sense(self, t):
        cell = self.grid.to_cell(*self.true[:2])
        if cell == self.last_cell and t - self.last_look < 5.0:
            return []
        self.last_cell, self.last_look = cell, t
        found = []
        for k, p in enumerate(self.people):
            dcell = max(abs(p.cell[0] - cell[0]), abs(p.cell[1] - cell[1]))
            for s in self.sensors:
                pre = SENSOR_PRESET[s]
                if t - self.reported.get((k, s), -1e9) < 10.0:
                    continue
                if s == "mmwave":
                    # radar reaches ~1 m sideways and ~1.5 m down. While hovering, a drone
                    # with a camera centres itself over the person first (on hardware:
                    # the CV final-approach loop), modelled as extra reach.
                    reach = SENSOR_PRESET["mmwave"]["range_m"]
                    if self.state == 2 and ("thermal" in self.sensors or "cv" in self.sensors):
                        reach += 0.35 * self.world.cell_m
                    if self.true[2] > self.mmwave_alt or np.hypot(p.x - self.true[0], p.y - self.true[1]) > reach:
                        continue
                elif dcell > fov_cells(s, self.world.cell_m):
                    continue
                if s == "ble" and not p.tag_id:
                    continue
                pod = pre["pod"]
                vis = self._vis()
                if vis is not None:
                    pod *= float(sensor_visibility(s, vis[p.cell]))   # trees hide him from cameras
                if self.rng.random() >= pod:
                    continue
                self.reported[(k, s)] = t
                if p.first_detected is None:
                    p.first_detected = t
                found.append(self._detection(p, s, t))
        return [self._send(d) for d in found]

    def _vis(self):
        """How well this vehicle's cameras see into each cell (None = everywhere clear)."""
        return getattr(self.world, "vis", None)

    def _detection(self, p, s, t):
        noise = self.rng.normal(0, 0.25 * self.world.cell_m, 2)
        rel = np.array([p.x, p.y]) - self.true[:2]
        x, y = self.est + rel + noise
        status, hr, br, tag, conf = 0, 0, 0, 0, 200
        if s == "thermal":
            conf = int(self.rng.integers(170, 230))
        elif s == "cv":
            conf = int(self.rng.integers(150, 220))
            if p.status in ("injured", "critical") and self.rng.random() < 0.6:
                status = P.STATUS_IDS["injured"]       # visible injury / odd posture
        elif s == "mmwave":
            conf = 245
            hr = int(np.clip(p.hr + self.rng.normal(0, 3), 1, 255))
            br = int(np.clip(p.br + self.rng.normal(0, 1), 1, 255))
        elif s == "ble":
            conf, tag = 250, p.tag_id
            if p.watch:
                hr = int(np.clip(p.hr + self.rng.normal(0, 2), 1, 255))
        det = P.Detection(float(x), float(y), P.SENSOR_IDS[s], conf, status, hr, br,
                          int(min(255, 10 * float(np.hypot(*rel)))), self.next_det & 0xFFFF, tag)
        self.queue[det.det_id] = [det, t]             # first copy goes out now, retransmit until acked
        self.made.append((det.det_id, t))
        self.next_det += 1
        self.stats["det_made"] += 1
        return det


class SimGateway:
    """ESP-NOW <-> serial, plus an unreliable air. loss = chance a packet is
    dropped; inside a jam window (t0, t1) loss is `jam_loss`."""

    def __init__(self, drones, rng, loss=0.0, jam=None, jam_loss=0.9):
        self.drones = {d.id: d for d in drones}
        self.rng, self.loss, self.jam, self.jam_loss = rng, loss, jam, jam_loss
        self.reader = P.FrameReader()
        self.stats = dict(up_sent=0, up_lost=0, down_sent=0, down_lost=0)

    def p_loss(self, t):
        if self.jam and self.jam[0] <= t < self.jam[1]:
            return self.jam_loss
        return self.loss

    def uplink(self, t, packets_by_drone):
        """Drone packets -> framed bytes for the Jetson (rssi byte first)."""
        out = bytearray()
        for did, pkts in packets_by_drone.items():
            d = self.drones[did]
            dist = float(np.hypot(*d.true[:2])) + 1.0
            rssi = int(np.clip(-40 - 20 * math.log10(dist), -100, -20))
            for raw in pkts:
                self.stats["up_sent"] += 1
                if self.rng.random() < self.p_loss(t):
                    self.stats["up_lost"] += 1
                    continue
                out += P.frame(bytes([rssi & 0xFF]) + raw)
        return bytes(out)

    def downlink(self, t, data):
        """Framed bytes from the Jetson -> ESP-NOW broadcast to every drone."""
        for raw in self.reader.feed(data):
            for d in self.drones.values():
                self.stats["down_sent"] += 1
                if self.rng.random() < self.p_loss(t):
                    self.stats["down_lost"] += 1
                    continue
                d.receive(raw, t)

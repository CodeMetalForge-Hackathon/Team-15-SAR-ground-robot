"""fleet/starlink.py — Starlink in the simulation, two ways.

Starlink         one terminal's link: tens of milliseconds of delay, and short
                 dropouts every few minutes (satellite hand-offs, something
                 blocking the sky). Under tree canopy a terminal drops a lot
                 more packets.
StarlinkGateway  the rover's radio: its packets go over Starlink to the
                 homebase instead of the short-range ESP-NOW mesh, so jamming
                 the mesh doesn't touch it, but canopy and outages do.
                 Same uplink()/downlink() calls as SimGateway.
CombinedGateway  drones on ESP-NOW + rovers on Starlink, behind one object, so
                 the mission loops don't change.
HQUplink         the homebase's own terminal sends each casualty report to a
                 remote HQ. Reports wait in a queue through an outage and go
                 when the sky comes back. In military mode it sends in short
                 bursts (a satellite terminal is a radio emitter too).
"""
from __future__ import annotations

import json
import math
from collections import deque

import numpy as np

from link import protocol as P


class Starlink:
    def __init__(self, rng, every_s=(90.0, 240.0), outage_s=(2.0, 9.0), latency_s=(0.025, 0.06)):
        self.rng = rng
        self.every_s, self.outage_s, self.latency_s = every_s, outage_s, latency_s
        self.outages = []                        # (start, end)
        self._next = float(rng.uniform(20.0, every_s[0]))
        self.forced = None                       # (start, end) from the dashboard

    def _schedule(self, t):
        while self._next <= t + 600:
            length = float(self.rng.uniform(*self.outage_s))
            self.outages.append((self._next, self._next + length))
            self._next += length + float(self.rng.uniform(*self.every_s))

    def online(self, t):
        self._schedule(t)
        if self.forced and self.forced[0] <= t < self.forced[1]:
            return False
        return not any(a <= t < b for a, b in self.outages)

    def outage_left(self, t):
        if self.forced and self.forced[0] <= t < self.forced[1]:
            return self.forced[1] - t
        return next((b - t for a, b in self.outages if a <= t < b), 0.0)

    def latency(self):
        return float(self.rng.uniform(*self.latency_s))

    def uptime(self, t):
        if t <= 0:
            return 100.0
        down = sum(max(0.0, min(b, t) - a) for a, b in self.outages if a < t)
        return round(100.0 * (1 - down / t), 1)


class StarlinkGateway:
    """Rovers <-> homebase over Starlink. Packets arrive after the link's delay."""

    def __init__(self, rovers, rng, link=None, canopy_loss=0.35):
        self.rovers = {r.id: r for r in rovers}
        self.rng = rng
        self.link = link or Starlink(rng)
        self.canopy_loss = canopy_loss
        self.up_q, self.down_q = deque(), deque()  # (deliver_at, raw / packet)
        self.reader = P.FrameReader()
        self.stats = dict(up_sent=0, up_lost=0, down_sent=0, down_lost=0)

    def _loss(self, rover, t):
        if not self.link.online(t):
            return 1.0
        vis = getattr(rover.world, "vis", None)      # sky view from where the rover is
        if vis is None:
            return 0.01
        cell = rover.grid.to_cell(*rover.true[:2])
        return 0.01 + self.canopy_loss * (1.0 - float(vis[cell]))

    def uplink(self, t, packets_by_rover):
        out = bytearray()
        for rid, pkts in packets_by_rover.items():
            r = self.rovers[rid]
            for raw in pkts:
                self.stats["up_sent"] += 1
                if self.rng.random() < self._loss(r, t):
                    self.stats["up_lost"] += 1
                    continue
                self.up_q.append((t + self.link.latency(), raw))
        while self.up_q and self.up_q[0][0] <= t + 1e-9:
            out += P.frame(bytes([(-55) & 0xFF]) + self.up_q.popleft()[1])
        return bytes(out)

    def downlink(self, t, data):
        for raw in self.reader.feed(data):
            self.down_q.append((t + self.link.latency(), raw))
        while self.down_q and self.down_q[0][0] <= t + 1e-9:
            raw = self.down_q.popleft()[1]
            for r in self.rovers.values():
                self.stats["down_sent"] += 1
                if self.rng.random() < self._loss(r, t):
                    self.stats["down_lost"] += 1
                    continue
                r.receive(raw, t)

    def summary(self, t):
        sent = max(1, self.stats["up_sent"])
        return dict(online=self.link.online(t), outage_left=round(self.link.outage_left(t), 1),
                    loss=round(100 * self.stats["up_lost"] / sent, 1), uptime=self.link.uptime(t))


class CombinedGateway:
    """ESP-NOW for the drones, Starlink for the rovers, one object for the mission loop."""

    def __init__(self, espnow, starlink):
        self.espnow, self.starlink = espnow, starlink
        self.reader = P.FrameReader()

    @property
    def jam(self):
        return self.espnow.jam

    @jam.setter
    def jam(self, value):
        self.espnow.jam = value                     # jamming the mesh doesn't touch Starlink

    @property
    def stats(self):
        return self.espnow.stats

    @property
    def drones(self):
        return {**self.espnow.drones, **self.starlink.rovers}

    def uplink(self, t, packets):
        air = {k: v for k, v in packets.items() if k in self.espnow.drones}
        ground = {k: v for k, v in packets.items() if k in self.starlink.rovers}
        return self.espnow.uplink(t, air) + self.starlink.uplink(t, ground)

    def downlink(self, t, data):
        air, ground = bytearray(), bytearray()
        for raw in self.reader.feed(data):
            dst = raw[5] if len(raw) > 5 else P.BROADCAST
            if dst == P.BROADCAST or dst in self.espnow.drones:
                air += P.frame(raw)
            if dst == P.BROADCAST or dst in self.starlink.rovers:
                ground += P.frame(raw)
        self.espnow.downlink(t, bytes(air))
        self.starlink.downlink(t, bytes(ground))


class HQUplink:
    """Homebase -> remote HQ over the homebase's own Starlink terminal."""

    def __init__(self, rng, military=False, link=None):
        self.link = link or Starlink(rng)
        self.military = military
        self.burst_s = 20.0 if military else 0.0     # EMCON: send in bursts, not all the time
        self.queue = {}                              # track id -> report waiting to go
        self.in_flight = []                          # (arrive_at, report)
        self.sent_key = {}                           # track id -> what HQ was last sent
        self.hq = {}                                 # track id -> report as HQ has it
        self.stats = dict(sent=0, delivered=0, retries=0, bytes=0)
        self.next_burst = 0.0
        self.was_online = True
        self.last_delivery = None

    def _report(self, tr, t):
        return dict(id=tr.id, status=tr.status, confirmed=tr.confirmed, assessed=tr.assessed,
                    hr=tr.hr, br=tr.br, x=round(tr.x, 1), y=round(tr.y, 1),
                    tag=hex(tr.tag_id) if tr.tag_id else None, ally=tr.ally, made=round(t, 1))

    def tick(self, t, hub):
        online = self.link.online(t)
        if online != self.was_online:
            hub._event(t, "starlink_down" if not online else "starlink_up",
                       secs=round(self.link.outage_left(t), 1) if not online else None)
            self.was_online = online
        for tr in hub.tracks:
            if not tr.confirmed:
                continue
            key = (tr.status, tr.assessed, bool(tr.hr or tr.br))
            last = self.sent_key.get(tr.id)
            moved = last is not None and math.hypot(tr.x - last[1][0], tr.y - last[1][1]) > 25.0
            if last is None or last[0] != key or moved:      # news: new person, new status, vitals,
                self.sent_key[tr.id] = (key, (tr.x, tr.y))   # or the position moved a lot
                self.queue[tr.id] = self._report(tr, t)     # newer news replaces older, unsent news
        if online and self.queue and t >= self.next_burst:
            for rep in self.queue.values():
                self.in_flight.append((t + 2 * self.link.latency(), rep))
                self.stats["sent"] += 1
                self.stats["bytes"] += len(json.dumps(rep))
            self.queue.clear()
            self.next_burst = t + self.burst_s
        keep = []
        for at, rep in self.in_flight:
            if at > t:
                keep.append((at, rep))
            elif self.link.online(t):
                self.hq[rep["id"]] = dict(rep, received=round(t, 1))
                self.stats["delivered"] += 1
                self.last_delivery = t
                hub._event(t, "hq_report", track=rep["id"], status=rep["status"],
                           delay_s=round(t - rep["made"], 1))
            else:                                    # lost in an outage: send it again later
                self.stats["retries"] += 1
                self.queue.setdefault(rep["id"], rep)
        self.in_flight = keep

    def outage(self, t, secs):
        self.link.forced = (t, t + secs)

    def summary(self, t):
        return dict(online=self.link.online(t), outage_left=round(self.link.outage_left(t), 1),
                    latency_ms=int(round(1000 * self.link.latency())), uptime=self.link.uptime(t),
                    queued=len(self.queue) + len(self.in_flight), sent=self.stats["sent"],
                    delivered=self.stats["delivered"], retries=self.stats["retries"],
                    burst=self.burst_s, last=round(self.last_delivery, 1) if self.last_delivery else None,
                    hq=sorted(self.hq.values(), key=lambda r: r["id"]))

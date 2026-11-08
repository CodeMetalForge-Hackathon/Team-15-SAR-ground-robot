"""fleet/hub.py — the homebase brain on the Jetson.

Feed it packets (from the ESP32-S3 gateway) and local messages (from the CV
code on the Jetson). Call tick(now) a few times a second. It returns the
waypoint packets to send. It never touches a clock or a port itself, so the
same class runs on hardware, over a pty, and inside the simulator.

What it does each tick
  1. link health    drones silent > link_timeout are marked LOST (their claim stays)
  2. battery        A* cost-to-home vs. time left -> return-to-base, then LAND
  3. confirm        an unconfirmed contact pulls the nearest FINDER (camera) down to watch it
                    (or an mmWave drone, if the loadout has one, for vitals)
  4. search         sequential MCTS: each drone plans on a belief its teammates already claimed;
                    thermal hunters are pulled toward phone/beacon SIGNAL AREAS from the sweepers
  5. radio          waypoints go out on change, and are re-broadcast (they double as acks)
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from link import protocol as P
from .planner import (FleetMCTS, Grid, apply_look, astar, claim_path, dist_field,
                      downhill, explain, fov_cells, snap_free, SENSOR_PRESET)

SEVERITY = {"critical": 4, "injured": 3, "unknown": 2, "ok": 1}   # rescue priority (unknown may be bad)
ROLE_NAMES = {"sweeper": "S", "hunter": "T", "finder": "F", "medic": "M", "search": "D"}
OBS_URGENCY = {"lying_down": 3.5, "not_moving": 3.2, "moving": 1.5}


def role_of(sensors) -> str:
    s = set(sensors or [])
    if "cv" in s:
        return "finder"          # camera: confirms people and watches how they're doing
    if "thermal" in s:
        return "hunter"          # thermal: finds heat signatures
    if "ble" in s:
        return "sweeper"         # radio: hears phones / beacons from far away
    if "mmwave" in s:
        return "medic"
    return "search"


def urgency(t) -> float:
    """Rescue priority. Vitals (from a wearable) beat camera observations;
    with neither, 'unknown' sits between 'moving' and 'not moving'."""
    if t.status in ("critical", "injured") or t.hr or t.br:
        return float(SEVERITY.get(t.status, 2)) + (0.5 if t.status == "critical" else 0)
    return OBS_URGENCY.get(t.observation, 2.0)
WORSE = {"unknown": 0, "ok": 1, "injured": 3, "critical": 4}       # merging evidence: worst wins


@dataclass
class HubConfig:
    endurance_s: float = 240.0      # flight time on a full pack (Tiny Whoop ~4 min)
    speed_mps: float = 5.0          # cruise speed, for time-to-home estimates
    reserve_s: float = 30.0         # never plan to land with less than this
    rtb_margin: float = 1.3         # x the A* time home, for wind and drift
    descent_mps: float = 1.0        # landing descent rate, counted in the time home
    base_alt: float = 30.0          # drone 1 altitude (m); others stacked above
    alt_step: float = 5.0           # vertical separation between drones
    confirm_alt: float = 1.5        # mmWave works within ~1.5 m
    hold_s: float = 8.0             # how long to hover over a contact
    arrive_tol: float = 0.35        # fraction of a cell that counts as "arrived"
    link_timeout: float = 5.0
    wp_period: float = 1.0          # waypoint re-broadcast period (s)
    tx_period_ds: int = 5           # tell drones: telemetry every 0.5 s
    look_period: float = 5.0        # re-count a hover as a new look after this
    gate_cells: int = 1             # contacts within this many cells are the same person
    claim_steps: int = 6
    n_sims: int = 200
    horizon: int = 18
    exposure: float = 0.0           # military: MCTS penalty for exposed cells
    military: bool = False
    allocate: bool = True           # False = no claiming of teammates' next cells (ablation)
    share_map: bool = True          # False = each drone only knows its own looks (no mesh, ablation)
    loadout: tuple = ()             # sensors per drone, as planned (roles are known before take-off)
    observe_alt: float = 12.0       # finder hovers this low to watch a person
    observe_s: float = 16.0         # ...for this long before giving up (camera needs ~12 s)
    lead_weight: float = 8.0        # how hard signal areas pull the thermal hunters


@dataclass
class DroneState:
    id: int
    alt: float
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    sigma: float = 0.0
    battery: int = 255
    state: int = 0
    sensing: int = 0
    wp_ack: int = 0
    rssi: int = 0
    last_seen: float = -1e9
    pose_t: float = -1e9            # when x, y were last reported
    airborne_since: Optional[float] = None
    cell: Optional[tuple] = None
    task: str = "idle"              # idle | search | confirm (vitals) | rtb | landed
    target: Optional[tuple] = None  # cell of the current waypoint
    target_xy: Optional[tuple] = None  # exact metres instead of the cell centre (hovering over a contact)
    cmd: int = P.CMD_GOTO
    z_cmd: Optional[float] = None
    goal: Optional[tuple] = None    # final cell for confirm transits
    hold_until: Optional[float] = None
    confirm_track: Optional[int] = None
    wp_seq: int = 0
    wp_sent_at: float = -1e9
    target_since: float = 0.0
    avoid: dict = field(default_factory=dict)   # cell -> until (cells it got stuck on)
    sent_key: Optional[tuple] = None
    det_seen: set = field(default_factory=set)
    det_ack: int = 0
    last_look: tuple = (None, -1e9)
    lost: bool = False
    rx_packets: int = 0

    @property
    def sensors(self):
        return P.mask_to_sensors(self.sensing)


@dataclass
class Track:
    id: int
    x: float
    y: float
    cell: tuple
    first_seen: float
    last_seen: float
    conf: float = 0.0
    hits: int = 0
    sensors: set = field(default_factory=set)
    drones: set = field(default_factory=set)
    status: str = "unknown"
    hr: int = 0
    br: int = 0
    tag_id: int = 0
    ally: Optional[bool] = None
    confirmed: bool = False         # a person: the camera saw them (or radar, or heat + their phone)
    assessed: bool = False          # vitals known (wearable or radar)
    checked: bool = False           # a finder already went to look
    observation: Optional[str] = None   # camera: moving | not_moving | lying_down
    obs_by: Optional[int] = None
    vitals_from: Optional[str] = None   # "wearable" | "radar"
    signal: Optional[str] = None        # linked signal area id
    false_alarm: bool = False

    @property
    def stage(self):
        if self.false_alarm:
            return "false_alarm"
        if self.observation or self.assessed:
            return "observed"
        if self.confirmed:
            return "confirmed"
        return "candidate"

    def as_dict(self):
        return dict(id=self.id, x=round(self.x, 2), y=round(self.y, 2), status=self.status,
                    confirmed=self.confirmed, assessed=self.assessed, conf=round(self.conf, 3),
                    hr=self.hr, br=self.br,
                    tag_id=hex(self.tag_id) if self.tag_id else None, ally=self.ally,
                    sensors=sorted(self.sensors), seen_by=sorted(self.drones), hits=self.hits,
                    first_seen=round(self.first_seen, 1), last_seen=round(self.last_seen, 1),
                    stage=self.stage, observation=self.observation, obs_by=self.obs_by,
                    vitals_from=self.vitals_from, signal=self.signal,
                    false_alarm=self.false_alarm, urgency=round(urgency(self), 2))


@dataclass
class SignalArea:
    """A phone/beacon heard by the sweepers. Each sighting = (sweeper x, y, estimated range):
    a ring. Several rings from different spots narrow it down to an area."""
    id: str
    tag_id: int
    obs: list = field(default_factory=list)       # (x, y, range_m)
    x: float = 0.0
    y: float = 0.0
    radius: float = 0.0
    hr: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    track: Optional[int] = None

    def as_dict(self):
        return dict(id=self.id, x=round(self.x, 1), y=round(self.y, 1), radius=round(self.radius, 1),
                    n=len(self.obs), tag=hex(self.tag_id) if self.tag_id else None, hr=self.hr or None,
                    first_seen=round(self.first_seen, 1), last_seen=round(self.last_seen, 1), track=self.track,
                    rings=[[round(x, 1), round(y, 1), round(r, 1)] for x, y, r in self.obs[-6:]])


def triage_from_vitals(hr, br):
    """PLACEHOLDER thresholds so the demo can rank contacts. Not medical advice:
    swap in whatever your medic or the CV/vitals teammate decides."""
    if not hr and not br:
        return "unknown"
    if (hr and (hr < 45 or hr > 140)) or (br and (br < 8 or br > 30)):
        return "critical"
    if (hr and (hr < 55 or hr > 115)) or (br and (br < 10 or br > 24)):
        return "injured"
    return "ok"


class Homebase:
    def __init__(self, world, n_drones=3, cfg: Optional[HubConfig] = None,
                 key: Optional[bytes] = None, allies=None, log_dir="results",
                 seq0: int = 1, home=None, verbose=True):
        self.world = world
        self.cfg = cfg or HubConfig()
        self.grid = Grid(world, home)
        self.home = self.grid.home
        self.mass = world.belief.copy()          # unnormalised: 1 - sum = cumulative POS
        self.key = key
        self.require_auth = bool(key) and self.cfg.military
        self.allies = set(allies or [])
        self.drones = {d: DroneState(d, alt=self.cfg.base_alt + (d - 1) * self.cfg.alt_step)
                       for d in range(1, n_drones + 1)}
        # roles come from the planned loadout (the operator packed the drones), else from telemetry
        self.roles, self.names = {}, {}
        counts = {}
        lo = list(self.cfg.loadout or [])
        for d in self.drones:
            r = role_of(lo[(d - 1) % len(lo)]) if lo else "search"
            counts[r] = counts.get(r, 0) + 1
            self.roles[d], self.names[d] = r, f"{ROLE_NAMES[r]}{counts[r]}"
            off = {"sweeper": 4, "hunter": 0, "finder": 2}.get(r, 0)
            self.drones[d].alt = self.cfg.base_alt + (off + counts[r] - 1) * self.cfg.alt_step
        self.signals = []
        self.lead = np.zeros_like(world.belief)

        # ablation: without a shared map every drone plans on its own private belief
        self.private = {d: world.belief.copy() for d in self.drones} if not self.cfg.share_map else None
        self.tracks = []
        self.home_field = dist_field(world, self.home)
        self.mcts = FleetMCTS(world, n_sims=self.cfg.n_sims, horizon=self.cfg.horizon,
                              exposure=self.cfg.exposure)
        self.replay = P.ReplayGuard()
        self.seq = seq0
        self.stats = dict(rx=0, rx_bad=0, rx_replay=0, tx=0, dets=0, rtb=0)
        self.verbose = verbose
        self.recalled = False
        self._now = 0.0
        self.trails = {d: [] for d in self.drones}   # (t, x, y) every ~1 s, for the dashboard
        self.events = []
        self.log_dir = log_dir
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            self._log = open(os.path.join(log_dir, "mission_log.jsonl"), "w")
        else:
            self._log = None

    # ----------------------------------------------------------------- input
    def on_raw(self, raw: bytes, rssi: int, now: float):
        try:
            pk = P.decode(raw, key=self.key, require_auth=self.require_auth)
        except P.PacketError as e:
            self.stats["rx_bad"] += 1
            self._event(now, "bad_packet", why=str(e))
            return
        if pk.src not in self.drones or pk.dst not in (P.HOME_ID, P.BROADCAST):
            return
        if self.key and pk.flags & P.FLAG_AUTH and not self.replay.ok(pk.src, pk.seq):
            self.stats["rx_replay"] += 1
            self._event(now, "replay_rejected", drone=pk.src, seq=pk.seq)
            return
        self.stats["rx"] += 1
        d = self.drones[pk.src]
        d.last_seen, d.rssi = now, rssi
        d.rx_packets += 1
        if d.lost:
            d.lost = False
            self._event(now, "link_back", drone=d.id)
        if pk.type == P.TELEMETRY:
            self._on_telemetry(d, pk.body, now)
        elif pk.type == P.DETECTION:
            self._on_detection(d, pk.body, now)

    def on_local(self, msg: dict, now: float):
        """JSON from code running on the Jetson itself (CV, an overhead tracker):
          {"type":"det","drone":2,"sensor":"cv","conf":0.8,"status":"injured","x":..,"y":..}
          {"type":"pose","drone":2,"x":..,"y":..,"z":..,"sigma":0.2}
        x, y are optional for "det": the drone's current position is used."""
        d = self.drones.get(int(msg.get("drone", 0)))
        if d is None:
            return
        if msg.get("type") == "pose":
            d.x, d.y = float(msg["x"]), float(msg["y"])
            d.z = float(msg.get("z", d.z))
            d.sigma = float(msg.get("sigma", d.sigma))
            d.last_seen = d.pose_t = now
            self._update_cell(d, now)
        elif msg.get("type") == "det":
            sensor = msg.get("sensor", "cv")
            det = P.Detection(float(msg.get("x", d.x)), float(msg.get("y", d.y)),
                              P.SENSOR_IDS.get(sensor, 2),
                              int(255 * float(msg.get("conf", 0.7))),
                              P.STATUS_IDS.get(msg.get("status", "unknown"), 0),
                              int(msg.get("hr", 0)), int(msg.get("br", 0)), 0, 0,
                              int(msg.get("tag", 0)))
            self._ingest(d, det, now)

    def _on_telemetry(self, d, t: P.Telemetry, now):
        was_flying = d.state in (1, 2, 3, 4)
        d.x, d.y, d.z, d.sigma = t.x, t.y, t.z, t.sigma
        d.pose_t = now
        d.battery, d.sensing, d.wp_ack = t.battery, t.sensing, t.wp_ack
        d.state = t.state
        flying = t.state in (1, 2, 3, 4)
        if flying and not was_flying:
            d.airborne_since = now
            d.task, d.target, d.goal, d.hold_until = ("rtb" if self.recalled else "search"), None, None, None
            self._event(now, "takeoff", drone=d.id, battery=t.battery)
        if not flying and was_flying:
            d.task, d.airborne_since = ("landed" if d.task == "rtb" else "idle"), None
            self._event(now, "landed", drone=d.id, battery=t.battery)
        self._update_cell(d, now)

    def _update_cell(self, d, now):
        tr = self.trails.setdefault(d.id, [])
        if d.state in (1, 2, 3, 4) and (not tr or now - tr[-1][0] >= 1.0):
            tr.append((now, round(d.x, 1), round(d.y, 1)))
            del tr[:-600]
        cell = snap_free(self.world, self.grid.to_cell(d.x, d.y))
        prev_cell, t_look = d.last_look
        d.cell = cell
        airborne = d.state in (1, 2, 3, 4)
        if airborne and d.sensing and (cell != prev_cell or now - t_look >= self.cfg.look_period):
            apply_look(self.world, self.mass, cell, d.sensors, d.sigma / self.world.cell_m)
            if self.private is not None:
                apply_look(self.world, self.private[d.id], cell, d.sensors, d.sigma / self.world.cell_m)
            d.last_look = (cell, now)

    def _on_detection(self, d, det: P.Detection, now):
        if det.det_id in d.det_seen:
            return                                   # a retransmit we already have
        d.det_seen.add(det.det_id)
        while ((d.det_ack + 1) & 0xFFFF) in d.det_seen:
            d.det_ack = (d.det_ack + 1) & 0xFFFF
        self._ingest(d, det, now)

    def _ingest(self, d, det: P.Detection, now):
        self.stats["dets"] += 1
        sensor = P.SENSOR_NAMES.get(det.sensor, "unknown")
        if sensor == "ble" and det.range_dm:
            self._ingest_signal(d, det, now)
            return
        conf = det.conf / 255.0
        cell = snap_free(self.world, self.grid.to_cell(det.x, det.y))
        tr = None
        if det.tag_id:
            tr = next((t for t in self.tracks if t.tag_id == det.tag_id), None)
        if tr is None:
            near = [t for t in self.tracks
                    if max(abs(t.cell[0] - cell[0]), abs(t.cell[1] - cell[1])) <= self.cfg.gate_cells
                    and (not det.tag_id or not t.tag_id)
                    # vitals are a fingerprint: very different heart/breath rates = a different person
                    and not (det.hr and t.hr and abs(det.hr - t.hr) > 20)
                    and not (det.br and t.br and abs(det.br - t.br) > 6)]
            if near:
                tr = min(near, key=lambda t: (t.x - det.x) ** 2 + (t.y - det.y) ** 2)
        new = tr is None
        if new:
            tr = Track(len(self.tracks) + 1, det.x, det.y, cell, now, now)
            self.tracks.append(tr)
        w = conf / max(tr.conf + conf, 1e-9)
        tr.x, tr.y = tr.x + w * (det.x - tr.x), tr.y + w * (det.y - tr.y)
        tr.cell = snap_free(self.world, self.grid.to_cell(tr.x, tr.y))
        tr.conf = 1 - (1 - tr.conf) * (1 - conf)
        tr.hits += 1
        tr.last_seen = now
        tr.sensors.add(sensor)
        tr.drones.add(d.id)
        if det.hr:
            tr.hr = det.hr
        if det.br:
            tr.br = det.br
        if det.tag_id:
            tr.tag_id = det.tag_id
            tr.ally = det.tag_id in self.allies if self.allies else None
        was_c, was_a, was_s, was_o = tr.confirmed, tr.assessed, tr.status, tr.observation
        if det.status in P.OBS:                          # a finder watched them: behaviour, not vitals
            tr.observation, tr.obs_by = P.OBS[det.status], d.id
            reported = "unknown"
        else:
            reported = P.STATUS.get(det.status, "unknown")
        if (det.hr or det.br) and not tr.vitals_from:
            tr.vitals_from = "radar" if sensor == "mmwave" else "wearable"
        vit = triage_from_vitals(tr.hr, tr.br)
        tr.status = max([tr.status, reported, vit], key=lambda s: WORSE[s])
        # a PERSON = the camera saw them, or radar, or heat where their phone/beacon is
        tr.confirmed = tr.confirmed or sensor in ("cv", "mmwave") or {"thermal", "ble"} <= tr.sensors
        tr.assessed = tr.assessed or bool(tr.hr or tr.br)
        self._link_signals(now)
        explain(self.world, self.mass, cell)
        if self.private is not None:
            explain(self.world, self.private[d.id], cell)
        changed = new or tr.confirmed != was_c or tr.assessed != was_a or tr.status != was_s \
            or tr.observation != was_o
        if new:
            ev = "contact_new"
        elif tr.observation and not was_o:
            ev = "observed"
        elif tr.assessed and not was_a:
            ev = "vitals"
        elif tr.confirmed and not was_c:
            ev = "confirmed"
        else:
            ev = "contact_update"
        self._event(now, ev, quiet=not changed, drone=d.id, name=self.names.get(d.id), sensor=sensor,
                    track=tr.id, x=round(det.x, 1), y=round(det.y, 1), conf=round(conf, 2),
                    status=tr.status, hr=tr.hr or None, br=tr.br or None,
                    tag=hex(det.tag_id) if det.tag_id else None, observation=tr.observation,
                    confirmed=tr.confirmed, assessed=tr.assessed)
        if self.cfg.military and det.tag_id and self.allies and det.tag_id not in self.allies:
            self._event(now, "unknown_tag_warning", tag=hex(det.tag_id), track=tr.id)
        self.write_casualties()

    # ------------------------------------------------------------- signals
    def _ingest_signal(self, d, det, now):
        """A sweeper heard a phone/beacon: (sweeper position, range) = a ring. Rings from
        different spots are combined into an area; hunters are pulled toward it."""
        key = det.tag_id or 0
        area = next((a for a in self.signals if key and a.tag_id == key), None)
        if area is None and not key:                   # anonymous signal: join a nearby area
            area = next((a for a in self.signals if not a.tag_id and
                         math.hypot(a.x - det.x, a.y - det.y) < a.radius + det.range_dm), None)
        new = area is None
        if new:
            area = SignalArea(f"P{len(self.signals) + 1}", key, first_seen=now)
            self.signals.append(area)
        area.obs.append((det.x, det.y, float(det.range_dm)))
        area.obs = area.obs[-24:]
        area.last_seen = now
        if det.hr:
            area.hr = det.hr
        old_r = area.radius
        self._locate(area)
        self._update_lead()
        self._link_signals(now)
        narrowed = not new and area.radius < 0.7 * old_r
        if new or narrowed:
            self._event(now, "signal_new" if new else "signal_narrowed", drone=d.id, name=self.names.get(d.id),
                        area=area.id, x=round(area.x, 1), y=round(area.y, 1), radius=round(area.radius),
                        tag=hex(key) if key else None, hr=area.hr or None, n=len(area.obs))

    def _locate(self, area):
        g, w = self.grid, self.world
        xs = np.array([g.to_xy((i, j)) for i in range(w.n) for j in range(w.n)])
        ll = np.zeros(len(xs))
        for x, y, r in area.obs:
            sig = 0.3 * r + 0.5 * w.cell_m
            dist = np.hypot(xs[:, 0] - x, xs[:, 1] - y)
            ll += -0.5 * ((dist - r) / sig) ** 2
        p = np.exp(ll - ll.max())
        p /= p.sum()
        area.x, area.y = float(p @ xs[:, 0]), float(p @ xs[:, 1])
        var = float(p @ ((xs[:, 0] - area.x) ** 2 + (xs[:, 1] - area.y) ** 2))
        area.radius = max(w.cell_m, math.sqrt(var) * 1.5)

    def _update_lead(self):
        self.lead = np.zeros_like(self.world.belief)
        g = self.grid
        for a in self.signals:
            if a.track is not None:
                continue                                 # already explained by a contact
            ci, cj = g.to_cell(a.x, a.y)
            rc = max(1.0, a.radius / self.world.cell_m)
            ii, jj = np.mgrid[0:self.world.n, 0:self.world.n]
            self.lead = np.maximum(self.lead, np.exp(-0.5 * ((ii - ci) ** 2 + (jj - cj) ** 2) / rc ** 2))
        self.lead[self.world.obstacles] = 0.0

    def _link_signals(self, now):
        for a in self.signals:
            if a.track is not None or not self.tracks:
                continue
            if a.radius > 3 * self.world.cell_m:
                continue                                 # not narrowed down enough to say whose phone
            cands = [t for t in self.tracks if not t.false_alarm and
                     (t.signal is None or (a.tag_id and t.tag_id == a.tag_id))]
            if not cands:
                continue
            tr = min(cands, key=lambda t: math.hypot(t.x - a.x, t.y - a.y))
            if math.hypot(tr.x - a.x, tr.y - a.y) <= a.radius + 0.5 * self.world.cell_m:
                a.track, tr.signal = tr.id, a.id
                tr.sensors.add("ble")
                if a.tag_id and not tr.tag_id:
                    tr.tag_id = a.tag_id
                    tr.ally = a.tag_id in self.allies if self.allies else None
                if a.hr and not tr.hr:
                    tr.hr, tr.vitals_from = a.hr, "wearable"
                    tr.assessed = True
                    tr.status = max([tr.status, triage_from_vitals(tr.hr, 0)], key=lambda s: WORSE[s])
                if not tr.confirmed and "thermal" in tr.sensors:
                    tr.confirmed = True
                self._update_lead()
                self._event(now, "signal_linked", area=a.id, track=tr.id, hr=a.hr or None)

    # ------------------------------------------------------------------ tick
    def tick(self, now: float) -> list:
        cfg = self.cfg
        self._now = now
        active = []
        tx_s = (20 if cfg.military else cfg.tx_period_ds) / 10.0
        timeout = max(cfg.link_timeout, 3.5 * tx_s)        # EMCON drones talk less often
        for d in self.drones.values():
            if d.state in (1, 2, 3, 4) and now - d.last_seen > timeout and not d.lost:
                d.lost = True
                self._event(now, "link_lost", drone=d.id, silent_s=round(now - d.last_seen, 1))
            if d.state in (1, 2, 3, 4) and not d.lost and d.cell is not None:
                active.append(d)

        for d in active:
            if self.recalled and d.task != "rtb":
                self._release_confirm(d)
                d.task, d.target = "rtb", None
            self._battery_check(d, now)
            self._stuck_check(d, now)
        self._assign_confirms(active, now)

        for d in active:
            if d.task == "rtb":
                self._step_rtb(d)
            elif d.task == "confirm":
                self._step_confirm(d, now)
        self._plan_search([d for d in active if d.task == "search"], now)
        return self._radio(now)

    def time_left(self, d, now):
        if d.battery != 255:
            return d.battery / 100.0 * self.cfg.endurance_s
        if d.airborne_since is None:
            return self.cfg.endurance_s
        return self.cfg.endurance_s - (now - d.airborne_since)

    def time_home(self, cell, d=None):
        """A* hops home x (fly one cell + wait up to one report for the next waypoint),
        plus the landing descent. The wait matters: in EMCON a drone reports every 2 s."""
        steps = self.home_field[cell]
        if steps == math.inf:
            return math.inf
        tx_s = (20 if self.cfg.military else self.cfg.tx_period_ds) / 10.0
        hop = self.world.cell_m / self.cfg.speed_mps + tx_s
        alt = d.alt if d is not None else self.cfg.base_alt
        return steps * hop + alt / self.cfg.descent_mps

    def _battery_check(self, d, now):
        if d.task == "rtb":
            return
        left = self.time_left(d, now) - self.cfg.reserve_s
        if left <= self.time_home(d.cell, d) * self.cfg.rtb_margin:
            self._release_confirm(d)
            d.task, d.target, d.goal, d.hold_until = "rtb", None, None, None
            self.stats["rtb"] += 1
            self._event(now, "rtb", drone=d.id, time_left=round(left + self.cfg.reserve_s, 1),
                        time_home=round(self.time_home(d.cell, d), 1))

    def _stuck_check(self, d, now):
        """Real drones get blocked (wind, an obstacle the map doesn't have, drift
        into a wall). If a hop takes far too long, give up on that cell for a bit."""
        if d.target is None or d.cmd != P.CMD_GOTO or self._arrived(d, d.target):
            return
        if d.state == 4 or now - d.pose_t > 3.0:      # it's holding on its own (no link): not stuck
            d.target_since = now
            return
        hop = self.world.cell_m / self.cfg.speed_mps
        if now - d.target_since > 4 * hop + 5:
            d.avoid[d.target] = now + 30.0
            self._event(now, "stuck", drone=d.id, cell=d.target)
            d.target = None

    def _feasible(self, d, cell, now):
        """Can this drone go to `cell` and still make it home with the reserve?"""
        hop = self.world.cell_m / self.cfg.speed_mps
        left = self.time_left(d, now) - self.cfg.reserve_s - hop
        return left > self.time_home(cell, d) * self.cfg.rtb_margin

    def _arrived(self, d, cell, now=None):
        """Within tolerance of the cell centre. With `now`, uses where the drone should be
        by now (it keeps flying between reports): in EMCON a report only comes every 2 s,
        and without this the drone would hover at every waypoint waiting for the next."""
        x, y = self.grid.to_xy(cell)
        px, py = d.x, d.y
        if now is not None and d.cmd == P.CMD_GOTO and d.target == cell:
            dx, dy = x - px, y - py
            dist = math.hypot(dx, dy)
            step = min(dist, self.cfg.speed_mps * max(0.0, now - d.pose_t))
            if dist > 1e-6:
                px, py = px + dx / dist * step, py + dy / dist * step
        return math.hypot(px - x, py - y) <= self.cfg.arrive_tol * self.world.cell_m

    def _step_rtb(self, d):
        d.z_cmd, d.target_xy = None, None
        if d.cell == self.home:
            d.target, d.cmd = self.home, P.CMD_LAND
        elif d.target is None or self._arrived(d, d.target, self._now) or d.cmd == P.CMD_LAND:
            nxt_from = d.target if d.target is not None and self._arrived(d, d.target, self._now) else d.cell
            d.target, d.cmd = downhill(self.world, self.home_field, nxt_from), P.CMD_GOTO

    def _can_confirm(self, d):
        s = d.sensors or []
        return "cv" in s or "mmwave" in s or (not s and self.roles.get(d.id) == "finder")

    def _needs_look(self, t):
        """A finder should go and look: not yet seen by a camera / not yet observed."""
        if t.checked or t.false_alarm:
            return False
        return not (t.confirmed and (t.observation or t.assessed))

    def _assign_confirms(self, active, now):
        pending = [t for t in self.tracks if self._needs_look(t)
                   and not any(d.confirm_track == t.id for d in self.drones.values())]
        pending.sort(key=lambda t: (-urgency(t), -t.conf))
        for tr in pending:
            cands = [d for d in active if d.task == "search" and self._can_confirm(d)]
            cands = [d for d in cands if self._feasible(d, tr.cell, now)]
            if not cands:
                continue
            d = min(cands, key=lambda d: abs(d.cell[0] - tr.cell[0]) + abs(d.cell[1] - tr.cell[1]))
            d.task, d.goal, d.confirm_track, d.target, d.hold_until = "confirm", tr.cell, tr.id, None, None
            self._event(now, "look_assigned" if "cv" in (d.sensors or ["cv"]) else "vitals_check",
                        drone=d.id, name=self.names.get(d.id), track=tr.id, status=tr.status)

    def _release_confirm(self, d):
        d.confirm_track, d.goal, d.hold_until, d.z_cmd, d.target_xy = None, None, None, None, None

    def _step_confirm(self, d, now):
        tr = next((t for t in self.tracks if t.id == d.confirm_track), None)
        finder = "cv" in (d.sensors or [])
        low_alt = self.cfg.observe_alt if finder else self.cfg.confirm_alt
        if tr is None or not self._needs_look(tr) or (not finder and tr.assessed):
            if tr is not None:
                tr.checked = True
            self._release_confirm(d)
            d.task, d.target = "search", None
            return
        d.goal = tr.cell
        dist = math.hypot(d.x - tr.x, d.y - tr.y)
        if dist <= self.world.cell_m:
            # close: hover over the contact's estimated position, not its cell centre
            d.target, d.target_xy = d.goal, (tr.x, tr.y)
            d.cmd, d.z_cmd = P.CMD_HOLD, low_alt
            if d.hold_until is None:
                d.hold_until = now + 60.0                  # max time to get over it and down
            over = dist <= 0.15 * self.world.cell_m + 0.5
            low = d.z <= low_alt + 0.25
            hold = self.cfg.observe_s if finder else self.cfg.hold_s
            vis = getattr(self.world, "vis", None)
            if vis is not None:
                hold /= max(float(vis[tr.cell]), 0.4)      # radar through leaves needs a longer look
            if over and low and d.hold_until - now > hold:
                d.hold_until = now + hold                  # over it and low: radar gets its look
            if now >= d.hold_until:
                tr.checked = True
                if finder:
                    self._event(now, "look_none", drone=d.id, name=self.names.get(d.id), track=tr.id,
                                note="camera saw no person here (false heat contact?)")
                else:
                    self._event(now, "vitals_none", drone=d.id, track=tr.id,
                                note="hovered, radar saw no vitals (false contact, or no breathing)")
                self._release_confirm(d)
                d.task, d.target = "search", None
            return
        d.hold_until, d.target_xy = None, None             # not over it (yet / any more): restart the clock
        if d.target is None or self._arrived(d, d.target, now) or d.cmd == P.CMD_HOLD:
            start = d.target if d.target is not None and d.cmd == P.CMD_GOTO and self._arrived(d, d.target, now) else d.cell
            path = astar(self.world, start, d.goal)
            if path is None:                               # truly unreachable (inside a no-fly zone)
                tr.checked = True
                self._release_confirm(d)
                d.task, d.target = "search", None
                return
            d.target, d.cmd, d.z_cmd = (path[0] if path else d.goal), P.CMD_GOTO, None

    def _plan_search(self, searchers, now):
        if not searchers:
            return
        total = float(self.mass.sum())
        claimed = self.mass / total if total > 0 else self.mass.copy()
        replan, taken = [], set()
        ids = {d.id for d in searchers}
        for d in self.drones.values():          # everyone else's current target is claimed
            if d.target is not None and d.state in (1, 2, 3, 4) and self.cfg.allocate:
                if d.id in ids and (self._arrived(d, d.target, now) or d.cmd != P.CMD_GOTO):
                    continue
                apply_look(self.world, claimed, d.target, d.sensors or ["thermal"])
                taken.add(d.target)
        for d in searchers:
            if d.target is None or self._arrived(d, d.target, now) or d.cmd != P.CMD_GOTO:
                replan.append(d)
        for d in sorted(replan, key=lambda d: d.id):
            sensors = d.sensors or ["thermal"]
            sensors = [x for x in sensors if x in SENSOR_PRESET] or ["thermal"]
            main = max(sensors, key=lambda x: fov_cells(x, self.world.cell_m))
            self.world.fov, self.world.pod = fov_cells(main, self.world.cell_m), SENSOR_PRESET[main]["pod"]
            here = d.target if (d.target is not None and d.cmd == P.CMD_GOTO
                                and self._arrived(d, d.target, now)) else d.cell
            moves = [m for m in self.world.neighbours(here)
                     if self._feasible(d, m, now) and d.avoid.get(m, 0) <= now and m != d.cell]
            if not moves:
                moves = [m for m in self.world.neighbours(here) if self._feasible(d, m, now)]
            free = [m for m in moves if m not in taken] if self.cfg.allocate else moves
            allowed = free or moves
            if not allowed:
                d.task, d.target = "rtb", None       # nowhere safe to go: head home
                self._step_rtb(d)
                continue
            plan_on = claimed if self.private is None else self.private[d.id]
            if self.roles.get(d.id) == "hunter" and self.lead.any():
                # go where phones were heard: mix the search map with the signal areas
                pn = plan_on / max(float(plan_on.sum()), 1e-12)
                ld = self.lead * (~self.world.obstacles)
                plan_on = 0.4 * pn + 0.6 * ld / max(float(ld.sum()), 1e-12)
            s = float(plan_on.sum())
            # the thermal hunter gets the full planning budget; sweepers (huge radio footprint)
            # and the finder (mostly waiting to be called) do fine with a quarter of it
            self.mcts.n_sims = self.cfg.n_sims if self.roles.get(d.id) in ("hunter", "search") \
                else max(20, self.cfg.n_sims // 4)
            nxt = self.mcts.next_move(self.world, plan_on / s if s > 0 else plan_on, here, allowed)
            d.target, d.cmd, d.z_cmd, d.target_xy = nxt, P.CMD_GOTO, None, None
            if self.cfg.allocate:
                taken.add(nxt)
                claim_path(self.world, claimed, nxt, sensors, self.cfg.claim_steps)

    def recall(self, now):
        """Operator: everyone home now (mission over, weather, threat)."""
        if not self.recalled:
            self.recalled = True
            self._event(now, "recall")

    # ----------------------------------------------------------------- radio
    def _radio(self, now):
        out = []
        tx_ds = 20 if self.cfg.military else self.cfg.tx_period_ds
        period = 3.0 if self.cfg.military else self.cfg.wp_period
        for d in self.drones.values():
            if d.target is None or d.state == 0:
                continue
            x, y = d.target_xy if d.target_xy is not None else self.grid.to_xy(d.target)
            z = d.z_cmd if d.z_cmd is not None else (0.0 if d.cmd == P.CMD_LAND else d.alt)
            key = (round(x, 1), round(y, 1), d.cmd, round(z, 2))
            changed = key != d.sent_key
            if changed:
                d.wp_seq += 1
                d.sent_key = key
                d.target_since = now
            if changed or now - d.wp_sent_at >= period:
                wp = P.Waypoint(x, y, z, float("nan"), d.cmd, tx_ds, d.det_ack, d.wp_seq)
                out.append(P.encode(wp, P.HOME_ID, d.id, self.seq, int(now * 1000), key=self.key))
                self.seq += 1
                d.wp_sent_at = now
                self.stats["tx"] += 1
        return out

    # ---------------------------------------------------------------- output
    def pos(self):
        """Cumulative probability of success for a single lost person."""
        return 1.0 - float(self.mass.sum())

    def casualties(self):
        return sorted([t for t in self.tracks if not t.false_alarm], key=lambda t: (-urgency(t), -t.conf))

    def write_casualties(self):
        if not self.log_dir:
            return
        with open(os.path.join(self.log_dir, "casualties.json"), "w") as f:
            json.dump([t.as_dict() for t in self.casualties()], f, indent=1)

    def status_line(self, now):
        parts = []
        for d in self.drones.values():
            bat = "?" if d.battery == 255 else f"{d.battery}%"
            tag = "LOST" if d.lost else d.task
            parts.append(f"{self.names.get(d.id, 'D' + str(d.id))} {tag:<7} {bat:>4}")
        conf = sum(t.confirmed for t in self.tracks)
        vit = sum(bool(t.observation or t.assessed) for t in self.tracks)
        return (f"t={now:6.1f}s | " + " | ".join(parts) +
                f" | signals {len(self.signals)} | contacts {len(self.tracks)} ({conf} people, {vit} checked) "
                f"| POS {100 * self.pos():4.1f}%")

    def _event(self, now, ev, quiet=False, **kw):
        rec = dict(t=round(now, 2), ev=ev, **kw)
        if quiet:
            rec["q"] = 1                       # routine update: logged, but not shown in the timeline
        self.events.append(rec)
        if self._log:
            self._log.write(json.dumps(rec) + "\n")
            self._log.flush()
        if self.verbose and not quiet and ev not in ("bad_packet",):
            extras = " ".join(f"{k}={v}" for k, v in kw.items() if v is not None and v is not False)
            print(f"  [{now:6.1f}s] {ev:<17} {extras}")

    def close(self):
        self.write_casualties()
        if self._log:
            self._log.close()

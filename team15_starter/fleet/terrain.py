"""fleet/terrain.py — real terrain under the search grid, and the personnel-
recovery scenario built on it.

Terrain comes from OpenStreetMap (forest, roads, water, buildings, clearings)
through the public Overpass API, once, then it's cached in results/. With no
internet it falls back to synthetic terrain and says so.

The scenario ("pr" = personnel recovery): one isolated soldier, a last known
position (LKP), reported hostile positions, and an authenticated ally beacon.
His hiding-place prior follows evasion behaviour: he moves away from the LKP,
stays under cover, keeps clear of roads and of the enemy, and stays near water.
"""
from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import numpy as np

CLASSES = ["open", "forest", "scrub", "water", "road", "trail", "building", "wetland"]
C = {name: k for k, name in enumerate(CLASSES)}

# how much a camera/thermal sensor can see into each class (1 = clear view)
VISIBILITY = {"open": 1.0, "forest": 0.35, "scrub": 0.6, "water": 1.0, "road": 1.0,
              "trail": 0.7, "building": 0.3, "wetland": 0.85}
# how attractive each class is as a hide site for an evader
COVER = {"open": 0.12, "forest": 1.0, "scrub": 0.75, "water": 0.0, "road": 0.0,
         "trail": 0.05, "building": 0.45, "wetland": 0.3}

OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
# a lost civilian isn't hiding: trails, open ground and buildings draw them in
COVER_CIVILIAN = {"open": 0.7, "forest": 0.45, "scrub": 0.4, "water": 0.0, "road": 0.5,
                  "trail": 1.0, "building": 0.8, "wetland": 0.2}
R_EARTH = 6378137.0


# ------------------------------------------------------------------ geometry
def xy_to_ll(x, y, origin):
    lat0, lon0 = origin
    return (lat0 + math.degrees(y / R_EARTH),
            lon0 + math.degrees(x / (R_EARTH * math.cos(math.radians(lat0)))))


def ll_to_xy(lat, lon, origin):
    lat0, lon0 = origin
    return (math.radians(lon - lon0) * R_EARTH * math.cos(math.radians(lat0)),
            math.radians(lat - lat0) * R_EARTH)


def cell_centers(n, cell_m, home):
    hi, hj = home
    j, i = np.meshgrid(np.arange(n), np.arange(n))
    return (j - hj) * cell_m, (hi - i) * cell_m          # x, y arrays shaped (n, n)


def _in_poly(px, py, poly):
    """Even-odd point-in-polygon, vectorised over px/py arrays."""
    inside = np.zeros(px.shape, dtype=bool)
    xs, ys = poly[:, 0], poly[:, 1]
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi, xj, yj = xs[i], ys[i], xs[j], ys[j]
        cross = ((yi > py) != (yj > py)) & (px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi)
        inside ^= cross
        j = i
    return inside


def _burn_line(grid, value, pts, n, cell_m, home, width_cells=0):
    hi, hj = home
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        steps = max(2, int(math.hypot(x1 - x0, y1 - y0) / (cell_m / 4)))
        for t in np.linspace(0, 1, steps):
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            j, i = int(round(x / cell_m)) + hj, hi - int(round(y / cell_m))
            for di in range(-width_cells, width_cells + 1):
                for dj in range(-width_cells, width_cells + 1):
                    if 0 <= i + di < n and 0 <= j + dj < n:
                        grid[i + di, j + dj] = value


# ------------------------------------------------------------------ OSM
def _classify(tags):
    t = tags or {}
    if "building" in t:
        return "building"
    if t.get("natural") == "water" or t.get("waterway") in ("riverbank",) or \
            t.get("landuse") in ("reservoir", "basin"):
        return "water"
    if t.get("natural") == "wetland":
        return "wetland"
    if t.get("landuse") == "forest" or t.get("natural") == "wood":
        return "forest"
    if t.get("natural") in ("scrub", "heath"):
        return "scrub"
    if t.get("landuse") in ("meadow", "grass", "farmland", "farmyard", "recreation_ground",
                            "winter_sports", "quarry", "industrial", "residential", "military") or \
            t.get("natural") in ("grassland", "bare_rock", "scree", "sand", "beach") or \
            t.get("leisure") in ("park", "pitch", "golf_course") or t.get("amenity") == "parking":
        return "open"
    return None


def rasterize_osm(osm, origin, n, cell_m, home, default="forest"):
    """OSM Overpass JSON -> class grid. Areas first (big to small), then lines on top."""
    px, py = cell_centers(n, cell_m, home)
    grid = np.full((n, n), C[default], dtype=np.int8)
    areas, lines = [], []
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        if el.get("type") == "way" and el.get("geometry"):
            pts = np.array([ll_to_xy(g["lat"], g["lon"], origin) for g in el["geometry"]])
            closed = len(pts) > 3 and np.allclose(pts[0], pts[-1])
            if "highway" in tags:
                kind = "trail" if tags["highway"] in ("path", "footway", "track", "bridleway", "steps", "cycleway") else "road"
                lines.append((kind, pts, 1 if tags["highway"] in ("motorway", "trunk", "primary") else 0))
            elif tags.get("waterway") in ("river", "stream", "canal", "brook"):
                lines.append(("water", pts, 1 if tags["waterway"] == "river" else 0))
            elif closed and _classify(tags):
                areas.append((_classify(tags), pts))
        elif el.get("type") == "relation" and tags.get("type") == "multipolygon" and _classify(tags):
            for m in el.get("members", []):
                if m.get("role") == "outer" and m.get("geometry"):
                    pts = np.array([ll_to_xy(g["lat"], g["lon"], origin) for g in m["geometry"]])
                    if len(pts) > 3:
                        areas.append((_classify(tags), pts))

    def area(p):
        return abs(np.dot(p[:-1, 0], p[1:, 1]) - np.dot(p[1:, 0], p[:-1, 1])) / 2

    for kind, pts in sorted(areas, key=lambda a: -area(a[1])):    # small areas win
        grid[_in_poly(px, py, pts)] = C[kind]
    for kind, pts, wide in lines:
        _burn_line(grid, C[kind], pts, n, cell_m, home, wide if cell_m < 8 else 0)
    return grid


def overpass_query(origin, n, cell_m, home, timeout=25):
    hi, hj = home
    x0, x1 = (-hj - 1) * cell_m, (n - hj) * cell_m
    y0, y1 = (hi - n) * cell_m, (hi + 1) * cell_m
    s, w = xy_to_ll(x0, y0, origin)
    nn, e = xy_to_ll(x1, y1, origin)
    bbox = f"{s:.6f},{w:.6f},{nn:.6f},{e:.6f}"
    return (f"[out:json][timeout:{timeout}];("
            f'way["highway"]({bbox});way["waterway"]({bbox});way["building"]({bbox});'
            f'way["natural"]({bbox});way["landuse"]({bbox});way["leisure"]({bbox});way["amenity"="parking"]({bbox});'
            f'relation["type"="multipolygon"]["natural"]({bbox});relation["type"="multipolygon"]["landuse"]({bbox});'
            f");out geom;")


def fetch_osm(origin, n, cell_m, home, timeout=25):
    q = overpass_query(origin, n, cell_m, home, timeout)
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    import time as _t
    deadline = _t.monotonic() + 75                     # give up on the network after ~a minute
    for url in OVERPASS:
        if _t.monotonic() > deadline:
            break
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "team15-sar-sim/1.0"})
            with urllib.request.urlopen(req, timeout=timeout + 5) as r:
                return json.loads(r.read().decode())
        except Exception as e:          # noqa: BLE001  (any network trouble -> try the next mirror)
            last = e
    raise OSError(f"Overpass unreachable: {last}")


def synthetic_terrain(n, cell_m, home, seed):
    """Offline stand-in: forest with clearings, a road and a stream."""
    rng = np.random.default_rng(seed + 777)
    px, py = cell_centers(n, cell_m, home)
    grid = np.full((n, n), C["forest"], dtype=np.int8)
    for _ in range(4):
        cx, cy, r = rng.uniform(0, n * cell_m, 2).tolist() + [rng.uniform(2, 4) * cell_m]
        grid[np.hypot(px - cx, py - cy) < r] = C["open"]
    road = [(-cell_m, rng.uniform(0.1, 0.3) * n * cell_m), (n * cell_m, rng.uniform(0.0, 0.4) * n * cell_m)]
    _burn_line(grid, C["road"], np.array(road), n, cell_m, home)
    k = np.linspace(0, 1, 12)
    stream = np.stack([k * n * cell_m, (0.55 + 0.2 * np.sin(k * 5 + seed)) * n * cell_m], -1)
    _burn_line(grid, C["water"], stream, n, cell_m, home)
    return grid


_OFFLINE = False    # after one failed fetch, don't make every new mission wait again


def load_terrain(origin, n, cell_m, home, seed=0, cache_dir="results", default="forest", quiet=False, osm=None):
    """osm: Overpass JSON the dashboard already downloaded in the browser (preferred)."""
    global _OFFLINE
    key = f"terrain_{origin[0]:.5f}_{origin[1]:.5f}_{n}_{cell_m:g}_{default}.json"
    path = os.path.join(cache_dir, key)
    say = (lambda *a: None) if quiet else print
    try:
        with open(path) as f:
            d = json.load(f)
        return np.array(d["grid"], dtype=np.int8), d["source"]
    except (OSError, ValueError, KeyError):
        pass
    if osm is None and _OFFLINE:
        return synthetic_terrain(n, cell_m, home, seed), "synthetic (offline)"
    if osm is None:
        say("  terrain: fetching OpenStreetMap for this area (first run only, up to a minute)...")
    try:
        if osm is None:
            osm = fetch_osm(origin, n, cell_m, home, timeout=40)
        grid = rasterize_osm(osm, origin, n, cell_m, home, default)
        source = f"OpenStreetMap ({len(osm.get('elements', []))} features; unmapped land = {default})"
        mix = ", ".join(f"{100 * float((grid == k).mean()):.0f}% {name}" for k, name in enumerate(CLASSES) if (grid == k).any())
        say(f"  terrain: {source}: {mix}")
    except OSError as e:
        _OFFLINE = True
        say(f"  terrain: {e}. Using synthetic terrain (it won't match the satellite map).")
        return synthetic_terrain(n, cell_m, home, seed), "synthetic (offline)"
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"grid": grid.tolist(), "source": source}, f)
    return grid, source


# ------------------------------------------------------------------ scenario
@dataclass
class Scenario:
    name: str
    brief: str
    origin: tuple
    terrain: np.ndarray
    source: str
    lkp: tuple                         # last known position, metres
    threats: list                      # [(x, y, radius_m)]
    prior: np.ndarray
    vis: np.ndarray                    # camera visibility per cell
    threat: np.ndarray                 # 0..1 exposure per cell
    nofly: np.ndarray                  # hostile cores: never fly here
    allies: set = field(default_factory=set)
    tags: list = field(default_factory=list)   # beacon id carried by each hidden person
    minutes_ago: int = 35

    def regions(self, mass):
        """Share of the current belief in each kind of place (for the 'where he likely is' panel)."""
        m = mass / max(mass.sum(), 1e-12)
        n = m.shape[0]
        px, py = self._xy(n)
        near = np.hypot(px - self.lkp[0], py - self.lkp[1]) <= 300
        t = self.terrain
        water_near = _dilate(t == C["water"], 2)
        out = [
            ("Under trees, within 300 m of where he went down", float(m[(t == C["forest"]) & near].sum())),
            ("Under trees, further out", float(m[(t == C["forest"]) & ~near].sum())),
            ("Scrub or brush", float(m[t == C["scrub"]].sum())),
            ("By a stream or pond (water source)", float(m[water_near & (t != C["forest"]) & (t != C["scrub"])].sum())),
            ("Buildings or ruins", float(m[t == C["building"]].sum())),
            ("Open ground or trails", float(m[np.isin(t, [C["open"], C["trail"], C["road"], C["wetland"]]) & ~water_near].sum())),
        ]
        return [(k, round(100 * v, 1)) for k, v in out]

    def _xy(self, n):
        return self._centers

    def describe(self, x, y, cell_m, home):
        """Ground truth facts about a spot, for the recovery report."""
        n = self.terrain.shape[0]
        j, i = int(round(x / cell_m)) + home[1], home[0] - int(round(y / cell_m))
        i, j = min(max(i, 0), n - 1), min(max(j, 0), n - 1)
        px, py = self._centers
        cls = CLASSES[self.terrain[i, j]]
        roads = np.isin(self.terrain, [C["road"]])
        d_road = float(np.min(np.hypot(px[roads] - x, py[roads] - y))) if roads.any() else None
        d_threat = min((math.hypot(x - tx, y - ty) - r for tx, ty, r in self.threats), default=None)
        return dict(terrain=cls, road_m=None if d_road is None else round(d_road),
                    threat_m=None if d_threat is None else round(max(0.0, d_threat)),
                    lkp_m=round(math.hypot(x - self.lkp[0], y - self.lkp[1])))


def _dilate(mask, r):
    out = mask.copy()
    n = mask.shape[0]
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            sh = np.zeros_like(mask)
            sh[max(0, di):n + min(0, di), max(0, dj):n + min(0, dj)] = \
                mask[max(0, -di):n - max(0, di), max(0, -dj):n - max(0, dj)]
            out |= sh
    return out


ALLY_BEACON = 0x7E5A11ED


def personnel_recovery(origin, n, cell_m, home, seed=0, n_people=1, cache_dir="results",
                       default_cover="forest", quiet=False, osm=None, lkp=None, threats=None,
                       civilian=False):
    """lkp / threats: set by the operator in the dashboard, or None for random.
    threats=[] means no hostiles. civilian=True: a lost hiker, not an evader."""
    rng = np.random.default_rng(seed + 4242)
    terrain, source = load_terrain(origin, n, cell_m, home, seed, cache_dir, default_cover, quiet, osm)
    px, py = cell_centers(n, cell_m, home)
    span = n * cell_m
    if lkp is None:
        lkp = (span * rng.uniform(0.45, 0.65), span * rng.uniform(0.45, 0.65))
    lkp = (float(lkp[0]), float(lkp[1]))
    if threats is None:
        threats = []
        if not civilian:
            for corner in rng.permutation([(0.9, 0.25), (0.25, 0.9), (0.9, 0.9)])[:2]:
                tx = span * float(np.clip(corner[0] + rng.uniform(-0.08, 0.08), 0.05, 1.0))
                ty = span * float(np.clip(corner[1] + rng.uniform(-0.08, 0.08), 0.05, 1.0))
                threats.append((tx, ty, span * rng.uniform(0.17, 0.22)))
    threats = [(float(x), float(y), float(r)) for x, y, r in threats]
    threat = np.zeros((n, n))
    nofly = np.zeros((n, n), dtype=bool)
    for tx, ty, r in threats:
        d = np.hypot(px - tx, py - ty)
        threat = np.maximum(threat, np.clip(1 - d / r, 0, 1))
        nofly |= d < 0.4 * r
    nofly[home] = False

    # evader behaviour: away from the crash site but not far (ring), under cover,
    # off roads, near water, away from the enemy
    d = np.hypot(px - lkp[0], py - lkp[1])
    sigma = 0.25 * span
    ring = (d / sigma ** 2) * np.exp(-d ** 2 / (2 * sigma ** 2)) + 0.15 / sigma
    table = COVER_CIVILIAN if civilian else COVER
    cover = np.vectorize(lambda k: table[CLASSES[k]])(terrain)
    road = _dilate(terrain == C["road"], 1)
    water = _dilate(terrain == C["water"], 2)
    prior = ring * cover * np.where(road & (terrain != C["road"]), 0.3, 1.0) \
        * np.where(water & (terrain != C["water"]), 1.35, 1.0) * (1 - 0.95 * threat)
    prior[nofly] = 0
    prior = prior / prior.sum()
    # people don't always follow the model: keep 15% spread over every place he could be
    # (LastSeen's "none of these"). Otherwise someone in an unlikely spot is never searched.
    valid = ~nofly & (terrain != C["water"])
    prior = 0.85 * prior + 0.15 * valid / valid.sum()
    vis = np.vectorize(lambda k: VISIBILITY[CLASSES[k]])(terrain)

    who = "person" if n_people == 1 else f"{n_people} people"
    if civilian:
        brief = (f"Missing {who}, last seen {round(math.hypot(*lkp))} m from the homebase, 35 minutes ago. "
                 f"Lost hikers drift to trails, clearings and buildings. Some carry a phone that the drones can hear. "
                 f"Terrain: {source}.")
        name, allies, tags = "Civilian search", set(), [0] * n_people
    else:
        hostile = ("Hostile positions reported to the " + " and ".join(_bearing(t, (0, 0)) for t in threats) + ". ") \
            if threats else "No hostiles reported. "
        brief = (f"Isolated {'soldier' if n_people == 1 else 'crew of ' + str(n_people)}, last known position "
                 f"{round(math.hypot(*lkp))} m from the homebase, 35 minutes ago. Each carries an authenticated "
                 f"beacon (short range, intermittent). {hostile}Radio is contested: low-emission mode, signed packets. "
                 f"Terrain: {source}.")
        tags = [ALLY_BEACON + k for k in range(n_people)]
        name, allies = "Personnel recovery", set(tags)
    sc = Scenario(name, brief, tuple(origin), terrain, source, lkp, threats,
                  prior, vis, threat, nofly, allies=allies, tags=tags)
    sc._centers = (px, py)
    return sc


def _bearing(p, frm):
    ang = (math.degrees(math.atan2(p[0] - frm[0], p[1] - frm[1])) + 360) % 360
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][int((ang + 22.5) // 45) % 8]

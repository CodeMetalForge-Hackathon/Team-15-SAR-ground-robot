# Range integration contract (navigation, dashboard, Qwen)

One process, `python3 -m ranging serve`, owns the sensor. Everyone else reads
**snapshots**. No consumer opens GPIO or polls the hardware.

This is an **additive, separate stream** (`team15.range_snapshot/1`). It does
not change the observation contract (§8.2), the camera sightings
(`perception/SIGHTING_FORMAT.md`) or the route planner.

**Do not POST range snapshots to `/observations`.** A range is not a person
observation. It has no `cell` or `kind`. The range is the nearest echo in the
forward beam. It is **never a "distance to person"** unless an association with
a camera detection has been validated, and no such association exists today.

## Transports

| Consumer | Use | How |
|---|---|---|
| Navigation (same Pi) | `RangeClient()` | reads `/dev/shm/team15_range.json` (atomically replaced, tmpfs, no network) |
| Anything on the Pi | `GET http://127.0.0.1:8765/range`, `GET /health` | `serve --host 127.0.0.1` (default) |
| Dashboard on the Mac | `GET http://100.97.93.118:8765/range` over Tailscale | `serve --host 0.0.0.0 --cors-origin http://127.0.0.1:8000` |
| Debug | `python3 -m ranging watch [--url …]` | prints what a consumer sees |

## Navigation API (wheel-control worker)

```python
from ranging import RangeClient

rc = RangeClient()                      # or RangeClient(url="http://127.0.0.1:8765/range")

def forward_ok() -> bool:
    return rc.forward_motion_allowed()  # False on ANY doubt: stale, invalid, missing, unreadable, BLOCKED

snap = rc.get()                          # full snapshot (below); never raises
```

Rules for the navigation controller:
1. **Call `forward_motion_allowed()` before every forward motor command, and
   again at least every 100 ms while moving forward.** If it is `False`, stop
   forward motion. `UNKNOWN` means stop, the same as `BLOCKED`.
2. Don't cache the answer. Freshness is re-checked on every `get()` against the
   reading's own timestamp. A crashed service therefore turns into UNKNOWN within
   `stale_after_s` (0.5 s).
3. The sensor sees only a **15° forward cone**. It says nothing about reversing,
   turning or the sides. Those motions need their own policy, which is outside
   this module.
4. In `CAUTION`, forward motion is allowed but should be slowed. The thresholds
   assume `max_speed_mps = 0.30`. **Do not drive faster than the
   `max_speed_mps` in the range config**, because the BLOCKED distance is the
   stopping distance at that speed.
5. Open space with nothing within range gives `OUT_OF_RANGE`/`NO_ECHO`, which
   maps to UNKNOWN, so the robot does not drive forward there. This is
   deliberate: a missing echo is not proof of a clear path.

### Adapter for `rover/` (feature/rover-navigation)

`rover/sensors.py` expects `RangeReading(t, status OK|NO_ECHO|ERROR, range_m,
max_range_m, source, seq)` with `t` on the controller clock.
`ranging.rover_io.GroveRangeIO` produces exactly those fields, plus our verdict:

```python
from ranging.rover_io import GroveRangeIO
from rover.sensors import RangeReading

class PiRangeIO:                                  # navigator IO.clock()/read_range()
    def __init__(self):
        self.g = GroveRangeIO()                   # reads /dev/shm/team15_range.json
        self.last = None
    def clock(self) -> float:
        return GroveRangeIO.clock()               # time.monotonic(): MUST be the navigator clock
    def read_range(self):
        f = self.g.read_fields()                  # never raises
        self.last = f
        return RangeReading(**{k: f[k] for k in ("t", "status", "range_m", "max_range_m", "source", "seq")})
    def forward_motion_allowed(self) -> bool:     # AND this into every forward command
        return bool(self.last and self.last["forward_motion_allowed"])
```

| Our state | `status` | `range_m` | `forward_motion_allowed` |
|---|---|---|---|
| fresh VALID, CLEAR / CAUTION | `OK` | decision range | `true` |
| fresh VALID, **BLOCKED** | `OK` | decision range (honest, for the obstacle map) | **`false`** |
| VALID but UNKNOWN (filter window not full) | `ERROR` | null | false |
| `NO_ECHO`, `OUT_OF_RANGE` | `NO_ECHO` | null | false |
| any other status, **stale**, unreadable, other host | `ERROR` | null | false |

Required on the navigation side. These are points to agree on; this branch does
not edit `rover/`:
1. **AND `forward_motion_allowed` into the forward gate.** `rover.sensors.assess()`
   checks only `range_m < required_clear_m`. If `required_clear_m` is below our
   `blocked_threshold_m` (0.28 m now), a BLOCKED reading would pass as CLEAR.
   Also set `required_clear_m ≥ blocked_threshold_m`. That value is included in
   every reading's fields.
2. **Keep `NoEchoPolicy.UNKNOWN` for the Grove sensor.** `CLEAR_TO_MAX` must
   not be used with real hardware. A missing echo is not proof of a clear path
   (fail-safe STOP).
3. Navigation's `clock()` must be `time.monotonic()` on the same Pi.
4. `sensor_max_age_s = 0.20` (navigation) is stricter than our 0.5 s, which is
   fine, because the stricter limit wins. At a 0.1 s sample interval, one missed
   ping will stop the robot. Don't set the interval above 0.1 s.

## Snapshot schema `team15.range_snapshot/1`

| Field | Type | Meaning |
|---|---|---|
| `schema` | str | `team15.range_snapshot/1` |
| `obstacle_status` | `CLEAR` \| `CAUTION` \| `BLOCKED` \| `UNKNOWN` | after freshness is re-checked by the reader |
| `forward_motion_allowed` | bool | `true` only for fresh CLEAR/CAUTION |
| `range_m` | float \| null | decision range: nearest echo in the beam, `min(latest valid, rolling median)`. `null` when untrustworthy |
| `valid` | bool | latest reading valid |
| `obs_time` | float | epoch s of the latest ping (Pi wall clock, NTP) |
| `stale_after_s` | float | freshness limit |
| `freshness` | `{age_s, stale, stale_after_s, checked_at}` | computed **by the reader** at read time |
| `latest` | reading | raw last ping (below) |
| `assessment` | object | `status, reason, nearest_range_m, median_range_m, valid_in_window, thresholds{blocked_m, caution_m, hysteresis_m}, range_semantics` |
| `geometry` | object | `floor_intercept_m, stopping_distance_m, blocked_threshold_m, caution_threshold_m, blind_spots[]` |
| `health` | object | `state` (`STARTING`/`OK`/`DEGRADED`/`FAULT`), `consecutive_invalid`, `counts{status: n}`, `last_error`, `reopen_count`, `hint` |
| `provenance` | object | `source_mode` (`LIVE-HW`/`SIMULATED`), `platform` (`BENCH`/`SIM`), `source`, `driver`, `host`, `gpiochip`, `gpio_bcm`, `wiring_verified_by`, `service_boot_id`, `config_sha256` |
| `published_at`, `published_time`, `published_mono_ns` | | when the service wrote the snapshot |
| `sensor_id`, `sensor_type`, `measurement_type`, `sensor_mount` | | `grove-us-front`, `GROVE_ULTRASONIC`, `FORWARD_OBSTACLE_RANGE`, `FRONT` |
| `error` | str | only on reader-side failure snapshots (service unreachable or unreadable) |

Reading (`latest`, `team15.range_reading/1`):

```json
{"schema": "team15.range_reading/1", "sensor_type": "GROVE_ULTRASONIC",
 "measurement_type": "FORWARD_OBSTACLE_RANGE", "sensor_id": "grove-us-front",
 "distance_m": 0.853, "valid": true, "timestamp": "2026-11-07T23:40:01.120+00:00",
 "obs_time": 1794094801.12, "mono_ns": 81234567890123, "seq": 412, "sensor_mount": "FRONT",
 "measurement_status": "VALID", "echo_us": 4974.0, "source": "RASPBERRY_PI_5",
 "driver": "gpiod", "detail": null}
```

`measurement_status` is one of `VALID`, `NO_ECHO`, `ECHO_TIMEOUT`,
`MISSED_ECHO_START`, `OUT_OF_RANGE`, `BELOW_MIN_RANGE`, `LINE_STUCK_HIGH`,
`DRIVER_ERROR` or `NOT_STARTED`. **Every status except VALID has
`distance_m: null`.** This is enforced by the data type.

Compatibility: fields may be added in `/1`, but none will be removed or have
their meaning changed. Readers must ignore unknown fields. A breaking change
means `/2`.

## Dashboard (T2) example

Panel: `ranging/examples/range_panel.html` is self-contained and polls `/range`.
It shows the status, range, age, health and provenance, and shows UNKNOWN when a
fetch fails. To embed it in the PR #5 dashboard, the dashboard owner can add a
read-only proxy. This is a suggestion; this branch does not edit `dashboard/`:

```python
# dashboard/app.py (owner's choice)
from ranging import RangeClient
_range = RangeClient(url=os.environ.get("RANGE_URL", "http://100.97.93.118:8765/range"))

@app.get("/api/range")
def api_range():
    return _range.get()   # always a dict; UNKNOWN + error on failure
```

Label it **"Forward obstacle range (ultrasonic)"**, never "distance to person".
Show `provenance.source_mode` (SIMULATED / LIVE-HW), as for the other sensors.

## Qwen tool (T3), read-only

```json
{"name": "get_forward_range",
 "description": "Latest forward ultrasonic obstacle range of the ground robot. Read-only. Not a distance to any person.",
 "parameters": {"type": "object", "properties": {}, "additionalProperties": false}}
```

Result: `{obstacle_status, range_m, valid, freshness.age_s, health.state, provenance.source_mode}`
taken from `RangeClient().get()`. The tool takes no arguments and moves nothing.
When stating a range, Qwen must quote the tool result and its age.

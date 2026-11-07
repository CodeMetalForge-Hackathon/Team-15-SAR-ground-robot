# ranging: Grove Ultrasonic Ranger for the Team 15 ground robot

A forward obstacle range service for the RoverC-Pro + Raspberry Pi 5. It is read
by the navigation controller, the rescue dashboard and the Qwen assistant.
Stdlib only. The hardware driver also needs the system `python3-libgpiod` (2.x),
which is already on the Pi.

| File | What |
|---|---|
| `reading.py` | `RangeReading` + `MeasurementStatus`. An invalid reading **cannot** carry a distance (enforced in `__post_init__`) |
| `config.py` | `SensorConfig`, `ElectricalConfig` and the **electrical gate** `check_electrical()` |
| `drivers.py` | `RangeDriver` base, `SimulatedDriver`, `GpiodDriver` (Pi 5, libgpiod v2, kernel edge timestamps), `make_driver()` |
| `obstacle.py` | Rolling-window filter + `ObstacleAssessor` → CLEAR / CAUTION / BLOCKED / UNKNOWN, hysteresis, geometry |
| `service.py` | `RangeService` (sampler thread → snapshot file + HTTP + JSONL evidence) and `RangeClient` (consumer) |
| `cli.py` | `python3 -m ranging check-config | read | serve | watch | calibrate` |
| `WIRING.md` | **Hardware connection guide and checklist** (hardware teammate) |
| `INTEGRATION.md` | **Navigation / dashboard / Qwen contract** |
| `examples/range_panel.html` | Dashboard panel example |
| `configs/` | `simulated.json`, `pi5_gpio5.UNVERIFIED.json` (template, refused until verified) |

## Quick start (no hardware)

```
python3 -m ranging read --count 20 --sim-scenario approach    # wall approaching at 0.25 m/s
python3 -m ranging serve --sim-scenario approach              # HTTP :8765/range + /dev/shm snapshot
python3 -m ranging watch --url http://127.0.0.1:8765/range    # what navigation sees
python3 -m pytest -q ranging/tests
```

Simulator scenarios: `static` (`--sim-distance`), `approach`, `open` (nothing
in range), `disconnected`. Also `--sim-noise` (SD in m) and `--sim-dropout`.

## Hardware gate

GPIO is touched only when **all** of these hold:
1. The config selects `"driver": "gpiod"`.
2. `--hardware` is passed on the command line.
3. `check_electrical()` passes: VCC 3.3 V on a V2.0 board, or 5 V with a level
   shifter recorded. VCC header pin consistent with the stated voltage. GPIO is
   not reserved. `wiring_verified_by` and `wiring_verified_at` are set. The
   check runs again inside `GpiodDriver.__init__`.

The shipped `pi5_gpio5.UNVERIFIED.json` fails item 3 by design. See `WIRING.md`.

## Measurement safety rules

- Missing echo, timeout, out-of-range, below-minimum, stuck line or driver error:
  `valid=false` and `distance_m=null`. These are never turned into a distance.
- The latest reading invalid, or older than 0.5 s, gives **UNKNOWN**, with
  `forward_motion_allowed=false`.
- Decision range = `min(latest valid, rolling median of 5)`. A closer reading
  acts on the next ping. A single long outlier cannot clear an obstacle.
- Relaxing a state (BLOCKED → CAUTION → CLEAR, or out of UNKNOWN) needs range >
  threshold + 5 cm for 3 consecutive readings. Getting stricter is immediate.
- The consumer re-checks freshness (`RangeClient`, the dashboard panel), so a
  crashed service becomes UNKNOWN.
- `range_m` is the nearest echo in a 15° beam. **Not a distance to a person.**

## Calibration (team to do)

The default thresholds are **conservative placeholders**:

| Parameter | Default | Basis |
|---|---|---|
| `max_speed_mps` | 0.30 | placeholder, RoverC-Pro speed not measured |
| `decel_mps2` | 0.5 | placeholder |
| `control_latency_s` | 0.20 | placeholder (nav loop + I²C motor command) |
| `safety_margin_m` | 0.10 | |
| → stopping distance | 0.18 m | `v·(latency + sample interval) + v²/2a` |
| → BLOCKED at | ≤ 0.28 m (+ sensor setback) | |
| → CAUTION at | ≤ 0.68 m | BLOCKED + 0.40 m |
| `mount_height_m` | 0.08 | **measure on the robot** |

**Geometry warning:** with the sensor 8 cm above the floor and a 15° cone, the
lower beam edge reaches the floor at **0.61 m**. That is inside the CAUTION band,
so floor echoes may show as obstacles. If they do, mount the sensor higher
(10 cm puts the floor intercept at 0.76 m, 15 cm at 1.14 m) or tilt it up a few
degrees, then record `mount_height_m` / `mount_pitch_deg`. `geometry` in every
snapshot reports the floor intercept and the blind spots.

Measure the real stopping distance: drive at the configured speed, command a
stop, and tape the distance travelled. Update the config.

## Test results

`python3 -m pytest -q ranging/tests` → **71 passed** (macOS, Python 3.13, 2026-11-07).
On the Pi (Debian 13.7, Python 3.13.5) these pass too: the simulator CLI, and
the gate refusing the unverified config with exit 2. The real libgpiod 2.2.0 API
names used by the driver were checked by import only. Pytest isn't installed on
the Pi and no GPIO line was requested.

Coverage: known distances at 0.1 / 0.3 / 0.5 / 1.0 / 1.5 / 2.5 m; Seeed formula
agreement; no echo; out of range and below minimum; disconnected sensor
(simulator and fake libgpiod); stale readings and sampling gaps; rapid approach
(BLOCKED on the next ping); Gaussian noise at the threshold with no oscillation;
spikes; a false clearance from a single long spike or from NO_ECHO; 13 invalid
electrical configs; the CLI `--hardware` gate; the fake-gpiod driver (valid
ping, line driven only for the trigger, stuck-high never driven, error → reopen);
the service snapshot contract; HTTP endpoints; safe client defaults (missing,
corrupt or foreign-schema file, unreachable URL); a dead service becoming stale;
an inconsistent snapshot unable to grant motion.

**Not yet done: the real sensor.** Wiring is unverified (`WIRING.md` §4–6). The
tape-measure accuracy demo is pending the hardware teammate's sign-off.

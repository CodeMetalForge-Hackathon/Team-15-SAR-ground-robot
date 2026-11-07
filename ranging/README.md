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
| `rover_io.py` | Adapter to `rover.sensors.RangeReading` (navigation worker) + forward verdict |
| `cli.py` | `python3 -m ranging check-config | read | serve | watch | calibrate | floor-check | diagnose` |
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
3. `check_electrical()` passes. Every item of WIRING.md §5 must be recorded:
   - a V2.x revision, with a photo reference
   - wiring done with the power off
   - continuity checked
   - measured VCC 3.20–3.45 V, and SIG idle ≤ 3.4 V
   - the mount measured
   - a VCC header pin that matches the stated voltage
   - a non-reserved GPIO
   - a named verifier and time

   5 V is allowed only with a level shifter. The check runs again inside
   `GpiodDriver.__init__`. When the driver opens the line, it also checks
   read-only that the chip is `pinctrl-rp1`, the line is named `GPIO5`, and the
   line is unused.

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

## Diagnostics for invalid readings (motion is always STOP)

`health.diagnosis.code` names a likely cause only when the evidence supports it:
`ECHO_NOT_ENDING` (timeout), `TARGET_BEYOND_RANGE` (the echo was measured, so
the sensor is alive), `TARGET_TOO_CLOSE`, `RELEASE_TOO_SLOW`, `LINE_FAULT`,
`DRIVER_FAULT`, `NO_RESPONSE_EVER` (SIG never went high: consistent with
disconnected, unpowered or wrong pin) and `NO_RESPONSE_AFTER_ECHOES` (the sensor
answered earlier: consistent with open space, an absorbing target, or a
connection lost since then). Software can't tell "disconnected" from "nothing in
range" for certain until `floor-check` records what the physical board does with
no target. `diagnosis.evidence` says what each verdict is based on.

## Test results

`python3 -m pytest -q ranging/tests` → **109 passed** (macOS, Python 3.13, 2026-11-07).
On the Pi (Debian 13.7, Python 3.13.5), these were checked:
- The simulator CLI works.
- The gate refuses the unverified config (exit 2).
- libgpiod 2.2.0 has the API names the driver uses, checked by import only.
- A read-only line-info query returns `pinctrl-rp1` / `GPIO5` / unused.

No GPIO line has been requested.

Coverage:
- **Distances and echoes:** known distances at 0.1 / 0.3 / 0.5 / 1.0 / 1.5 /
  2.5 m; agreement with the Seeed formula; no echo; out of range and below
  minimum.
- **Fault conditions:** disconnected sensor (simulator and fake libgpiod);
  stale readings and sampling gaps.
- **Filtering:** rapid approach (BLOCKED on the next ping); Gaussian noise at
  the threshold with no oscillation; spikes; no false clearance from a single
  long spike or from NO_ECHO.
- **Electrical gate:** 25 invalid electrical configs, including V1.0, a missing
  photo, hot-plug not ruled out, and out-of-range meter readings; the CLI
  `--hardware` gate.
- **Fake-gpiod driver:** valid ping; line driven only for the trigger; SIG
  timing evidence recorded; stuck-high line never driven; wrong chip, wrong
  line name or busy line refused; error → reopen.
- **Diagnosis:** 8 conditions, each one still STOP.
- **Rover adapter:** BLOCKED reported honestly but motion not allowed; UNKNOWN,
  stale, no-echo, other-host and unreachable all give no motion.
- **Tools:** `floor-check` verdicts and the no-target signature; calibration
  fit and margin.
- **Service and client:** snapshot contract; HTTP endpoints; safe client
  defaults; a dead service becoming stale; an inconsistent snapshot unable to
  grant motion.

## Hardware blockers (GPIO stays locked)

1. The PCB revision has not been confirmed as V2.0. A photo is needed.
2. The WIRING.md §5 checklist has not been done: wiring with the power off,
   continuity, VCC and SIG meter readings, mount measurements.
3. The Hailo stacking header pass-through has not been confirmed physically.
4. Not measured on hardware: `release_us`, `echo_start_us`, floor echoes at the
   installed height, the no-target signature, and accuracy at
   0.3 / 0.5 / 1.0 / 1.5 / 2.0 m.
5. RoverC-Pro speed, deceleration and control latency are not measured, so the
   stopping distance is still a placeholder.
6. The navigation side has not yet agreed to AND in `forward_motion_allowed`
   and to keep `NoEchoPolicy.UNKNOWN` for hardware (INTEGRATION.md).

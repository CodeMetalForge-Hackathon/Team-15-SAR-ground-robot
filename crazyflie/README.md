# Bluetooth-guided drone + rover demo

Run from the repository root with Python 3.10+; simulation needs no dependencies:

```sh
python3 crazyflie/demo_mission.py --dry-run
python3 crazyflie/demo_mission.py --dry-run --scenario safe
python3 crazyflie/demo_mission.py --dry-run --target-inches -24 -8
python3 crazyflie/demo_mission.py --dry-run --search-rounds 2 --sample-seconds 3
```

Scenarios: `injured`, `safe`, `hidden` (person seen after a 360° scan), `phone-only`,
`empty`. The visual scenario is independent of the beacon signal. `empty` means no
person/phone was visually observed; it does not turn off the simulated beacon.
Add `--log /tmp/new-demo.jsonl` for a new JSONL log file; existing files are refused.

## How the search works

1. Take off and sample at the origin and four nearby cardinal points.
2. At each point, collect a five-second window and compute median RSSI.
3. Revisit the starting point and the strongest point. Accept that direction only
   if both comparisons improve by at least 3 dB (`--improvement-db`). This threshold
   is a tunable demo heuristic, not a statistically established confidence level.
4. Optionally repeat with half the step size (`--search-rounds 2`).
5. Return and land. Send the strongest confirmed sample point to the rover as a
   candidate area, translated into the rover frame. The rover remains manual.

If readings are insufficient, the receiver disconnects, position cannot be held,
or no improvement repeats, the script returns/lands and does not dispatch the
rover. It does not infer distance, phone model, human presence or an exact beacon
position. A previously confirmed candidate can be retained if a later search
round has no clear improvement.

Default step is 0.6 m. Search points stay within ±1.2 m XY; flight commands remain
within the guide's ±1.5 m envelope. Default minimum is eight fresh samples per
window. The script polls `/api/discovery` at no more than four times per second,
so a five-second window yields up to about 20 samples, **not every packet received
by the scanner**. Repeated snapshots with unchanged packet counts are discarded,
as are readings older than 0.5 seconds. Movement readings are excluded from each
window. This sampling filters noise but does not eliminate orientation/multipath
errors. Test step size and the signal margin in your actual demo space.

Two five-second rounds cannot fit the reserved flight budget, so use three-second
windows for two rounds. Network delays can still cause an early safety return.

## Dry-run

Simulation is the default and opens no hardware or network connections. Virtual
time advances immediately. A deterministic noisy path-loss fixture generates RSSI
from the current simulated pose. `--target-inches` sets that fixture's hidden
beacon location in the rover frame (default 20,5 inches); the search algorithm
does not receive the hidden location. Changing it changes the selected direction.
There is no prescribed four-minute wall-clock presentation duration.

## Live drone with the existing scanner dashboard

The ESP32 receiver must travel with the drone, with power and a telemetry path to
the host. **A stationary receiver next to the Jetson cannot guide drone movement.**
The current dashboard expects USB serial, so this mode requires a workable physical
or forwarded serial arrangement. This change does not add a wireless scanner link.

Start the existing discovery server on the host connected to that receiver:

```sh
python3 -m discovery.server --serial /dev/cu.usbmodem2101
```

Inspect `http://127.0.0.1:8765/api/discovery` and identify your demo beacon's exact
`id` in `signals`. Use a controlled beacon on/off test to select the right one;
RSSI strength or an Apple classification alone does not establish phone identity.
This ID is a temporary, unverified session identifier. It can change on server
restart or entry expiry; a missing ID will not switch to another nearby device.

The team's `sar_sim.backends.crazyflie_backend.CrazyflieLink` is still required and
is absent from this checkout. Obtain it, put its project root on `PYTHONPATH`, and
install its dependencies. Then:

```sh
python3 crazyflie/demo_mission.py --live-drone --height-m 0.5 \
  --signal-id REPLACE_WITH_EXACT_ID --scanner-on-drone \
  --discovery-url http://127.0.0.1:8765 \
  --uri radio://0/80/2M/E7E7E7E7E7
```

Use `--discovery-url http://HOST:PORT` if the dashboard has been explicitly exposed
at a different address. The stock server binds to loopback. No discovery server,
serial ownership, authentication or replay-state logic was changed. The proximity
readings are **unverified advertisements**, independent of the authenticated
beacon panel; packets are not promoted into fresh authenticated sightings.

The script first requires a fresh reading for the selected ID, then commands the
drone. Jetson boot, rover motors, camera/CV, visual condition and phone check-in
remain operator steps. No phone messages are sent. Scenario fixtures are never used
for live visual observations. `--target-inches` is simulation-only, not a live target.

## Coordinates and flight limits

The rover starts at (0,0), sharing the drone's boot heading. +x is forward and +y
left. Default drone placement is 8 inches right of the rover; set the measured
`--drone-right-inches`. Drone points are meters from its boot position; the logged
`rover_move.target_xy_inches` is the candidate in the rover frame. The drone lands
at its own original takeoff point, not on a moving rover.

Simulation retains the screenshot's five-inch altitude (0.127 m). Live mode requires
`--height-m` between 0.2 and 1.2 m. Follow the provided Crazyflie guide's positioning
deck, radio setup, clear flight area and first-flight procedure with Gavin present.
Run the outline's WASD checks with the existing vehicle control tools first.

The external backend must expose `vbat`, `pose()`, `takeoff()`, `go_to()`, `wait()`
and a context manager that lands/disconnects on exceptions. Position telemetry
must be available in that coordinate frame. During sampling, positions must be
finite and within 0.20 m of the requested sample point. This is a coarse hold check,
not collision avoidance or calibrated positioning accuracy.

Voltage is checked throughout waits; missing/invalid voltage or below 3.3 V requests
landing. Search returns by the 120-second budget; at 140 seconds the program requests
landing in place, reserving ten seconds toward the outline's 150-second limit.
Ctrl+C exits the flight context immediately. Physical landing timing and radio-loss
handling depend on the backend; these host-side timers cannot control a stalled
backend. **Live flight and physical RSSI performance have not been tested.**

## Verification

```sh
python3 -m unittest discover -s tests -p test_demo_mission.py -v
python3 -m unittest discover -s tests -p test_rssi_search.py -v
```

Tests cover signal-dependent route selection, repeated comparisons, inconclusive
signals, lost/sparse feeds, HTTP freshness/deduplication, coordinate handoff, battery
and timer limits, and exception landing. Rover/CV/phone integrations remain future
hardware work.

## Manual WASD drone control

Open an interactive terminal from the repository root:

```sh
python3 crazyflie/keyboard_control.py --dry-run
```

Simulation runs at real keyboard speed. For the actual drone, after verifying the
team backend and following the same preflight procedure:

```sh
python3 crazyflie/keyboard_control.py --live-drone --height-m 0.5
```

| Key | Action |
| --- | --- |
| T | Take off (once per session) |
| W / S | Forward / backward along boot-frame x |
| A / D | Left / right along boot-frame y |
| R / F | Raise / lower altitude |
| H | Return above takeoff x/y at current altitude |
| + / - | Increase / decrease movement speed by 0.05 m/s |
| Space, L, Q, Ctrl+C | Request landing and exit |

One accepted movement key sends a 10 cm position step; change it with `--step-m`
(0.025–0.2 m). The terminal must have focus. This is step control, not a joystick:
while a move is running, other movement keys are discarded; OS key repeat can
issue another step after completion. Landing keys remain active during moves
and takeoff. With no movement input the drone holds its last commanded position.

Movement speed starts at 0.2 m/s. Press `+` (or `=` without Shift) to increase it,
or `-` to decrease it, in 0.05 m/s increments within 0.05–0.30 m/s. The terminal
prints the selected speed. Set the initial value with `--speed-m-s 0.15`.
Speed changes affect the next movement, including H/home, and can be entered
while a move is running; they do not interrupt the current waypoint or alter its
step distance. Takeoff and landing timing are unchanged. Commands have a minimum
0.2-second duration, so short steps may have a lower average speed. This setting
controls waypoint duration, not a measured instantaneous velocity.
Targets are clamped to ±1.5 m XY and altitude 0.2–1.2 m. Battery checks and the
120-second airborne limit remain active without keyboard input. On a safety event,
the program requests landing in place rather than returning horizontally. Landing
still depends on the backend's exception-safe context manager. Backend calls that
stall can delay key handling. The terminal settings are restored on exit.

Manual mode is a separate flight session; it does not switch into autonomous
search or operate the rover. It needs no BLE scanner. For standalone RoverC Pro WASD over USB with the CPlus SE, see
[`../rover/README.md`](../rover/README.md). Rover driving is not integrated into
the autonomous mission. Keyboard control has
been tested in simulation only.

```sh
python3 -m unittest discover -s tests -p test_keyboard_control.py -v
```

# Team-15 hardware link: drones → ESP32-S3 → Jetson

```
 drone 1: ESP32 + sensors ─┐
 drone 2: ESP32 + sensors ─┼─ ESP-NOW (2.4 GHz, channel 1) ─►  ESP32-S3 gateway ─ USB ─►  Jetson: homebase.py
 drone 3: ESP32 + sensors ─┘  ◄── waypoints (broadcast) ─────                    ◄────    (plans for every drone)
                                                                                           ▲
                                                               CV on the Jetson ─ UDP JSON ┘
```

The Jetson does all the thinking. It keeps one shared map of where people
might be, plans every drone with MCTS, and sends each one its next waypoint.
Drones report where they are, what they sense, and who they found.

## What runs where

| Device | Code | Job |
|---|---|---|
| Jetson (homebase) | `homebase.py` | shared belief map, 3-drone MCTS, A* return-to-base, contacts, casualty list |
| ESP32-S3 on the Jetson | `firmware/gateway/gateway.ino` | dumb pipe: ESP-NOW ⇄ USB serial |
| ESP32 on each drone | `firmware/drone_node/drone_node.ino` | telemetry, detections, waypoints, link-loss failsafe |
| Your laptop | `homebase.py --sim`, `fleet_sim.py --pty` | the same homebase code against simulated drones |

The bytes on the radio are defined once, in `link/protocol.py` and
`firmware/t15_protocol.h`. `python tests/test_link.py` proves both sides
produce identical bytes.

## Coordinates

Everything is in metres in one local frame. The homebase is (0, 0). Put the
AprilTag / UWB anchor on the homebase (mothership). x = east, y = north, z = up.
No GPS anywhere.

## 1. Jetson

```bash
pip3 install numpy pyserial matplotlib
sudo usermod -aG dialout $USER        # once, then log out and back in
python3 homebase.py --port /dev/ttyACM0
```

Field mission defaults: 24×24 cells of 20 m, 3 drones, 30 m altitude.
For a room with Tiny Whoops / Crazyflies:

```bash
python3 homebase.py --port /dev/ttyACM0 --n 12 --cell-m 0.5 --speed 1 --endurance 240
```

If MCTS is slow on the Jetson, add `--sims 80`.
Results: `results/casualties.json` (highest priority first) and `results/mission_log.jsonl`.

## 2. Gateway (ESP32-S3 on the Jetson)

Arduino IDE → Boards Manager → install **esp32 by Espressif** (compiled against 3.3).
Board: **ESP32S3 Dev Module**. Open `firmware/gateway/gateway.ino`, upload.

- Plugged into the native **USB** port: set *USB CDC On Boot: Enabled*. The Jetson sees `/dev/ttyACM0`.
- Plugged into the **UART/COM** port: leave it Disabled. The Jetson sees `/dev/ttyUSB0` (or `ttyACM0`).
- Do not add `Serial.print` to the gateway. That serial line carries binary frames.

## 3. Drone node (ESP32 on each drone)

Open `firmware/drone_node/drone_node.ino`. Edit the settings block:

```cpp
#define DRONE_ID      1        // 2 and 3 on the other drones
#define SENSING_MASK  (T15_SENS_THERMAL | T15_SENS_MMWAVE)   // what this drone carries
#define USE_MR60BHA2  0        // 1 if the Seeed 60 GHz radar is attached
#define BENCH_MODE    1        // 1 until a real pose source is wired in
```

Compiles cleanly for ESP32, ESP32-S3, XIAO ESP32-S3 and XIAO ESP32-C6 (the
board that comes with the MR60BHA2 radar kit).

## 4. Bench test (no drones needed)

1. Flash the gateway and 1–3 drone nodes (different `DRONE_ID`s).
2. `python3 homebase.py --port /dev/ttyACM0`
3. Open a drone's Serial Monitor at 115200. You should see `[wp 1] GOTO x=... y=...` lines.
   In bench mode the node walks toward each waypoint at 1 m/s and reports that as its pose.
4. Type `d` in the Serial Monitor: a fake thermal hit. The homebase prints `contact_new`.
5. Type `v`: fake radar vitals (hr 82, br 16). The homebase prints `vitals`.
6. Unplug the gateway for 10 s: the node prints `[link] lost: holding position`. Plug it back: `homebase back`.

That proves the whole radio chain before anything flies.

## Dress rehearsal without any hardware

```bash
python3 fleet_sim.py --pty            # prints a port like /dev/pts/5 (Mac: /dev/ttys004)
python3 homebase.py --port /dev/pts/5 # second terminal
```

`fleet_sim.py` pretends to be the gateway plus three drones on a virtual
serial port. The homebase cannot tell the difference.

## Hooks for each teammate

**Gavin (drone + hardware)**, in `drone_node.ino`:
- `get_pose()`: where the drone is, in metres from the homebase, plus its uncertainty `sigma`.
  Options: Crazyflie Flow deck, UWB ranging to the homebase, or let a camera at the homebase
  track the drones and send pose JSON (below).
- `apply_waypoint()`: hand the waypoint to the flight controller (MSP / CRSF / cflib).
- `battery_pct()`, `flight_state()`: report the real values. Until then the homebase
  uses time in the air.

**Mabelle (sensors / ID)**: when your sensor hears someone, call

```cpp
t15_report(T15_SENS_ID_BLE, 0.98, T15_ST_UNKNOWN, hr, 0, range_m, tag_id, 0, 0);
```

`tag_id` is the unique ID you design (0 = none). Heart rate from a watch goes in `hr`.
Ally IDs go in a text file, one per line, used with `--allies allies.txt`.
In `--military` mode an unknown tag raises an `unknown_tag_warning`.

**Mohammed (CV)**: if CV runs on the Jetson, send JSON to UDP `127.0.0.1:5515`:

```python
import json, socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(json.dumps({"type": "det", "drone": 2, "sensor": "cv", "conf": 0.8,
                     "status": "injured"}).encode(), ("127.0.0.1", 5515))
# x, y (metres) are optional: without them the drone's position is used.
# Tracking drones from a homebase camera:
s.sendto(json.dumps({"type": "pose", "drone": 2, "x": 3.1, "y": 1.2, "z": 1.0,
                     "sigma": 0.2}).encode(), ("127.0.0.1", 5515))
```

## Messages (all little-endian, ≤ 51 bytes, fits ESP-NOW's 250)

| Type | Direction | Fields |
|---|---|---|
| TELEMETRY | drone → home | x, y, z, yaw, sigma, battery %, state, sensors-on mask, waypoint ack |
| DETECTION | drone → home | x, y, sensor, confidence, status, heart rate, breath rate, range, det_id, tag_id |
| WAYPOINT | home → drone | x, y, z, yaw, cmd (goto/hold/rtb/land), telemetry period, detection ack, wp_seq |

Every packet carries a CRC. With `--key` it also carries an 8-byte HMAC-SHA256
tag and a sequence number, so forged and replayed packets are rejected.

## What the homebase does

1. **Search.** Shared belief map with MCTS. Drones plan one after another, and each one
   treats its teammates' next cells as already covered. So they fan out instead of
   chasing the same hotspot.
2. **GPS-denied looks.** A "looked here, saw nothing" update is spread over where the
   drone might really be (its reported `sigma`). Drift doesn't fool the map.
3. **Vitals.** A new contact pulls the nearest drone with mmWave down to hover over it.
   Heart and breath rate give a status. The status thresholds are **placeholders**, not medical advice.
4. **Battery.** A* distance home vs. time left. The drone comes back before it has to,
   lands, and the mothership recharges it.
5. **Jamming.** Detections are stored on the drone until the homebase acks them.
   A drone that hears nothing for 8 s holds; after 20 s it flies home on its own.
6. **Military.** `--military --key secret` → signed packets only, 4× fewer emissions
   (EMCON telemetry), exposure cost in MCTS. Optional lower TX power in firmware.

## Honest limits

- Not yet run on real radios. The protocol is verified byte-for-byte in C and Python.
  The firmware compiles for four boards. Range and loss on ESP-NOW still need a field test.
- Sensor models in the simulator are simple (detect probability per look, footprint in cells).
- Two people within about one cell with similar vitals show up as one contact.
  Different ID tags or clearly different vitals keep them apart.
- Tiny Whoops have no position estimate of their own. Someone has to provide `get_pose()`.
- Radar needs the drone within about 1 m of the person. The sim assumes the camera centres
  the drone over the contact while it hovers. On hardware that's the CV final-approach loop.
- The MR60BHA2 code follows Seeed's documented API. Check it against their example sketch.

## Results so far (simulation, 20 missions each, field map, 3 hidden people)

Time until every person was detected at least once (mean ± 95% CI):

| Setup | Time to find all 3 |
|---|---|
| 1 drone | 216 ± 80 s |
| 3 drones, no shared map | 147 ± 51 s |
| 3 drones, shared map | 101 ± 20 s |
| 3 drones, shared map + claims | **93 ± 16 s** |

All 20 missions found everyone in every setup. The shared map (the radio link)
gives most of the gain. Claims add a little and make the timing more consistent.
Raw rows: `results/fleet_eval_fleet.csv`. Re-run with `python3 fleet_eval.py --study fleet`.

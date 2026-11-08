# Fly to the phone (minimum drone demo)

`crazyflie/fly_to_phone.py` takes off to 5 in, flies 5 ft straight ahead, hovers
over the phone, flies back and lands. It reports to mission control as the
`crazyflie` node and writes a JSON report.

**The drone carries nothing.** The phone's identity and RSSI come from the
stationary ESP32 scanner (discovery.server) next to the Jetson. The drone flies
to where the phone is. It does not steer by signal strength. Present it that
way: "the Jetson detects and authenticates the phone, then dispatches the drone."

## Before flying

- Flow deck v2 on the drone. The script refuses to fly without a position estimate.
- A textured, well-lit floor. Shiny or plain floors make the Flow deck drift, and
  that is the usual cause of "it flies badly".
- A fresh battery: takeoff is refused below 3.6 V.
- Point the drone straight at the phone. "Forward" is the way the drone faces at boot.
- Put the phone 5 ft in front, with 2 ft of clear space around the path.

## Run it (from the repo root)

```sh
# 0. Rehearse without hardware (real time, so the operator view can watch)
python3 crazyflie/fly_to_phone.py --coordinator http://127.0.0.1:8080

# 1. Ground scanner, as usual
python3 -m discovery.server --serial /dev/cu.usbmodemXXXX --test-keys --state STATE --scope TESTKEY-...

# 2. Bridge (optional). It MUST use --fence 2.0: 5 ft is 1.52 m and the default fence (1.5 m) refuses it.
python3 -m sar_sim.cf_bridge --uri radio://0/80/2M/E7E7E7E7E7 --fence 2.0

# 3. Fly. Stop `mission_control.agent --node crazyflie` first; only one program can be the crazyflie node.
python3 crazyflie/fly_to_phone.py --live-drone --preflight-confirmed \
    --discovery-url http://127.0.0.1:8765 --alias 1 --wait-for-phone 30 \
    --coordinator http://127.0.0.1:8080
```

`--alias N` waits for an authenticated, enrolled beacon. `--signal-id ID` uses an
unverified advertisement instead, and the report labels it UNVERIFIED. With
`--wait-for-phone 0` the drone takes off immediately.

## What the operator view gets

`GET /api/state` -> `nodes.crazyflie.telemetry`:

| Field | Meaning |
| --- | --- |
| `position_m`, `battery_v`, `airborne` | live, already drawn on the Crazyflie card |
| `mission.phase` | connecting, waiting_for_phone, takeoff, outbound, at_phone, returning, landing, on_ground, aborted, no_phone |
| `mission.summary` | one line, e.g. "Phone found: Enrolled beacon 001 (verified, TEST KEYS), -61 dBm over 12 packets, ground scanner" |
| `mission.finding` | label, alias or id, verified, mode_label, rssi_dbm_median, samples |
| `mission.outcome` | completed, aborted, no_phone, error |

The result stays live for 30 s after landing (`--linger-s`).

## Safety (all of these land the drone where it is)

Operator STOP or pause in mission control; mission control unreachable for 2 s;
battery under 3.3 V; position estimate lost; drifting out of the corridor
(0.45 m around the path); missing the takeoff or phone waypoint by more than
0.25 / 0.30 m; 45 s flight limit; Ctrl+C; the bridge refusing a command.

5 in is inside ground effect. If the hover bounces, use `--height-in 12`.

## Tests

```sh
python3 -m unittest discover -s tests -p test_fly_to_phone.py -v
```

They have been run in simulation, and through CrazyflieLink, the bridge and the
repo's simulated Crazyflie. They have not been run on the real drone.

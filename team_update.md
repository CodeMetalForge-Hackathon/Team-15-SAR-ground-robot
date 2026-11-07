# Hardware + Simulation Update (Gavin)

## Hardware status

- **Raspberry Pi 5 + Hailo-8 AI chip: working.** The Hailo install didn't build the driver for the Pi's kernel because a build tool (`dkms`) was missing. Fix if anyone hits it:
  ```bash
  sudo apt install dkms
  sudo apt install --reinstall hailort-pcie-driver
  ```
- **Base station:** a Jetson Orin Nano, stationary for the proof of concept. Its location is the map origin (0,0). For the pitch: it would later mount on a large gas-powered drone or UAV.
- **Pi's role:** handles sensors and video. It runs person detection on camera/drone video with the Hailo chip and sends small JSON detections to the Jetson. The Jetson handles the map, combining data, planning and the dashboard.
- **ESP32 boards:** 2× XIAO ESP32-C5 (scan 2.4 + 5 GHz Wi-Fi and Bluetooth) and 1× XIAO ESP32-S3 Plus.
  - C5 #1 rides on the scout drone as a phone scanner.
  - C5 #2 is a wearable "victim" beacon broadcasting an ID plus heart rate.
  - The S3 plugs into the Jetson by USB and collects data from the others over ESP-NOW (a direct board-to-board radio link with no router needed, so the venue Wi-Fi's device blocking doesn't matter).
- **Drones:** we have one Emax Tinyhawk Lite. It can't hold position on its own, so it'll be a **manually flown camera scout** whose video feeds the CV pipeline. Crazyflie or Tello are the autonomous options if we can get them, and the code is ready for either.
- **Still need:** a Pi camera (with a Pi 5 cable) or USB webcam, and a 5.8 GHz FPV receiver with USB output for the Tinyhawk video.

## Multi-drone simulation (`sar_sim`)

Since we only have one drone, I built a simulation of the full swarm. It's written in Python (numpy + matplotlib) and has an optional 3D physics mode using Crazyflie models.

### What it does

- 3 drones (configurable) search a **2 km × 2 km area on a 20 m grid** with **no GPS**, matching Aurora's mapping plan.
- **Position tracking:** each drone estimates its position by dead reckoning, so its error grows as it flies. It drops ESP32 anchor nodes, and the error resets near those anchors or the mothership.
- **Sensors:**
  - thermal camera, including false alarms
  - Bluetooth phone scanning, with distance estimated from signal strength
  - camera confirmation at close range, reporting injured/OK plus heart rate if the victim has a wearable
- **Shared probability map:** every cell holds the probability that a victim is there, updated from all sensors. Bluetooth signals guide the search, while thermal and camera hits trigger confirmation. Signals from victims already found get filtered out.
- **Planner:** drones split the area, fly toward high-probability unsearched ground, send the nearest drone low to confirm a candidate, and return to the mothership to recharge when the battery runs low.
- Every detection uses our **data contract format**: `{source_id, t, type, x, y, err, ...}`.

### Results compared to a simple back-and-forth sweep

| | Our planner | Simple sweep |
|---|---|---|
| All 3 victims found (10 runs) | 90% of runs | 80% |
| Typical first find | 258 s | 527 s |
| With a last-known location: all found (8 runs) | 100% of runs | 62% |
| With a last-known location: typical first find | 54 s | 252 s |

### How to run it

```bash
py -m pip install numpy matplotlib
py run_sim.py                          # live map
py run_sim.py --compare --runs 10      # our planner vs sweep
py run_sim.py --log detections.jsonl   # dump detection packets
```

Live view keys: **space** pause · **+/-** speed · **t** show/hide true victim positions · **c** probability/coverage layer · **q** quit

## Where each person plugs in

| Person | Files | What to do |
|---|---|---|
| **Aurora** (mapping) | `belief.py`, `planner.py` | `belief.py` holds the layered grid. Replace `_pick_search_target` with your MCTS/A*. |
| **Mabelle** (sensors) | `sensors.py` | Thermal and Bluetooth models plus the packet format. Test the beacon ID/encryption idea here. |
| **Mohammed** (CV) | `sensors.py` (`rgb` packets) | Where real Hailo/Jetson detections plug in. |
| **Everyone** | `drone.py` | All code talks to a common `Drone` interface (`takeoff`, `goto`, `land`, `get_pose`, `get_detections`). A real Crazyflie or the Tinyhawk can replace a simulated drone without changing the planning or mapping code. |

## Pitch angle

The system works with any drone. Today we demo one piloted scout plus a simulated swarm, and the same code is ready to fly real autonomous drones launched from a mothership.

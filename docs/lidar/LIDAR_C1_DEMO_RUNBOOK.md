# LiDAR demo runbook

## 1. SIMULATED demo (Mac; no hardware; safe any time)

```bash
python3 -m lidar replay --scenario 08_obstacle_approaching --serve      # http://127.0.0.1:8775/
# pick scenarios in the drop-down; every view is badged SIMULATED
python3 -m dashboard.serve --range-fixture lidar/fixtures/dashboard_range_series_approach.json
# existing Forward obstacle range card, fed from the LiDAR FRONT sector (shows UNKNOWN…BLOCKED, SIMULATED)
```

Talking points:
* 360° coverage versus Grove's 15° cone;
* "no return" reads UNKNOWN (scenario 01, glass in 17);
* a misconfigured orientation is dangerous, which is why there is no default offset (15);
* stale and disconnected data are greyed out (12, 13, 14).

**Never** say a LiDAR distance is the person's distance.

## 2. Pre-scan (hardware teammate): LIDAR_C1_HARDWARE_CHECKLIST.md, items 1–10

## 3. FIRST STATIONARY PHYSICAL SCAN: needs explicit user approval (not done)

**The full, authoritative procedure is LIDAR_C1_STATIONARY_SCAN_PROCEDURE.md** (authorization record, setup, preflight, measurements, abort criteria). The summary below is for orientation only.

1. The rover motor bridge is unpowered or e-stopped, the wheels are off the floor, and the emergency power cutoff is in reach.
2. On the Pi: `pip install pyserial==3.5`. Copy `c1_pi5.UNVERIFIED.json` to `c1_pi5.json` and fill it from the checklist.
3. `python3 -m lidar check-config --config c1_pi5.json --hardware` must print `ok: true`.
4. `python3 -m lidar scan-once --config c1_pi5.json --approved-by "<approver>" --scans 20`. Record GET_INFO, health, the points per revolution, the scan rate and `capture_start_to_processed_s`.
5. Afterwards, `vcgencmd get_throttled` must read 0x0. If not, stop and record it.

## 4. Alignment (Stage C)

Put a 30 cm box 1.00 m away on the robot's measured forward axis. Read `closest.sensor_bearing_deg` (θ). Then `forward_offset_deg = θ` for a clockwise sensor, because robot = −θ + offset = 0. Repeat at ±90°. Record `alignment_verified_by/_at/_method`. Then check the 8 sectors with the box at each of 0/45/…/315.

## 5. Abort

Pull the cutoff. Software: Ctrl-C. The driver's `__exit__` sends STOP and closes the port.

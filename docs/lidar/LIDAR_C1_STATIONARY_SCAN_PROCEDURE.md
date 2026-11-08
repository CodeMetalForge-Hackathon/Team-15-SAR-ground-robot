# First stationary LiDAR scan: procedure (PREPARED ONLY, NOT EXECUTED)

**Do not power or rotate the LiDAR** until all of the following are true:
1. the hardware teammate has completed LIDAR_C1_HARDWARE_CHECKLIST.md items 1–10;
2. a **different** person has independently verified items 1–3 and 7;
3. the user has **explicitly authorized this specific test** (record below).

No rover motion and no gripper are involved at any point. The rover's motor bridge is not powered.

## 0. Authorization record (fill in before step 1)

| Field | Value |
|---|---|
| Checklist completed by / at | |
| Independent verifier / at | |
| User authorization (quote, date/time) | |
| Test scope authorized | "stationary scan, N = 20 revolutions, bench location ___" |
| Operator at the bench | |
| Person at the power cutoff | |

Anything outside the authorized scope (more scans, a different location, wheels on the floor, rover powered) needs a new authorization.

## 1. Setup (power OFF)

1. The robot is on a bench. **Wheels are off the floor**, the RoverC-Pro battery is disconnected or its switch is OFF, and the StickC bridge is unplugged.
2. The LiDAR is mounted level and the cable strain relief is checked (items 5 and 6).
3. The emergency power cutoff (item 9) is within reach of a named person. Test it once with the LiDAR unpowered.
4. Nobody's eyes are at scan-plane height. Clear 1 m around the sensor except the planned test targets.
5. Targets: a matte box (~30 × 30 cm) and a tape measure on the floor along the robot's forward axis.

## 2. Software preflight (LiDAR still unpowered)

```bash
cd ~/Team-15 && git log -1 --format=%h          # record the commit
vcgencmd get_throttled                           # must be 0x0
pip install pyserial==3.5                        # Pi only
cp lidar/configs/c1_pi5.UNVERIFIED.json ~/lidar_c1_pi5.json   # fill from the checklist; keep outside Git
python3 -m lidar check-config --config ~/lidar_c1_pi5.json --hardware   # must print "ok": true
```

If the gate refuses, stop. Do not edit the gate; fix the checklist entry only with a real measurement.

## 3. Power-up and enumeration

1. Connect the adapter (LiDAR power path as verified in item 3).
2. Watch for the sensor's motor spin-up. If you smell or hear anything abnormal, **cut power**.
3. Run `python3 -m lidar discover`. Confirm that the recorded `/dev/serial/by-id/...` is present and is **not** the StickC.
4. Run `vcgencmd get_throttled`; it must read 0x0.

## 4. The scan (authorized scope only)

```bash
python3 -m lidar scan-once --config ~/lidar_c1_pi5.json --approved-by "<user, as recorded>" --scans 20 \
    | tee ~/lidar_first_scan_$(date -u +%Y%m%dT%H%M%SZ).json
```

The driver sends STOP and closes the port on exit, and on Ctrl-C. Record:

| Measurement | Expected (datasheet / placeholder) | Measured |
|---|---|---|
| GET_INFO model byte, firmware | record → `expected_model_id` | |
| GET_HEALTH | GOOD | |
| Legacy SCAN descriptor answered | yes (otherwise use the SDK fallback, see DRIVER §1) | |
| Points per revolution | ≈ 500 | |
| Scan rate | ≈ 10 Hz | |
| `capture_start_to_processed_s` p50 / max | ≤ 0.15 s | |
| Box at 1.00 m on the forward axis: `closest.range_m` | 1.00 ± 0.03 m | |
| Box at 1.00 m: `closest.sensor_bearing_deg` (θ) | → `forward_offset_deg = θ` for CW | |
| `vcgencmd get_throttled` after the scan | 0x0 | |

## 5. After the scan

* Power off. Save the JSON outside Git and attach it to the Stage C evidence.
* **Do not** set `HARDWARE_VERIFIED`, enable any rover source, or change defaults. Report the results to the user, who decides the next step: calibration at 0.3/0.5/1/2/3 m, sector checks at 0/45/…/315°, footprint/fiducial measurement and latency p99 (rover-owner request R3).

## 6. Abort criteria (power off immediately)

Any of the following: abnormal noise, smell or heat; `get_throttled` ≠ 0x0; an unexpected device path; the Pi becoming unresponsive; the rover or the StickC found powered; anyone entering the scan plane at eye height.

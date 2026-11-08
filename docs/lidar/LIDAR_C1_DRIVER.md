# RPLIDAR C1 driver

## 1. Runtime choice

| Option | License | C1 support | Decision |
|---|---|---|---|
| Slamtec `rplidar_sdk` (C++) | BSD-2-Clause | Official; supports C1 | **Reference** for protocol constants. It is not linked: it would need a C++ build on the Pi and a subprocess/FFI layer, and it cannot run in our Python CI without hardware |
| `rplidar` / `rplidar-roboticia` (PyPI) | MIT | Written for A1/A2. C1 use at 460800 baud is reported by users, not by Slamtec | Not used. It is unmaintained and auto-handles the motor via DTR |
| **Own legacy-protocol codec + pyserial** | ours; pyserial BSD-3-Clause | Uses the documented legacy SCAN; **unverified on our unit** | **Chosen.** Small and auditable, fully mockable in CI, no native build |

pyserial (`pyserial==3.5`) is needed **only on the Pi**. It is not added to `requirements.txt`, so CI and the Mac dashboard are unchanged. Install it on the Pi only after the checklist passes.

**Fallback if legacy SCAN is not answered at Stage C:** build the official SDK's `ultra_simple` (BSD-2), wrap its stdout in a transport, and keep `lidar.processing` unchanged. That will be a reviewed follow-up.

## 2. API

```python
from lidar.config import LidarConfig
from lidar.driver import RplidarC1Driver, LidarDisconnected, LidarTimeout, LidarHealthError

cfg = LidarConfig.load("lidar/configs/c1_pi5.json")      # hardware: check_hardware_gate runs here
with RplidarC1Driver(cfg) as drv:                         # STOP, flush, GET_INFO (model check), GET_HEALTH
    drv.start_scan()                                      # SCAN; waits for the A5 5A descriptor (skips junk)
    scan = drv.read_scan()                                # one revolution: start flag to next start flag
# exit: STOP, flush, close. It also runs on exceptions and is idempotent
```

| Requirement | Where |
|---|---|
| Device discovery (list only) | `lidar.discovery.discover()` / `python -m lidar discover`. Never opens a port, never auto-selects |
| Explicit device selection | `cfg.device` must equal `checklist.device_path_by_id` (a `/dev/serial/by-id/` path) |
| Connect / disconnect | `connect()`, `disconnect()` (idempotent), context manager |
| Scan start / stop | `start_scan()`, `stop_scan()` (STOP, ≥ 1 ms wait, input flush) |
| Timestamped acquisition | `capture_start_mono_ns` = arrival of the revolution's first node (the conservative capture time), plus `capture_end_mono_ns` and wall time |
| Distance / bearing | `distance_q2/4` mm → m; `angle_q6/64` deg (SENSOR frame, clockwise) |
| Invalid / zero samples | 0 → `NO_RETURN`; below min / above max range; `LOW_QUALITY`; `NON_FINITE`; `SELF_OCCLUDED` |
| Quality | 6-bit quality kept per sample; `min_quality` threshold (placeholder 10) |
| Disconnection recovery | `LidarDisconnected`: the port is closed and the state is DISCONNECTED; the caller reconnects with backoff (`cfg.reconnect_backoff_s`) |
| Timeouts | `read_timeout_s`; `scan_timeout_s` (0.6 s) without a complete revolution → `LidarTimeout`, and the partial revolution is discarded |
| Corruption | check bits S/!S and C; resync by alignment search; > 5 % corrupt nodes → PARTIAL |
| Concurrent access | `SerialTransport` opens with `exclusive=True` (flock) |
| Health | GET_HEALTH not GOOD → `HEALTH_ERROR`; scanning refused |

## 3. States

`DISCONNECTED → CONNECTED → SCANNING → CONNECTED` (stop) / `DISCONNECTED` (transport failure) / `HEALTH_ERROR` (bad health or model). The processing layer adds `GATE_LOCKED` and `TIMEOUT` as connection states for display.

## 4. What the driver never does

It does not toggle DTR/RTS to control a motor (the C1's motor is integrated, and the scan command starts it). It sends no express or dense scan commands and no undocumented commands. It touches no GPIO and never talks to the rover.

## 5. Stage C verification items for the driver

1. `GET_INFO` answers; record the model byte and firmware.
2. `GET_HEALTH` = GOOD.
3. Legacy `SCAN` answers with descriptor `A5 5A 05 00 00 40 81`.
4. Measure the points per revolution and the scan rate. The datasheet says ≈ 5 kHz sampling and a typical ≈ 10 Hz scan rate; our `min_points=200` and the 7–13 Hz window are placeholders.
5. Measure the capture-start-to-processed latency (`scan-once` reports `capture_start_to_processed_s`).
6. STOP actually stops the motor.

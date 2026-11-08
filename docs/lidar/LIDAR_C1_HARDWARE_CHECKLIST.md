# RPLIDAR C1 hardware checklist (gate for the FIRST physical scan)

**Status: nothing on this checklist has been done.** The LiDAR has not been powered. Every answer must come from a measurement or an inspection, never from a photo or an assumption. Each field maps 1:1 to `checklist.*` in `lidar/configs/c1_pi5.UNVERIFIED.json`, and `lidar.config.check_hardware_gate` refuses to open the serial port until all of them are recorded.

| # | Item | How to verify | Config field(s) | Pass |
|---|---|---|---|---|
| 1 | Exact model **C1M1-R2** | Read the label on the unit; photograph it (keep the photo outside Git) | `model_label_read`, `model_evidence_ref` | equals `C1M1-R2` |
| 2 | Compatible USB adapter + pinout | Identify the adapter (make/model). **Do not assume the small green board in our photos is compatible.** Compare each connector pin (VCC, GND, TX, RX, and any MOTOCTL/NC) with the C1 datasheet using a meter in continuity mode. Record the VID:PID from `lsusb` | `adapter_identified`, `adapter_pinout_verified`, `adapter_usb_vid_pid` | pinout matches the datasheet; TX/RX are not swapped onto VCC |
| 3 | Safe supply + startup current | Bench supply with a current limit first. Measure V at the LiDAR connector and the peak current at spin-up. **A USB-UART adapter does not necessarily supply the correct scanner/motor power: check where VCC comes from** | `supply_voltage_measured_v`, `startup_current_measured_a` | 4.9–5.25 V; current recorded |
| 4 | Pi supply headroom | With the Hailo, the IMX708 camera and Wi-Fi all running, plus the LiDAR, run 5 min, then `vcgencmd get_throttled` and `vcgencmd pmic_read_adc EXT5V_V`. The Pi 5 limits total USB current (≈ 600 mA unless the PSU negotiates 5 A or `usb_max_current_enable=1`; 1.6 A with a 5 A supply) | `pi_supply_headroom_ok`, `pi_throttled_after_test` | `throttled=0x0`; EXT5V ≥ 5.0 V |
| 5 | Mount + scan plane | Mount the sensor level. Its plane must clear the camera mast, the gripper and the wheels. Record every self-occluded sensor-angle window. Measure the forward offset with a target on the robot's forward axis (DEMO_RUNBOOK §4) | `mount_scan_plane_clear`; `mount.*` | the plane is unobstructed except the recorded windows |
| 6 | Cable strain relief | Cable tied down, clear of the wheels and of the gripper's travel at both extremes | `cable_strain_relief_ok` | passes a tug test; no contact during manual wheel rotation |
| 7 | USB enumeration + permissions | Plug in 3 times; check that `/dev/serial/by-id/...` is stable and that the user is in `dialout`. **Distinguish it from the M5StickC bridge's serial port.** | `usb_enumeration_ok`, `device_path_by_id` | the by-id path is stable and is not the StickC |
| 8 | Independent wiring inspection | A **different** person repeats items 1–3 and 7 | `independent_wiring_inspection_by` | not the same person as `verified_by` |
| 9 | Physical emergency power cutoff | A switch, or pulling a connector, removes LiDAR power (and rover power) at once without the Pi | `emergency_power_cutoff_ok` | tested once |
| 10 | Safe stationary location | Table or bench, rover wheels **off the floor**, the motor bridge unpowered or e-stopped, nobody's eyes at scan-plane height (Class 1 laser per the vendor, still standard practice) | `stationary_test_location` | recorded |
| — | Sign-off | Name + ISO time | `verified_by`, `verified_at` | — |
| — | GET_INFO model byte | Read during the first approved scan; record it in `expected_model_id` for later runs | `expected_model_id` | recorded |

## Power risk analysis (includes the earlier Pi dropouts)

* **History:** the Pi dropped off the network at least once on 2026-11-07, cause **unknown**: volatile journal, see Team-15-Robot IMPLEMENTATION_JOURNAL. The suspects were heavy CPU load (the Qwen llama-server benchmark) and USB back-feed through the StickC charging path, which is why the VBUS-blocking adapter is required. A spinning LiDAR is a new constant USB load plus an inrush at motor start.
* **Mitigations:**
  * Measure the startup current (item 3).
  * Re-run `get_throttled` with **everything** running (item 4).
  * Prefer powering the LiDAR from a separate, current-limited 5 V supply with a common ground, if the adapter allows it.
  * Never hot-plug the LiDAR while the Hailo is running inference, until item 4 passes.
  * If `get_throttled` ever shows a non-zero value after a LiDAR run, stop and record it. Do not retry under load.
* **Failure behaviour (software):** a brownout or unplug raises `LidarDisconnected`. The panel shows DISCONNECTED and the sectors read UNKNOWN. The rover adapter returns ERROR, which can never be fresh. No motion depends on the LiDAR in this PR in any case.

## After the checklist

Request **explicit approval** for the first stationary scan (LIDAR_C1_DEMO_RUNBOOK.md §3). No autonomous motion at any point during initial LiDAR testing.

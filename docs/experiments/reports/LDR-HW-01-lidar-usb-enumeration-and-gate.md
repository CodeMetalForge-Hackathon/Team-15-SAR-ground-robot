# LDR-HW-01: RPLIDAR C1 USB enumeration checks and hardware-gate attempts (sub-runs a–g)

**Label: REAL HARDWARE (read-only: USB/kernel/power inspection only; no serial command sent)**, except sub-run f, which is **SIMULATED** · **Status: INCONCLUSIVE.** The adapter was detected. The LiDAR itself was never queried. Real scan **NOT VERIFIED**.
Back to: [15 RPLIDAR C1](../../15_RPLIDAR_C1.md) · [LiDAR hardware checklist](../../lidar/LIDAR_C1_HARDWARE_CHECKLIST.md) · [stationary scan procedure](../../lidar/LIDAR_C1_STATIONARY_SCAN_PROCEDURE.md)

## In one paragraph (plain language)

The team wanted to run two real LiDAR obstacle tests: a chair 1 m ahead, then the chair moved aside. First we checked whether the Pi could see the LiDAR at all. The Pi saw the **USB-to-serial adapter board** (a Silicon Labs CP2102N chip) three times, with the same serial number each time. But that chip runs from USB power and appears the same whether or not a LiDAR is plugged into it. Actually talking to the LiDAR means opening the serial port and asking "who are you?" (GET_INFO). The software refuses to open the port until 17 physical safety checks are recorded, and only 2 of them could be filled from the Pi's own diagnostics. The rest needed a multimeter, a USB power meter, photos and two people, and none were supplied. So **no command was ever sent to the LiDAR**. Its model, firmware and health are unknown, and no real scan exists. The demo used the labelled simulation instead.

## 1. Objective

Phase 1: determine whether the C1 is connected and the hardware gate can pass. Phase 2, authorized by the team at 08:31 UTC but never reached: a bounded GET_INFO + GET_HEALTH exchange with no scan and no motor. Phase 3 (scan) needed a separate approval and was never reached.

## 2. Setup

- Raspberry Pi 5, kernel 6.18.60+rpt-rpi-2712. User in `dialout`. pyserial 3.5 present on the Pi.
- SLAMTEC RPLIDAR C1, expected label C1M1-R2 (**label never read**), plus a "small green" USB adapter board. Its make and model were never identified, and its pinout was never verified.
- Software: PR #11 branch head `7e61595` on the Mac. The gate check ran on the Mac with `python3 -B -m lidar check-config --config <cfg> --hardware`. On the Pi, only read-only commands ran: `lsusb`, `lsusb -t`, `ls -l /dev/serial/by-id`, `udevadm info`, `fuser`, `journalctl -k`, `vcgencmd get_throttled / measure_temp / pmic_read_adc EXT5V_V`, `vcgencmd get_config usb_max_current_enable`, and `/proc/device-tree/chosen/power/max_current`.
- No model or checkpoint. No ground-truth target was used, because no scan ran.

## 3. Results (each sub-run separately; times UTC, session console log 2026-11-08; Pi local time UTC−5)

| Sub-run | UTC | Adapter | Power | Gate | Notes |
|---|---|---|---|---|---|
| **a** | 08:21 | **Detected**: `10c4:ea60` "CP2102N USB to UART Bridge Controller", driver `cp210x`, 12 Mbit/s, bus 3 port 1, `/dev/ttyUSB0`, stable `/dev/serial/by-id/usb-Silicon_Labs_CP2102N_…-if00-port0`, serial `0cec01cd3f70f011916c94301045c30f`, `bMaxPower 100mA`. Plugged in at 08:19:18. No kernel errors | `throttled 0x0`, EXT5V 5.25 V, core 0.75 V, 47.2 °C. 3 A supply reported, `usb_max_current_enable=0` (≈ 600 mA total USB budget) | refused (template) | Verdict **INCONCLUSIVE**: the adapter enumerates identically with or without a C1 |
| **b** | 08:31–08:33 | **Not detected** (root hubs only; no `/dev/ttyUSB*`; no USB events this boot) | `0x0`, 5.17–5.19 V, 47–48 °C | `check-config --hardware`: **refused, 17 blockers** | The Pi had restarted at ≈ 08:22. The first report suspected a brownout; the operator then said the restart was intentional, and the report was corrected |
| **c** | 08:37 | **Detected** again, same serial, now bus 1 port 1. Kernel: attach 08:34:57, **disconnect 08:35:01** (after 4 s), an unfinished enumeration at 08:35:21, clean attach 08:36:05 | `0x0`, 5.17 V, 47.7 °C | not re-run | The 4 s drop is consistent with the cable being moved between ports. Otherwise it would point to a marginal connector |
| **d** | 08:46 | **Not detected** at boot (no enumeration attempt in the kernel log) | **5 A supply**: `max_current 0x1388` = 5000 mA, `usb_max_current_enable=1` (≈ 1.6 A USB budget); `0x0`, 5.18 V, 44.4 °C | **17 blockers** | Pi on mains instead of portable power. For the second boot in a row, the adapter needed a re-plug |
| **e** | 08:47–08:54 | **Detected**: clean attach 08:46:15, same serial, bus 1, port free | `0x0`, 5.18 V, 45.0–49.4 °C | Working copy outside Git filled with **2 fields from diagnostics** (`adapter_usb_vid_pid 10c4:ea60`, `device_path_by_id`): **15 blockers** | Deliberately **not** marked: `usb_enumeration_ok` (no deliberate 3-replug test; the 4 s drop is unexplained) and `pi_supply_headroom_ok` / `pi_throttled_after_test` (idle only, no full-load test). The first gate attempt failed on an extra `_evidence` key, so evidence notes went to a sidecar file |
| **f** | 08:56–08:57 | — | — | re-run once: **15 blockers** | Fallback: SIMULATED replay server on `127.0.0.1:8775`. `02_obstacle_ahead` FRONT **BLOCKED**, closest 0.2409 m at robot 350.57° / sensor 189.43°; `04_obstacle_left` FRONT **CLEAR** 2.4914 m, closest 0.2436 m LEFT (robot 90.03°). **Label SIMULATED. Fixture values, not a chair** |
| **g** | 09:08 | Detected; stable since 08:46:15; no disconnects | `0x0`, 5.16 V, 48.8 °C | 15 blockers | C1 datasheet read in the session: start current **800 mA typical**, running 230–260 mA, 4.8–5.2 V, ripple ≤ 150 mV. The manual says the motor only spins on a scan command, so a still head with a lit LED is normal idle. **The gate accepts up to 5.25 V, above the 5.2 V datasheet maximum**; not changed |

**Still open at the end (15 items):**
- `model_label_read` and `model_evidence_ref`;
- `adapter_identified` and `adapter_pinout_verified`;
- `supply_voltage_measured_v` and `startup_current_measured_a`;
- `pi_supply_headroom_ok` and `pi_throttled_after_test`;
- `mount_scan_plane_clear` and `cable_strain_relief_ok`;
- `usb_enumeration_ok`;
- `emergency_power_cutoff_ok`;
- `stationary_test_location`;
- `verified_by/_at`;
- `independent_wiring_inspection_by`.

In addition, `expected_model_id` must be set before `LidarConfig.validate` accepts hardware mode (see §6).

## 4. Metrics and why

USB VID:PID, serial number and by-id path establish **adapter identity and stability**. Kernel events establish connect/disconnect history. `get_throttled`, EXT5V, the supply current limit and temperature establish **power headroom**, which matters because the C1's start current (≈ 0.8 A) exceeded the 3 A supply's ≈ 600 mA USB budget. The gate output is the authoritative go/no-go.

## 5. Evidence

- Session console log, 2026-11-08 08:21–09:12 UTC (all printed outputs above).
- The working config copy and `EVIDENCE.json` were kept in a session scratch folder on the Mac, outside Git. They are not preserved as project evidence and were not hashed.
- Nothing was written on the Pi.

## 6. Limitations and confounders

- **An enumerating adapter is not a detected LiDAR.** No GET_INFO was sent, so the C1's presence is unconfirmed.
- The Pi restarted between sub-runs: uptime 5 min at 08:31, 1 min at 08:37, 1 min at 08:46. So the sub-runs are not one continuous session. Exact boot times are uncertain, because kernel-log timestamps and `uptime` disagree slightly.
- There is no dedicated GET_INFO-only command. `scan-once` always proceeds to SCAN. A reviewed `probe` command would be needed for the authorized non-scanning test.
- **Gate deadlock:** `LidarConfig.validate` requires `expected_model_id` before connecting, but the checklist says to read it via GET_INFO during the first approved scan.

## 7. What this proves / does NOT prove

**Proves:**
- a CP2102N USB-UART bridge (serial `0cec01cd…c30f`) enumerated cleanly on the Pi on two different USB ports, with a stable by-id path and correct permissions;
- the Pi's idle power was healthy on both supplies;
- the 5 A supply raises the USB current budget to ≈ 1.6 A;
- the LiDAR gate refused every time, as designed.

**Does NOT prove:**
- that a C1 is attached or powered;
- the model, firmware, serial number or health;
- that the adapter's pinout matches the C1;
- legacy SCAN support;
- any distance or bearing;
- the scan rate;
- power behaviour with the motor spinning.

## 8. What we would change next time

1. Read and photograph the C1 label and the adapter board **before** the session.
2. Bring a USB power meter and a multimeter.
3. Add a reviewed `lidar probe` command: STOP, GET_INFO, GET_HEALTH, close; no SCAN; recording the model byte.
4. Resolve the `expected_model_id` ordering.
5. Tighten the voltage bound to the datasheet's 5.2 V.
6. Do the 3-replug stability test deliberately, with each re-plug announced.

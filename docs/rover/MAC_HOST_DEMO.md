# Mac-hosted rover + live camera demo (runbook)

Architecture: **Pi IMX708 → SSH/Tailscale → Mac (Faster R-CNN, camera_mapping, dashboard, `rover.mac_host`) → USB → M5StickC bridge firmware → RoverC-Pro.**
Wheel commands never pass through the Pi. Qwen/LoRA/RAG are off the critical path (`--no-qwen`).

## 1. Start / stop

```bash
cd Team-15                         # this branch
PORT=8000 scripts/camera_demo.sh --no-qwen          # live Pi camera + Faster R-CNN + dashboard
#   fallback, no Pi:  REPLAY_GLOB="$HOME/Team15_evidence/camera_live_test/person-*/D1-*[0-9].png" scripts/camera_demo.sh --replay --no-qwen
open http://localhost:8000/demo                      # camera | robot-relative map | controller + timeline
python3 -m rover.mac_host                            # second terminal: rover host, SIMULATED driver (no wheel moves)
```
Stop: `Ctrl-C` in each terminal (the demo script stops everything it started, and `mac_host` zeroes its output on exit).
Hardware stop: the RoverC power switch. Firmware stop (once it's flashed): StickC button A.

`mac_host` commands: `approve <name>`, `fwd <speed> <s>`, `back <speed> <s> rear-clear`, `left|right <speed> <s>`, `stop`, `estop`, `status`.
Every request goes through the camera veto and then `SafetySupervisor`. Autonomous, Qwen-originated or model-originated motion is refused.

## 2. What each gate does
| Input | Result |
|---|---|
| No camera state, stale (> 1 s), or not `LIVE-HW` | HOLD: no motion of any kind |
| Person in the forward corridor / corridor BLOCKED | STOP: forward vetoed, running motion stopped |
| Corridor CAUTION / UNKNOWN, or camera not CALIBRATED | HOLD: forward vetoed |
| Corridor blocked and a LEFT/RIGHT path is observed clear | OPERATOR_REVIEW with a suggestion. Never executed automatically. |
| No candidate is observed clear | OPERATOR_INTERVENTION |
| Supervisor | operator approval, fresh range reading, measured voltage + threshold, bridge acks, ≤ 0.30 speed, ≤ 1 s commands, ramp, heartbeat |
| StickC firmware | 250 ms link watchdog, button-A e-stop (cleared only locally), zero at boot, re-ARM required after any fault |

No detections is never treated as clearance: CLEAR requires every corridor cell to be observed FREE, and that needs a measured mount.

## 3. Hardware readiness (2026-11-08 09:00 ET)
| Item | State |
|---|---|
| Pi SSH (Tailscale) | OK (Pi rebooted ~08:50) |
| IMX708 | OK, live frames to the Mac, ~160 ms detector, ~390 ms capture→dashboard |
| StickC USB | **Plugged into the Pi, not the Mac.** FTDI 0403:6001, "Hades2001 / M5stack", serial `7D520E63EE`. Move the cable to the Mac. |
| Controller model | original M5StickC or StickC Plus (FTDI bridge; the Plus2 uses a CH9102). **Read the board label.** |
| Firmware on the StickC | unknown (the port was never opened). Assume it is not the bridge firmware. |
| Bridge firmware | compiles for StickC / Plus / Plus2 after two fixes on this branch. **Not flashed.** |
| Battery | not measured (the RoverC has no battery register) |
| Camera calibration | UNCALIBRATED, mount unmeasured, so distances are UNKNOWN and the corridor is never CLEAR |

## 4. Steps that need explicit approval, in order
1. **Move the USB cable** to the Mac. Then: `system_profiler SPUSBHostDataType; ls /dev/cu.usbserial-7D520E63EE*`. The dashboard USB badge should turn DETECTED.
2. **Flash** (RoverC power switch OFF, wheels lifted). Use the FQBN that matches the label:
   `arduino-cli upload --fqbn m5stack:esp32:m5stack_stickc_plus -p /dev/cu.usbserial-7D520E63EE1 firmware/stickc_roverc_bridge`
   (or `m5stack_stickc`). On macOS the FT2232 shows two nodes. The ESP32 UART is normally the second (`…1`). Check that the upload log says "Connected".
3. **Bridge check, motors unpowered**: the screen shows `DISARMED`. Button A shows `ESTOP`. A long press on B returns to `DISARMED`.
4. **Wheels-lifted pulses** (≤ 0.3 s, low speed, a teammate at the power switch). These are blocked by design today, see §5.

## 5. Why the wheel test cannot run through the current gates (needs a reviewed bench mode)
- `RoverCAdapter` refuses to exist until `WheelMapping` is verified, but the mapping can only be measured by spinning the wheels.
- `SafetySupervisor` requires a fresh range reading (no ranging sensor is on the Mac) and a measured voltage from a power source no software reads.

Proposed `rover/bench.py` (not implemented; review + approval needed): a wheels-lifted mode that
- takes an operator-typed multimeter voltage (valid 60 s, threshold required) and an operator assertion "WHEELS_LIFTED" (valid 30 s) in place of the range gate;
- allows only raw library `y = ±20` for ≤ 0.3 s through the same `BridgeTransport` (ARM, watchdog, CRC, session);
- records `{operator, t, result, wheels_lifted, observations}` to `~/Team15_evidence/wheel_tests/latest.json`, which the dashboard shows;
- can never run with `wheels_lifted` unset, and never enables floor motion.

## 6. Video (2:00)
| Time | Show | Source label |
|---|---|---|
| 0:00–0:15 | Problem, the robot on the bench (phone camera) | real |
| 0:15–0:35 | `/demo`: a consenting person walks in, box + confidence, bearing ray on the map | LIVE-HW |
| 0:35–0:55 | A chair placed ahead. Corridor UNKNOWN/BLOCKED. Navigation recommendation STOP + operator. | LIVE-HW |
| 0:55–1:15 | Wheels: only if §4.4 passed. Otherwise `pytest rover/tests/test_mac_host_e2e.py -v` + `mac_host` refusing `fwd` | SIMULATED, say so |
| 1:15–1:35 | Aerial-ground rescue simulation | SIMULATED |
| 1:35–1:55 | `pytest -q` (581 passed), GitHub PR | test evidence |
| 1:55–2:00 | Capabilities + limitations | — |

Narration (≈ 30 s): *"A Raspberry Pi camera streams to the Mac, where Faster R-CNN finds people and obstacles in real time. Every detection is placed on a robot-relative map by bearing. Distance stays 'unknown' because we haven't physically calibrated the camera yet, and we won't guess. When someone or something is in the path, the robot's deterministic safety layer says stop and asks the operator. Our language models only advise. The wheels are driven through a watchdog bridge that stops the motors within 250 ms if the link drops. That's tested in simulation. On real wheels, it's next once the firmware is flashed and bench-verified."*

Consent: only people who have agreed may appear on camera. Live frames are not stored in Git.

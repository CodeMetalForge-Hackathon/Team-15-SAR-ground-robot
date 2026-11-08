# Pi-hosted rover control: runbook (controller on the Pi)

**Chain:** Pi IMX708 → Mac (Faster R-CNN, camera_mapping, dashboard) → Qwen advisor (advice only) → **signed link** → Pi (`rover.pi_host`: camera veto + SafetySupervisor + bridge) → USB → StickC firmware (250 ms watchdog, button-A e-stop) → RoverC-Pro.

## 1. Launch (mock motors: no serial port is opened)
```bash
# Mac, terminal 1: live camera + dashboard
PORT=8000 scripts/camera_demo.sh --no-qwen
# Mac, terminal 2: Qwen + LoRA advisor (falls back to --base if the adapter cannot be verified active)
Q=~/Documents/Team-15-Qwen; HF_HUB_OFFLINE=1 $Q/.venv-lora/bin/python scripts/qwen_rover_advisor.py \
   --adapter $Q/lora/out/rescue-lora-v0.2-run2/ckpt-0088 --port 8095 --log ~/Team15_evidence/qwen_rover/advice.jsonl
# Pi, terminal 3 (from the Mac):
ssh -tt team15-pi 'cd ~/team15_rover && exec python3 -u -B -m rover.pi_host --mock-motors --bind 100.97.93.118'
# Mac, terminal 4: the 20 s session (or --faults; or no flag = forward + mirror status only)
python3 scripts/ai_rover_session.py --pi http://100.97.93.118:8765 --demo20
open http://localhost:8000/demo
```
**Stop:** Ctrl-C in each terminal. Losing the Mac link makes the Pi stop and latch COMMS_LOST within 0.5 s. A Pi or host hang trips the StickC watchdog (250 ms, once the bridge firmware is flashed). An e-stop is cleared only by restarting `pi_host` on the Pi.
**Key:** `~/.config/team15/rover_link.key` (mode 600) on both machines. Requests without a valid signature get HTTP 401.
**Deploy a new commit:** `git archive HEAD rover | ssh team15-pi 'rm -rf ~/team15_rover/rover && tar -x -C ~/team15_rover'`

## 2. Controller facts (read-only, 2026-11-08)
| | |
|---|---|
| USB | FTDI `0403:6001`, "Hades2001 / M5stack", serial `7D520E63EE`, `ftdi_sio`, `/dev/ttyUSB0` |
| Stable path | `/dev/serial/by-id/usb-Hades2001_M5stack_7D520E63EE-if00-port0` |
| Model | **original M5StickC or StickC Plus.** The USB descriptor cannot tell them apart. Read the label (the Plus is longer, with a 1.14" screen). |
| Firmware on it | unknown. The port has never been opened. |
| Staged on the Pi | `~/team15_rover/firmware_staged/bridge_m5stack_stickc{,_plus}.merged.bin` + `SHA256SUMS` (verified). esptool 4.8.1 in `~/team15_rover/.venv-flash` |

## 3. ModemManager exclusion (needs approval: system config)
`docs/rover/udev/77-team15-stickc-mm-ignore.rules` matches only serial `7D520E63EE`.
```bash
scp docs/rover/udev/77-team15-stickc-mm-ignore.rules team15-pi:/tmp/
ssh team15-pi 'sudo install -m 644 /tmp/77-team15-stickc-mm-ignore.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger --action=change /dev/ttyUSB0 && udevadm info -q property -n /dev/ttyUSB0 | grep ID_MM_DEVICE_IGNORE'
# expect ID_MM_DEVICE_IGNORE=1.  Undo: sudo rm /etc/udev/rules.d/77-team15-stickc-mm-ignore.rules && sudo udevadm control --reload
```

## 4. Flash (needs approval). RoverC power switch OFF, wheels lifted.
```bash
ssh team15-pi
cd ~/team15_rover/firmware_staged && sha256sum -c SHA256SUMS
B=bridge_m5stack_stickc_plus.merged.bin      # or bridge_m5stack_stickc.merged.bin, per the label
P=/dev/serial/by-id/usb-Hades2001_M5stack_7D520E63EE-if00-port0
../.venv-flash/bin/esptool.py --chip esp32 --port $P chip_id          # reads the chip; resets the StickC
../.venv-flash/bin/esptool.py --chip esp32 --port $P --baud 750000 write_flash 0x0 $B
```
Expected afterwards: the StickC screen shows `DISARMED` on maroon. Button A shows `ESTOP`. Holding B for 1 s returns to `DISARMED`.

## 5. First supervised wheel test (needs separate approval)
Preconditions, all recorded in `~/Team15_config/hardware_verification.json`:
- model;
- firmware SHA;
- link;
- wiring;
- measured battery voltage and threshold;
- `stop_on_link_loss_ms` measured;
- teammate at the power switch;
- all four wheels off the surface.

1. `pi_host --serial $P --usb-serial 7D520E63EE --verification …`. Today it **refuses**: the wheel mapping is unmeasured and there is no range or power source.
2. That refusal is correct. Pulses need the reviewed bench mode proposed in `MAC_HOST_DEMO.md` §5: operator-typed voltage and WHEELS_LIFTED assertions, raw `y = ±20` for ≤ 0.3 s through the same bridge. It is not implemented.
3. Sequence once approved: STOP (screen `DISARMED`, wheels still) → ARM → forward ≤ 0.3 s → STOP → backward ≤ 0.3 s → STOP → unplug USB while turning, and expect a stop within ≤ 250 ms → record `~/Team15_evidence/wheel_tests/latest.json`.

## 6. Video (20 s segment)
Screen-record `/demo` (⌘⇧5 → "Record selected portion") while `--demo20` runs. Logs are written to `~/Team15_evidence/ai_rover_sessions/<stamp>/session.jsonl`. Say "SIMULATED MOTOR OUTPUT" over the wheel registers. Only consenting people should be in view.

# Crazyflie drone path (Team-15)

This is how Mabelle's scanner rides on the Crazyflie 2.1+. Her scanner never transmits.
The Crazyflie's own radio carries the scanner lines to the Jetson.

```
BLE phones ))) scanner (ESP32, listen-only)
                 |  wire: scanner TX -> Crazyflie RX2, 115200
                 v
          Crazyflie 2.1+  running firmware/crazyflie_scanner_app
                 |  Crazyradio (the drone's normal radio link)
                 v
  Jetson / laptop:  sar_sim.cf_bridge  (owns the Crazyradio)
        |                         |
        | /tmp/t15-scanner-1      | 127.0.0.1:8770
        v                         v
  discovery.server          CrazyflieLink  <- crazyflie/demo_mission.py, keyboard_control.py
  (+ BLE-ID checker)                        <- homebase planner (next step)
```

## What's here

| File | What it does |
| --- | --- |
| `firmware/crazyflie_scanner_app/` | App flashed onto the Crazyflie. It reads scanner lines on RX2 and sends them over the radio. It also lands the drone if the Jetson goes quiet. |
| `sar_sim/cf_bridge.py` | Runs on the computer with the Crazyradio. It owns the radio, feeds the scanner port, and handles safety landings. |
| `sar_sim/backends/crazyflie_backend.py` | `CrazyflieLink`, the driver Mabelle's demo and keyboard control load. |
| `sar_sim/cf_core.py` | The cflib code that talks to one drone. |
| `sar_sim/scanner_codec.py` | Rebuilds the scanner's exact text lines from the drone's packets. |
| `tests/test_cf_*.py` | Tests with a simulated drone that runs the real app code. |

## 1. Wiring (Gavin)

- **Signal:** scanner TX pin (`UART_TX_PIN` in `esp32_scanner.ino`) goes to Crazyflie **RX2**. That's right-side header, pin 2.
- **Ground:** scanner GND to Crazyflie GND.
- **Power:** use **VCOM** (battery voltage, max 1 A) into the scanner board's battery input. Don't use VCC: it's 3.0 V and max 100 mA, which is too little for BLE scanning.
- **Levels:** the Crazyflie's IO pins are 5 V tolerant, so the ESP32's 3.3 V TX is fine.
- **Decks:** the Flow deck v2 is fine. The AI deck also uses UART2, so it can't go on with the scanner.
- **Weight:** the max payload is 15 g, deck and scanner included. Flight time drops with load.

## 2. Flash the Crazyflie app (once per drone)

Do this on the Mac. A Jetson Nano's stock Ubuntu 18.04 compiler is probably too old for this firmware.

```bash
git clone --recursive --branch 2026.08 https://github.com/bitcraze/crazyflie-firmware.git ~/crazyflie-firmware
brew install --cask gcc-arm-embedded        # the ARM compiler
python3 -m pip install cflib cfclient
cd ~/Team-15/firmware/crazyflie_scanner_app
make CRAZYFLIE_BASE=~/crazyflie-firmware -j8
python3 -m cfloader flash build/cf2.bin stm32-fw -w radio://0/80/2M/E7E7E7E7E7
```

To check it worked, connect with the cfclient app. A `t15scan` group should appear under Parameters.

## Test without flying (bench mode)

The drone sits on the table on its USB cable. It needs no Flow deck, and every flight command is refused.

```bash
python3 -m sar_sim.cf_bridge --bench --uri usb://0
```

Every 5 s it prints battery, decks and scanner-line counts. With the scanner wired and the drone app flashed, Mabelle's discovery server works too: `python3 -m discovery.server --serial /tmp/t15-scanner-1`.

## 3. Run it (one terminal each, from the repo root)

```bash
# A. The bridge (always first)
python3 -m sar_sim.cf_bridge --uri radio://0/80/2M/E7E7E7E7E7

# B. Mabelle's discovery server, reading the drone's scanner port
python3 -m discovery.server --serial /tmp/t15-scanner-1
#    add her checker flags as usual, e.g. --test-keys --state PATH --scope TESTKEY-...

# C. Her demo, or keyboard control
python3 crazyflie/demo_mission.py --live-drone --height-m 0.5 --signal-id ID --scanner-on-drone
python3 crazyflie/keyboard_control.py --live-drone --height-m 0.5
```

For more drones, add more `--uri` flags to the bridge. Drone 2's scanner port is `/tmp/t15-scanner-2`.
`CrazyflieLink` can also run with no bridge. It then opens the radio itself, but there are no scanner lines in that mode.

## Safety layers

1. **Her demo:** a 120 s search budget, landing at 140 s, and landing below 3.3 V.
2. **Bridge:** lands the drone if the program flying it crashes or goes quiet for 2 s. It also lands on no pose for 1 s, or on a battery below 3.0 V.
3. **Bridge fence:** refuses commands outside ±1.5 m or 0.1–1.5 m up. It also refuses takeoff below 3.5 V.
4. **Drone app:** lands on its own after 3 s without hearing the bridge. That covers radio loss or a dead laptop.
5. **Exit:** leaving `with CrazyflieLink(...)` always lands, even on an error.

## Honest limits

- **Python 3.10 or newer**, the same as her demo. JetPack 4 on a Jetson Nano ships Python 3.6. So run the bridge on the laptop, or install a newer Python on the Jetson.
- **Not flown on real hardware yet.** It's tested with a simulated drone that runs the real app code, and with Mabelle's own demo, discovery server and checker.
- **Advert detail:** the drone keeps only what her code reads, which is the name (first 19 bytes) and the Apple flag. Other advert fields aren't sent. Token rows keep the full token, and names are cut to 11 characters.
- **Busy rooms:** adverts are capped at 5 per second per device and 60 per second in total. The 115200 baud wire also limits the scanner to about 110 lines per second.
- **Landing:** a quiet-Jetson landing happens in place. The drone doesn't fly home first.
- **Fence:** it's a box check, not obstacle avoidance. Position comes from the deck, and the Flow deck needs a textured floor and light.

## Tests

```bash
python3 -m unittest discover -s tests -p "test_cf_relay.py"     # drone app vs her parsers (fast)
python3 -m unittest discover -s tests -p "test_cf_bridge.py"    # flying and safety (~40 s)
T15_E2E=1 python3 -m unittest discover -s tests -p "test_cf_e2e.py" -v   # her demo end to end (~70 s)
```

The relay tests compile the drone app's C code for your computer, so they need a C compiler (`cc`).

# RoverC Pro: USB and Wi-Fi keyboard control

Controller: **M5StickC Plus SE**. The receiver supports USB, its own Wi-Fi network,
and a shared 2.4 GHz network. Keyboard commands and motor limits are identical
across USB and Wi-Fi. Dry-run is the default.

```sh
python3 rover/keyboard_control.py --dry-run
```

## Wireless option A: rover-hosted network

This works without a router. On the M5 screen, find `WiFi`, `Key` and `AP`.
Connect your computer to that Wi-Fi network using the displayed key, then run:

```sh
python3 rover/keyboard_control.py --wifi 192.168.4.1
```

If a private pairing profile has not been exported, the client prompts for the
same key shown on the M5. The key is generated on the device and persists across
reboots. No passwords or pairing keys are included in this repository or README.
Only one station can join the rover's access point at a time.

Your laptop leaves its previous Wi-Fi while connected to the rover-hosted network;
that network does not provide internet access. Use the shared-network option if
internet access or communication with other demo devices is needed.

## Wireless option B: shared network

Use a 2.4 GHz network with a normal Wi-Fi password, or an open network. Enterprise
username/certificate authentication and captive-portal sign-in are not implemented.
The laptop can use another band on the same LAN if routing permits communication.

While USB is connected, stop any running keyboard client, then run:

```sh
~/.codex/venvs/roverc/bin/python rover/wifi_setup.py \
  --serial /dev/cu.usbserial-7D520E63EE --join
```

The setup script asks for the network name and a hidden password entry. It sends
those credentials to the M5 over USB and stores them in the controller's NVS,
not in repository files. The M5 tries to reconnect to that network after reboot.
Setup prints the assigned shared-network IP, also shown as `LAN` on the M5 screen.
Run the client with that IP:

```sh
python3 rover/keyboard_control.py --wifi REPLACE_WITH_ROVER_LAN_IP
```

Keep the computer and rover on networks that allow direct communication. Guest
client isolation can prevent control even when both devices joined successfully.
During the on-site shared-network check, the rover obtained a LAN address, but
traffic from the Mac was rejected with `Communication prohibited by filter`.
Use the rover-hosted network or a shared network that permits peer communication;
changing the rover password or motor power does not resolve this network policy.
The rover-hosted network remains enabled as a fallback. Connecting to a shared
network may change the access point's radio channel and briefly interrupt AP clients.

Remove saved shared-network credentials with:

```sh
~/.codex/venvs/roverc/bin/python rover/wifi_setup.py \
  --serial /dev/cu.usbserial-7D520E63EE --forget
```

## Pairing profile and status

The USB setup command exports the generated pairing key to
`~/.codex/roverc/connection.json` with file mode 600 on macOS/Linux. The keyboard
client reads it automatically. Shared-network passwords are not stored in this
profile. Use the default path outside the repository for this private file.

To export only the pairing profile, without changing networks:

```sh
~/.codex/venvs/roverc/bin/python rover/wifi_setup.py \
  --serial /dev/cu.usbserial-7D520E63EE
```

To inspect network status without exporting the key:

```sh
~/.codex/venvs/roverc/bin/python rover/wifi_setup.py \
  --serial /dev/cu.usbserial-7D520E63EE --status
```

Wi-Fi uses TCP port 5000 and requires pairing before accepting commands. Pairing
restricts command access; it does not provide TLS encryption on a shared LAN.
One TCP controller is allowed at a time. A paired Wi-Fi controller owns movement;
USB movement is refused while that client is connected. USB STOP and the physical
front-button lock remain available. Provisioning over USB stops motion and drops
the network controller before changing settings.

Once connected over Wi-Fi, USB can be unplugged **provided the M5 controller and
rover base both have charged batteries and are switched on**. The M5's battery and
the rover's motor battery are separate. Unplugged operation and actual wireless
range need a physical demo-space test.

## Controls

| Key | Action |
| --- | --- |
| W / S | Forward / backward |
| A / D | Strafe left / right |
| Z / C | Rotate in opposite directions |
| + or = / - | Raise / lower motor command by 5 |
| I | Query receiver/motor status without moving |
| X | Stop, keep keyboard session open |
| Space, Q, L, Ctrl+C | Stop and exit |

Motor command starts at 20/100 and is limited to 5–50 (`--power`). It is not meters
per second. Each movement key requests a 250 ms pulse. Key repeat can renew motion;
the initial OS repeat delay may cause a pause. Terminal input cannot detect key
release, so stopping occurs on pulse timeout or an explicit stop. Keep wheels
raised for the initial direction check.

The screen shows the last command, motor power and `Moves RX` count. The client
prints sent commands and receiver replies. MOVE is acknowledged only after the
requested motor registers are read back; this does not prove wheel rotation.

## Base detection and startup order

`LOCKED=0` means the front-button motor lock is clear. `READY=0` means the rover's
I2C controller was not detected; it is separate from Wi-Fi pairing. Check the base's
rear switch, battery and controller seating. The original receiver cached this
result at boot; with that image, power the base first, then reset the M5.

The updated receiver source retries detection once per second while stopped and
before readiness checks. It requests/verifies zero motor commands before marking a
recovered base ready. It does not clear the front-button lock or move the rover.
This update requires a USB firmware upload; compiling the source alone does not
change an already-installed controller.

## Stop behavior

The receiver requests stop when no new MOVE arrives for 250 ms, on detected paired
TCP disconnect, invalid commands or motor-register mismatch. Losing Wi-Fi can take
longer to be detected by TCP, but does not refresh the independent pulse timeout.
Pressing the M5 front button locks movement until reset; queued commands cannot
clear the lock. No movement is requested at boot, pairing, or client connection.

The client attempts STOP on exit. On communication failure it reports that stop
acknowledgement is unconfirmed. The controller-side timeout depends on the M5 and
firmware continuing to run; it is not a hardware emergency cutoff. The gripper,
CV and autonomous navigation are not controlled by these scripts.

## USB fallback

The isolated Python environment on this Mac includes pyserial:

```sh
~/.codex/venvs/roverc/bin/python rover/keyboard_control.py \
  --serial /dev/cu.usbserial-7D520E63EE
```

Other hosts need Python 3.10+ and `pyserial` for USB/setup. Wi-Fi driving needs only
the Python standard library. Use an interactive terminal with focus. Keep other
serial monitors/clients closed. The USB client uses an advisory exclusive lock,
one-second write timeout and startup retries; applications ignoring that lock can
still interfere. Intermittent USB failures have occurred on this Mac; try another
data cable/port if they recur.

## Build and install

The SE uses the `M5StickCPlus` board profile with M5Unified. Dependencies:
M5Unified 0.3.0, M5GFX 0.3.0, M5-RoverC 0.0.1 and ArduinoJson 7.4.3.
Microphone/IMU initialization is disabled; the rover uses GPIO0 SDA / GPIO26 SCL.

```sh
arduino-cli lib install M5Unified M5GFX M5-RoverC ArduinoJson
arduino-cli compile --fqbn esp32:esp32:m5stack_stickc_plus \
  --output-dir /tmp/team15-roverc-wifi-build firmware/roverc_usb
```

Uploading replaces the current application. The original 4 MB clock firmware and
a working USB receiver image are backed up privately in
`~/.codex/backups/roverc-2026-11-07/`; restoration has not been tested.
This Mac has required ROM bootloader mode (`--no-stub`) and a slow upload baud rate
for reliable writes. Keep the keyboard client closed during uploads.

## Verification and references

```sh
python3 -m unittest tests.test_rover_keyboard tests.test_rover_wifi -v
```

Tests cover keyboard mapping, limits, USB startup retries, real loopback TCP
pairing/commands/disconnects and private profile writes. Loopback tests use a fake
receiver and never request physical motor movement.

- [StickC Plus SE hardware](https://docs.m5stack.com/en/core/StickC-Plus_SE)
- [StickC Plus SE Arduino setup](https://docs.m5stack.com/en/arduino/m5stickc-plus_se/program)
- [RoverC motor library](https://github.com/m5stack/M5-RoverC)
- [RoverC Pro I2C protocol](https://docs.m5stack.com/en/protocol/K036-B/I2C)
- [Espressif Wi-Fi API](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html)

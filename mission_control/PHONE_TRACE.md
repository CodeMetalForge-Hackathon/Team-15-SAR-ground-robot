# Live phone → ESP32 trace (no vision)

This viewer uses actual USB scanner reports, not simulated advertisements. Red
marks the ESP32 origin; blue marks the selected beacon. The default link diagram
is schematic: its dot positions do not encode distance or bearing. Camera mode
uses manually placed dots. There is no object detector or camera/radio localization.

## Start the receiver host

Close any other program owning the ESP32 serial port. On the computer with the
ESP32, from the repository root:

```sh
python3 -m mission_control.trace --serial /dev/cu.usbmodem101 --host 0.0.0.0
```

On Linux, use the actual serial device, such as `/dev/ttyACM0`. This starts one
exclusive serial reader, a local web server on port 8082, and prints a temporary
viewer token. Open <http://127.0.0.1:8082/trace> on that host and enter the token.
It opens no robot control connections and creates no fake radio observations.
Without verification flags, targets remain explicitly unverified. Use a controlled
beacon on/off test; a strong signal or Apple advertisement is not phone identity.

## OLF C1 Rotating mode

The current C1 app uses **public synthetic test keys**, not production enrollment.
Keep the app open in the foreground; backgrounding it stops its advertisements.
Initialize a private, separate test replay-state file once, outside this repository:

```sh
python3 -m ble_id init-state --state ~/phone-trace-state.json --scope TESTKEY-phone-trace
python3 -m mission_control.trace --serial /dev/cu.usbmodem101 --host 0.0.0.0 \
  --test-keys --state ~/phone-trace-state.json --scope TESTKEY-phone-trace
```

Never reset replay state to make an old token appear fresh. On restart, a receiver
may need to wait for the next 30-second token before it can publish this alias.
If exactly one verified alias is available, the viewer selects it automatically.
The page retains the **SYNTHETIC TEST KEYS** label. Production may instead use the
existing `--keys`, `--state` and `--scope` arguments with actual enrolled keys.

Two independent channels are displayed:

- **Fresh authentication:** the existing verifier persists a new counter before
  publishing it. Its age/count remain unchanged by duplicate advertisements.
- **RF activity:** repeated reports of that already-published token may update
  the beacon's RSSI, advertisement age and graph. Their tag and time window must
  still pass verification, and the alias/counter must match a published sighting.
  Forged, stale/future, unpublished or verifier-halted inputs cannot create activity.

RF reports are not new authenticated sightings. Hearing a replayed current token
cannot establish that the phone or a person is physically present. The new
`trace_signals` API field is kept separate from `/api/beacons` fresh sightings.

## SOS status

OLF C1 now supports a signed SOS toggle with its enrolled tag. See
[SOS_STATUS.md](SOS_STATUS.md) for phone steps and the separate replay-state setup.

## Camera and a second viewer

1. Open the localhost viewer on the host, select **Camera**, then **Share this
   device's camera**, and grant camera access yourself. The browser publishes
   JPEG frames to the same local server, without audio, recording or detection.
   Alternatively run on a Pi with `--pi-camera` for its directly attached camera.
2. On another device, open `http://HOST_LAN_IP:8082/trace` and enter the viewer token.
   **Copy viewer token** is available in the logged-in localhost viewer. Tokens
   are not put in URLs. Choose **Camera → Use host camera** on the other device.
3. **Place origin**, then tap the receiver in the image. **Place phone**, then
   tap the phone. Positions are manual image annotations; moving the phone does
   not automatically move its dot. RSSI still updates from the ESP32.

The shared camera requires a data path on the LAN that permits peer traffic.
The venue network previously returned `Communication prohibited by filter`, so
another device may require a private router/network. A successful local page
does not prove another device can reach that address.

Browser camera access requires a secure context: localhost works on the receiver
host; a remote plain-HTTP viewer can watch the host camera but normally cannot
open its own camera. No certificate bypass is required. Only one browser publisher
can own the camera feed at a time; a running Pi camera refuses browser uploads.
Frames disappear after one second without fresh data. Video is kept in memory
and shared only through the authenticated local camera endpoint, at up to 5 fps
from the browser. No model or vision pipeline is loaded.

## A-01 antenna

The attached Seeed FPC A-01 is a 2.4 GHz antenna; see the
[manufacturer's antenna datasheet](https://files.seeedstudio.com/wiki/XIAO_WiFi/antenna/FPC_Antenna_2.4GHz_2.9dbi_for_XIAO_ESP32C3/res/Datasheet_2.4GHz_FPC_Antenna_2.9dbi_for_XIAO_ESP32C3.pdf).
Reception and RSSI depend on orientation and environment. This setup has one
receiver and no measured bearing, calibrated range, or camera alignment. The
blue/red visual is not triangulation or a geographic phone position.

## Verification

```sh
python3 -m unittest tests.test_phone_trace tests.test_mission_control \
  tests.test_mission_media tests.test_mission_tracking -q
node --check mission_control/static/trace.js
```

The 14 trace tests cover actual pseudo-terminal → serial reader → HTTP transport,
source labels, authentication, missing/stale RF, verification/replay separation,
persistence failure, rotating-alias continuity, authenticated camera uploads,
camera publisher ownership, invalid frames and frame expiry. Camera overlays
were checked with an explicitly simulated feed and test image; real phone RF
reception was verified separately on the attached ESP32. Actual webcam sharing
and access from a second physical device still require those devices to connect.

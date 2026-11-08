# Local network and operator control

This package runs entirely on your local machines. No Sites, cloud service,
internet connection, database, Node.js runtime, or Python package installation is
needed for the coordinator, browser dashboard, simulated agents, or Wi-Fi rover
agent. Use **Python 3.10 or newer**. Live Crazyflie flight requires the team's
external guide backend and its dependencies, which are absent from this checkout.

## Try it on this computer

From the repository root:

```sh
python3 -m mission_control.demo
```

Open <http://127.0.0.1:8080>. Paste the temporary operator token printed in the
terminal. This command starts **three simulated agents** on loopback only; it
opens no robot, radio, serial, or camera connections. To select another port use
`--port 8081`. Tokens disappear when the demo exits.

1. Wait for all three agents to show ready. Their first connection pauses control.
2. Click **Take control**, then **Resume**.
3. Choose a device and action, then **Request action**.
4. Review its parameters under **Approvals**, then **Approve** or **Reject**.
5. **Pause** and **Stop + Land** both cancel pending actions and request rover
   stop and drone landing. Re-enabling requires an explicit operator action.

## Rover Pi camera and Bluetooth

For a live phone-to-ESP32 link view with blue/red markers, RSSI history, camera
sharing without vision, and another-device access, see [PHONE_TRACE.md](PHONE_TRACE.md).

The camera occupies the whole screen behind compact controls on the left and
Bluetooth/recordings on the right. **Hide panels** clears the sidebars;
**Fullscreen** expands the entire interface, retaining Pause and Stop + land.
No camera footage is simulated when the Pi camera is disconnected.

Attach the Pi camera to the rover's Pi. On that Pi, verify the camera with
`rpicam-hello --list-cameras`, then run the coordinator with its camera enabled:

```sh
python3 -m mission_control.server --host 192.168.15.10 --pi-camera
```

This uses Raspberry Pi's `rpicam-vid` MJPEG output (1280×720, 15 fps), as described
in the [official camera documentation](https://www.raspberrypi.com/documentation/accessories/camera-software.html).
Install the Raspberry Pi OS `rpicam-apps` tools if missing. The operator receives
the latest frame over the same authenticated connection as the dashboard, at
up to 10 frames/s. No extra camera port, webcam permission, or third-party stream
service is needed. Frames older than one second are hidden. Video is not written
to disk by the Pi; **Record camera** explicitly starts a browser-side clip of the
received frames. Recordings contain camera imagery only, with no audio or UI.
Hardware camera compatibility, frame rate and wireless latency require testing
on the actual Pi/camera. This preview is not a guaranteed real-time flight feed.

Bluetooth reads the existing discovery service on `http://127.0.0.1:8765`.
Alternatively, connect the ESP32 directly to the operator server using
`--serial /dev/cu.usbmodem2101` (replace with the current USB device). This
uses a single serial reader and supplies the BLE workspace, phone RSSI history,
and signed status without a separate discovery server. The same `--keys` or
`--test-keys`, `--state`, `--scope`, and optional `--sos-state` flags documented
in [PHONE_TRACE.md](PHONE_TRACE.md) enable verification. Reuse existing replay
state files; stop their previous receiver process before starting this one.
For example:

```sh
.venv/bin/python -m mission_control.server --port 8092 \
  --serial /dev/cu.usbmodem2101 --test-keys \
  --state ~/.codex/state/team15/phone-trace-20261108.json \
  --scope TESTKEY-phone-trace-20261108 \
  --sos-state ~/.codex/state/team15/phone-trace-20261108.sos-v2.json
```

To use the separate discovery service, start it as documented in [discovery/README.md](../discovery/README.md),
on the host holding the USB scanner. It remains the only serial reader. To use
another host, add `--discovery-url http://SCANNER_HOST:8765` to the coordinator;
that service must be explicitly reachable on your LAN. The stock discovery CLI
binds to loopback. Nearby signals remain labeled **unverified**; verified beacons
retain their verifier source, test-key label, age and stale status.

**Record** in the Bluetooth panel saves periodic receiver snapshots. **Recordings**
supports camera playback, Bluetooth timeline scrubbing, download and deletion.
**Open video** and **Open BLE** import existing local captures. Clips and captures
are saved in this browser's IndexedDB, scoped to the exact dashboard URL/origin;
they are not uploaded to the Pi or cloud. Download important recordings before
clearing browser storage or changing dashboard hostnames. If browser persistence
fails, the current tab still offers download. Camera recording is capped at ten
minutes/approximately 128 MB; Bluetooth at 10,000 samples/approximately 32 MB.
Feed loss stops and saves an active capture. Stop recordings before closing the
tab; closing the browser during a capture may lose its final data.

Keep this browser tab visible. Hiding the tab requests pause and stops renewing
its lease; closing it, losing Wi-Fi, or suspending the laptop expires the lease.
The UI has no continuous-motion button: each rover approval is one bounded
250 ms motor pulse. Drone moves are absolute boot-frame coordinates in meters.

## Paths relative to the Jetson

Select **Paths** beside Camera for an equal-scale XY trail map, altitude graph,
and distance-from-origin graph for both vehicles. The Jetson is the fixed mission
origin `(0,0,0)` with +X forward, +Y left and +Z up, in meters. Its orientation is
defined at mission setup; this is not automatic tracking of a moving Jetson.
Colors distinguish drone (orange) and rover (olive/dashed). Hollow markers are
last-known positions; unavailable or unaligned positions are not invented.
**Save paths** exports source-labeled histories as JSON. Up to 600 samples per
vehicle are kept in coordinator memory, sampled at most five times per second.
Gaps greater than two seconds break trails instead of joining across missing data.

The drone's estimator reports in its boot frame. While paused, take operator
control, open **Align boot frames**, and enter the measured drone boot origin
XYZ and heading relative to the Jetson. Yaw is counterclockwise toward +Y.
Apply alignment to start a new trail. This affects plots only; flight commands
still use the drone boot frame. Rebooting a robot invalidates its boot alignment.
Alignment is memory-only and must be repeated after coordinator restart.

The RoverC motor protocol supplies no odometry. For a live rover trail, feed a
real localization source (for example external tracking or odometry) to the rover
agent with `--pose-file /tmp/rover-pose.json`. Atomically replace that file with:

```json
{"position_m":[0.4,-0.2,0.0],"frame":"jetson","sampled_at":1794096000.0}
```

`sampled_at` must be the actual Unix timestamp for the measurement, no older than
two seconds; the value above is only a schema example. `frame` can be `jetson`
(already aligned, so no second transform) or `boot` (requires alignment). The
pose file is bounded to 4096 bytes. A missing, stale or malformed optional pose
file hides tracking data without changing motor-control readiness. It can also
be used on the drone agent with an external localization source.

Without localization, live rover status is **No position**. Live drone status is
**Needs alignment** until its frame is configured. Simulated vehicle poses are
explicitly labeled **SIMULATED**. Simulated rover pulses use a simple 5 cm step
at power 20 and 15° turns, solely to exercise the graphs; these are not calibrated
motor distances or real odometry. Commands/approvals never create live positions.

## Physical network

```text
Operator browser ── LAN HTTP ── Pi 5 coordinator :8080
                                      │
Jetson vision → Jetson agent ── HTTP ───┤
                                      │
              Pi rover agent ── HTTP ──┤
                     └── TCP :5000 → M5StickC → RoverC
                                      │
          Pi Crazyflie agent ── HTTP ──┘
                     └── USB Crazyradio → radio → Crazyflie
```

Use a local router/access point with a normal WPA2 password, a 2.4 GHz SSID for
the M5StickC, DHCP enabled, and **guest/client isolation disabled**. Put all devices
on the same LAN; Ethernet is suitable for stationary Pi/Jetson hosts. Internet
uplink is optional. The existing rover hotspot permits only one client and is
not the shared network for this layout. A venue network previously blocked peer
traffic even after the rover joined successfully; use a LAN you control.

Example router reservations (configure these in the router; these are not
hard-coded into the software):

| Device | Example address | Role |
| --- | --- | --- |
| Router | `192.168.15.1` | LAN / DHCP |
| Pi 5 | `192.168.15.10` | Coordinator + robot agents |
| Jetson Nano | `192.168.15.20` | Vision + telemetry agent |
| RoverC M5StickC | `192.168.15.30` | Existing paired TCP receiver |
| Operator | DHCP | Browser interface |

Only the coordinator needs an inbound port: TCP 8080 from operator and Jetson
on the team subnet. The Pi needs outbound TCP 5000 to the rover. Agents make
outbound HTTP requests and need no inbound firewall openings. A Jetson without
an installed Wi-Fi interface can use Ethernet to the router. The laptop does not
connect directly to the rover while the Pi agent owns that control connection.

HTTP bearer authentication isolates operator and device roles; HTTP and the
existing rover TCP protocol are **not encrypted**. Use the private team LAN and
keep these ports off public networks. This is a local prototype, not a hardened
public web service. Do not port-forward it to the internet.

## Provision the Pi

Copy/clone this repository to the Pi. Run from its root:

```sh
python3 -m mission_control.server --init
python3 -m mission_control.server --host 192.168.15.10
```

The first command creates `~/.config/team15/network.json` with mode 600 and
distinct random tokens for `operator`, `rover`, `crazyflie`, and `jetson`. It refuses
to overwrite existing credentials. The server binds to loopback by default;
`--host` is an explicit opt-in to LAN access. Use the Pi's actual assigned IP.
State and event history are in memory. Every coordinator restart discards pending
actions and starts paused. Keep one coordinator per mission.

Read the operator token **in a local terminal on the Pi** and paste it into the
operator browser at `http://192.168.15.10:8080`:

```sh
python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".config/team15/network.json").read_text())["operator"])'
```

Never put credentials in this repository, a URL, a screenshot, or a command-line
argument. The browser holds the token only in tab memory; refresh requires login
again. Export only a device's own role token when moving it to another host:

```sh
python3 -m mission_control.server --export-role jetson --out /tmp/team15-jetson.json
scp /tmp/team15-jetson.json YOUR_JETSON_USER@192.168.15.20:~/team15-jetson.json
rm /tmp/team15-jetson.json
```

On the Jetson, ensure `chmod 600 ~/team15-jetson.json`. Tokens are static until
you deliberately replace the private files and restart the processes. Never
delete or rotate credentials while a robot is in motion.

## Connect the RoverC

Join the M5StickC to `Team15-Field` using the existing USB setup in
[rover/README.md](../rover/README.md#wireless-option-b-shared-network). Its USB
setup utility requires `pyserial`; ordinary Wi-Fi operation needs only Python's
standard library. Export the pairing profile on the Pi, or securely copy the
existing private profile to `~/.codex/roverc/connection.json` on the Pi with mode
600. Stop other rover keyboard clients: only one TCP controller is supported.

On the Pi, in another terminal:

```sh
python3 -m mission_control.agent --node rover --live --rover-host 192.168.15.30
```

This uses the existing `WiFiLink`, including pairing, readiness checks, MOVE
acknowledgements and the firmware's independent 250 ms pulse timeout. Stop
acknowledgement means the receiver replied, not that wheels were observed stopped.
Battery telemetry is unavailable on this path and is not invented. Initially
check directions with wheels raised, then test unplugged operation in the demo
space. Both rover and M5 batteries must be powered.

## Connect the Crazyflie

Plug Crazyradio into the Pi running its agent. The drone itself does not join the
Wi-Fi network. The adapter reuses the existing
`sar_sim.backends.crazyflie_backend.CrazyflieLink` interface. **That module is not
in this repository**: obtain the team's backend, install its dependencies, set
its project root on `PYTHONPATH`, and validate its radio/positioning setup before
using live mode. A missing backend fails at startup; it never falls back to a
simulation. Other compatible backends can use `--backend-module MODULE`.

After the physical preflight described in [crazyflie/README.md](../crazyflie/README.md):

```sh
python3 -m mission_control.agent --node crazyflie --live --preflight-confirmed \
  --uri radio://0/80/2M/E7E7E7E7E7
```

Backend contract: `CrazyflieLink(uri)` is a context manager exposing `vbat`,
`pose()`, `takeoff(height, duration)`, `go_to(x,y,z,yaw,duration)`, and
`wait(seconds)`. Commands must return promptly. `pose()` must report finite
coordinates in the boot frame with current telemetry. `__exit__` must land and
disconnect on normal and error exits. A blocked or broken backend cannot be made
safe by host-side timers; radio-loss behavior must be configured and physically
tested separately.

Flight requests are limited to x/y ±1.5 m, altitude 0.2–1.2 m and move duration
corresponding to at most 0.2 m/s average waypoint speed. Actual flight dynamics
depend on the backend. Battery below 3.3 V/unavailable, invalid/out-of-envelope
telemetry, a 120-second flight budget, or network/control loss requests landing
by exiting that context. After a live flight is landed, restart the agent and
repeat preflight for another flight. Startup safety requests while grounded do
not consume the preflight.

The airborne BLE scanner still needs a separately implemented wireless telemetry
path. This package does not invent that radio bridge or move the existing
exclusive serial reader. BLE-ID replay-state ownership and verified-beacon APIs
remain in the existing discovery service; vision observations are not promoted
to authenticated sightings.

## Connect the Jetson

Copy the repository and its exported role credential onto the Jetson. Run:

```sh
python3 -m mission_control.agent --node jetson --live \
  --coordinator http://192.168.15.10:8080 \
  --credentials ~/team15-jetson.json \
  --telemetry-file /tmp/team15-vision.json
```

Your vision process should atomically replace `/tmp/team15-vision.json` with a
JSON object of at most 8192 bytes at least once every two seconds, for example:

```json
{"camera_status":"running","detections":[{"label":"person","confidence":0.84}]}
```

These values must come from the actual vision process. No camera model or
detector is bundled. Without `--telemetry-file`, the agent reports its network
connection and explicitly says no vision publisher is configured. Missing,
malformed or oversized files stop reporting readiness; files older than two
seconds are labeled stale. The operator UI renders observation text without
interpreting it as HTML. This interface publishes detections, not a video stream.

For network setup before hardware is ready, omit `--live` on any agent. That
device is labeled **SIMULATED**; combining it with live agents visibly labels the
dashboard **MIXED**. A live rover can still move in mixed mode, after approval.

## Control and failure behavior

| Condition | Behavior |
| --- | --- |
| Operator lease | Single owner; heartbeat every ~650 ms; expires after 3 s |
| Device heartbeat | Agents sync ~150 ms plus request/backend time; stale after 2 s |
| Agent joins/restarts | Pause mission and request stop/landing |
| Agent recovers from an error | Pause; require explicit operator re-enable |
| A previously joined device is offline/not ready | Re-enable refused until it recovers |
| Request proposed | No dispatch until separately approved; expires after 20 s |
| Request approved | Must be delivered within 2 s; delivered at most once |
| Acknowledgement missing | Mark unconfirmed and pause; no automatic motion retry |
| Pause / Stop + Land | Cancel pending/approved actions; request rover stop and drone landing |
| Coordinator/network failure | Local agent requests safety; rover firmware pulse timeout remains independent |
| Two device agents | A fresh device session rejects a second agent with a different boot ID |
| Coordinator restart | Agent detects new instance, requests safety; operator must reclaim control |

Command states are `pending`, `approved`, `dispatched`, `acknowledged`, `failed`,
`unconfirmed`, `expired`, `cancelled`, and `rejected`. Acknowledged means the
adapter accepted/submitted the command, **not physical mission completion**.
In-flight operations cannot be recalled over a disconnected network. Stop and
land are requests, not a certified emergency cutoff; keep physical controls
available and verify actual robot behavior before a live demo.

## API for integration

All APIs require `Authorization: Bearer ROLE_TOKEN`. POST bodies are JSON,
bounded to 16 KiB. Node tokens can only access their own sync endpoint;
only the operator token can read state or invoke operator operations.

| Endpoint | Request / result |
| --- | --- |
| `GET /api/state` | Node health, telemetry, command queue, recent events |
| `GET /api/tracks` | Jetson-frame path histories, alignment and source/freshness status |
| `POST /api/frame` | `{session,node,translation_m:[x,y,z],yaw_deg}`; paused operator only |
| `GET /api/camera/frame` | Authenticated latest JPEG; 503 when absent/stale |
| `GET /api/bluetooth` | Read-only discovery + verifier snapshots |
| `POST /api/claim` | `{}` → random control `session` |
| `POST /api/heartbeat` | `{session}` renews control lease |
| `POST /api/resume` | `{session}` enables proposals; does not move robots |
| `POST /api/propose` | `{session,node,action,params}` → proposal `id` |
| `POST /api/approve`, `/api/reject` | `{session,id}` |
| `POST /api/pause`, `/api/stop` | `{}`; any authenticated operator can stop |
| `POST /api/nodes/NAME/sync` | `{boot,mode,telemetry,result}` → lease, revision, optional command |

Use the supplied agent rather than polling sync manually: delivery removes a
command from its queue and agent-side lease/TTL checks are required. Telemetry
and command/event histories are bounded and memory-only. This is a controlled
step-by-step mission interface; an autonomous planner and persistent mission
database are not included.

## Verification

```sh
python3 -m unittest tests.test_mission_control tests.test_rover_wifi \
  tests.test_rover_keyboard tests.test_keyboard_control tests.test_mission_media -v
node --check mission_control/static/app.js
node --check mission_control/static/media.js
```

Tests use real HTTP/TCP loopback transports, simulated agents, a fake M5 receiver,
and the existing fake flight backend. They exercise approval-to-command flow,
authentication/role isolation, operator and device loss, duplicate agents,
expiry, stop behavior and landing-context handling. **Physical router setup,
Pi/Jetson installation, wireless range, live motors/flight and the external vision
publisher must still be verified on the team's hardware.**

## Four-view field workspace

The root dashboard now opens a screen-filling overview with four expandable views:
**Drone simulation**, **BLE signals**, **Camera / computer vision**, and **Operator
 decisions**. All use the Team-15 SAR Command Ops design. The compact toolbar
keeps Stop + land available while a view is expanded. Enter the operator/viewer
token once; it is shared only with same-origin child views and held in tab memory.
The token is never placed in a URL or persisted. Live video is not recorded;
training images are saved only by an explicit capture/label action.
`/control` retains the original coordinator view and `/trace` the phone signal view.

Install the optional simulator/vision packages in the Python environment used to
run the dashboard (Python 3.13 is verified on this Mac):

```sh
uv pip install --python .venv/bin/python -r mission_control/vision-requirements.txt
.venv/bin/python -m mission_control.server --port 8093
```

The existing `mission_control.trace` command also serves the workspace at `/`.
Use `--runtime-python /path/to/python` on either server when the detector and
numpy live in a separate environment. The simulator starts on demand in its own
loopback-only child process; its controls never dispatch hardware commands. The
role-based fleet implementation is imported from `GavinPrescott-sim-roles`
(commit `159c678`) into `team15_starter`.

In Live vision, **Start this camera** requests browser camera access and sends
JPEG frames to this authenticated local server. **Use host / Pi feed** runs
inference on the camera feed already provided by `--pi-camera` or an existing
browser publisher. Selecting the host source explicitly replaces a browser
publisher and opens the server’s built-in or USB webcam (index 0), unless a Pi
camera process already owns the feed. Stop vision releases a host webcam opened
this way.
The Pi feed must be configured with --pi-camera; no camera frames are fabricated. Browser camera access requires localhost or HTTPS.
**Stop vision** releases this view's browser camera and stops inference.
The camera preview is independent of inference: the host camera targets 30 FPS,
and the browser displays raw frames without waiting for detection. The browser
interpolates the latest bounding boxes, fades them after 400 ms, and expires them
after 900 ms. Video FPS and detection FPS are shown separately. This overlay is
an estimate between computed observations; it does not claim inference on every
video frame. Duplicate JPEGs are skipped with conditional requests.

Fast mode uses COCO-pretrained SSDLite320 MobileNetV3; Detailed uses the existing
Faster R-CNN ResNet-50 FPN v2. Both retain person and cellphone categories at score
≥0.6. Phone boxes are visual candidates and are not associated with BLE identities.
Fast mode trades small/partial-object recall for speed: in the bench fixtures it
found 3 rather than 4 people in the street image, while both found 2 people in
the second image and no people in the dog image. Weights use torchvision's cache.
The [SSDLite model documentation](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.detection.ssdlite320_mobilenet_v3_large.html)
describes the base model. No camera observations create approved robot actions.

### Teach Crazyflie / RoverC

Open Live vision → Teach Crazyflie / RoverC. Freeze an image, draw a tight box
for every visible selected robot, and save it. Images remain local under
`~/.local/share/team15/vision-training`, outside Git, with private file permissions.
Save empty scenes as background examples to reduce false positives. Collect
at least 20 labeled frames of each robot you want to train, with at least two
capture sessions after changing the angle/background. A class can be trained
alone; untrained robot classes remain disabled.

Train robot detector starts a local SSDLite fine-tuning job. Complete capture
sessions are held out, so adjacent frames from one burst do not appear in both
training and validation. Activation requires at least five held-out examples per
selected class and ≥80% precision and recall at IoU 0.5 and score 0.6. A rejected
candidate is retained for inspection; it does not replace the validated model.
These thresholds are a small bench acceptance gate, not flight validation.

To run training directly:

```sh
.venv/bin/python -m perception.train --classes drone --epochs 20 --activate
```

The active checkpoint is `robots.pt`; candidate weights and `progress.json` stay
in the same local training folder. Live inference reloads a validated checkpoint
when its modification time changes. Person/phone detection remains in the base
model; the custom model adds only the hardware classes that passed validation.

The BLE view uses a full-width 30-second RSSI plot with a tight automatic scale.
Receiver details open as a drawer instead of occupying a permanent side column.
Dashboard access, ESP32 scanning and selected-beacon reception remain separate.

The animation follows the supplied demo script, with coordinates in inches:
Jetson BLE cue → drone takeoff/search/identity log → drone home and handoff →
rover camera approach → 360° inspection → rover home → operator report.
The four-minute script plays at 8× by default and can be paused, scrubbed, or
stepped by stage. Drone flight is limited to two minutes in the scripted timeline,
with the 2:30 hard-return rule shown; the low-battery case returns earlier.

Cases cover human injured, human safe, no human with a visible phone, no human
and no phone, an obstructed view, and low battery. Reports use colored condition
indicators and stop for operator choices: search another spot, swap battery and
relaunch, or end. Phone-only permits releasing both vehicles; no-phone permits
only the drone. Those choices change the animation only. Live RSSI is independent;
map positions, example RSSI, vision, phone check-in and reports are illustrative.
No robot commands, phone messages or reports are transmitted. Reduced-motion
preferences start playback paused.

Drag the dividers in Overview to change the width and height of all four views.
In BLE, drag the divider between the graph and animation. Dividers accept arrow
keys (Shift for larger changes) and double-click to reset. Percentages are saved
locally in this browser; no credentials or feed data are stored with them.
**Reset layout** restores the default splits and panel sizes. Receiver, vision
and simulator detail panels have a corner resize grip; decision cards can be
resized vertically. On narrow screens, overview cards resize vertically.

The Mission view opens the scripted animation at full size. **Show graph** adds
a resizable live RSSI region; **Hide graph** gives that space back to the map.
The report/notes overlay also has a corner resize grip. Hidden workspace views
pause their animation timelines. The previous fleet simulator remains at
`/simulation/` for separate software experiments.

The Decisions view opens an operator exercise with seven synthetic scenarios
and fourteen decisions drawn from the demo script. A resizable visual sits
beside the evidence and response options. Answers explain consequences, allow
retries, and count first-attempt successes separately. Progress stays in this
tab. Scenario choice, random case, review visual, reset and next-question
controls are local to the exercise; they send no robot commands or reports.
**Practice decision** in Mission/BLE selects the matching case. **Live controls**
opens the existing authenticated control workflow in a separate embedded view.

**How it works** (`/#about`, standalone `/about`) explains the project with
an interactive system diagram, radio/vision/planning/control filters, device
inputs and outputs, the mission sequence, technologies, and team roles. It
distinguishes prototype software, simulated behavior, and the deployment
roadmap from the CMF brief. This view needs no token and starts no devices.

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
Start that service as documented in [discovery/README.md](../discovery/README.md),
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

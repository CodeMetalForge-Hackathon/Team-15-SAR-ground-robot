# Passive BLE discovery

A local dashboard backed by actual ESP32 USB advertisements, independent of
the authenticated beacon verifier. No iPhone app, internet connection, Python
packages, or mission dashboard is required. macOS/Linux host with Python 3.10+.

From the repository root, with the flashed ESP32 connected:

```sh
python3 -m discovery.server --serial /dev/cu.usbmodem2101
```

Open <http://127.0.0.1:8765>. Change `--serial` if the USB device name changes;
use `--port 8766` if needed. Close Arduino Serial Monitor and other serial
readers first. One process owns the receiver at a time. Stop with Ctrl+C.
The server binds only to loopback and reconnects when USB returns at the same
device path. A stopped receiver/heartbeat or unreachable server is visibly
reported; previously heard entries remain historical until expiry.

## What the page shows

- All BLE advertisements the receiver hears, including those without a service UUID.
- Temporary session labels, latest RSSI in dBm, advertisement counts and host reception age.
- A 30-second history sampled at most twice per second, with gaps when unheard.
- Stale fading after 5 seconds; removal after 60 seconds; at most 256 entries.
- Filters for all signals, recently heard signals and possible Apple devices.
- Optional browser camera preview, enabled by the operator; no recording,
  computer vision, bounding boxes, or radio-to-camera association.

Apple classification checks manufacturer AD type `0xFF` for little-endian
company ID `0x004C`. This is a spoofable hint, not brand authentication or an
iPhone classifier. Names are also untrusted advertisement contents. RSSI is
not distance, bearing, coordinates, or identity. This view creates no rescue
observations or routes. Multiple addresses may belong to one device, and
multiple devices may share an address. Absence of signals does not establish
absence of devices or people.

Only session-keyed address hashes reach the API; raw addresses and payloads
are not retained in discovery state or written to disk. Advertised names may
contain personal information and are displayed locally in memory. Session
labels reset on server restart or entry expiry. Counts represent processed
reports, not a measurement of all packets over the air.

## Firmware

The existing scanner remains passive (`setActiveScan(false)`), with no
connections, advertising or Wi-Fi initialization. It emits a separate channel:

```text
#BLE,<rssi>,<address>,<address_type>,<payload_hex>
```

Existing beacon CSV and `#RAW` lines remain unchanged. Heartbeats append
`,passive=1,discovery=1`; the host requires a fresh heartbeat before accepting
discovery data. The two-second startup drain discards queued observations.
Radio passivity is established here by code/configuration, not an independent
over-the-air sniffer measurement.

Build and flash the connected ESP32-C5 (Arduino CLI, installed ESP32 core and
NimBLE-Arduino 2.x required):

```sh
arduino-cli compile --fqbn esp32:esp32:esp32c5:CDCOnBoot=cdc --output-dir /tmp/team15-discovery-build firmware/esp32_scanner
arduino-cli upload --fqbn esp32:esp32:esp32c5:CDCOnBoot=cdc --port /dev/cu.usbmodem2101 --input-dir /tmp/team15-discovery-build firmware/esp32_scanner
```

Stop the discovery server before flashing or running C1 captures. To switch
back to authenticated-beacon experiments, stop this server and use the C1
capture tools; they ignore comment-prefixed discovery records.

## Verification

```sh
python3 -m unittest discover -s tests -p test_discovery.py -v
node --check discovery/static/app.js
```

The tests exercise AD parsing, malformed input, session privacy, bounded
history, expiry, missing heartbeats, HTTP serving and a real pseudo-terminal
reader including fragmentation and disconnect. Test advertisements are
synthetic fixtures only and never used by the dashboard runtime.

## Authenticated beacon verification (optional, C3)

The same single serial reader can also verify BLE-ID tokens. Verification is off
unless you choose keys explicitly. Close any other server using the port first.

```sh
# Labelled experiment with the PUBLIC SYNTHETIC TEST KEYS (C1 iPhone app):
python3 -m ble_id init-state --state ~/olf-testkey-state.json --scope TESTKEY-bench   # once
python3 -m discovery.server --serial /dev/cu.usbmodem2101 \
  --test-keys --state ~/olf-testkey-state.json --scope TESTKEY-bench

# Production: keys.json (chmod 600, {"format": "olf-ble-id-keys/1", "scope": ..., "keys": {...}}).
# Published synthetic keys are refused. Each mission gets its own state:
python3 -m ble_id init-state --state ~/olf-MISSION-state.json --scope MISSION-NAME   # once
python3 -m discovery.server --serial /dev/cu.usbmodem2101 \
  --keys ~/olf-keys.json --state ~/olf-MISSION-state.json --scope MISSION-NAME

# Software-only demo (SIMULATED, private pseudo-terminal, never opens hardware):
python3 -m ble_sim serve --port 8766
```

The page's **Verified beacons** panel lists only tokens that passed the
signature, window and replay checks and whose state was saved first. Replay,
forged, unknown and malformed rows stay in the diagnostics drawer. A verified
beacon isn't a location, a distance, or proof that a person is present.
Missing, corrupt or wrong-scope state, a second process on the same state file,
bad keys, an unset host clock, or a failed save stop verification visibly.
Tests: `python3 -m pytest tests`. Evidence: `docs/ble-id/runs/c3-20261107T205707Z/`.

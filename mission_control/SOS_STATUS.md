# Phone SOS tag

Open OLF C1 → **Start beacon**, then turn **SOS** on. The ESP32
passively receives the signed service UUID; `/trace` shows **SOS ACTIVE** for
the enrolled alias. Turn it off to send signed Normal status. Keep the app open.
The phone saves SOS across app restarts; Start is always manual.
The main screen shows broadcasting status, SOS and Start/Stop. The gear button
opens technical details, test modes, UUIDs, counters and logs. Stopping or
backgrounding the app stops transmission, without clearing the saved SOS.

This is a local prototype using the app's visibly labelled **public synthetic
test key**. It does not call emergency services, send messages, or command robots.
Normal means the SOS flag was cleared, not proof that someone is safe. Bluetooth
reception supplies neither a geographic position nor proof of physical presence.

## Apple Watch

The companion watch app can set/clear the paired phone’s SOS tag using a live,
acknowledged connection. See [watch setup](../ios/BeaconC1/WATCH.md). The phone
remains the BLE transmitter and must be open and broadcasting.

## Receiver setup

Use the existing v1 enrollment arguments plus a **separate** v2 replay-state file.
Initialize only once for a new mission, never reset an existing replay state:

```sh
python3 -m ble_id init-state --state ~/phone-sos-v2.json --scope TESTKEY-phone-trace:SOSv2
python3 -m mission_control.trace --serial /dev/cu.usbmodem101 --host 0.0.0.0 \
  --test-keys --state ~/phone-trace-state.json --scope TESTKEY-phone-trace \
  --sos-state ~/phone-sos-v2.json
```

The existing v1 state must already exist as described in [PHONE_TRACE.md](PHONE_TRACE.md).
Production `--keys` uses the same `--scope` plus `:SOSv2` for its independent v2
state. No ESP32 firmware update is needed. The trace API adds `sos` with signed
sightings; v2 `trace_signals` retain the same enrolled alias ID across rotations.

The receiver persists replay state before publishing status. Repeated packets
only refresh RF activity. Replayed status, a tampered flag, an old Normal tag,
or a v1 tag cannot clear a newer SOS. A signed newer Normal update clears it.
Receiver failure or authentication age over 70 seconds marks status stale;
SOS remains **SOS · LAST KNOWN**. UI connection loss also retains a cached alert.
On verifier restart, status is unknown until a fresh, newer token is received;
replay high-water state survives, but last-known status is not restored from disk.

## Wire format v2

One 16-byte service UUID, with no advertised local name or extra BLE data:

| Bytes | Field |
| --- | --- |
| 0 | Version `0x02` |
| 1 | Enrolled alias `1..255` |
| 2–5 | Big endian `(window << 5) \| (revision << 1) \| sos` |
| 6–15 | First 10 bytes of HMAC-SHA256(key, `OLF/BLE-STATUS/v2` + bytes 0–5) |

`window = floor(unix_seconds / 30)` uses 27 bits; revision uses 4 bits;
SOS uses 1 bit. The receiver accepts only current/adjacent windows and strictly
increasing `(window << 4) | revision` per alias. The phone durably allocates a
revision before advertising, including set/clear, Start and each rotation.
After 16 allocations in a window, wait for the next window. Clock rollback,
corrupt sender state or uncertain writes withhold new status rather than reusing
an order. Receiver missing/corrupt/wrong-scope state fails closed. Existing v1
format, domain and frozen vectors are unchanged. Public test keys, real-time
relays, and malicious rollback/deletion of state remain outside identity proof.

Reference key bytes `00..1f`, alias 1, window 59802572:

| Revision | Status | UUID |
| --- | --- | --- |
| 0 | Normal | `02017210-7980-93FF-D776-54EF38E8C8ED` |
| 1 | SOS | `02017210-7983-424B-3137-DC7C1ED5AA69` |
| 2 | Normal | `02017210-7984-03AC-DD8C-F2D2CF388A19` |

## Verification

```sh
python3 -m unittest tests.test_sos_status tests.test_phone_trace \
  tests.test_mission_control tests.test_mission_media -q
swiftc ios/BeaconC1/BeaconC1/Token.swift ios/BeaconC1/BeaconC1/SOSState.swift \
  ios/BeaconC1/tests/SOSChecks.swift -o /tmp/olf-sos-check
/tmp/olf-sos-check
node --check mission_control/static/trace.js
```

The native iOS build also validates the SwiftUI toggle and CoreBluetooth sender.
Tests cover signed set/clear ordering, duplicate handling, flag tampering,
stale/future tokens, disk failures, receiver loss, replay across restarts, v1/v2
isolation and Swift/Python reference vectors. Hardware reception must be checked
separately with the phone foregrounded and the ESP32 connected.

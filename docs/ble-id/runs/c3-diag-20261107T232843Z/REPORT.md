# C3 debug: why the live iPhone → browser check showed no verified card

Run: `c3-diag-20261107T232843Z` · November 7, 2026 · native macOS 26.1, ESP32-C5 on `/dev/cu.usbmodem2101`
Evidence kind: **REAL HARDWARE** (iPhone 14 Pro, OLF C1 app on Rotating with **PUBLIC SYNTHETIC TEST KEYS**) → passive ESP32 → serial. No dashboard was involved.

## Question

The live run `c3-native-20261107T215002Z` scanned about 25 advertisements per
second for 120 s, but saw **no** OLF token, and nothing was verified. That
report gave the cause as "the app was not broadcasting", without evidence. Is
the token on the air at all, and does the firmware report it?

## What we tried

`python3.13 -B tools/c3/diag_reception.py /dev/cu.usbmodem2101 docs/ble-id/runs/c3-diag-20261107T232843Z 60` (commit `7cf7e97`).

The tool reads the receiver directly for 60 s, with the dashboard stopped. It
looks for OLF v1 tokens in three places: the raw `#BLE` advertisements (128-bit
UUID fields), the `rssi,name,uuid` rows, and the `#RAW` rows. It checks each
tag with the public test key. It stores no device addresses or other devices'
payloads.

## What happened

| Measure | Value |
| --- | --- |
| Serial lines / heartbeats (all with discovery fields) | 4,920 / 59 |
| BLE advertisements reported | 2,750 |
| OLF tokens in raw advertisements | 1,056 |
| OLF tokens in `rssi,name,uuid` rows | 1,056 (one row for every raw OLF advert) |
| OLF tokens in `#RAW` rows | 1,055 |
| Distinct tokens (30 s windows) | 3 (`59803137`–`59803139`) |
| Single-shot HMAC check with the test key | 2,112 of 2,112 valid (`verified:fresh`) |
| RSSI of the first tokens | −96 / −97 dBm (proximity hint only) |
| **Verdict** | **RECEPTION OK**: the iPhone token is on the air, and the firmware reports it on every channel the verifier uses |

## What this establishes

- **Receiver, firmware and row format:** these are not the cause. Firmware rows
  match the verifier's expected format, heartbeats carry the required discovery
  fields, and RSSI is within range.
- **The failed run's cause:** in run `215002Z`, no OLF advertisement was on
  the air during the 120 s capture. The app stops advertising whenever iOS
  backgrounds it, including on screen lock. The likely cause is the screen
  locking or the app being backgrounded; this is consistent with the data, but
  not observed directly.
- **Corroborating, but outside the recorded window:** the replay state for
  scope `TESTKEY-bench-c3-native-20261107T215002Z` later held alias 1, counter
  `59802973`. That is the window starting 22:06:30 UTC, about 16 minutes after
  that capture started at 21:50:24 UTC. So that run's dashboard stayed up after
  its capture and verified a genuine live token once the phone advertised. It
  isn't counted as proof, because no capture or browser record covers it.

## Problems found while debugging

1. **The native check exited silently.** In run `c3-native-20261107T233154Z`,
   the script stopped after printing the Python version, with no message. The
   cause was `set -e` (added in `6a1a860`) together with
   `cat "$E/wheels.log" 2>/dev/null`: that file exists only when wheels are
   fetched. Fixed in `5efcb5b`, which also gives the pytest and unittest steps
   explicit exit-code messages. That run's partial folder is kept as evidence.
2. **A committed evidence file was rewritten after the fact.** In the working
   tree, `c3-native-20261107T215002Z/summary.txt` (committed in `f4208d4`)
   changed at 23:27:55 UTC: `replay state on disk: {}` and the FAIL line were
   replaced with `{1: 59802973}`. This session didn't make that change, and it
   is **not committed**. The committed version is the record of that run.
   Restore it with `git checkout -- docs/ble-id/runs/c3-native-20261107T215002Z/summary.txt`,
   or keep the new reading as a separate, dated note. Don't overwrite the
   original.

## Still open

- The live iPhone → ESP32 → verifier → **browser** check with a recorded
  capture is still **UNTESTED**. Next step: `bash ~/Team-15/tools/c3/native_macos_check.sh`
  with the phone screen on (Auto-Lock off) and the app on Rotating.
- C1 video review and shared mission integration remain **PENDING**.

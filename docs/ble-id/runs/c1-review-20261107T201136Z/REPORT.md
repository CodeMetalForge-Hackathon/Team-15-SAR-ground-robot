# C1 progress: built, installed, and scanner flashed; beacon proof pending

Run: `c1-review-20261107T201136Z` · November 7, 2026 · Mac bench
Source commit: `8c514f9` on `culubo/sensor-id-specs`.

**C1 IS INCOMPLETE.** The ESP32 scanner is running. The app is installed on the
iPhone, but iOS has not permitted launch. No phone beacon reception, rotation,
or proof video has been demonstrated in this run.

## What changed?

We built the supplied C1 prototype and repaired the runner and evidence checks.
The runner now requires an explicit board/port, pins dependencies, stops on
failures, and uploads the binary that was just built. Serial capture uses a
bounded Python process instead of background shell pipelines. The scanner emits
heartbeats, so an empty capture cannot masquerade as a successful stopped-app
control. The analyzer requires complete capture durations, scanner activity,
structured raw service-UUID bytes, and three successive tokens observed in their
own host time windows. A failed analysis exits nonzero.

The phone app refuses to start if its reference self-check fails, keeps the
display awake during advertising, and stops explicitly when backgrounded. This
C1 app tests foreground transport only; it does not test background support.

## What did we actually test?

| Check | Expected | Observed | Status |
| --- | --- | --- | --- |
| Analyzer and serial tooling, synthetic data/pseudo-terminal | Reject bad evidence and pass known fixtures | 12 tests passed | PASSED, SOFTWARE ONLY |
| CryptoKit reference calculation on Mac | Match fixed A1 payload | Self-check PASS | PASSED, SOFTWARE ONLY |
| iPhone app compilation/signing | Build successfully for connected phone | Build succeeded | PASSED, BUILD ONLY |
| App installation | Install on actual iPhone | Installed as OLF C1 | PASSED, REAL DEVICE |
| App launch | Open and request Bluetooth permission | iOS reports profile must be trusted or signature/entitlements invalid | BLOCKED; trust step requested |
| Firmware compilation | Build for C5 with USB CDC | 751,965 program bytes; 27,472 global-data bytes | PASSED, BUILD ONLY |
| Firmware upload | Write and verify flash | Upload succeeded; tool verified written-data hash | PASSED, REAL HARDWARE |
| Scanner smoke check | Live scanning heartbeat | Four `scanning=1` heartbeats during a 5-second capture | PASSED, REAL HARDWARE; configuration-level evidence only |
| App stopped/static/rotating captures | 30/60/120 seconds with required observations | Not run | UNTESTED |
| Physical proof video | Playable view of phone, Mac, and board | Not recorded | UNTESTED |

The software tests include tampered tags, beacon detected during the stopped
control, empty/truncated captures, stopped scanner, malformed input, UUID bytes
hidden in manufacturer data, cached counter batches, and nonzero failure exits.
The pseudo-terminal tests exercise timeout and occupied-port handling, not BLE.
No reception latency, discovery rate, radio range, or battery life was measured.

## Environment and failures

- User changed the board from an S3 to a C5 during this run. Chip identification
  confirms ESP32-C5 rev 1.0, USB Serial/JTAG, 48 MHz crystal, and 8 MB flash.
  We used generic `esp32:esp32:esp32c5:CDCOnBoot=cdc`, with its default 4 MB
  partition layout on the 8 MB device. No board-specific pins are used.
- Arduino CLI 1.5.1, existing ESP32 core 3.3.11; installed approved dependency
  NimBLE-Arduino at exactly 2.5.1. Xcode 26.3, build 17C529.
- Connected iPhone 14 Pro, iOS 26.0 build 23A5326a. Developer Mode changed from
  disabled to enabled during the run. Existing local signing identity was used;
  no credentials were requested or written into source.
- Initial generic signed build succeeded, but installation failed because its
  provisioning profile did not include this phone. A device-specific build
  registered the destination and installation then succeeded. Launch still fails;
  the requested manual developer-profile trust step has not been confirmed.
- A diagnostic using Homebrew Python's `plistlib` failed due to a local expat
  library mismatch. A following build attempt had an empty destination and
  failed before compiling. System Python handled profile inspection successfully.
  Neither failed diagnostic is counted as a successful check.

## Where is the proof?

- [Manifest, source hashes, tool versions and binary hashes](manifest.json)
- [12 software tests](software-tests.log)
- [CryptoKit reference self-check](swift-token-check.log)
- [Final iOS build](ios-build-final.log), [installation](ios-install-final.log),
  [launch failure](ios-launch-final.log)
- [C5 firmware build](firmware-build-c5.log), [upload](firmware-upload.log)
- [Chip identification](chip-identification.log), [flash size](flash-identification.log)
- [Actual scanner heartbeat capture](scanner-smoke.tsv)

Committed build/device logs have personal identifiers masked and trailing
whitespace normalized. Unmodified log
copies remain locally under `_c1_media/c1-review-20261107T201136Z/original-logs/`,
outside Git. No video exists yet. Firmware/app build products remain in `/tmp`;
source and compile commands permit rebuilding them.

## Reproduce the completed checks

From the repository root:

```sh
python3 -B -m unittest discover -s tools/c1 -p 'test_*.py' -v
bash -n tools/c1/run_c1.sh tools/c1/capture_serial.sh
"/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" \
  compile --fqbn esp32:esp32:esp32c5:CDCOnBoot=cdc \
  --output-dir /tmp/ble-c1-c5-firmware firmware/esp32_scanner
xcodebuild -project ios/BeaconC1/BeaconC1.xcodeproj -scheme BeaconC1 \
  -sdk iphoneos -configuration Debug -derivedDataPath /tmp/ble-c1-build \
  CODE_SIGNING_ALLOWED=NO build
```

Signing for a physical phone additionally needs the existing Xcode team and a
device-specific destination. Do not copy masked identifiers from these logs.
The full runner requires explicit `FQBN`, `PORT`, and `DEVELOPMENT_TEAM` variables;
it flashes hardware unless `BUILD_ONLY=1` is supplied. Do not rerun the upload
just to collect serial data.

## Next step

On the phone, trust the app's development profile in Settings > General > VPN &
Device Management, open OLF C1, allow Bluetooth, and leave it stopped. Confirm
whether a second phone/camera is available. Then collect the stopped, static, and
rotating trials with video and run the analyzer. Until that happens C1 remains
incomplete. This work does not authorize or implement C2/dashboard integration.

# Passive discovery validation — November 7, 2026

Implemented and run locally on the connected ESP32-C5 using
`esp32:esp32:esp32c5:CDCOnBoot=cdc`, ESP32 core 3.3.11 and NimBLE-Arduino 2.x.

- Arduino CLI compilation passed: 752,627 bytes program, 27,472 bytes global RAM.
- Upload to `/dev/cu.usbmodem2101` passed; esptool verified flashed hashes.
- Live API smoke check: `source=LIVE-HW`, `mode=passive`, `status=scanning`,
  253 processed advertisements, 19 retained signal entries, 80 history points,
  zero malformed advertisements. These are one snapshot's counts, not distinct
  physical-device counts or proof of any specific iPhone.
- Browser displayed the live receiver state, growing packet counts, RSSI plots
  and stale entries. The possible-Apple filter and return to all signals worked.
- Eight discovery unit/integration tests passed, including pseudo-terminal input
  fragmentation and disconnect; JavaScript syntax check passed.

The camera is intentionally off by default. Camera capture permission and live
camera preview have not been exercised during this validation. No camera object
detection is implemented. No independent RF sniffer verification was performed.
No specific nearby device was identified or associated with an owner. This is a
standalone discovery page, not a change to the team's mission dashboard branch.

Start/restart instructions and limitations: [discovery/README.md](../../discovery/README.md).

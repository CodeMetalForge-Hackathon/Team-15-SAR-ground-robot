# C1 results: real foreground BLE reception; video review pending

Run: `c1-capture-20261107T202438Z` · November 7, 2026 · Mac bench

**The capture checks passed on the rotating retry. C1 is not fully complete:
the physical video has not yet been received, played, or reviewed.**

## What can we now show?

A real iPhone advertised our exact reference UUID, and the ESP32-C5 received it
intact. In rotating mode, the scanner received five consecutive time counters;
the host independently recomputed matching HMAC tags with the public synthetic
test key. This establishes foreground carrier feasibility for this configuration.
It is not production enrollment, replay protection, rescue localization, or
interference-resilience evidence.

The user operated the phone and confirmed a second camera was available. The
user signaled filming start and the static/rotating phone actions in chat. The
Mac displayed the actual live console. Filming and phone-state provenance still
need confirmation from the original video; neither has been inferred from logs.

## Expected versus observed

All three stages below used actual hardware. A/B are original successful trials;
C is the successful retry. The first C attempt remains separate and failed.

| Stage | Acceptance target | Measured result | Capture result |
| --- | --- | --- | --- |
| A: app stopped | 30 s, active scanner, zero test UUIDs | 30.004556 s; 29 heartbeats; zero test-beacon rows | PASS |
| B: Static A1 | 60 s; exact reference UUID and matching raw AD bytes | 60.000782 s; 1,665 exact A1 rows and 1,665 matching raw AD rows | PASS |
| C: Rotating, retry | 120 s; at least three consecutive fresh counters, correct tags and raw AD bytes | 120.000709 s; 3,273 rows; five consecutive counters; zero invalid tags | PASS |

Successful stages have zero malformed lines and zero scanner-error diagnostics.
Rotating analysis counted 3,266 rows received in their exact current host window
with matching raw service data; seven boundary rows fell in the adjacent window
allowed by the existing freshness check. Those seven are not needed to establish
the five-counter sequence.

RSSI, a proximity hint only: static min/median/max = -99/-80/-76 dBm; rotating
= -99/-86/-74 dBm. Distances and orientations were not measured, so these values
do not establish range or distance accuracy. Reception rows are not independently
counted transmissions; no delivery ratio is reported. Start-to-first-reception
latency was not measured because phone taps preceded capture by an unknown delay.

## Failed attempt, diagnosis, and revised collection procedure

The first C trial lasted 120.004265 seconds and received 3,284 test-beacon rows.
It included five consecutive current counters with valid tags, but also two old
static A1 rows and two malformed fragments at startup. The old rows arrived
within 0.5 ms of capture start. The unchanged analyzer rejected the attempt.

This is consistent with buffered USB/device output and opening a stream between
line boundaries. A host input flush had not removed the device-side backlog.
The raw data is preserved; no startup rows were removed from that attempt.

Before the retry, source commit `1582429` added an explicitly declared two-second
startup drain and line alignment. Every byte read during this drain is saved in
`capture_C_rotating.tsv.warmup.txt`. The full graded 120 seconds start afterward.
The acceptance criteria and analyzer were unchanged. The 12 software tests passed
again, including the capture tests against a synthetic pseudo-terminal. Those
tests are software evidence, not additional radio trials.

The original stopped and static captures used the earlier acquisition code and
already passed without this drain. This report does not pretend all captures
were collected with the same source revision.

## Proof and reproduction

- [Final analyzer result](c1_analysis.json) and [command output](analysis_final.log)
- [Measurements JSON, including per-counter counts and first/last timestamps](metrics.json)
- [Measurements CSV](metrics.csv)
- Raw capture [A: stopped](capture_A_stopped.tsv), [B: static](capture_B_static.tsv),
  [C: rotating retry](capture_C_rotating.tsv)
- [Retry startup drain, retained separately](capture_C_rotating.tsv.warmup.txt)
- [Failed first rotating capture](attempt1_capture_C_rotating.tsv),
  [failed analyzer result](attempt1_c1_analysis.json), [output](analysis_attempt1.log)
- [Unfilmed preliminary stopped control](preflight_A_unfilmed.tsv), excluded from
  the formal A/B/C result table
- [12 software tests after collection fix](software-tests-retry.log)
- [Live console shown for filming](live-console.log)
- [Manifest, source revisions, and artifact checksums](manifest.json)
- [Earlier app/firmware builds and verified flash upload](../c1-review-20261107T201136Z/REPORT.md)

From the repository root, reproduce grading without hardware:

```sh
python3 -B tools/c1/analyze_c1.py docs/ble-id/runs/c1-capture-20261107T202438Z
python3 -B -m unittest discover -s tools/c1 -p 'test_*.py' -v
```

The first command writes a new analysis JSON from the retained raw captures and
returns zero for this final result. To reproduce the failed trial, use a separate
temporary directory with the same A/B files and the `attempt1_` C file renamed
to `capture_C_rotating.tsv`; do not overwrite the retained evidence.

## Configuration and remaining limits

- iPhone 14 Pro, iOS 26.0 build 23A5326a; foreground C1 app with explicit static
  and rotating modes, using the public alias-1 synthetic key.
- ESP32-C5 rev 1.0, 8 MB detected flash. Generic C5 target with USB CDC and
  default 4 MB partition layout. NimBLE-Arduino 2.5.1, ESP32 core 3.3.11.
- Passive scanning configured, 100 ms scan window and interval, duplicates
  enabled. No independent RF sniffer checked receiver transmissions.
- App/firmware and original capture code: `8c514f9`; retry capture code:
  `1582429`. The manifest records the exact source commit for each capture.
- One bench configuration; no C4 distance/discovery/lifecycle experiments, no
  production keys, no pure C2 replay verifier, and no shared-dashboard posting.
- The phone's developer profile was trusted by the user. Native app launch
  succeeded after that action. Bluetooth permission and UI actions were performed
  by the user; original video review is still pending.

## Next step

Locate the original proof video on the Mac, verify playback and coverage of the
three stages plus the failed attempt/retry, record timestamps and its SHA-256,
and link the playable artifact. Until then the video gate is PENDING. Keep the
second specification and C2/dashboard implementation on hold.

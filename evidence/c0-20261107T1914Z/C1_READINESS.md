# C1 readiness checklist

Status as of 2026-11-07 19:50 UTC. **C1 not started and not authorized.**
Nothing was installed, flashed, or connected.

How this was checked: the only shell available is a Linux VM on your computer.
It can see your Team-15 folder but **not** your Mac's real USB devices,
`/Applications`, Xcode, or a connected iPhone. Its USB list shows only Apple
virtual devices. Every hardware and tooling item below is therefore
**MISSING (unverified)** until you confirm it. Each row gives a read-only
command to run on the Mac (Terminal) or a place to look.

Legend: **READY** = verified · **MISSING** = not verified or not present ·
**BLOCKED** = waiting on someone else's decision.

## Hardware and tools

| # | Item | What C1 needs | Status | How to verify (read-only) |
| --- | --- | --- | --- | --- |
| 1 | ESP32 board | BLE-capable ESP32 (C3/S3/C6 class); exact model and chip | **MISSING**. The build plan lists two Seeed boards of unknown type; nothing identified | Read the silkscreen; plug it in, then `system_profiler SPUSBDataType \| grep -A8 -i -E "espressif\|seeed\|cp210\|ch34\|usb jtag"` and `ls /dev/cu.*` |
| 2 | USB data cable | Data, not charge-only | **MISSING** | The board appears in `ls /dev/cu.*` when plugged in |
| 3 | iPhone model | Exact model | **MISSING** | Settings > General > About > Model Name |
| 4 | iOS version | Exact version and build | **MISSING** | Settings > General > About > iOS Version |
| 5 | Developer Mode on the iPhone | Required to run a locally signed app (iOS 16+) | **MISSING** | Settings > Privacy & Security > Developer Mode |
| 6 | Xcode on the Mac | Installed, version recorded | **MISSING** | `xcodebuild -version` and `xcode-select -p` |
| 7 | Signing access | An Apple ID / team in Xcode able to sign for this iPhone (a free personal team works for local testing; apps expire after 7 days) | **MISSING** | Xcode > Settings > Accounts shows the account and a team |
| 8 | iPhone visible to Xcode | Paired and trusted | **MISSING** | `xcrun devicectl list devices` (Xcode 15+) |
| 9 | Mac model and macOS | Record in evidence | **MISSING** | `sw_vers` and `system_profiler SPHardwareDataType \| grep -E "Model\|Chip\|Memory"` |
| 10 | Arduino toolchain | `arduino-cli`, ESP32 core, NimBLE-Arduino, all at pinned versions, downloaded before going offline | **MISSING**. Not installed, and not to be installed until C1 is authorized | `arduino-cli version` (expected: not found) |
| 11 | Python + pyserial for the raw capture | Python 3.11 to match CI; `pyserial` | **MISSING** on the Mac (VM has 3.10.12, no pyserial) | `python3 --version`; `python3 -c "import serial"` |

## Filming and measurement setup

| # | Item | What C1 needs | Status | Notes |
| --- | --- | --- | --- | --- |
| 12 | Second phone or camera | Films the iPhone screen and the host display in one frame, ≥30 fps | **MISSING** | Required for the feasibility video |
| 13 | Screen recording on the Mac | Built in (Cmd-Shift-5); no install needed | **MISSING** (untested) | Check there's free disk space for the original clips |
| 14 | Video storage outside Git | A durable link location plus SHA-256 for each clip | **MISSING** | The spec keeps large videos out of Git |
| 15 | Bench layout | Phone and ESP32 at a tape-measured 1 m, line of sight | **MISSING** | Tape measure and masking tape; C1 itself needs only close range |
| 16 | Clocks | Mac and iPhone set to automatic time before going offline | **MISSING** | Token counters depend on both clocks being roughly right |

## Decisions and prerequisites from other people

| # | Item | Status | Blocks |
| --- | --- | --- | --- |
| 17 | BLE ownership: Teammate D's Pi scanner, our ESP32 module, or both (question R7) | **BLOCKED**, not asked yet (draft in `OWNER_QUESTIONS.md`) | Whether C1 is worth running at all, and whether the iPhone app is shared |
| 18 | Which Seeed board, if any, is free for us | **BLOCKED** (Teammate D) | Item 1 |
| 19 | Who owns and signs the iPhone app; which phone the demo uses | **BLOCKED** (team) | Items 3 to 8 |
| 20 | Hardware time vs the build plan's 60-minute BLE box | **BLOCKED** (team) | Scope of C1 and C4 |
| 21 | Dashboard labelling of BLE (R1) | **BLOCKED** (Teammate B) | Not C1: C1 is phone-to-ESP32 only. Blocks C3 |
| 22 | Amendment 1, A1 to A7 | **PROPOSED**, awaiting your decision | Not C1. Blocks C3 |
| 23 | Your authorization to start C1 (install tools, flash, record) | **NOT GIVEN** | Everything above |

## What is already ready

- **Reference payload:** vector A1,
  UUID `01010390-83cc-c438-cfa7-043609b9d1c4`, with expected on-air bytes
  `c4d1b9093604a7cf38c4cc8390030101`.
- **Synthetic alias-1 key for the rotating stage:** in
  `protocol_vectors_v1.json`.
- **The plan:** C1 stages and pass/fail rules are in `EXPERIMENT_PLAN.md`, E1.

## Minimum to start C1

Items 1 to 8 and 10 to 13 verified, item 16 set, and items 17, 19, and 23
answered. Items 9, 14, 15, 18, and 20 should be recorded during C1, but don't
gate it.

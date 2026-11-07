# Sensor-ID: Operation Lost and Found

Status: revised specification for review. Implementation is NOT authorized yet.
This document may be handed to Claude or another coding agent. Do not create
module code, install dependencies, flash hardware, or claim tests passed until
the user explicitly authorizes implementation. No testing or video evidence has
been produced by this specification review.

C0 found that the `forge/` and `Reading` interfaces assumed below do not exist.
`SENSOR_ID_SPEC_AMENDMENT_1.md` proposes replacements (PROPOSED, not adopted);
see `evidence/c0-20261107T1914Z/REPORT.md`.

## Branch and handoff

Work on `culubo/sensor-id-specs`, the branch containing these specifications and
the user-provided `CMF .pdf`. Before editing or committing, check
`git branch --show-current` and `git status --short`. Keep checkpoint commits on
this branch; do not implement or commit directly on `main`. Creating the branch
does not authorize implementation. If a separate implementation branch is later
requested, branch from this work and record its name in the handoff.
Pushing, merging, and changing shared branch history require separate user
authorization; the current handoff is local only.

## Scope and prerequisite check

Code Metal Forge 2026 hackathon: offline search and rescue without GPS, cell
service, or infrastructure. Own only the authenticated BLE ID module. Do not
change mapping, camera/CV, drone hardware, fusion, or pipeline behavior.

At review time this checkout contains only LICENSE and Git metadata. The named
Python interfaces, dashboard, Makefile, and sensor registry are not present.
Before implementation, inspect the actual integration branch and record the
Sensor API, Reading fields and timestamp units, dashboard behavior, and existing
test baseline. Do not invent replacement infrastructure to make a demo pass.
Missing integration code is a blocker for integration acceptance.

## Goal and honest claims

Foreground iPhone app -> BLE advertisement -> passive ESP32 scanner -> USB
serial -> Python verifier -> existing Reading contract.

Authenticate possession of an enrolled secret and enforce bounded freshness.
This is authentication, NOT encryption: advertisement contents are public.
A valid token does not prove a person is alive, physically present, or carrying
the enrolled phone. HMAC cannot prevent real-time relay or use of a stolen key.
RSSI is only a proximity hint, never coordinates or a distance estimate.
Apple Watch support is outside this MVP until separately demonstrated.

## Platform feasibility gate

CoreBluetooth peripheral advertising supports local name and service UUID keys;
do not use manufacturer data or service data on iOS. Advertisement packing is
best effort. Byte arithmetic and an advertising-start callback do not prove
that an ESP32 received the complete payload.

Use one rotating 128-bit service UUID as the proposed carrier. No required local
name or second discovery UUID. Verify exact byte preservation in a raw ESP32
capture before building the complete flow. If iOS alters or hides the carrier,
report the failed experiment and propose a revision; do not silently shorten
authentication or substitute simulated reception.

Baseline support is foreground only. Apple's documented background behavior
omits the local name and places service UUIDs in an iOS-specific overflow area.
Newer OS features may affect background privileges; do not assume applicability.
Test foreground, background, screen locked, and force-quit separately on the
actual device/OS. Background/locked operation is outside the baseline support
claim. Mark unperformed experiments UNTESTED; use UNSUPPORTED only for a specific
configuration with an established limitation. If locked-phone reception
is required for the rescue use case, that requirement blocks full acceptance.

Receiver must be passive: no scan requests, connections, GATT reads, advertising,
or Wi-Fi transmissions. Set NimBLE passive scanning explicitly. A local-name
approach requiring a scan response conflicts with this receiver requirement.
The survivor phone necessarily transmits BLE; “receive only” applies to the
scanner. Runtime is offline; obtain tools/dependencies beforehand.

## Proposed wire format: version 1

Freeze this format before implementation; no “base32 or hex” alternatives.
Represent exactly 16 bytes as one 128-bit service UUID:

| Bytes | Field |
| --- | --- |
| 0 | Protocol version, exactly 0x01 |
| 1 | Public enrollment alias, 1..255; 0 reserved |
| 2..5 | Unsigned 32-bit counter, big endian |
| 6..15 | First 10 bytes (80 bits) of HMAC-SHA256 |

Counter = floor(Unix UTC seconds / 30). Both endpoints need a reasonably set
clock before going offline. No runtime NTP dependency. Reject counter overflow.
HMAC input = ASCII `OLF/BLE-ID/v1` followed by bytes 0..5, without a separator
or NUL. Each alias has a distinct random 32-byte key. This format supports at
most 255 enrolled aliases; expanding capacity requires a reviewed format change.
The alias is publicly trackable; do not claim anonymity or broadcast names/PII.

UUID textual order corresponds to these bytes in order, formatted 8-4-4-4-12 hex
digits. Account explicitly for BLE UUID byte order at the scanner boundary.
Treat it as a 128-bit CoreBluetooth UUID value; do not regenerate UUID version
or variant bits. Cross-language vectors and real captures must prove round-trip.

The proposed 80-bit tag is a prototype tradeoff to fit one UUID, not a claim of
production security. Do not reduce it further to make advertising work.
Use hmac.compare_digest for authentication tags; no token equality with `==`.
Do not log keys or commit real enrollment data. Use synthetic keys in evidence.
iOS stores its one provisioned key in Keychain using system Security APIs;
scanner/verifier provisioning uses ignored keys.json with restrictive permissions.
Never bundle the verifier's full key database into the phone app.

## Verification and replay semantics

Pure functions: make_token(key, counter, *, alias) returns the 16-byte payload;
verify(payload, keys, seen, *, now) returns a decision and proposed next state.
No I/O, hidden clock reads, or in-place state mutation in the verifier.
Decision includes internal reason and authenticated alias when available; these
are diagnostics, not additions to Reading. Sensor persists accepted state before
emitting verified. State is scoped to enrollment/mission and shared across zones
within one verifier process; independent offline verifiers have independent state.

Classification order:
1. Malformed framing/length, unsupported version, reserved alias 0, invalid
   RSSI, or unrelated BLE: drop, increment a reason counter, emit no Reading,
   and do not mutate state. Alias 0 is malformed even with a valid-looking tag.
2. Well-formed version-1 payload with an unenrolled alias: unknown.
3. Enrolled alias but invalid HMAC over header: forged, regardless of time/counter.
4. Valid HMAC but counter outside current window +/- 1: replay, reason `stale`
   (below the window) or `future` (above it).
5. Valid HMAC and acceptable window but counter <= that alias's highest accepted
   counter: replay, reason `duplicate` (equal) or `not_newer` (lower). Otherwise
   persist the new high-water mark and emit verified.

Reason labels are diagnostics for decision logs and counters, not new kinds.
Alias 0 handling and these labels were accepted by the user on 2026-11-07.

Only authenticated, fresh tokens advance state. Invalid input must not poison
replay state. Authenticated future-window acceptance can make the current window
obsolete; test and document that tradeoff. Window boundaries can permit almost
60 seconds of age, so do not claim an exact 30-second freshness guarantee.

Repeated advertisements within one window are expected. Under this strict policy
the first is verified and subsequent receptions are replay (reason duplicate),
which does not establish malicious activity. Dashboard must not erase a prior
verified observation because a duplicate arrived. Check its expiry behavior
against the 30-second rotation; if incompatible, report the integration conflict
instead of editing protected files or quietly changing replay semantics.

Persist replay state atomically across verifier restarts, using standard-library
storage. Missing state is allowed only on explicit first initialization; corrupt
or lost existing state fails closed. Document that rollback of the state store,
compromised keys, and real-time relays are outside the prototype's protection.

## Output contract and adapters

Emit Reading(sensor="ble_id", zone, t, value, kind) using forge/packet.py.
kind is verified, replay, forged, or unknown. value is finite RSSI in dBm as float.
zone is scanner configuration, default "A". t uses the existing contract's units
and is the host reception timestamp, distinct from the token counter.
Do not edit forge/packet.py, forge/fuse.py, or forge/pipeline.py.
The contract contains no person-ID field: demonstrate a verified BLE observation,
not a named person, unless existing supported integration already provides this.

ESP32 prints newline-delimited CSV `rssi,name,uuid` at 115200 baud. Name is empty
for this protocol; UUID is canonical 128-bit text, one row per advertised UUID.
Use a real CSV parser, bounded line lengths, strict validation, and separate
diagnostic output. No secrets, MAC identity, or invented RSSI for missing values.
Pin the exact board FQBN, Arduino ESP32 core, NimBLE library, scan settings, and
duplicate-filter settings. Verify token rotation is visible even with one MAC.

Create ble_id.py (Sensor adapter), ble_verify.py (pure protocol), ble_sim.py
(deterministic fixtures), firmware/esp32_scanner/esp32_scanner.ino, an actual
buildable ios/BeaconApp project with privacy strings and provisioning instructions,
and tests/test_ble_id.py. Wire only the existing get_sensors registry.
Split helpers/tests as needed; keep handwritten source files below 150 lines.
Documentation, test-vector data, generated project files, and evidence are exempt.

Python: standard library, pyserial, pytest. NimBLE-Arduino for ESP32. iOS:
SwiftUI, CoreBluetooth, CryptoKit, and system Security for Keychain. bleak remains
optional and deferred: backend-dependent passive behavior must be checked first.
Ask before adding any other dependency or changing Reading. Build tools are
development prerequisites; record versions and installation requirements.

sim mode uses a fixed-seed schedule and injected clock. live mode requires an
explicit serial device or an unambiguous supported discovery result. Missing,
ambiguous, or disconnected hardware fails visibly; NO automatic simulation
fallback. Startup and video must clearly identify SIMULATED or LIVE source.

## Required tests after implementation authorization

Run the existing baseline first. Tests must pass without attached hardware.
Use independent fixed expected vectors, including Python/Swift agreement, rather
than only testing a generator against its own verifier. Keep sleeps out of unit
tests. Include negative controls that would fail if authentication were bypassed.

| Area | Minimum evidence |
| --- | --- |
| Authentication | Valid, wrong key, altered alias/counter/tag, unknown alias |
| Freshness | Window edges, stale/future, duplicate, out-of-order, clock jumps |
| State | No poisoning, per-alias isolation, cross-zone use, restart/corruption |
| Parsing | Bad CSV/UUID, truncation, empty fields, oversized lines, nonfinite RSSI |
| Transport | Missing port, disconnect, timeout, rotation and duplicate reporting |
| Integration | Exact Reading fields, zone/time, registry, dashboard observation |
| No reception | Simulated packet loss produces no Reading; recovery resumes |

“Out of range” is not a fifth kind or a low-RSSI cutoff. A packet received with
weak RSSI is still eligible for authentication. Physical range loss means no
packet was received. Simulation of loss proves logic, not radio range.
Cover all four output kinds, including unknown, plus loss and malformed input.

## Measurement and evidence requirements

After authorization, create an evidence directory with run ID, commit plus dirty
diff, commands, UTC timestamps, environment/tool versions, exit codes, full test
logs, build logs, synthetic fixtures, raw serial capture, decision log, metrics
CSV/JSON, and a report. Link each reported number to its input and calculation.
Record failures and skipped runs. Never replace missing observations with zero.

Software experiment: at least 100 deterministic trials per classification and
loss scenario; report input counts, output confusion matrix, rejection reasons,
and p50/p95 host receive-to-decision latency using a monotonic clock. Require
100% expected classification for fixed fixtures and zero invalid verified events.
This finite result is not a measured cryptographic false-accept probability.
Report hardware, workload, sample size, warmup, and timing boundaries. Software
latency excludes radio delay and phone advertising delay; do not call it end-to-end.

Radio experiment: actual iPhone + ESP32, at least 20 timed Start-to-first-verified
trials in foreground at a recorded 1 m unobstructed setup. Proposed demo target:
at least 19/20 discoveries within 10 seconds; report every timeout and latency
distribution. Also run 60-second captures at 1 m, 3 m, and 5 m, and behind one
described obstruction where available. Record orientation, distance method,
phone/OS, board, power, scan settings, reception counts, verified windows, and
RSSI distribution. Distances describe the experiment, not inferred locations.
Do not report packet-delivery ratio without an independently known transmit count.
Report missing equipment/setup as UNTESTED; do not extrapolate to rubble.

Run separate background, locked, and force-quit captures for at least 60 seconds
each, with transitions visible. Label results by exact phone/OS and configuration.
No claims about battery life without a separate measured battery experiment.

## Mandatory proof video

Deliver playable video files plus a timestamped evidence index, not just a script,
screenshots, a generated animation, or a claim that recording would be possible.
Screen recording may use existing OS tools; do not add packages without approval.
Keep original clips; label cuts and do not conceal failed attempts.

Software clip: show run ID, source revision/dirty state, SIMULATED banner, actual
test command with exit status, fixture schedule, all four decisions, packet loss,
and a verified dashboard observation if integration is available. Link exact logs.

Hardware clip: show actual phone/ESP32, LIVE banner and selected serial device,
offline setup with BLE enabled, phone Start action, raw received payload, matching
verification, and dashboard response. Show stop/loss and recovery, token rotation,
and foreground/background/lock transitions. A filmed host display and phone can
establish timing in one frame without synchronized device clocks. A stitched
screen capture alone does not prove physical end-to-end latency.

Forged/replay injections may be software fixtures but must be visibly labeled
INJECTED. They cannot count as over-the-air tests. Do not claim receive-only RF
compliance from application logs alone; name any sniffer verification performed.
If hardware or recording capability is unavailable, deliver software evidence,
mark the missing hardware/video evidence BLOCKED or UNTESTED, and leave the
relevant acceptance gate incomplete. Never fabricate video or measurements.

## Commit checkpoints and human-readable proof

These checkpoints apply after implementation is authorized. Do not batch all
work into one final commit or save all explanations until the final handoff.
At each checkpoint: run its checks, capture evidence, commit the scoped work,
then present the checkpoint report before starting the next stage. Continue
autonomously within authorized scope when the gate passes; checkpoints do not
require repeated permission. A failed prerequisite blocks dependent work, while
independent work may continue with its own status clearly shown.

| Checkpoint | Scope and gate | Suggested commit subject |
| --- | --- | --- |
| C0 | Inspect real interfaces; record baseline commands/results, protocol vectors, and experiment plan. Missing integration remains blocked. | docs(ble-id): record baseline and acceptance plan |
| C1 | Minimal iPhone-to-passive-ESP32 carrier experiment: prove exact bytes and rotation in real captures before building the full flow. Include actual build logs and feasibility video. | feat(ble-id): validate foreground UUID transport |
| C2 | Pure verifier, independent vectors, all classifications, clock boundaries, and replay-state behavior pass software tests. | feat(ble-id): verify authenticated tokens with replay checks |
| C3 | Serial adapter, simulator, registry, and existing dashboard flow pass integration checks; missing/disconnected hardware fails visibly. | feat(ble-id): integrate explicit live and simulated sources |
| C4 | Run the prescribed radio, lifecycle, and timing experiments. Publish raw measurements and playable proof. Failed experiments are valid evidence but do not pass the gate. | test(ble-id): record measured end-to-end results |
| C5 | Reproduce software checks from a clean checkout; audit claims against evidence; deliver final proof index and remaining blockers. | docs(ble-id): publish verified results and limitations |

Commit subjects must match reality. For a failed C1 experiment, use a subject
such as `test(ble-id): record UUID transport failure`, not “validate transport.”
Do not label C1 passed without hardware; later software work cannot substitute
for its evidence. Protocol unit tests may run independently of that blocker.

Each checkpoint gets evidence/<run-id>/REPORT.md. Its first screen must answer,
in ordinary language, without requiring the reader to open code:

1. What changed, and what can the user now observe?
2. What did we actually try? Label SIMULATED, BUILD ONLY, or REAL HARDWARE.
3. What happened? State expected versus observed results, sample counts, units,
   failures/timeouts, and the acceptance target. Say “not measured” when needed.
4. Where is the proof? Link the playable clip with timestamps, raw logs/data,
   test/build commands and exit codes, and the tested source revision.
5. What does this establish, what remains unproven, and what happens next?

Use a compact expected/observed/pass-or-fail table and a short narrated or
captioned walkthrough explaining what to watch for. Explain terms on first use:
for example, “replay means this already-used ID was rejected.” Show both success
and a negative control. Do not present a terminal wall of green output as the
entire explanation. A blocked checkpoint still gets a clear report.

Keep complete originals even if the human-facing walkthrough is edited shorter.
Videos are mandatory for behavioral checkpoints C1, C3, and C4; C2 may use the
software proof clip, and C0/C5 may link prior evidence with a written audit.
A missing video leaves the relevant proof gate incomplete. C5 must link both
the final software clip and final live hardware clip required above.

Record the code commit tested and a hash of relevant uncommitted changes if any.
Prefer testing a clean code commit, then adding a separate evidence commit that
references it. The report cannot cite its own not-yet-created commit hash.
Keep logs, summaries, and artifact checksums in Git where appropriate; store
large videos outside Git and provide durable, accessible links plus SHA-256
checksums. Before declaring delivery complete, check that the videos play and
that the links work. Never stage unrelated files or real keys.

## Completion gates and handoff

Report gates separately: (1) software verified, (2) exact ESP32 and iOS builds
verified, (3) foreground hardware verified, (4) integration verified, (5) video
and measurements delivered. All applicable gates are required for full completion.
`make test` and `make sim` are acceptance commands only if supplied by the actual
integration repository; propose necessary module-only targets if absent.
Compilation does not prove radio operation; simulator footage is software proof.

README and final report must distinguish PASSED, FAILED, UNTESTED, BLOCKED,
UNSUPPORTED, and STUB. For every gate give command/run ID and artifact link.
List measured results, sample sizes, limitations, remaining blockers, and exact
reproduction steps. Do not call an empty implementation or placeholder a pass.
After implementation authorization, use small clear commits without unrelated
teammate changes; do not commit secrets or large video files by default.

Broader support and stronger claims are governed by
[the follow-up validation specification](SENSOR_ID_VALIDATION_SPEC.md). That
document does not supersede these constraints or authorize implementation.

## References used in this review

- [Apple: peripheral advertising keys, byte budget, and overflow behavior](https://developer.apple.com/documentation/corebluetooth/cbperipheralmanager/startadvertising(_:))
- [Apple: documented background advertising behavior](https://developer.apple.com/library/archive/documentation/NetworkingInternetWeb/Conceptual/CoreBluetooth_concepts/CoreBluetoothBackgroundProcessingForIOSApps/PerformingTasksWhileYourAppIsInTheBackground.html)
- [Apple: current CoreBluetooth overview, including newer background privileges](https://developer.apple.com/documentation/corebluetooth)
- [NimBLE: passive scanning and duplicate filtering](https://h2zero.github.io/NimBLE-Arduino/class_nim_b_l_e_scan.html)
- [Python: HMAC and compare_digest](https://docs.python.org/3/library/hmac.html)

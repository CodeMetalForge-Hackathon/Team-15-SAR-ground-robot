# Local verification

Verified November 7, 2026 (America/New_York), on this Mac. No physical robot,
radio, camera, router configuration, Pi, or Jetson was operated during these checks.

- **270 passed, 0 failed, 0 skipped:** the repository's existing standard-library
  runner, `tools.c5.reproduce_c5.run_all_tests()`, including 19 new mission-control
  tests and the existing BLE, discovery, rover, Crazyflie and search tests.
- **41 targeted tests passed:** `python3 -m unittest tests.test_mission_control
  tests.test_rover_wifi tests.test_rover_keyboard tests.test_keyboard_control -q`.
- Browser flow exercised against `python3 -m mission_control.demo`: token login,
  claim control, enable actions, propose a rover pulse, observe pending approval,
  approve and observe acknowledgement, propose/approve simulated takeoff,
  observe simulated altitude 0.50 m, request Stop + Land, observe paused state and
  simulated altitude return to 0.00 m.
- Real loopback HTTP → coordinator approval → live rover adapter → fake TCP M5
  receiver test confirms `MOVE w 20` only after approval and `STOP` on operator stop.
- State-machine tests cover operator/device loss, stale vision, role isolation,
  duplicate agents, proposal/delivery expiry, no automatic movement redelivery,
  failed/missing acknowledgements, and control ownership.
- An artificially slow HTTP response consumes the command TTL; its movement is
  rejected locally. Coordinator disconnect invokes simulated drone landing.
- CLI smoke check creates temporary mode-600 credentials, starts the real server
  entry point, claims control, verifies lease expiry without client traffic,
  and checks clean SIGINT shutdown.
- Python compilation, `node --check mission_control/static/app.js`, and
  `git diff --check` pass.

The full runner above uses this repository's pytest compatibility shim; this is
not a claim that the pytest executable was installed or invoked.

Hardware gates still pending: router peer connectivity/range, Pi and Jetson
installation, private role-file transfer, powered RoverC directions/stop behavior,
the absent external Crazyflie backend and flight/radio-loss behavior, an actual
Jetson vision publisher, and an airborne scanner telemetry link.

Dashboard screenshot from the simulated browser run:
`../_media/mission-control/dashboard.png` (local, ignored media artifact).

## Camera workspace update

The interface now uses a camera background with controls on the left and Bluetooth
and recordings on the right. Browser checks used an isolated loopback fixture on
port 8081, visibly labeled **TEST CAMERA** and **SIMULATED**, without hardware:

- Recorded and saved camera and Bluetooth captures; decoded the resulting
  1280×720 video and scrubbed the Bluetooth recording to its final sample.
- Reloaded the page and reopened both recordings from IndexedDB; video playback
  decoded successfully after recreating document-scoped blob URLs.
- Checked per-action approvals, fullscreen and camera focus mode. Pause and
  Stop + land remained available with sidebars hidden.
- Disconnected the fixture server during both captures; both automatically
  stopped and saved, with live feeds marked offline.
- Stopped the isolated test server and returned the preview to port 8080, with
  no invented camera or Bluetooth data. The camera and receiver are offline;
  robot agents remain explicitly simulated.

**278 passed, 0 failed, 0 skipped** using the same repository-wide standard-library
runner. This includes eight new media transport tests: fragmented/oversized/stale
JPEG handling, missing Pi camera tooling, real subprocess shutdown, operator-only
frame access, the real discovery HTTP bridge, offline Bluetooth behavior and CSP.
Both JavaScript syntax checks and `git diff --check` pass. Live Pi camera and
wireless frame-rate/latency tests still require the actual hardware.

## Jetson-frame path visualization

**60 targeted tests passed**, including 11 new tracking tests, the existing
network/media suites and the rover/drone control suites. Tracking checks cover
90° frame rotation plus translation, native Jetson-frame positions, missing rover
localization, invalid/stale/duplicate samples, bounded histories, gap segmentation,
estimator restart invalidation, pose-file freshness and paused operator alignment.
An actual HTTP agent-to-paths test confirms position and simulation provenance.

Browser checks used an isolated, explicitly SIMULATED position fixture: XY trails
for both vehicles, altitude and distance charts, camera/path switching, focus mode,
frame-alignment form, and JSON download. The exported file was parsed and checked
for the Jetson origin, meter units, source labels and nonempty position histories.
The isolated fixture was stopped afterward; the normal local demo has no invented
live tracks. Live rover localization and measured boot-frame alignments still
require hardware setup. JavaScript syntax, Python compilation and diff checks pass.

## Live phone trace

The attached ESP32 was read through the existing exclusive passive serial reader
on `/dev/cu.usbmodem101`, with no firmware change. A seven-second initial check
received 2,528 advertisements with zero malformed rows. After the operator
confirmed OLF C1 was foregrounded in Rotating mode, the normal verifier admitted
alias 1 using explicitly labeled **SYNTHETIC TEST KEYS** and a separate replay-state
file outside Git. A later live snapshot showed 10 newly verified rotating tokens
and 7,265 RF reports for alias 1, latest RSSI -34 dBm with 0.03 s reception age.
No other device's names, addresses or raw payloads were saved in the evidence.

**52 targeted tests passed**, including 14 trace tests. Duplicate RF activity
cannot refresh verified age/count or replay state; forged/stale/future tokens,
unpublished replay-state entries and persistence failures do not create trace
activity. Tests cover the actual pseudo-terminal-to-HTTP path, viewer auth, camera
publisher ownership, complete/invalid JPEG handling and frame expiry.

Browser verification confirmed the live alias auto-selection, red receiver and
blue beacon link diagram, source/test-key labels and actual RSSI history. A separate
SIMULATED fixture with a test camera image verified manual camera pin placement
and the explicit no-vision/no-localization labels; that fixture was stopped.
Actual webcam permission/sharing and access from a second physical device remain
operator checks. The live viewer remains on port 8082, with the physical receiver
as its only serial source. JavaScript syntax, Python compilation and diff checks pass.


## Signed phone SOS status (2026-11-08)

- `tests.test_sos_status`: signed SOS/Normal transitions within one window,
  old/conflicting status rejection, tampering, time bounds, duplicate RF vs
  authenticated status age, persist-before-publish, write failure, restart,
  receiver loss, namespace isolation and legacy v1 exclusion.
- Native Swift checks in `ios/BeaconC1/tests/SOSChecks.swift` pass for frozen v1
  and v2 vectors, durable set/clear and restore, rollback, revision exhaustion,
  corrupt state and write failure. Signed iOS build succeeded and was installed
  on the connected iPhone 14 Pro.
- Real foreground phone → USB ESP32 → authenticated HTTP `/trace` showed
  **SOS ACTIVE**, then **Normal · signed status** after clear. Evidence is local
  and ignored: `_media/phone-trace/sos-live.png`, `sos-cleared-live.png`, and
  `sos-hardware-check.json`. Real RF is LIVE-HW; test keys remain visibly labelled.
- Background delivery and emergency-service dispatch are not implemented.

Setup and protocol: [SOS_STATUS.md](SOS_STATUS.md).


## Watch SOS remote (2026-11-08)

- Added the OLFWatch target, embedded watch app, shared schemes and phone
  WatchConnectivity bridge. Both integrated iOS/watchOS device and simulator
  builds pass with signing disabled.
- Native `WatchCommandChecks.swift` passes set/clear, stale-order rejection,
  expiry, clock-skew and malformed-request checks. Existing `SOSChecks.swift`
  also passes for durable phone state and v1/v2 vectors.
- A paired iPhone/watch simulator received the phone's SOS OFF snapshot through
  WatchConnectivity and displayed Phone connected. The small watch layout was
  visually checked; local screenshot `_media/phone-trace/watch-ui.png`.
- Physical watch signing/install is pending: Xcode reported No Accounts and no
  provisioning profile for `com.culubo.olf.beaconc1.watchkitapp`; the paired
  physical watch is currently unavailable. No physical watch SOS/haptic or
  watch→phone→ESP32 round trip has been claimed as verified.

Setup and limitations: [WATCH.md](../ios/BeaconC1/WATCH.md).

## Four-view workspace (2026-11-08)

- Real HTTP tests cover the four-panel entrypoint, same-origin embedding policies,
  authenticated vision controls, missing/stale frame handling, cross-origin POST
  rejection, and a real isolated simulator process with SSE and pause controls.
- Existing coordinator, media, tracking and phone-trace tests still pass. Fleet
  and Python/C protocol checks pass after the role-based simulator update.
- Browser QA verified the Team-15 Ops palette, overview/expanded views, shared
  login, and visible Stop + land controls. The four working panels occupy the
  screen below the compact toolbar after connection.
- A real host webcam published 195 JPEG frames during a 45-second check through
  the authenticated camera endpoint. The actual Faster R-CNN worker returned
  live person boxes and annotated frames at roughly 210–224 ms per inference.
  The browser displayed those frames in both overview and expanded vision views.
  The webcam publisher was released after verification; no video was recorded.
- The USB receiver and robot agents were disconnected in this run and remained
  labeled offline. Pi camera/Hailo operation was not tested. The browser camera
  permission flow remains dependent on the browser's permission prompt; host-feed
  inference was verified separately using the physical webcam.

- The final native host-camera fallback was verified from the in-app workspace:
  Use host / Pi feed opened the built-in camera, produced fresh person detections
  at about 196 ms per frame, and Stop vision removed both child processes and
  cleared the displayed result. This removes browser camera permission as a
  prerequisite for viewing the server's own camera.
- Final layout uses full-bleed map/camera panels, translucent overlaid controls,
  a hide-controls toggle, and a 43 px main toolbar.

## Independent video, visible phones, and Crazyflie training

- The in-app view measured 28–29 video FPS independently of about 14–15
  detection updates/s in fast mode. The older view polled at 350 ms (2.86 FPS).
  Bench SSDLite CPU inference was about 58 ms, versus about 202 ms for Faster
  R-CNN; Detailed mode remains available for its better small-object recall.
- Person and cellphone category mappings were checked against torchvision's
  weight metadata. Unit tests keep these separate from custom robot class IDs.
  No visual phone is mapped automatically to a BLE identity.
- The camera displays raw JPEGs; SVG boxes interpolate between observations,
  fade at 400 ms and expire at 900 ms. New host selection replaces an old browser
  publisher instead of inheriting its lower upload rate.
- 67 integration/unit checks pass, plus a real synthetic-data training/evaluation
  smoke run that correctly refused to activate an insufficiently validated model.
- The real Crazyflie data currently contains 17 positive frames and eight
  verified background frames. The first vertical-pose photograph was captured
  separately from the later horizontal-pose burst and is held out.
- A Crazyflie-only candidate completed 20 epochs using 24 training images. On
  the one independent check image it produced one true positive and one extra
  overlapping box (one false positive at IoU 0.5). It was NOT activated. Further
  second-angle frames are required before the validation gate can pass. RoverC
  training is deferred at the user's request.
- Candidate re-evaluation is available with `python -m perception.evaluate
  --activate`. It excludes all training capture sessions and preserves the
  existing active model unless the independent validation gate passes.

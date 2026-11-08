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

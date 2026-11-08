# MAP-05: Camera loss → STALE → UNKNOWN, and runner auto-restart

**Label:** RECORDED HARDWARE (replayed Pi frame; the "camera loss" was simulated by killing the runner process). **Status:** COMPLETE.

**In plain words.** If the camera stops sending pictures, the dashboard must not keep showing the last answer as if it were current. We killed the camera program on purpose while the dashboard was open. Within 2 seconds the dashboard said STALE, emptied the map to "unknown" and marked the route as unusable. The launch script restarted the camera program, and new frames arrived about 10 seconds later.

## 1. Objective and hypothesis

Verify invariant (d), "stale data reads UNKNOWN", end to end through the dashboard API, together with the demo script's auto-restart. Hypothesis: within `stale_after_s` = 2 s of the last frame, `/api/perception` reports `STALE`, assessment `UNKNOWN`, an all-`U` map and route `STALE_NOT_USABLE`, and `scripts/camera_demo.sh` restarts the runner.

## 2. Date, hardware, software

- **Date:** 2026-11-08. Run A 11:47:47–11:48:10 UTC (22.7 s); run B 11:48:39–11:53:02 UTC.
- **Mac:** M4 Pro.
- **Code:** the `feature/camera-mapping` working tree with the review fixes applied (11:44–11:45 UTC), before they were committed as `c7ed6c5` (11:51:50 UTC). This includes the `stale_view` map blanking.
- **Launch:** `scripts/camera_demo.sh --replay` / `--replay --no-qwen`.

## 3. Data and N

| Run | Directory | States | Segments (runner instances) |
|---|---|---|---|
| A | `20261108-064743` | 46 | 1 (11:47:47–11:48:10) |
| B | `20261108-064835` | 486 | 3: 11:48:39–11:48:48 (18), 11:48:58–11:51:50 (344), 11:51:59–11:53:02 (124) |

The segments were identified during this audit from `frame_seq` restarting at 1.

## 4. Procedure

1. Start the script in replay mode and wait for frames.
2. Kill only the camera runner (11:48:48 UTC).
3. Poll `/api/perception` and `/api/perception/health` during the stale window and take a headless-Chrome screenshot.
4. Wait for the restart.

## 5. Ground truth

The known kill time, and the state that is expected while frames are missing.

## 6. Metrics

- the time from the last frame to `STALE`;
- the content of the stale view;
- the gap from the last frame before the kill to the first frame after the restart.

## 7. Results

- The API returned `status: STALE`, assessment `UNKNOWN` ("perception data stale (… s old)"), all-`U` map rows with no footprints, and route `STALE_NOT_USABLE` within the 2 s threshold (session console log, 11:49:19 UTC; the screenshot is in a temporary scratch area, not published).
- **Restart gap: 9.98 s** (last frame 11:48:48.0, first new frame 11:48:58.0 UTC), recomputed from the state file. That matches "auto-restart in about 10 s" in EVALUATION §7.
- **Second gap of 8.56 s** (11:51:50 → 11:51:59): this script's runner restarted again and then kept posting into the *new* live-mode dashboard started at 11:51:55. That is the stray producer of [DSH-02](DSH-02-dashboard-duplicate-producer.md). The segment ends at 11:53:02, when the process was killed by hand.

## 8. Failures found

The run surfaced two bugs:

- The script's INT/TERM trap returned into its restart loop instead of exiting, which is why this runner outlived its test.
- The dashboard accepted that runner alongside the live one.

Both were fixed in `73539a7` (see DSH-02).

## 9. Evidence

| File | Where | SHA-256 |
|---|---|---|
| Run A `perception.jsonl` | `$TEAM15_EVIDENCE/camera_mapping/20261108-064743/` | `14fa9ebb2a861fdf4dfac0b030d3d78a8d230b6f2e774d8061ad4d9e9aa74090` |
| Run A `camera.log` | same | `f5de445343539c8603a18b130c82ea16aaedd8c9f03b1aa13d9b970b50af6f26` |
| Run B `perception.jsonl` | `$TEAM15_EVIDENCE/camera_mapping/20261108-064835/` | `a7aaf43351a685edc4e76fc48bb985880b52a05bee26b66bfa14a052d4efebd4` |
| Run B `camera.log` (3 runner starts) | same | `b01eeaf88194235d108421ae759c92b055d64e660ae1e78098bc35502054aac8` |
| Unit tests | `test_camera_disconnect_degrades_to_unknown`, `test_dashboard_roundtrip_and_staleness`, `test_stale_view_draws_no_free_or_occupied_cells`, `test_dashboard_camera_disconnect_health` | — |

## 10. Limitations

- The camera loss was simulated by killing the process. A real network drop of the Pi stream goes through `perception.pi_source` reconnects (`reconnect 1/3` lines appear in MAP-06's log) before the runner gives up, so the timing would differ.
- The browser-side staleness (`clientStale`) was checked only by screenshot.

## 11. What it proves / does not prove

- **Proves:** the server-side stale path and the restart work with recorded data.
- **Does not prove:** how long a real Pi network outage takes to be detected.

## 12. Next time

Script the check (kill the process, then poll with assertions) so that it can run in CI against the dashboard with a fake runner. Test a real `ssh` drop.

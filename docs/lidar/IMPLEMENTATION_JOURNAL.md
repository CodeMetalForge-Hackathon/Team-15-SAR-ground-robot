# LiDAR implementation journal

## 2026-11-07/08: RPLIDAR C1 migration, Stage A/B (user-authorized: implement, test, push a draft PR, then audit; no merge, no hardware)

- Fetched origin/main: still **06a69b9**. Created worktree `~/Documents/Team-15-wt/rplidar-c1`, branch `feature/rplidar-c1-ground-robot`, from origin/main. I did not edit any other agent's worktree.
- Read the merged contracts read-only: `ranging/` (Grove, PR #7), `rover/sensors.py` + `pi_io.py` (PR #8), `core/range_view.py` + `dashboard/range_source.py` (PR #5), and the Qwen `$QWEN_WORKSPACE/docs/SENSOR_FUSION_CONTRACT.md` (separate repo).
- **Design decision:** the PR is purely additive. New: `lidar/`, `docs/lidar/`, `.github/workflows/lidar.yml`. **Zero edits** to `ranging/`, `rover/`, `dashboard/`, `core/`, `pytest.ini` and `requirements.txt`, so there is nothing to coordinate before merge and no shared-interface change.
- Findings that shaped the adapters:
  - `rover/sensors.py:from_rover_fields` accepts only `source == "grove-ultrasonic"`. The LiDAR adapter uses the honest source `rplidar-c1`, so the rover rejects it (ERROR → UNKNOWN). That is the intended Stage B behaviour. Allowlisting is a rover-owner change (R1) after Issue #9.
  - `core/range_view.hardware_verified` requires `driver == "gpiod"`, so LiDAR data is always badged SIMULATED on the existing card.
  - `ranging.RangeClient` accepts any `team15.range_snapshot/1`, and `GroveRangeIO` relabels it `grove-ultrasonic`. That is a spoofing path. Mitigations: the LiDAR compat snapshot always sets `forward_motion_allowed: false`, and its writer refuses Grove's `/dev/shm` path (both tested).
  - The StickC bridge (planned) is also a USB-serial device. The mitigation is an explicit by-id path, an exclusive lock and the GET_INFO model check (merge audit).
- Runtime: our own legacy-protocol codec + pyserial (BSD-3, Pi only). The Slamtec SDK (BSD-2) serves as the reference and fallback. Legacy SCAN on the C1 is **unverified**.
- Qwen workstream (team-15-qwen-11) asked for the contract; I sent the draft and then answered (a)–(c). As a result I added `mount` and `scan_capture_start_*` to `team15.lidar_sectors/1`. I asked them to validate against our fixtures rather than re-implement the rules. I did not touch the Qwen repo.
- Tests: lidar 92 passed. Existing suites unchanged: default pytest 340, ranging 126, so the 466 baseline still holds. See LIDAR_C1_TEST_REPORT.md.
- **Hardware: nothing powered, nothing scanned, no GPIO/motor/servo code paths added.** The gate refuses the unverified config; `scan-once` refuses without `--approved-by`.
- Pushed 9041c05; **draft PR #11** opened; CI 6/6 pass (lidar, ci, perception × push/PR).
- Merge audit (LIDAR_C1_MERGE_AUDIT.md): main + #11 merges clean; 558 passed combined; the only conflicts against active branches (`.gitignore` with aurora-integration / #6) already exist against main without LiDAR. 12 semantic items reviewed; none blocking Stage A/B. Temp worktree deleted.

## 2026-11-08: footprint-aware clearance round (user decisions: keep draft, keep Grove, coordinate with rover owner, harden; no hardware)
- Rover owner (dashboard-integration-26) reviewed the proposal and tightened it: bumper reference, horizon never max range, a 100 % near zone (blocked + stopping distance), occlusion windows uncovered and signed off, a lateral-offset transform test. All implemented in `lidar/footprint.py`, with names mirroring NavConfig (`robot_width_m` with no default, `width_margin_m` 0.05, `lookahead_m` 1.0).
- Hardening:
  - clear evidence needs quality ≥ 20 (mirror phantoms);
  - far-zone gap ≤ 2°;
  - occlusion re-applied at assessment;
  - body-fiducial orientation monitor (wrong offset, sign error, rotation);
  - unknown footprint gives UNKNOWN;
  - a lookahead below the rover's required clearance is refused.
- 5 new scenarios (21–25). The LiDAR suite grew from 92 to 124. Full regression: **590 passed / 0 failed / 0 skipped**.
- Prepared `LIDAR_C1_STATIONARY_SCAN_PROCEDURE.md`, not executed. The gates are still enabled; no rover/ or Grove change.

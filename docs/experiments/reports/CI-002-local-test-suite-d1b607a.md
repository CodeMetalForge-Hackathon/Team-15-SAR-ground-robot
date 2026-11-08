# CI-002 · Full local test-suite run at `d1b607a`

**Label:** SIMULATED / MOCKED / SYNTHETIC test inputs, plus one RECORDED HARDWARE frame (a Pi camera image replayed by one test). Executed on the bench-class Mac, not on robot hardware.
**Status:** COMPLETE.
**Related:** [19 Testing and benchmarks](../../19_TESTING_AND_BENCHMARKS.md) · [CI-001](CI-001-ci-regression-history.md)

## In plain words

We checked out the final hackathon code and ran every automated test the repository contains, on one Mac, the way a new developer would. All 818 pytest tests passed, as did a separate 30-check script that proves the drone-fleet software and its C firmware encode messages identically. We also checked that the three "hardware safety gates" refuse to run with the unverified example configs. This tells us the code base is self-consistent and the gates fire. It tells us nothing about whether a sensor or motor works.

## 1. Objective

Confirm the test counts that the documentation quotes, at the exact revision it describes. Find which tests depend on private data. Re-check the hardware gates without touching hardware.

## 2. Setup

| Item | Value |
|---|---|
| Date | 2026-11-08 (local) |
| Software commit | `d1b607a` (Merge PR #17), in the clean docs worktree (only untracked `docs/` files present) |
| Machine | macOS 26.6.1, arm64 (Apple silicon Mac) |
| Python | 3.13.5 (Anaconda) |
| Packages | pytest 8.3.4, numpy 2.1.3, opencv 4.13.0, fastapi 0.115.6, starlette 0.41.3, uvicorn 0.34.0, httpx 0.28.1, networkx 3.4.2, torch 2.12.0, torchvision 0.27.0 |
| Cached model weights | `fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth`, `fasterrcnn_resnet50_fpn_v2_coco-dd69338a.pth` in `~/.cache/torch/hub/checkpoints` |
| Private data present | robotics SIMULATED fixtures (default `$ROBOT_WORKSPACE/fixtures`); recorded Pi frames in `$TEAM15_EVIDENCE/camera_pi_validation/` |
| Hardware attached | none. The Pi was unreachable, and no serial device or sensor was connected |

## 3. Procedure

```bash
python3 -m pytest -q -p no:cacheprovider -rs                           # default testpaths
for d in lidar/tests ranging/tests qwen_advisory/tests team15_starter/tests; do
  python3 -B -m pytest -q -p no:cacheprovider -rs "$d"
done
for d in planner/tests perception/tests dashboard/tests tests/e2e rover/tests camera_mapping/tests; do
  python3 -m pytest -q -p no:cacheprovider "$d"                         # per-package split
done
(cd team15_starter && python3 -B tests/test_link.py)
python3 -m planner.route A G
python3 -m lidar check-config --config lidar/configs/c1_pi5.UNVERIFIED.json --hardware; echo $?
python3 -m lidar scan-once   --config lidar/configs/c1_pi5.UNVERIFIED.json;            echo $?
python3 -m ranging check-config --config ranging/configs/pi5_gpio5.UNVERIFIED.json --hardware; echo $?
```

**Ground truth:** pytest's own pass/fail verdicts, and the CLI exit codes.
**Metrics:** passed / failed / skipped counts and wall time. Skips matter because each one marks a test whose evidence is missing.

## 4. Results

| Suite | Passed | Failed | Skipped | Time |
|---|---|---|---|---|
| default (`pytest.ini` testpaths) | **540** | 0 | 0 | 12.75 s |
| ├ planner/tests | 19 | 0 | 0 | 0.14 s |
| ├ perception/tests | 39 | 0 | 0 | 7.18 s |
| ├ dashboard/tests | 70 | 0 | 0 | 0.83 s |
| ├ tests/e2e | 31 | 0 | 0 | 1.67 s |
| ├ rover/tests | 284 | 0 | 0 | 2.07 s |
| └ camera_mapping/tests | 97 | 0 | 0 | 2.01 s |
| lidar/tests | **124** | 0 | 0 | 1.76 s |
| ranging/tests | **126** | 0 | 0 | 3.41 s |
| qwen_advisory/tests | **23** | 0 | 0 | 0.23 s |
| team15_starter/tests | **5** | 0 | 0 | 2.83 s |
| **pytest total** | **818** | 0 | 0 | |
| `team15_starter/tests/test_link.py` (script) | 30 `ok` checks, `ALL LINK TESTS PASSED` | — | — | — |

Warnings: 2, both `DeprecationWarning` from `websockets.legacy` via uvicorn, in `tests/e2e/test_live_camera_integration.py::test_end_to_end_pipe_into_real_server`. They are harmless at the pinned versions.

| Check | Expected | Observed |
|---|---|---|
| `planner.route A G` | OK, A-B-C-D-E-F-G, 60 m | `{"status": "OK", …, "length_m": 60, "reason": "shortest known walking route"}` |
| LiDAR `check-config --hardware` on the UNVERIFIED config | refuse | exit 2 |
| LiDAR `scan-once` on the UNVERIFIED config | refuse | exit 3 |
| Ranging `check-config --hardware` on the UNVERIFIED config | refuse | exit 2 |

### 4.1 Comparison with CI

CI's `ci` job reports **532 passed, 8 skipped** for the same 540 tests (run 42479330397). The 8 that skip in CI pass here: 6 range-panel tests (private fixtures), the Faster R-CNN blank-frame test (weights), and the recorded-Pi-frame regression (frames and torch). [19 §3.2](../../19_TESTING_AND_BENCHMARKS.md#32-why-ci-skips-8-tests-that-pass-locally) has the details.

## 5. Evidence

The raw pytest outputs are kept in the audit session's scratch directory, not committed. Their SHA-256 values:

| Output | SHA-256 |
|---|---|
| default suite | `af5f353a758a6c805eeb541f4c4a7e1bedb50f48794f2499f1b56c58c373babc` |
| lidar/tests | `314da15393ea9717ae7519180aa1e9eaac9d4d47508f4480b5b8e0ef6fd90cd0` |
| ranging/tests | `ac09f8a0ff72607d24c11059e6e862130200afd32e4678da6722b9909ea92fef` |
| qwen_advisory/tests | `acbd8afb334d9f80dd17722f4dfed5570c321dcbb5f0a6037b4f5bc6d0c12f1b` |
| team15_starter/tests | `e6b662da0c78fdc0d5edf39da6538beaa8724c8b9219b159c597832bc5a3cca2` |

These hashes identify the captured text only. Re-running the suites produces different timings, and so different hashes.

## 6. Limitations and confounders

- One machine and one Python version (3.13.5). CI covers 3.11 with the exact pins.
- The run used the operator's private fixtures and frames. Another developer will see 8 skips.
- `scan-once` was refused by the config gate before any serial open. No device was attached, so this run does not show how the command behaves *with* a device present.
- Pass counts say nothing about coverage of code without tests (for example, `camera_mapping/live.py`'s network loop is exercised only by manual runs).

## 7. What this proves, and what it does not

**Proves:** at `d1b607a` every automated test in the repository passes on a machine set up like the bench Mac. The documented counts (540 / 124 / 126 / 23 / 5) are correct. The three CLI hardware gates refuse the shipped unverified configs.

**Does not prove:** camera distance accuracy, detector false-alarm rate, motor stopping behaviour, firmware correctness, sensor driver behaviour on real devices, or Qwen answer quality. See [19 §7](../../19_TESTING_AND_BENCHMARKS.md#7-what-the-tests-do-not-prove).

## 8. What we would change next time

- Ship small public SIMULATED stand-ins for the private fixtures, so a clean checkout runs the whole suite.
- Make `test_link.py` a pytest module, so it is counted and can run in CI.
- Record `pip freeze` with every local run, or ship a lock file.

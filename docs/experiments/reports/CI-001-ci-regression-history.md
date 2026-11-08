# CI-001 · GitHub Actions regression history (7–8 Nov 2026)

**Label:** SIMULATED / MOCKED / SYNTHETIC test inputs, run on GitHub-hosted runners. No hardware is involved.
**Status:** COMPLETE (an analysis of every recorded run).
**Related:** [19 Testing and benchmarks](../../19_TESTING_AND_BENCHMARKS.md) · [CI-002 local run](CI-002-local-test-suite-d1b607a.md) · [21 Troubleshooting](../../21_TROUBLESHOOTING.md) · [27 Timeline](../../27_PROJECT_TIMELINE.md)

## In plain words

Every time someone pushed code or opened a pull request, GitHub ran our automatic tests on a clean Linux machine. We looked at all 184 of those runs. Three failed. Two of the three were the same problem seen twice: a new version of the OpenCV library had removed a function we use. We fixed it by pinning exact library versions. The third was a privacy test doing its job: it blocked image files from being committed, and some legitimate map icons had to be added as named exceptions. No failure was a bug in the robot's logic.

## 1. Objective and hypothesis

- **Objective:** establish what CI actually ran during the hackathon, how often it failed, why, and how each failure was fixed.
- **Hypothesis:** CI failures were caused by environment and dependency drift rather than logic regressions, because every PR author ran the suites locally before pushing.

## 2. Setup

| Item | Value |
|---|---|
| Date of analysis | 2026-11-08 |
| Period covered | 2026-11-07 18:59:31 UTC → 2026-11-08 12:14:55 UTC |
| Repository | `CodeMetalForge-Hackathon/Team-15` (private) |
| Final commit | `d1b607a` (Merge PR #17) |
| Runner | `ubuntu-latest`, Python 3.11 (`ci`, `lidar`, `ranging`, `qwen`) or 3.13 (`perception`) |
| Data sources | `gh run list --limit 200 --json databaseId,workflowName,headBranch,headSha,status,conclusion,createdAt,event,displayTitle`; `gh api repos/{owner}/{repo}/actions/runs --paginate` for workflow paths; `gh run view <id> --log-failed` for the three failures; `gh run view <id> --log` for pass/skip counts |
| N | 184 runs (all the runs the API returned; fewer than the 200 limit, so the list is complete) |

## 3. Procedure

1. Pulled the run list and the per-run workflow file path. The path is needed because `perception.yml` was displayed as `ci` until PR #10.
2. Grouped the runs by workflow file, conclusion, event and branch.
3. For every non-success run, read the failed-step log and identified the failing test and its exception.
4. Found the fixing commit with `git log -- requirements.txt .github/workflows/` and the next successful run on the same branch.
5. Read the pass and skip counts of the final-revision runs from their logs.

**Ground truth:** the GitHub Actions run records and logs.
**Metrics:** run count, failure count, failure rate, time to fix, and pass/skip counts on the final revision. These were chosen because they answer "did CI catch real problems, and was `main` green when the event ended?"

## 4. Results

### 4.1 Totals

| Workflow file | Display name(s) | Runs | Success | Failure |
|---|---|---|---|---|
| `.github/workflows/ci.yml` | ci | 84 | 81 | **3** |
| `.github/workflows/perception.yml` | ci (10 runs, before PR #10), perception (53) | 63 | 63 | 0 |
| `.github/workflows/ranging.yml` | ranging | 19 | 19 | 0 |
| `.github/workflows/lidar.yml` | lidar | 14 | 14 | 0 |
| `.github/workflows/qwen.yml` | qwen-advisory | 4 | 4 | 0 |
| **Total** | | **184** | **181** | **3** (1.6 %) |

By event: 105 `push`, 79 `pull_request`. Most PR commits ran each workflow twice, once per event, so a third of the compute is duplicated.

By branch (runs): `feature/rplidar-c1-ground-robot` 38, `main` 27, `t2/dashboard-a-to-g` 21, `feature/camera-mapping` 16, `feature/rover-navigation` 15, `feature/issue-9-fail-closed-forward` 12, `qwen/model-docs` 12, `feature/grove-distance` 12 (ranging only; that branch had no `ci.yml`), `GavinPrescott-sim-roles` 9, `feature/stickc-usb-bridge` 8, `qwen/advisory-integration` 6, `ci/perception-workflow-name` 4, `t1/camera-person` 4.

### 4.2 The three failures

| Run id | Created (UTC) | Event | Branch @ commit | Failing test | Exception | Suite result |
|---|---|---|---|---|---|---|
| 42403983799 | 2026-11-07 18:59:31 | push | `t2/dashboard-a-to-g` @ `3797530` | `perception/tests/test_live_camera.py::test_blank_image_no_person` | `AttributeError: module 'cv2' has no attribute 'HOGDescriptor'` (at `perception/live_camera.py`, `self.hog = cv2.HOGDescriptor()`) | 1 failed, 30 passed |
| 42404031282 | 2026-11-07 19:00:06 | pull_request | same | same | same | same |
| 42478121738 | 2026-11-08 11:59:16 | pull_request | `GavinPrescott-sim-roles` @ `eddef53` | `dashboard/tests/test_dashboard.py::test_no_photos_tracked_in_git` | `AssertionError: assert ['team15_star...r-shadow.png'] == []` | 1 failed, 332 passed, 7 skipped |

**Failure 1–2: root cause.** At `3797530`, `requirements.txt` listed unpinned names (`pytest`, `networkx`, `fastapi`, `uvicorn`, `httpx`, `numpy`, `opencv-python-headless`). The runner's install log shows `opencv-python-headless-5.0.0.93`, together with fastapi 0.162.2, starlette 1.10.0, pytest 9.2.0 and numpy 2.4.6. OpenCV 5 no longer exposes `cv2.HOGDescriptor` in the main package, so the HOG detector's constructor failed.

**Fix:** commit `a36a658` (2026-11-07 14:00:23 −0500 = 19:00:23 UTC), "ci: pin requirements to the bench Mac's versions (opencv HOGDescriptor)", pinned all eight packages to the bench Mac's versions, including `opencv-python-headless==4.13.0.92`. A comment in the file records why. Both runs on `a36a658` (push 19:00:26, PR 19:00:29) passed. **Time to fix: under 1 minute after the first failure was reported.** The commit timestamps suggest the pin was prepared in parallel with the first push. Later, `perception.yml` (`cee428e`) installs `opencv-python-headless>=4.8,<5`, with a comment that OpenCV 5 moved HOGDescriptor.

**Failure 3: root cause.** PR #17 (Aurora fleet sim) vendored Leaflet's five UI icons under `team15_starter/fleet/web/leaflet/images/` so that the map works offline. The privacy test rejects every tracked `.jpg/.jpeg/.png/.heic/.mp4/.mov` file, because camera evidence must never enter Git. The branch had also forked from the initial commit, so CI only saw this when the PR's merge with `main` was tested.

**Fix:** `95b6f67` merged `main` into the branch. `159c678` (2026-11-08 07:13 −0500) added `VENDORED_ICONS`, an exact-path allow-list of the five icons, and untracked a 10 MB generated `mujoco_search.gif`. Every workflow passed on `159c678` and then on the merge `d1b607a`. **Time to fix: about 15 minutes.**

### 4.3 Final-revision results

| Run id | Workflow | Commit | Result |
|---|---|---|---|
| 42479330397 | ci | `d1b607a` | 532 passed, 8 skipped, 1 warning (17.53 s) |
| 42479330362 | perception | `d1b607a` | 38 passed, 1 skipped (6.38 s) |
| 42479254481 | ci | `159c678` | 532 passed, 8 skipped (11.70 s) |
| 42479254584 | perception | `159c678` | 38 passed, 1 skipped |
| 42479254463 | lidar | `159c678` | 124 passed, plus both gate-refusal steps |
| 42479254445 | ranging | `159c678` | 126 passed, plus the gate-refusal step |
| 42479254482 | qwen-advisory | `159c678` | 23 passed |

`lidar`, `ranging` and `qwen-advisory` did **not** run on `d1b607a` itself, because their path filters did not match. Their last runs are on `159c678`, the PR #17 head that `d1b607a` merges. `d1b607a` changes no file under their paths.

## 5. Failures and confounders

- `gh run list` reports the workflow's *current* display name, not the name at run time. Counting by name would misattribute 10 perception runs to `ci`. This report counts by file path.
- Runs on stacked branches (e.g. #8 on top of #5) re-test inherited code, so per-branch counts overlap.
- CI skips 8 tests that need torch weights, private SIMULATED fixtures or recorded Pi frames. A green CI does not cover those tests ([CI-002](CI-002-local-test-suite-d1b607a.md) does).
- `team15_starter/tests` is in no workflow, so CI history says nothing about it.

## 6. Evidence

| Evidence | Where | SHA-256 |
|---|---|---|
| Run list JSON (184 runs) | session scratch export of `gh run list` (not committed) | n/a (regenerable with the command in §2) |
| Failed logs | `gh run view 42403983799 --log-failed`, `gh run view 42478121738 --log-failed` | n/a (GitHub-hosted) |
| Fix commits | `a36a658`, `cee428e`, `8f351fe`, `edb6756`, `95b6f67`, `159c678` | git object ids |

## 7. Reproducibility

Anyone with read access to the repository can run:

```bash
gh run list --limit 200 --json databaseId,workflowName,headBranch,headSha,conclusion,createdAt,event
gh api 'repos/CodeMetalForge-Hackathon/Team-15/actions/runs?per_page=100' --paginate \
  --jq '.workflow_runs[] | [.id,.name,.path,.conclusion,.created_at,.head_branch,.event] | @tsv'
gh run view 42403983799 --log-failed
gh run view 42478121738 --log-failed
```

GitHub's log retention policy will eventually delete the logs.

## 8. What this proves, and what it does not

**Proves:** `main` was green on every workflow that ran on its final revisions. Each of the three CI failures was diagnosed and fixed with a targeted commit, two of them in under 15 minutes. The pinning decision in `requirements.txt` is grounded in an observed failure.

**Does not prove:** anything about hardware. It also does not cover the 8 data-dependent tests, `team15_starter/tests`, or the code-level correctness of features that have no tests.

## 9. What we would change next time

- Pin dependencies from the first commit, using a lock file, rather than after the first failure.
- Run `pull_request` events only, or add `concurrency:` groups, to remove the duplicated push+PR runs.
- Add a workflow for `team15_starter/tests` and the link script.
- Give every package's workflow the same Python version matrix (3.11 and 3.13).
- Add a CI job that runs the 8 data-dependent tests against public, synthetic substitutes for the private fixtures.

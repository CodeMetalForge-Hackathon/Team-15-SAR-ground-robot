# DSH-02: Two camera runners on one dashboard: the duplicate-producer bug and the 409 lock

**Label:** REAL HARDWARE (live Pi runner) + RECORDED HARDWARE (stray replay runner), observed together. **Status:** FAILED as observed, which is how the bug was found. The fix in `73539a7` is verified by a unit test (MOCKED) and by the SIGTERM shutdown check.

**In plain words.** During the second live camera test, an old test program was still running in the background. It replayed a saved photo and sent its results to the same dashboard as the live camera. The dashboard accepted both and kept switching between "LIVE CAMERA" and "RECORDED FRAMES" every few seconds, so the operator could not tell which picture was real. Both programs also competed for the laptop's GPU and slowed each other down. We changed the dashboard so that it accepts only one camera program at a time and refuses the second one, with a visible warning. We also fixed the launch script so that Ctrl-C actually stops it.

## 1. Objective

Find out why the dashboard's perception state was inconsistent during the live run [MAP-06](MAP-06-live-pi-run-2-person-chair.md), and prevent mixed sources.

## 2. Date, hardware, software

- **Date:** 2026-11-08 11:52:03–11:52:49 UTC (polling); fix committed 11:55:08 UTC (`73539a7`).
- **Producers:**
  1. the live runner (`scripts/camera_demo.sh`, Pi IMX708, `c7ed6c5`, with the Qwen advisor);
  2. a replay runner left over from `scripts/camera_demo.sh --replay --no-qwen`, started earlier from the uncommitted tree before `c7ed6c5`.
- **Dashboard:** `dashboard.serve` on :8000.

## 3. Data and N

15 polls of `/api/perception`, `/api/perception/health` and `/api/perception/advisory` over about 45 s (session console log), plus the two runners' JSONL files: [MAP-06](MAP-06-live-pi-run-2-person-chair.md) (live) and [MAP-05](MAP-05-camera-loss-stale-restart.md) run B, segment 3 (replay, 11:51:59–11:53:02 UTC).

## 4. Ground truth

The process list at 11:52:55 UTC showed both `camera_mapping.live --source replay … --jsonl …/20261108-064835/perception.jsonl` and the live runner.

## 5. Results

| Poll | frames_received | Displayed source | Advisory status |
|---|---|---|---|
| 1–2 | 8, 14 | RECORDED | — |
| 3 | 29 | LIVE | NOT_CONFIGURED |
| 4 | 46 | RECORDED | NOT_CONFIGURED |
| 5–6 | 64, 79 | LIVE | QWEN_GUARDED |
| 7 | 94 | LIVE | NOT_CONFIGURED |
| 8–9 | 109, 125 | LIVE | QWEN_GUARDED |
| 10 | 144 | LIVE | NOT_CONFIGURED |
| 11 | 160 | RECORDED | NOT_CONFIGURED |
| 12–13 | 177, 194 | LIVE | NOT_CONFIGURED |
| 14–15 | 209, 226 | RECORDED | NOT_CONFIGURED |

The displayed source changed 6 times in 15 polls. Advisories came from both producers: `QWEN_GUARDED` from the live runner, and `NOT_CONFIGURED` from the no-Qwen replay runner. The live runner's detector median was 245.9 ms, against 186.5 ms when running alone in [MAP-01](MAP-01-live-pi-run-1-latency.md).

## 6. Root causes

1. `PerceptionStore.post_frame` accepted any valid state, with no notion of who sent it.
2. `scripts/camera_demo.sh` used `trap cleanup EXIT INT TERM`. On INT or TERM, cleanup ran and then control *returned* into the runner-restart loop, so the earlier replay script survived its test and kept restarting its runner.

## 7. Fix (`73539a7`)

- **Producer identity.** Runners send `producer = "<hostname>:<pid>:<source>"`.
- **409.** While the active producer is live (a frame within 4 s), any other producer gets **HTTP 409** (`ConflictingProducer`). The conflict (rejected producer, active producer, count, time) is reported in `/api/perception/health` for 30 s and shown as a banner in panel D. Advisories from a non-active producer are refused.
- **Runner exits.** `camera_mapping.live` raises `ProducerConflict` on 409 and exits with code 4.
- **Script trap.** `trap cleanup EXIT; trap 'cleanup; exit 130' INT TERM`.
- **Test:** `test_dashboard_refuses_second_live_producer` (MOCKED; passes at `d1b607a`).

## 8. Verification of the shutdown fix (session console log, 2026-11-08 11:55 UTC)

| Check | Result |
|---|---|
| SIGINT sent to the script, which had been *started as a background job* | 3 demo processes left after 12 s. **Inconclusive**: non-interactive shells ignore SIGINT for background jobs, so the trap may never have run |
| SIGTERM to the script | **0** demo processes left after 10 s; "stopping demo processes…" printed |
| Interactive Ctrl-C in a foreground terminal | **UNVERIFIED** (no record) |

## 9. Evidence

| File | Where | SHA-256 |
|---|---|---|
| Live runner states | `$TEAM15_EVIDENCE/camera_mapping/20261108-065157/perception.jsonl` | `7017f97ce2671a281f0883b6f003386b1a29b877af72625f1660d5b9a47c98bb` |
| Stray replay runner states | `$TEAM15_EVIDENCE/camera_mapping/20261108-064835/perception.jsonl` | `a7aaf43351a685edc4e76fc48bb985880b52a05bee26b66bfa14a052d4efebd4` |
| Shutdown test run | `$TEAM15_EVIDENCE/camera_mapping/20261108-065518/perception.jsonl` (50 states) | `16e774ed09d90fed389571ec6eee48a6d4ff4c380a6462e5eb4a1e353e9f0698` |
| Polls and process list | session console log 11:52–11:55 UTC | — |

## 10. Limitations

The 409 lock is per dashboard process and keyed on a self-reported producer string. It prevents accidents, not a malicious sender. Note also that the dashboard is bound to localhost.

## 11. What it proves / does not prove

- **Proves:** the failure mode was real, and the lock and SIGTERM shutdown now behave as intended.
- **Does not prove:** that an interactive Ctrl-C stops everything.

## 12. Lesson

Any shared display needs a single-writer rule from the start. Test the demo script's signal handling in the same way the operator will use it, in a foreground terminal.

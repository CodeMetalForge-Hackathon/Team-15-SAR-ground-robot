# CAM-09 — MacBook bench camera: 60-second empty-scene false-alert test (runs CAM-09 to CAM-14)

**Label:** REAL HARDWARE (MacBook Pro built-in camera, bench). **Status:** FAILED / not passed. Of six attempts, one **FAIL** (CAM-12, a genuine false sighting from window reflections) and five **CONTAMINATED** (real people in view). No clean 60 s empty scene was ever recorded on the Mac. A clean empty scene was later recorded on the Pi ([CAM-24](CAM-24-pi-live-empty-and-object.md), run CAM-25).

**In plain words.** We pointed the camera at a supposedly empty part of the office for 60 s, six times, to see whether the person detector raises alerts when nobody is there. Five times a real person was somewhere in view: at the frame edge, beside the laptop, seated at the side. Once, pointed at windows, the detector "saw" people in the glass, reflections of people behind the camera, and raised a false alert with score 0.99. Where the view really was empty (a painted wall for 25 s, and about 78% of the frame for a full 60 s), it produced no person boxes at all.

## 1. Objective and hypothesis

Verify that an empty scene produces **zero sightings** under the default trigger rule: `PERSON_DETECTOR` score ≥ 0.6, box height ≥ 15% of the frame, 3 consecutive frames. The thresholds were **not** to be changed to manufacture a pass (operator instruction, session console log 2026-11-07 19:48 UTC). A real person entering marks the trial **CONTAMINATED**, not FAIL.

## 2. Date, hardware, software, model

| | |
|---|---|
| Date | 2026-11-07, 19:22–19:58 UTC |
| Camera / compute | MacBook Pro built-in camera, 1920×1080; MPS |
| Software | CAM-09/10/11 ran on working-tree code before `65684e3` (19:45:51 UTC). CAM-12/13/14 ran at `9efbed7` (session console log). |
| Model | Faster R-CNN R50 FPN v2 COCO, `--person-thresh 0.6`, `--trigger person`, `--confirm-frames 3` |
| Settings | `--start-delay-s 8 --duration-s 60` (PR #3), `--min-box-frac 0.15` (recorded in the CAM-12–14 summaries; **not recorded** for CAM-09–11, see §9) |

## 3. Data and N

Six runs of about 290–296 processed frames each (60 s at ≈4.9 fps). Every person box of every frame was logged to `*_frames.jsonl` (boxes only).

## 4. Procedure

The operator aimed the camera and confirmed "Ready". The tool discarded 8 s, captured 60 s, emitted any sighting, and wrote the summary. The session then inspected the evidence frame and the box positions in the frame log to classify the trial.

## 5. Ground truth

**Operator declaration of an empty scene**, plus inspection of the single saved evidence frame and of where the boxes fall in the frame log. There is no video, so frames other than the evidence frame are judged from box geometry only (for example, "edge-entering boxes up to 1,073 px tall are consistent with people walking in").

## 6. Metrics and why

Frames with any person box; frames with a trigger-height box; sightings emitted; and where the boxes are. Sightings are what an operator would see. Box counts and locations explain *why* they happened.

## 7. Results (recomputed from each frame log during this audit; trigger height 162 px)

| ID | Run | UTC | Scene | Frames | Person boxes (≥ 162 px) | Frames with a trigger box | Score range | Max box h (px) | Replayed first 3-frame alert (s) | Sightings | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CAM-09 | `D1-b1794079363-empty60` | 19:22:43 | open office | 295 | 245 (232) | 185 | 0.609–1.000 | 1080 | 2.08 | 1 (0.882) | **CONTAMINATED**: operator at the frame edge |
| CAM-10 | `D1-b1794079542-empty60b` | 19:25:42 | open office | 291 | 643 (540) | 268 | 0.602–1.000 | 1080 | 0.68 | 1 (0.998) | **CONTAMINATED**: person beside the laptop |
| CAM-11 | `D1-b1794080565-empty60c` | 19:42:45 | open office | 296 | 739 (391) | 294 | 0.602–0.998 | 745 | 0.61 | 1 (0.992) | **CONTAMINATED**: seated bystander |
| CAM-12 | `D1-b1794080931-empty60d` | 19:48:51 | two large windows, room physically empty | 294 | **1,767 (858)** | 294 | 0.601–0.998 | 393 | 0.65 | **1 false (0.991)**, box 100×326 px | **FAIL**: every box was on the glass (1,593 on the left window, 174 on the right) |
| CAM-13 | `D1-b1794081308-empty60e` | 19:55:08 | solid painted wall | 290 | 252 (246) | 141 | 0.604–1.000 | 1079 | 0.67 | 1 (0.988) | **CONTAMINATED**: a real hand at the right edge at +0.7 s; edge-entering boxes after 30 s. **0 person boxes from 5 s to 30 s (122 frames).** |
| CAM-14 | `D1-b1794081444-empty60f` | 19:57:24 | wall + windows with blinds closed | 295 | 337 (323) | 295 | 0.601–1.000 | 539 | 0.59 | 1 (1.000) | **CONTAMINATED**: all 337 boxes on one seated bystander at the left edge. **0 boxes in the other ≈78% of the frame for 60 s.** |

The recomputed figures agree with PR #3 (for example, 1,767 boxes and a 393 px maximum in CAM-12).

## 8. Failures and root causes

- **Window reflections (CAM-12):** Faster R-CNN detects people *as images*. It cannot tell a reflection or a person behind glass from a person in the room. The boxes were up to 393 px tall, above the 162 px filter. **Root cause: inherent to an appearance-only detector.** **Mitigation: aim the camera away from glass.** An operator-drawn ignore mask was proposed and never built.
- **Contamination (5 runs):** the open office never cleared. Lesson: choose a corner where nobody sits on either side, and watch both edges during the run.
- **Size filter effect:** PR #3 reports that replaying the earlier logs with the filter cut eligible frames from 236 to 38. It still left one false sighting in each of two empty runs (reflection boxes 165–291 px tall).

## 9. Contradiction found during this audit

PR #3 states that **all** empty-scene runs used `--min-box-frac 0.15`. The summaries for CAM-09/10/11 have **no `min_box_frac` field**, and those runs predate the commit that added the filter (`65684e3`, 19:45:51 UTC). Whether the filter was active in CAM-09–11 is therefore **UNVERIFIED**. It does not change their verdicts (CONTAMINATED), because their evidence boxes were taller than 162 px anyway.

## 10. Evidence files (private, `$TEAM15_EVIDENCE/camera/`)

| File | SHA-256 |
|---|---|
| `$TEAM15_EVIDENCE/camera/D1-b1794079363-empty60_summary.json` | `eded76619f59082730355823fca39017ce64f370ba1c91527cd8f9f906b47d95` |
| `$TEAM15_EVIDENCE/camera/D1-b1794079542-empty60b_summary.json` | `d7369bdcc3e52f466ea2a7db40d620377c3900428432cde5adf83683e10ebb88` |
| `$TEAM15_EVIDENCE/camera/D1-b1794080565-empty60c_summary.json` | `adec0c69e5c661316a64c881db0f6219b2eaeb414dc9106a1e078210189af68a` |
| `$TEAM15_EVIDENCE/camera/D1-b1794080931-empty60d_summary.json` | `60f0a1152b0bd0a01af6fc15ff2e27dcc64f4e8dcf1205739d2fd90827047a78` |
| `$TEAM15_EVIDENCE/camera/D1-b1794081308-empty60e_summary.json` | `a405f9fd46cc3e03299628df48a3c7e89805e744b9aa16a0dd747afc488cc6fb` |
| `$TEAM15_EVIDENCE/camera/D1-b1794081444-empty60f_summary.json` | `78218426c1fcc3e008ede8579f032823bf430ae33a91b1e2baa7c01b009d38ad` |

## 11. Limitations and confounders

The office was not controllable. Ground truth for frames other than the evidence frame is inferred from box geometry. There was one viewpoint per run. Reflections depend on lighting behind the camera, which was not recorded.

## 12. Reproducibility

```bash
python3 -B -m perception.live_camera --declare-drone D1 --sector G --start-delay-s 8 --duration-s 60 --label empty60
# then count boxes per frame from $TEAM15_EVIDENCE/camera/<run_id>_frames.jsonl (see 04 §16 for a replay snippet)
```

## 13. What this proves / does not prove

- **Proves:** reflective glass produces real, high-score false person alerts that the size filter cannot remove. A plain wall and closed blinds produced no person boxes over the windows of time and frame area that were really empty.
- **Does not prove:** a false-alert rate. No fully empty 60 s run exists on the Mac.

## 14. Next time

Use a controlled room. Record a short low-resolution context video, or store a few downscaled frames under no-people consent, to verify emptiness. Add an operator ignore mask for glass. Pre-register the PASS criterion before each run, as was done here.

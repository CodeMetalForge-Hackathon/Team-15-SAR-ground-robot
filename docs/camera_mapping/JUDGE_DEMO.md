# Judge demonstration: five steps (about 5 minutes)

**Setup (before the judges arrive).**

- The robot is **stationary** and the camera looks down the corridor.
- Participants have consented to being on camera.
- Start everything with one command:

```bash
cd ~/Documents/Team-15-wt/camera-mapping && scripts/camera_demo.sh
```

The script runs preflight checks, then the dashboard, the Qwen RAG advisor and the live Pi camera. It opens http://localhost:8000/ ; scroll to panels A–D. If the Pi is unreachable, run `scripts/camera_demo.sh --replay`. The dashboard then says RECORDED FRAMES; say so out loud.

**Opening line (15 s).** "This is a search-and-rescue reconnaissance view built from one camera. Everything you see is labelled:

- detections are LIVE from the Pi camera;
- distances are camera ESTIMATES with uncertainty, or UNKNOWN;
- navigation is advisory and simulated.

The robot does not move in this demo."

## 1. Person detection

A teammate walks into view.

- **Panel A:** a green box `person 0.9x`.
- **Panel C:** "⚠ Potential person detected · UNCONFIRMED".

**Say:** "The detector is our COCO Faster R-CNN on the Mac, at about 5 frames per second. A detection is a candidate, not a confirmed person. The operator decides."

## 2. Obstacle recognition and distance

Place a chair on the centreline at about 1 m.

- **Panel A:** `chair … ~1.0 m ±0.4` labelled `UNCALIBRATED_ESTIMATE`, or `UNKNOWN` with the reason.

**Say:** "Distance comes from where the chair meets the floor, using the measured camera height and tilt. We show the uncertainty. When the geometry isn't good enough — a box cut off by the frame, occlusion, an object off the floor — we say UNKNOWN instead of guessing."

## 3. Local map

- **Panel B:** the robot at the bottom, the blue camera field of view, and the chair as a red footprint with its uncertainty ellipse. Cells behind the chair stay grey (unknown).

**Say:** "This map is relative to the robot; we don't claim SLAM. Green means observed with nothing detected. Grey means unknown. We never assume the space behind an obstacle is clear."

## 4. Path assessment and alternate route

- **Panel C:** **BLOCKED**, with the reason "chair #N at ~1.0 m overlaps the corridor".
- Slide the chair about 0.3 m to one side, at about 1.5 m. The status changes and a blue route appears on that side:
  - **solid** = through observed-free cells;
  - **dashed** = it would cross unobserved space, so the robot should look first.

**Say:** "The verdict is deterministic: CLEAR, CAUTION, BLOCKED or UNKNOWN. A route is a suggestion for the operator, never a motion command. The rover's own safety supervisor and range sensor still gate any movement."

## 5. Rescue guidance (Qwen + RAG)

- **Panel C:** the "Qwen (guarded, RAG)" box. It summarises the scene, flags the person for operator review, explains the blocked path, suggests the next observation, and cites knowledge-base sources (for example `team-ugv-guide#false-positives-at-ground-level`).

**Say:** "Qwen3.5-2B runs locally with retrieval over our rescue knowledge base, behind a guard. It explains and prioritises; it has no authority. Motor-like output is discarded."

Closing proof, optional: press Ctrl-C on the camera.

- Panel D: **STALE**.
- The map empties to unknown and the status becomes UNKNOWN.
- The script restarts the camera within about 10 s.

**Say:** "When we lose the camera, we never keep showing the last answer."

## What not to claim

- Measured or verified distances, unless the calibration report says `CALIBRATED`. Even then they are camera estimates.
- That the fine-tuned LoRA adapter is deployed. The demo runs **base Qwen3.5-2B + RAG + guard**.
- Autonomous driving, SLAM, or detection of boxes. COCO has no box class.

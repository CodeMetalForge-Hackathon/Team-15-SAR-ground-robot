# CAM-20 — Pi camera orientation check on the wheeled-robot mount (`orient-1794095449791`)

**Label:** REAL HARDWARE (Pi 5 + IMX708 on the wheeled robot, Tailscale). **Status:** COMPLETE. Rotation 180 was verified upright and accepted by the operator.

**In plain words.** The first Pi photo of a person came out upside down, so before the next person test we checked the camera's orientation on the robot with a single picture of the room. One copy was left as delivered and one rotated by 180°. In the rotated copy, ceiling tiles and lights were at the top, so 180° became the confirmed setting. The check also measured exposure and sharpness to confirm the lens was clear.

## 1. Objective and hypothesis

Decide whether the receiver should rotate the Pi's frames by 0° or 180° at the robot mount, and confirm that only one rotation is applied in the pipeline (no double rotation). Hypothesis: the bench inversion (CAM-17) came from the camera being the other way up on the bench, not from a software bug.

## 2. Date, hardware, software

| | |
|---|---|
| Capture time | 2026-11-07 23:50:49 UTC (`capture_time` 1794095449.79; the file name uses milliseconds) |
| Hardware | Raspberry Pi 5 Model B Rev 1.1, `imx708`, on the wheeled robot, CanaKit wall adapter |
| Software | `perception/orientation_check.py` (first in local commit `29c7336`, rewritten into `d847270`, pushed to PR #3) |
| Settings | 1280×720, 5 fps, rotation 0 at capture, 3 s auto-exposure settle |

## 3. Data and N

One frame (Pi frame seq 17), saved as `rot0.png`, `rot180.png` and a side-by-side `compare.jpg`, plus `report.json`.

## 4. Procedure

```bash
python3 -m perception.orientation_check --pi-host "$PI_HOST" --pi-user "$PI_USER" --pi-key "$TEAM15_PI_KEY"
```

The tool waits 3 s for auto-exposure, keeps the last frame, computes the statistics, and writes the files without overwriting (open mode `xb`). The session assistant and the operator viewed the comparison image and picked the upright version.

## 5. Ground truth and criteria

Human judgement of "up" from scene cues (ceiling tiles and lights at the top). The automated exposure criteria in `frame_stats()`: mean luma in [40, 215], at most 25% clipped pixels at either end, and Laplacian variance ≥ 30 (lens not blocked or badly blurred).

## 6. Results

| Measure | Value | Pass? |
|---|---|---|
| Exposure | 18,473 µs; analogue gain 1.50; libcamera lux estimate 264.8 | — |
| Mean luma | 123.8 | yes (40–215) |
| Fraction dark (< 10) / bright (> 245) | 0.0252 / 0.0039 | yes (≤ 0.25) |
| Laplacian variance (sharpness) | 63.3 | yes (≥ 30) |
| `exposure_ok` | true | yes |
| Pi-reported `sensor_mount_rotation` | 180 (a fixed device-tree value) | not used as truth |
| Pi transform | identity | single rotation, on the receiver |
| **Upright version** | **rotation 180** | operator accepted (session console log 23:53 UTC) |

Outcome: `DEFAULT_PI_ROTATION = 180` in `perception/pi_source.py`, with a comment citing this check. Regression tests `test_default_rotation_is_robot_mount_180`, `test_robot_mount_frame_is_upright_with_defaults` and `test_single_rotation_only` are in `perception/tests/test_orientation.py`.

## 7. Failures, confounders and a contradiction

- **The report contains a stale warning.** It has a `double_rotation_if_receiver_180` field reading "possible double rotation: the Pi already compensates a 180 deg mount, and the receiver rotates another 180 deg". That warning came from the earlier local commit (`29c7336`), which wrongly defaulted to 0°. It was removed in `d847270`, because it would fire on the correct setting. The decision rests on the image, not on that field.
- **Camera aim:** the frame showed the camera pointing sideways and tilted a few degrees at a close door frame. The operator re-aimed it before the 2026-11-08 tests.
- **Privacy:** the frame shows part of a person (sleeve or torso, no face) whose consent was not recorded. `DO_NOT_TRAIN_OR_DISTRIBUTE.txt` sits beside the files. The images must not be shared or used for training.

## 8. Evidence files (private, `$TEAM15_EVIDENCE/orientation_checks/`)

| File | SHA-256 |
|---|---|
| `$TEAM15_EVIDENCE/orientation_checks/orient-1794095449791_report.json` | `0a0a359402b0923eab2a698b5c0d142278e6540c5947b51305b94415fcb405a2` |
| `$TEAM15_EVIDENCE/orientation_checks/orient-1794095449791_rot0.png` (not distributable) | `cdfa67aab53bb37d43cac3b24178f36e7ae013f4f10239a95f3865be76b77a0a` (as recorded in the report) |
| `$TEAM15_EVIDENCE/orientation_checks/orient-1794095449791_rot180.png` (not distributable) | `4c52406ef3e0a9ab039417f493cd3978dc72651bcb9150aa8e134c6140ffb66c` (as recorded) |
| `$TEAM15_EVIDENCE/orientation_checks/orient-1794095449791_compare.jpg` (not distributable) | `df52f578cea4bd335dc92e7e0a340c8c65fc29822b2be3fb1e253d04aa36c119` (as recorded) |

## 9. Limitations

Valid only for this physical mount. The decision is a human visual judgement, with no automatic horizon test. It does not verify level (roll) or tilt (pitch), which matter for ground-plane distance ([05 Depth and distance](../../05_DEPTH_AND_DISTANCE_ESTIMATION.md)).

## 10. What this proves / does not prove

- **Proves:** with the camera in that mount, receiver rotation 180 gives upright frames, and the pipeline applies exactly one rotation.
- **Does not prove:** the correct rotation after any remount. Re-run the check every time.

## 11. Reproducibility and next time

Use the command in §4 with no people in view. Next time, point the camera at a scene with text or a door, and make sure the frame really is free of people before capture.

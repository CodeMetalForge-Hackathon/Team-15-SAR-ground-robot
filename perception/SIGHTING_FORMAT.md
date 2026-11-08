# Bench camera sighting format (T1 → T2)

`python3 -B -m perception.live_camera` prints **one JSON line per sighting** on
stdout. It also appends the same line to `sightings.jsonl` in the evidence dir
(default `~/Team15_evidence/camera`, which must be outside any Git work tree).
Diagnostics go to stderr only, so stdout can be piped straight into
`POST /observations`.

## One sighting per person
Repeated frames of the same candidate are **attached** to the sighting, not
re-emitted:

- **First sighting:** needs 3 consecutive frames that pass the trigger rule below.
- **Later frames:** while the candidate keeps reappearing, nothing new is emitted.
  This includes short drop-outs and pose changes such as standing to seated.
- **New sighting:** only after the candidate has been absent for 60 s (`--rearm-s`,
  matching the guide's SYNTHETIC same-drone/same-cell dedup window).
- **Across runs:** each run has its own `boot_id` (`b<epoch>`), so `obs_id`s never
  collide between runs.
- **Limit:** the bench camera has no identity. Two people in view at the same
  time give one sighting.

## Trigger rule and detector labels
Every detector runs on every frame. Each result is labeled with its family and
never merged with another family:

| `detector_family` | Detector | Raises a sighting by default? |
|---|---|---|
| `PERSON_DETECTOR` | torchvision Faster R-CNN ResNet-50 FPN v2, COCO-pretrained, class "person" | **yes** (score ≥ 0.6, box height ≥ 15 % of frame) |
| `FULL_BODY_HOG` | OpenCV HOG people detector (the original full-body detector) | no (only with `--trigger any`) |
| `UPPER_BODY_HAAR` | OpenCV Haar upper-body | no (only with `--trigger any`) |
| `FACE_ONLY` | OpenCV Haar frontal face (sees a face, not a body) | no (only with `--trigger any`) |

`confidence` is always `null`, because none of these scores is a calibrated
probability. Show `evidence.detector_score` together with
`evidence.detector_score_kind`, plus `evidence.detector_family`.

## Fields
| Field | Meaning |
|---|---|
| `obs_id` | `{drone}-{boot}-{seq:06d}`, unique per sighting |
| `drone_id`, `boot_id`, `seq` | declared drone (`--declare-drone`, default D1), run id, sighting number in the run |
| `source_mode` / `platform` | always `LIVE-HW` / `BENCH`. Not an aerial detection. |
| `sensor` / `kind` / `how` | `rgb` / `PERSON_VISUAL` / `SECTOR_ONLY` |
| `cell`, `cell_source` | sector assigned by the operator (`--sector G`), `OPERATOR_ASSIGNED`. It is not measured. |
| `operator` | optional `--operator` id, else null |
| `obs_time`, `obs_time_iso` | capture time of the evidence frame (epoch s, and UTC ISO-8601) |
| `evidence.frame_ref` | absolute path of the **exact, unannotated** evidence frame (lossless PNG) on the capturing Mac |
| `evidence.frame_sha256` | SHA-256 of that PNG |
| `evidence.annotated_ref` | JPEG copy with all boxes drawn (for display) |
| `evidence.bbox` | `[x, y, w, h]` of the triggering box, in `frame_size` pixels |
| `evidence.count_in_frame` | boxes of the trigger family in that frame (may include bystanders and reflections) |
| `evidence.detections_in_frame` | every detection in that frame, each with its own `family` |

| `evidence.camera` | camera and transport provenance (below). Additive field: older sightings may not have it |

Not sent (ingest adds them): `rx_time`, `stale_after_s`.

## Camera sources (`--source local|pi`)
- `local` (default): this machine's camera, as before. `obs_time` is the time the
  frame was read. `evidence.camera` = `{"source": "local", "transport": "local", ...}`.
- `pi`: the Raspberry Pi 5 camera (Sony IMX708), sent as JPEG frames over SSH
  (see `perception/pi_source.py`). Nothing is installed on the Pi: the sender
  script is sent over SSH stdin and runs in memory.
  - `obs_time` is the **Pi's capture time** of the evidence frame (the
    picamera2 `SensorTimestamp` mapped to the Pi's NTP wall clock), not the Mac
    arrival time. `evidence.camera.rx_time` is the arrival time and
    `capture_to_rx_s` is the gap between the two.
  - Orientation: exactly one software rotation, on the receiver
    (`--pi-rotation`, default 180 for the wheeled-robot mount, verified with
    `python -m perception.orientation_check`). The Pi requests an identity
    transform; it reports `sensor_mount_rotation` (a fixed device-tree value,
    180, compensated by libcamera regardless of the physical mount) and
    `pi_transform`, both recorded in `evidence.camera`. The dashboard does not
    rotate images. Re-run the orientation check after any remount. The saved
    PNG, the `bbox` and `frame_size` are all in the rotated, upright image.
  - Sighting `D1-b1794091323-000001` (bench mount, `rotation_deg: 180`) is
    upside down because the camera was the other way up on the bench. It is
    kept unchanged as historical evidence; its checksums still match.
  - Only the newest frame is processed. Older frames that arrive in a burst are
    dropped (counted in the run summary under `pi_stream`).
  - `evidence.camera` example:
    `{"source": "pi5-imx708", "device": "Raspberry Pi camera (remote, bench)", "pi_model": "Raspberry Pi 5 Model B Rev 1.1", "sensor_model": "imx708", "transport": "ssh-jpeg", "stream_size": [1280, 720], "stream_fps": 5.0, "jpeg_quality": 80, "rotation_deg": 180, "rotation_applied_by": "receiver", "sensor_mount_rotation": 180, "pi_transform": "<libcamera.Transform 'identity'>", "capture_clock": "sensor", "pi_frame_seq": 62, "capture_time": 1794090200.898, "rx_time": 1794090201.11, "capture_to_rx_s": 0.212}`
    `sensor_model` and `pi_model` are reported by the Pi at connect time, not assumed.
    `capture_clock` is `sensor`, or `pi_wall_at_request` if the sensor timestamp
    was missing or implausible.
  - Still a bench camera: `source_mode`/`platform` stay `LIVE-HW`/`BENCH`, `cell` is
    operator-assigned, `how` is `SECTOR_ONLY`, and the sighting stays unconfirmed
    until an operator acts on the dashboard. The Pi camera is not airborne and
    gives no position.
  - Exit code 3 if the Pi can't be reached or the stream is lost (after 3 reconnect
    attempts, or no frame for 60 s).

## Example (real bench sighting, 2026-11-07, teammate standing full body)
```json
{"obs_id": "D1-b1794078678-000001", "drone_id": "D1", "boot_id": "b1794078678", "seq": 1, "source_mode": "LIVE-HW", "platform": "BENCH", "sensor": "rgb", "kind": "PERSON_VISUAL", "how": "SECTOR_ONLY", "cell": "G", "cell_source": "OPERATOR_ASSIGNED", "operator": null, "obs_time": 1794078679.624, "obs_time_iso": "2026-11-07T19:11:19.624+00:00", "confidence": null, "evidence": {"frame_ref": "$TEAM15_EVIDENCE/camera/D1-b1794078678-000001.png", "frame_sha256": "6bf7b492335e8a558f82756b331cd72681778819f848c9fb5569b9d30856850c", "annotated_ref": "$TEAM15_EVIDENCE/camera/D1-b1794078678-000001_annotated.jpg", "frame_size": [1920, 1080], "bbox": [842, 512, 196, 565], "detector": "torchvision_frcnn_r50_fpn_v2_coco", "detector_family": "PERSON_DETECTOR", "detector_score": 0.9997, "detector_score_kind": "frcnn_class_score", "count_in_frame": 3, "detections_in_frame": [{"detector": "torchvision_frcnn_r50_fpn_v2_coco", "family": "PERSON_DETECTOR", "bbox": [842, 512, 196, 565], "score": 0.9997, "score_kind": "frcnn_class_score"}, {"detector": "torchvision_frcnn_r50_fpn_v2_coco", "family": "PERSON_DETECTOR", "bbox": [2, 689, 293, 387], "score": 0.9988, "score_kind": "frcnn_class_score"}, {"detector": "torchvision_frcnn_r50_fpn_v2_coco", "family": "PERSON_DETECTOR", "bbox": [625, 766, 61, 75], "score": 0.8593, "score_kind": "frcnn_class_score"}, {"detector": "opencv_haar_frontalface_default", "family": "FACE_ONLY", "bbox": [954, 159, 651, 651], "score": 0.1629, "score_kind": "haar_level_weight"}, {"detector": "opencv_haar_upperbody", "family": "UPPER_BODY_HAAR", "bbox": [762, 435, 351, 288], "score": 1.7701, "score_kind": "haar_level_weight"}]}}
```
In this frame the second person box is a seated bystander and the third is a
reflection in a window. The trigger box is the teammate.

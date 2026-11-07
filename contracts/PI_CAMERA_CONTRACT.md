# Pi camera → Mac detector → dashboard: interface contract

Owner: T2 (integration). Implementer of `perception/`: T1 (camera worker, PR #3).
Code reference: `contracts/pi_frame_stream.py` (stdlib only; import it, don't copy it).

## 1. Transport (tested 2026-11-07 over the venue Tailscale relay)
- The Pi runs a single sender script, piped to `ssh -i ~/.ssh/team15_pi_ed25519 -o BatchMode=yes team15@100.97.93.118 python3 - <args>`. **Nothing is installed or written on the Pi.**
- Sender: picamera2, `create_video_configuration(main={"size": (1280, 720), "format": "RGB888"}, transform=Transform(hflip=1, vflip=1))`, so it is rotated **180° on the Pi** and the frames are already upright. JPEG quality 80, 5 fps.
- Capture time: `capture_time = time.time() - (time.clock_gettime(CLOCK_BOOTTIME) - SensorTimestamp/1e9)`. The Pi clock is NTP-synchronized.
- Each frame is one record: `b"T15F" | u32 BE header_len | header JSON | u32 BE jpeg_len | JPEG`. Header fields are listed in `contracts/pi_frame_stream.py`; required are `seq`, `capture_time`, `w`, `h` and `rotation`.
- Measured: 4.86 fps, 37 KB/frame, 1.4 Mbit/s, capture → Mac median 256 ms, max 460 ms.

## 2. Mac-side frame source: `perception/pi_source.py` (T1)
```python
class PiFrameSource:
    def __init__(self, host="100.97.93.118", user="team15",
                 key="~/.ssh/team15_pi_ed25519", size=(1280, 720), fps=5.0,
                 rotation=180, jpeg_quality=80, read_timeout_s=2.0,
                 cmd: list[str] | None = None): ...
        # cmd overrides the ssh command (tests pass a local fake sender)
    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, "np.ndarray | None"]: ...
        # The NEWEST decoded BGR frame not yet returned (latest-frame-only:
        # older unread frames are dropped and counted). Each frame is returned
        # at most once. Waits up to read_timeout_s; returns (False, None) on
        # timeout or end of stream.
    def release(self) -> None: ...     # terminates ssh, joins the reader thread
    last_capture_time: float | None    # header capture_time of the last frame read()
    last_rx_time: float | None         # Mac time.time() when that record arrived
    last_header: dict | None
    last_jpeg: bytes | None            # the received JPEG bytes of that frame
    frames_received: int
    frames_dropped: int
    def camera_info(self) -> dict: ... # contracts.pi_frame_stream.camera_provenance(...)
```
- Decode records with `contracts.pi_frame_stream.read_record` in a reader thread.
- A bad magic or header is a hard error for the stream: log it to stderr and return `(False, None)`. Never return a guessed frame.

## 3. `perception/live_camera.py` changes (T1)
- `--source local|pi` (default **local**; the laptop camera path stays as it is), plus `--pi-host`, `--pi-user`, `--pi-key`, `--pi-size 1280x720`, `--pi-fps 5`, `--pi-rotation 180`.
- `obs_time = cap.last_capture_time` for the Pi source. **Never** use the Mac receive time. For the local source, keep `time.time()` at read.
- `make_sighting(..., camera=None)`: when given, put it at `evidence.camera`. For the Pi, use `camera_provenance(source=PI5_IMX708, frame_size=(w, h), rotation_deg=180, host=<header host or "raspberrypi">, frame_seq=header["seq"], capture_to_rx_s=last_rx_time - last_capture_time, jpeg_quality=80)`. For local, use `camera_provenance(source=MAC_LOCAL, frame_size=..., rotation_deg=0)`.
- Evidence: keep `frame_ref` (PNG of the decoded frame) and `annotated_ref` as now. Recommended: also save the received JPEG bytes unchanged as `evidence.source_jpeg_ref`, with `evidence.source_jpeg_sha256`.
- Stdout stays one JSON line per sighting. The dedup gate, `boot_id`, the trigger rule and detector labels are unchanged.

## 4. What the dashboard enforces (T2, `core/ingest.py`)
- `evidence.camera` is optional, so old sightings stay valid. They show "camera not reported".
- If present, `camera.source` must be one of `PI5_IMX708` or `MAC_LOCAL`, and `transport` and `capture_clock` must be known values.
- `PI5_IMX708` sightings must be `source_mode=LIVE-HW`, `platform=BENCH`, `how=SECTOR_ONLY`, `cell_source=OPERATOR_ASSIGNED`, `capture_clock=PI_SENSOR_TIMESTAMP_NTP`. Otherwise they are rejected with 422.
- `SECTOR_ONLY` sightings must not carry coordinates (`xy_m`, `lat`, `lon`, `alt_m`, `bearing_deg`). Otherwise they are rejected with 422.
- `obs_time` is stored as sent. If `obs_time_iso` is present, it must agree with `obs_time` to within 1 s. `rx_time` is added separately. A sighting more than 2 s in the dashboard's future is flagged `clock_skew` (shown, not rejected).
- A sender can never set `confirmation`. Every sighting starts `unconfirmed`.
- Duplicates are dropped by `obs_id` and by `evidence.frame_sha256`.

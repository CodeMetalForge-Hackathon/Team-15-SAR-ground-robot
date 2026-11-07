# Pi camera → Mac detector → dashboard: interface contract

Owner: T2 (integration). `perception/` is owned by T1 (camera worker, PR #3).
**This describes what shipped in PR #3 `4d3093d`.** The first draft of this contract (binary `T15F` records, `PiFrameSource`, `PI5_IMX708`) was superseded before anyone used it.

## 1. Transport (owned by `perception/pi_source.py`)
- `ssh -T -o BatchMode=yes … python3 -u - W H FPS Q` with `SENDER_SCRIPT` on stdin. **Nothing is installed or written on the Pi.**
- Stream: one `T15HELLO {json}\n` (sensor model, Pi model, size, fps), then `T15FRAME {json}\n<len bytes of JPEG>` per frame. The frame header has `seq`, `t_capture`, `clock` and `len`.
- The wire format is private to `perception/pi_source.py`: sender and receiver live in one file, so it can't drift. T2 doesn't parse it.
- `PiCameraSource` / `open_pi_camera()`:
  - same `read()` / `release()` / `isOpened()` as `cv2.VideoCapture`;
  - newest frame only, and a frame is never returned twice;
  - the 180° rotation is applied **on arrival**;
  - reconnects up to 3 times;
  - exits with code 3 when the stream is lost.

## 2. `evidence.camera` (see `contracts/camera_provenance.py`)
| field | Pi (`--source pi`) | local (`--source local`, default) |
|---|---|---|
| `source` | `pi5-imx708` (as reported by the Pi; `pi-unknown` if not) | `local` |
| `transport` | `ssh-jpeg` | `local` |
| `capture_clock` | `sensor` (fallback `pi_wall_at_request`) | `receiver_wall_at_read` |
| `capture_time` | Pi capture time of the evidence frame (= `obs_time`) | — |
| `rx_time`, `capture_to_rx_s` | Mac arrival time, and arrival − capture | — |
| also | `device`, `pi_model`, `sensor_model`, `stream_size`, `stream_fps`, `jpeg_quality`, `rotation_deg`, `rotation_applied_by`, `pi_frame_seq` | `device`, `rotation_deg` |

## 3. What the dashboard enforces (`core/ingest.py`)
- `evidence.camera` is optional. Older sightings stay valid and show "camera not reported".
- **Pi sightings** are rejected with 422 unless all of these hold:
  - `source_mode=LIVE-HW`, `platform=BENCH`, `how=SECTOR_ONLY`, `cell_source=OPERATOR_ASSIGNED`;
  - `transport=ssh-jpeg`;
  - `capture_clock` is a Pi clock;
  - `obs_time` equals `camera.capture_time` (to within 2 ms). The sighting time is the Pi capture time, never the Mac arrival time.
- **Local sightings** must have `transport=local` and `capture_clock=receiver_wall_at_read`.
- **Any other** `camera.source` is rejected with 422.
- `SECTOR_ONLY` sightings must not carry coordinates (`xy_m`, `lat`, `lon`, `alt_m`, `bearing_deg`).
- If `obs_time_iso` is present, it must agree with `obs_time` to within 1 s.
- A capture time more than 2 s in the dashboard's future is flagged `clock_skew`, not hidden.
- `rx_time` (dashboard ingest time) is stored separately. `obs_time` is never rewritten.
- A sender can never set `confirmation`. Every sighting starts `unconfirmed`.
- Duplicates are dropped by `obs_id` and by `evidence.frame_sha256`.

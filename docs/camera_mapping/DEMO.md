# Camera mapping demo: launch commands

The robot stays **stationary**. No motor, StickC or firmware step is involved.

## Before you start

- Get the participants' consent before pointing the camera at people.
- Aim the camera along the floor of the demo corridor. On 2026-11-08 at 06:23 it faced a plain wall.
- Check that no other process holds the Pi camera:

```bash
ssh team15-pi 'pgrep -af "picamera|rpicam"'   # must print nothing
```

## Terminal 1: dashboard

```bash
cd ~/Documents/Team-15-wt/camera-mapping
python3 -B -m dashboard.serve --port 8000
```

Open http://localhost:8000/. Panels A–D are below the existing sector map.

## Terminal 2: Qwen advisory service (optional, RAG + guard)

```bash
curl -s localhost:11434/api/version     # Ollama must answer
python3 -B -m camera_mapping.qwen_launcher --qwen-root ~/Documents/Team-15-Qwen --port 8090
```

## Terminal 3: live camera perception

```bash
python3 -B -m camera_mapping.live --source pi --pi-host team15-pi \
    --dashboard http://127.0.0.1:8000 --qwen-url http://127.0.0.1:8090 \
    --jsonl ~/Team15_evidence/camera_mapping/run-$(date +%H%M).jsonl
```

Add `--depth metric` to show the mono-depth cross-check (≈117 ms extra every 3rd frame).

## Without the Pi

Replay recorded Pi frames. They are labelled RECORDED, never LIVE:

```bash
python3 -B -m camera_mapping.live --source replay --replay "$HOME/Team15_evidence/camera_pi_validation/*.png" --dashboard http://127.0.0.1:8000
```

## Demo script

1. **Empty corridor.** Panel B shows FREE cells in the FOV. The corridor reads CLEAR only if the mount was measured; otherwise UNKNOWN.
2. **Chair at about 1 m on the centreline.** Panel A shows `chair ~1.0 m ±…` (UNCALIBRATED_ESTIMATE). Panel B shows a red footprint and an UNKNOWN shadow behind it. Panel C shows **BLOCKED** and "Hold position".
3. **Move the chair to the side.** The corridor reads CLEAR or CAUTION, and a route appears (solid = observed-free, dashed = through unobserved space).
4. **A person walks in.** Panel C shows "Potential person detected · UNCONFIRMED" and Qwen explains the scene, citing RAG sources.
5. **Stop the camera (Ctrl-C).** Panel D shows STOPPED; the map goes STALE and the assessment UNKNOWN.

## Stop everything

Press Ctrl-C in each terminal.

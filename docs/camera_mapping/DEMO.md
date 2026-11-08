# Camera mapping demo: launch

The robot stays **stationary**. No motor, StickC or firmware step is involved. Get participants' consent before pointing the camera at people.

## One command

```bash
cd ~/Documents/Team-15-wt/camera-mapping
scripts/camera_demo.sh               # live Pi camera + Qwen RAG advisor + dashboard on :8000
```

| Variant | Command |
|---|---|
| No Pi: recorded Pi frames, labelled **RECORDED** | `scripts/camera_demo.sh --replay` |
| Deterministic advisory only | `scripts/camera_demo.sh --no-qwen` |
| Add the mono-depth cross-check (unvalidated, not fused; about 126 ms every third frame) | `scripts/camera_demo.sh --depth` |
| Other port | `PORT=8001 scripts/camera_demo.sh` |
| Other Pi host | `PI_HOST=team15-pi scripts/camera_demo.sh` |

Preflight checks:

- Python dependencies are installed.
- The dashboard port is free.
- SSH to the Pi works.
- The **Pi camera is not in use** (nothing is killed).
- Ollama is up. If it is not, the advisor degrades to deterministic and says so.

The script then:

- opens http://localhost:8000/ (panels A–D are below the sector map);
- prints a status line every 5 s;
- writes logs and a `perception.jsonl` (state only, no images) to `~/Team15_evidence/camera_mapping/<timestamp>/`.

If the camera runner stops, the dashboard stays up and shows STALE → UNKNOWN, and the runner is restarted (up to 5 times). Ctrl-C stops everything the script started.

Qwen is **base Qwen3.5-2B (Ollama `qwen3.5:2b-q4_K_M`) + RAG + guard** through `rescue_qwen.service`. **The LoRA adapter is not deployed.** If Ollama or the service is down, the deterministic summary is shown and labelled.

## Manual (three terminals)

```bash
python3 -B -m dashboard.serve --port 8000
python3 -B -m camera_mapping.qwen_launcher --qwen-root ~/Documents/Team-15-Qwen --port 8090
python3 -B -m camera_mapping.live --source pi --pi-host team15-pi --dashboard http://127.0.0.1:8000 --qwen-url http://127.0.0.1:8090
```

The judge script is in `JUDGE_DEMO.md`; calibration is in `CALIBRATION.md`.

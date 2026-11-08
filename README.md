# Team-15: search-and-rescue ground robot (CodeMetal Forge 2026)

A teleoperated wheeled rescue robot (M5Stack RoverC-Pro with a Raspberry Pi 5 and camera; RPLIDAR C1 in progress).

- **Perception:** a camera-based person-candidate detector, with results shown on an operator dashboard.
- **Navigation:** route planning and a safety supervisor, tested in simulation; hardware is gated.
- **Qwen:** an optional local assistant that explains evidence and proposes read-only mission steps.

**Safety model:** people stay in the loop. The operator confirms or rejects every person candidate. The motion code is deterministic, and the safety supervisor and e-stop are deterministic. **Qwen has no autonomous rover-motion authority.**

## Repository layout

| Path | What |
|---|---|
| `perception/` | camera person-candidate pipeline |
| `dashboard/` | operator dashboard |
| `planner/` | route graph and planner |
| `rover/` | RoverC-Pro navigation and safety supervisor (simulation-tested) |
| `ranging/` | range-sensor handling |
| `contracts/`, `core/`, `fixtures/`, `tests/` | shared contracts, core code, fixtures and end-to-end tests |
| `docs/` | design documents; `docs/qwen/` for the Qwen model |

Run the tests with `pip install -r requirements.txt && pytest -q`.

## Qwen rescue intelligence (advisory only)

| | |
|---|---|
| Base model | [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) (Apache-2.0), revision `15852e8c` |
| Fine-tuning | LoRA (r 16, α 32), vision frozen, 15.63 M parameters. SFT on 689 records: synthetic mission steps, 7 public Co-GLANCE frames and 4 metadata-only bench-camera rows |
| RAG | SQLite FTS5 over 47 documents (2 marked "cite only") with provenance and an injection quarantine |
| Tool use | one read-only tool request per step, validated by a deterministic safety gate. Guard and deterministic fallback |
| Result | **218/230** correct mission steps on a frozen simulated benchmark, **0** unsafe motion requests (base model under Hugging Face without an output grammar: 0/230, because no output parsed; with Ollama's JSON grammar: 56/230 with RAG). Measured with RAG context |
| Limitations | synthetic, in-distribution benchmark; no hardware evaluation; 2 missed sensor-timeout stops; no transfer to the LiDAR or delivery tasks. The LiDAR LoRA pilot was **not promoted** |

### Model weights / Hugging Face

The adapter is on Hugging Face: **[huggingface.co/MOHDMUBASHIR/team15-qwen3.5-2b-rescue-mission-lora](https://huggingface.co/MOHDMUBASHIR/team15-qwen3.5-2b-rescue-mission-lora) (public, revision `21013d4`)**. The base weights are loaded from the [official Qwen repository](https://huggingface.co/Qwen/Qwen3.5-2B) and are not redistributed. No weights are stored in this Git repository. The repository is public, so no Hugging Face login is needed.

```python
from peft import PeftModel
from transformers import AutoModelForImageTextToText, AutoProcessor
import torch
proc = AutoProcessor.from_pretrained("Qwen/Qwen3.5-2B", revision="15852e8c16360a2fea060d615a32b45270f8a8fc")
model = AutoModelForImageTextToText.from_pretrained("Qwen/Qwen3.5-2B", revision="15852e8c16360a2fea060d615a32b45270f8a8fc", dtype=torch.bfloat16)
model = PeftModel.from_pretrained(model, "MOHDMUBASHIR/team15-qwen3.5-2b-rescue-mission-lora").eval()
```

The architecture, training, RAG and tool-use workflow, full benchmarks and limitations are in [docs/qwen/MODEL.md](docs/qwen/MODEL.md).

## License

See [LICENSE](LICENSE). Qwen3.5-2B is licensed under Apache-2.0 by the Qwen team.

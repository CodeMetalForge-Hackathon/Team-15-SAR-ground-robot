#!/usr/bin/env bash
# Launch the dual-robot search-and-rescue SIMULATION (aerial scout + ground rover) on localhost.
# Offline: needs no Raspberry Pi, no robot, no internet. Qwen is optional (deterministic fallback).
#
#   scripts/run_dual_rescue.sh                 # http://localhost:8000/rescue
#   PORT=8010 QWEN_URL=http://127.0.0.1:8090 scripts/run_dual_rescue.sh
#   EVIDENCE_DIR=~/Team15_evidence/camera scripts/run_dual_rescue.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
QWEN_URL="${QWEN_URL:-}"
EVIDENCE_DIR="${EVIDENCE_DIR:-$HOME/Team15_evidence/camera}"
args=(--port "$PORT")
if [[ -z "$QWEN_URL" ]] && curl -fsS -m 2 http://127.0.0.1:8090/health >/dev/null 2>&1; then
  QWEN_URL="http://127.0.0.1:8090"
fi
[[ -n "$QWEN_URL" ]] && args+=(--qwen-url "$QWEN_URL") && echo "Qwen advisory: $QWEN_URL (display only, authority NONE)"
[[ -z "$QWEN_URL" ]] && echo "Qwen advisory: not running -> reports use the labelled DETERMINISTIC fallback"
[[ -d "$EVIDENCE_DIR" ]] && args+=(--rescue-evidence-dir "$EVIDENCE_DIR") && echo "Recorded camera evidence: $EVIDENCE_DIR"
echo "Open http://localhost:${PORT}/rescue   (P = presentation mode, Space = start/pause, 1-7 = cameras)"
exec python3 -m dashboard.serve "${args[@]}"

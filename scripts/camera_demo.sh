#!/usr/bin/env bash
# Team-15 camera mapping judge demo: dashboard + Qwen RAG advisory + live camera perception.
#
#   scripts/camera_demo.sh                 # live Pi camera (default)
#   scripts/camera_demo.sh --replay        # recorded Pi frames, labelled RECORDED (no Pi needed)
#   scripts/camera_demo.sh --no-qwen       # deterministic advisory only
#   scripts/camera_demo.sh --depth         # add the (unvalidated) mono-depth cross-check
#
# Env overrides: PORT (8000), QWEN_PORT (8090), PI_HOST (team15-pi), QWEN_ROOT (~/Documents/Team-15-Qwen),
#                REPLAY_GLOB ($HOME/Team15_evidence/camera_pi_validation/*.png)
# Nothing here touches motors, the StickC bridge or firmware. Ctrl-C stops everything it started.
set -u
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"; QWEN_PORT="${QWEN_PORT:-8090}"; PI_HOST="${PI_HOST:-team15-pi}"
QWEN_ROOT="${QWEN_ROOT:-$HOME/Documents/Team-15-Qwen}"
REPLAY_GLOB="${REPLAY_GLOB:-$HOME/Team15_evidence/camera_pi_validation/*.png}"
SOURCE=pi; QWEN=1; DEPTH=()
for a in "$@"; do
  case "$a" in
    --replay) SOURCE=replay ;;
    --no-qwen) QWEN=0 ;;
    --depth) DEPTH=(--depth metric) ;;
    -h|--help) sed -n 2,12p "$0"; exit 0 ;;
    *) echo "unknown option $a"; exit 2 ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$HOME/Team15_evidence/camera_mapping/$STAMP"     # outside Git: may describe people
mkdir -p "$LOG"
PIDS=()
cleanup() {
  trap - EXIT INT TERM
  echo; echo "stopping demo processes..."
  for p in ${PIDS[@]+"${PIDS[@]}"}; do [ -n "$p" ] && kill "$p" 2>/dev/null; done
  wait 2>/dev/null
  echo "logs: $LOG"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM      # must exit: otherwise the restart loop would carry on

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; exit 1; }
port_busy() { lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
wait_http() { for _ in $(seq 1 60); do curl -sf "$1" >/dev/null && return 0; sleep 0.5; done; return 1; }

echo "== preflight"
python3 -c "import torch, torchvision, cv2, fastapi, uvicorn" 2>/dev/null || fail "python deps missing (torch/torchvision/cv2/fastapi/uvicorn)"
ok "python deps"
port_busy "$PORT" && fail "port $PORT busy (another dashboard?). Use PORT=8001 $0"
ok "dashboard port $PORT free"
python3 - <<'EOF' || fail "camera_mapping config unreadable"
from camera_mapping.config import load_config
c = load_config("camera_mapping/configs/imx708_robot.json")
print(f"       calibration={c.calibration_status} mount_measured={c.mount.usable} intrinsics={c.camera.source}")
if not c.mount.usable:
    print("       NOTE: mount unmeasured -> distances via ground plane UNKNOWN, corridor never CLEAR, no routes")
EOF
if [ "$SOURCE" = pi ]; then
  ssh -o BatchMode=yes -o ConnectTimeout=6 "$PI_HOST" true 2>/dev/null \
    || fail "cannot ssh to $PI_HOST. Fix Tailscale/SSH, or run: $0 --replay"
  ok "ssh $PI_HOST"
  busy="$(ssh -o BatchMode=yes "$PI_HOST" "ps -eo pid,args | grep -E '[p]icamera2|[r]picam-|[p]ython3 -u -'" 2>/dev/null)"
  [ -n "$busy" ] && fail "Pi camera already in use:\n$busy\n(stop that session first; nothing was killed)"
  ok "Pi camera free"
else
  ls $REPLAY_GLOB >/dev/null 2>&1 || fail "no replay frames at $REPLAY_GLOB"
  ok "replay frames (labelled RECORDED on the dashboard)"
fi
QWEN_URL=()
if [ "$QWEN" = 1 ]; then
  if ! curl -sf localhost:11434/api/version >/dev/null; then
    warn "Ollama not answering: advisory will be DETERMINISTIC only (start 'ollama serve' to enable Qwen)"
  elif port_busy "$QWEN_PORT"; then
    if curl -sf "localhost:$QWEN_PORT/health" | grep -q '"advisory_only":true'; then
      ok "reusing Qwen advisory service on :$QWEN_PORT"; QWEN_URL=(--qwen-url "http://127.0.0.1:$QWEN_PORT")
    else
      warn "port $QWEN_PORT busy with something else: advisory DETERMINISTIC only"
    fi
  else
    python3 -B -m camera_mapping.qwen_launcher --qwen-root "$QWEN_ROOT" --port "$QWEN_PORT" > "$LOG/qwen.log" 2>&1 &
    PIDS+=($!)
    if wait_http "http://127.0.0.1:$QWEN_PORT/health"; then
      ok "Qwen3.5-2B base + RAG + guard on :$QWEN_PORT (LoRA adapter NOT deployed)"
      QWEN_URL=(--qwen-url "http://127.0.0.1:$QWEN_PORT")
      # warm the model so the first judge-visible advisory is not a cold load
      curl -s -m 60 -X POST "localhost:11434/api/generate" -d '{"model":"qwen3.5:2b-q4_K_M","prompt":"ok","stream":false,"think":false,"options":{"num_predict":1}}' >/dev/null || true
    else
      warn "Qwen service failed to start (see $LOG/qwen.log): DETERMINISTIC only"
    fi
  fi
fi

echo "== starting"
python3 -B -m dashboard.serve --port "$PORT" > "$LOG/dashboard.log" 2>&1 &
PIDS+=($!)
wait_http "http://127.0.0.1:$PORT/api/perception" || fail "dashboard did not start (see $LOG/dashboard.log)"
ok "dashboard  http://localhost:$PORT/"

if [ "$SOURCE" = pi ]; then SRC=(--source pi --pi-host "$PI_HOST"); else SRC=(--source replay --replay $REPLAY_GLOB); fi
start_camera() {
  python3 -B -m camera_mapping.live "${SRC[@]}" --dashboard "http://127.0.0.1:$PORT" ${QWEN_URL[@]+"${QWEN_URL[@]}"} ${DEPTH[@]+"${DEPTH[@]}"} \
    --jsonl "$LOG/perception.jsonl" >> "$LOG/camera.log" 2>&1 &
  CAM=$!; PIDS+=($CAM)
}
start_camera

for _ in $(seq 1 90); do
  n="$(curl -sf "localhost:$PORT/api/perception/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["frames_received"])' 2>/dev/null || echo 0)"
  [ "${n:-0}" -gt 0 ] && break
  kill -0 $CAM 2>/dev/null || { tail -5 "$LOG/camera.log"; fail "camera runner exited"; }
  sleep 1
done
[ "${n:-0}" -gt 0 ] || { tail -5 "$LOG/camera.log"; fail "no frames reached the dashboard in 90 s"; }
ok "camera frames flowing ($SOURCE)"
command -v open >/dev/null && open "http://localhost:$PORT/#percep"

echo
echo "== DEMO RUNNING: http://localhost:$PORT/  (panels A-D below the sector map)"
echo "   source=$SOURCE  qwen=$([ ${#QWEN_URL[@]} -gt 0 ] && echo 'base Qwen3.5-2B + RAG (guarded)' || echo 'deterministic only')"
echo "   logs: $LOG    Ctrl-C to stop"
# The dashboard stays up if the camera runner stops: it shows STALE -> UNKNOWN (never the last status).
# The runner is restarted up to MAX_RESTARTS times (e.g. a Wi-Fi drop on the Pi stream).
MAX_RESTARTS="${MAX_RESTARTS:-5}"; restarts=0
while true; do
  if ! kill -0 $CAM 2>/dev/null; then
    tail -3 "$LOG/camera.log"
    if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
      warn "camera runner stopped $restarts times; dashboard stays up showing STALE/UNKNOWN. Ctrl-C to exit."
      while kill -0 "${PIDS[0]}" 2>/dev/null || curl -sf "localhost:$PORT/api/perception" >/dev/null; do sleep 5; done
      exit 1
    fi
    restarts=$((restarts + 1))
    warn "camera runner stopped; dashboard now shows STALE/UNKNOWN. Restart $restarts/$MAX_RESTARTS in 5 s"
    sleep 5
    start_camera
  fi
  sleep 5
  curl -sf "localhost:$PORT/api/perception" | python3 -c 'import json,sys
s=json.load(sys.stdin); a=s.get("assessment",{})
o=", ".join("%s#%s" % (x["object_class"], x["track_id"]) for x in s.get("objects",[])) or "none"
print("   [%s] corridor=%s objects=%s det=%sms" % (s.get("status"), a.get("status"), o, (s.get("latency_ms") or {}).get("detector_ms")))' 2>/dev/null
done

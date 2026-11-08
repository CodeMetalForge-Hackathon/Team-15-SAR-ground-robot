#!/bin/bash
# One command for the drone demo. From the repo root:
#
#   ./crazyflie/run_demo.sh 3                         fly 3 ft to the phone
#   RSSI_CAL="1:-52 3:-63" ./crazyflie/run_demo.sh 3   hop from the phone's signal, never past 3 ft
#
# It starts mission control (http://127.0.0.1:8080) and the ESP scanner with the phone
# verifier (http://127.0.0.1:8765), or reuses them if they are already running, waits for
# the phone, asks you to confirm the drone is ready, then flies. Ctrl+C lands the drone.
# Servers it started keep running for the operator view until you press Ctrl+C at the end.
#
# Settings (environment variables, all optional):
#   ESP_PORT   serial port of the ESP (default: the only /dev/cu.usbmodem*)
#   DRONE      drone address (default ble://Crazyflie)
#   HEIGHT_IN  hover height in inches (default 12)
#   ALIAS      enrolled phone alias (default 1)
#   RSSI_CAL   two calibration readings "1:-52 3:-63" to set the hop from the signal
#   DRY_RUN=1  no drone, no ESP: simulated flight, real mission control
# Anything after the distance is passed to fly_to_phone.py (e.g. --hover-s 6).

set -u
cd "$(dirname "$0")/.." || exit 1

FORWARD_FT="${1:-3}"
[ $# -gt 0 ] && shift
DRONE="${DRONE:-ble://Crazyflie}"
HEIGHT_IN="${HEIGHT_IN:-12}"
ALIAS="${ALIAS:-1}"
MC_URL="http://127.0.0.1:8080"
SCAN_URL="http://127.0.0.1:8765"
STATE="$HOME/t15-demo-state.json"
SCOPE="TESTKEY-demo"
STARTED=()

say() { printf '\n== %s\n' "$*"; }
up() { curl -s -o /dev/null --max-time 1 "$1"; }

cleanup() {
  if [ ${#STARTED[@]} -gt 0 ]; then
    say "Stopping the servers this script started"
    kill "${STARTED[@]}" 2>/dev/null
  fi
}
trap cleanup EXIT

# --- Python environment -----------------------------------------------------------
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "No .venv here. Create it once with: uv venv --python 3.13 .venv && source .venv/bin/activate && uv pip install cflib bleak"
  exit 1
fi

# --- Mission control --------------------------------------------------------------
if up "$MC_URL/"; then
  say "Mission control already running at $MC_URL"
else
  if [ ! -f "$HOME/.config/team15/network.json" ]; then
    python -m mission_control.server --init || exit 1
  fi
  say "Starting mission control (log: /tmp/t15-mission-control.log)"
  python -m mission_control.server > /tmp/t15-mission-control.log 2>&1 &
  STARTED+=($!)
  for _ in $(seq 1 20); do up "$MC_URL/" && break; sleep 0.5; done
  up "$MC_URL/" || { echo "Mission control did not start:"; tail -5 /tmp/t15-mission-control.log; exit 1; }
fi
echo "   operator view: $MC_URL"

# --- ESP scanner + phone verifier ---------------------------------------------------
FLY_SCAN=(--discovery-url "$SCAN_URL" --alias "$ALIAS" --wait-for-phone 60)
if [ "${DRY_RUN:-0}" = 1 ]; then
  say "DRY RUN: simulated drone and phone"
  FLY_SCAN=()
elif up "$SCAN_URL/api/beacons"; then
  say "Scanner already running at $SCAN_URL"
  if curl -s --max-time 1 "$SCAN_URL/api/beacons" | grep -q '"status": *"off"'; then
    echo "   WARNING: it was started without --test-keys, so the phone can't be verified."
    echo "   Stop it and rerun this script so it starts the scanner itself."
    exit 1
  fi
else
  if [ -z "${ESP_PORT:-}" ]; then
    PORTS=(/dev/cu.usbmodem*)
    if [ ! -e "${PORTS[0]}" ]; then echo "No ESP found (/dev/cu.usbmodem*). Plug it in with a data cable."; exit 1; fi
    if [ ${#PORTS[@]} -gt 1 ]; then echo "Several ports: ${PORTS[*]}. Pick one: ESP_PORT=/dev/cu.usbmodemXXX $0 $FORWARD_FT"; exit 1; fi
    ESP_PORT="${PORTS[0]}"
  fi
  if [ ! -f "$STATE" ]; then
    python -m ble_id init-state --state "$STATE" --scope "$SCOPE" || exit 1
  fi
  say "Starting the ESP scanner on $ESP_PORT (log: /tmp/t15-discovery.log)"
  python -m discovery.server --serial "$ESP_PORT" --test-keys --state "$STATE" --scope "$SCOPE" \
    > /tmp/t15-discovery.log 2>&1 &
  STARTED+=($!)
  for _ in $(seq 1 20); do up "$SCAN_URL/api/beacons" && break; sleep 0.5; done
  if ! up "$SCAN_URL/api/beacons"; then
    echo "Scanner did not start:"; tail -5 /tmp/t15-discovery.log
    echo "If it says busy: another program has $ESP_PORT open (check: lsof $ESP_PORT)."
    exit 1
  fi
fi

# --- Flight -------------------------------------------------------------------------
FLY=(python crazyflie/fly_to_phone.py --height-in "$HEIGHT_IN" --forward-ft "$FORWARD_FT"
     --coordinator "$MC_URL" "${FLY_SCAN[@]}")
if [ -n "${RSSI_CAL:-}" ]; then
  # shellcheck disable=SC2206
  CAL=($RSSI_CAL)
  FLY+=(--distance-from-signal --rssi-cal "${CAL[@]}" --max-forward-ft "$FORWARD_FT")
fi
if [ "${DRY_RUN:-0}" = 1 ]; then
  FLY+=("$@")
else
  FLY+=(--live-drone --uri "$DRONE" "$@")
  say "Preflight"
  echo "   - Crazyflie phone app closed, drone USB unplugged"
  echo "   - drone on its start mark, red/green LEDs pointing at the phone"
  echo "   - patterned paper under the whole path, nothing in the way"
  echo "   - phone ${FORWARD_FT} ft ahead with the beacon app open"
  read -r -p "   Ready to fly? Type yes: " ok
  [ "$ok" = "yes" ] || { echo "Not flying."; exit 0; }
  FLY+=(--preflight-confirmed)
fi

say "Flying (Ctrl+C lands the drone)"
"${FLY[@]}"
RESULT=$?

if [ ${#STARTED[@]} -gt 0 ]; then
  say "Done (exit $RESULT). Servers stay up for the operator view; press Ctrl+C to stop them."
  wait
fi
exit $RESULT

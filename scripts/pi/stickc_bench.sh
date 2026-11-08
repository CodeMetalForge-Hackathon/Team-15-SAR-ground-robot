#!/usr/bin/env bash
# Wheels-lifted bench steps through rover/bench.py (Team-15 bridge firmware only). Stops at the first failure.
#   stickc_bench.sh check  "<operator>" <battery_V>   # status + STOP + firmware watchdog (needs RoverC ON, wheels lifted)
#   stickc_bench.sh pulses "<operator>" <battery_V>   # forward 0.3 s -> STOP -> backward 0.3 s -> STOP  (FINAL APPROVAL)
source "$(dirname "$0")/stickc_common.sh"
STEP=${1:-}; OP=${2:-}; V=${3:-}
[ -n "$OP" ] && [ -n "$V" ] || die "usage: $0 check|pulses <operator> <measured battery volts>"
port_free
B=(python3 -B -m rover.bench --port "$P" --usb-serial 7D520E63EE --operator "$OP" --battery-v "$V" --min-battery-v 3.6 --wheels-lifted)
cd ~/team15_rover
run() {
  echo "== $*" | tee -a "$LOG"
  local out rc=0
  out=$("${B[@]}" "$@" 2>&1) || rc=$?
  printf '%s\n' "$out" >> "$LOG"
  printf '%s\n' "$out" | grep -aE '"(ok|state|state_after_silence|error|direction|raw_y|commanded_s)"' || true
  [ "$rc" = 0 ] || die "$* failed with exit $rc (firmware zeroes on any error; see $LOG)"
}
case "$STEP" in
  check)  run status; run stop; run watchdog; run stop ;;
  pulses) run stop; run forward; sleep 2; run stop; run backward; sleep 1; run stop ;;
  *) die "step must be check or pulses" ;;
esac
echo "DONE $STEP. Now record what you SAW:  python3 -B -m rover.bench record --port $P --usb-serial 7D520E63EE --operator \"$OP\" --wheels-lifted --observed 'PASS: <each wheel, direction, stop>'" | tee -a "$LOG"

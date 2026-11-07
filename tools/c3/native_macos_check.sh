#!/bin/bash
# C3 native macOS tests + REAL iPhone -> ESP32 -> verifier -> browser check.
# PUBLIC SYNTHETIC TEST-KEY MODE (labelled experiment, not a production enrollment).
#   bash ~/Team-15/tools/c3/native_macos_check.sh [/dev/cu.usbmodemXXXX]
# Never stops other processes: if the receiver or port 8765 is busy, it says who and exits.
set -uo pipefail
ROOT="$HOME/Team-15"; cd "$ROOT" || exit 2
[ "$(uname -s)" = Darwin ] || { echo "ERROR: run this on the Mac (native macOS)"; exit 2; }
RUN="c3-native-$(date -u +%Y%m%dT%H%M%SZ)"; E="$ROOT/docs/ble-id/runs/$RUN"; mkdir -p "$E"
CM="$E/commands.log"; : > "$CM"
step() { echo "\$ $*" >> "$CM"; "$@"; local rc=$?; echo "exit=$rc" >> "$CM"; return $rc; }
echo "== $RUN  (evidence: $E)"

echo "== 1/5 Environment"
{ echo "utc: $(date -u +%FT%TZ)"; sw_vers; uname -m
  system_profiler SPHardwareDataType | grep -E "Model Name|Chip|Memory"
  echo "python3: $(command -v python3) $(python3 --version 2>&1)"; echo "node: $(node --version 2>&1)"
  echo "HEAD: $(git rev-parse HEAD)"; echo "status:"; git status --short; } > "$E/environment.txt" 2>&1
cat "$E/environment.txt"

echo "== 2/5 Native macOS tests (pinned pytest 8.3.4 wheels, outside the repo)"
BASE=""; for c in python3.13 python3.12 python3.11 python3.10; do command -v "$c" >/dev/null && { BASE=$(command -v "$c"); break; }; done
[ -n "$BASE" ] || BASE=$(command -v python3)            # stable release preferred over pre-releases
PY="$BASE"; DEPS="$HOME/.olf-c3-pytest-$(basename "$BASE")"
echo "python for tests and dashboard: $BASE ($("$BASE" --version 2>&1))" | tee -a "$E/environment.txt"
# No pip: Homebrew Python's pyexpat can fail on macOS 26, which breaks pip. Fetch pinned pure-Python
# wheels from PyPI, check each against PyPI's published SHA-256, unpack outside the repo.
if ! PYTHONPATH="$DEPS" "$PY" -c "import pytest" 2>/dev/null; then
  step "$PY" - "$DEPS" > "$E/wheels.log" 2>&1 <<'WHEELS' || { echo "ERROR: could not fetch pytest wheels (see wheels.log)"; exit 6; }
import hashlib, io, json, os, sys, urllib.request, zipfile
dest = sys.argv[1]; os.makedirs(dest, exist_ok=True)
for name, ver in {"pytest": "8.3.4", "pluggy": "1.5.0", "iniconfig": "2.0.0", "packaging": "24.2"}.items():
    meta = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=30))
    w = next(u for u in meta["urls"] if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("py3-none-any.whl"))
    data = urllib.request.urlopen(w["url"], timeout=60).read()
    got = hashlib.sha256(data).hexdigest()
    if got != w["digests"]["sha256"]:
        sys.exit(f"checksum mismatch: {w['filename']}")
    zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
    print(w["filename"], "sha256", got, "matches PyPI")
WHEELS
fi
cat "$E/wheels.log" 2>/dev/null
step env PYTHONPATH="$DEPS" "$PY" -B -m pytest -v -p no:cacheprovider tests > "$E/pytest_native_macos.log" 2>&1
echo "pytest exit=$?: $(tail -1 "$E/pytest_native_macos.log")"
step "$PY" -B -m unittest discover -s tests -p test_discovery.py -v > "$E/discovery_unittest_macos.log" 2>&1
echo "discovery unittest exit=$?: $(tail -1 "$E/discovery_unittest_macos.log")"
command -v node >/dev/null && { step node --check discovery/static/app.js && step node --check discovery/static/beacons.js && echo "JS syntax OK"; }

echo "== 3/5 Receiver"
PORT="${1:-}"
if [ -z "$PORT" ]; then
  PORTS=(/dev/cu.usbmodem*); [ ${#PORTS[@]} -eq 1 ] && [ -e "${PORTS[0]}" ] || { echo "ERROR: need exactly one /dev/cu.usbmodem*, found: ${PORTS[*]}"; exit 3; }
  PORT="${PORTS[0]}"
fi
echo "port: $PORT" | tee "$E/receiver.txt"
if lsof "$PORT" >/dev/null 2>&1; then echo "BUSY: $PORT is open by:"; lsof "$PORT" | tee -a "$E/receiver.txt"
  ps -o pid,ppid,etime,command -p "$(lsof -t "$PORT" | paste -sd, -)" | tee -a "$E/receiver.txt"
  echo "Stop that reader (for example the plain discovery server, Ctrl+C in its Terminal), then rerun."; exit 4; fi
if lsof -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then echo "BUSY: port 8765 is in use:"; lsof -iTCP:8765 -sTCP:LISTEN
  echo "Stop that server, then rerun."; exit 4; fi

echo "== 4/5 Live run · PUBLIC SYNTHETIC TEST KEYS · fresh scope and state outside the repo"
SD="$HOME/.olf-c3"; mkdir -p "$SD"; chmod 700 "$SD"
SCOPE="TESTKEY-bench-$RUN"; STATE="$SD/$SCOPE.json"
step "$PY" -m ble_id init-state --state "$STATE" --scope "$SCOPE" | tee -a "$E/receiver.txt"
"$PY" -B -m discovery.server --serial "$PORT" --test-keys --state "$STATE" --scope "$SCOPE" > "$E/server.log" 2>&1 &
SRV=$!; echo "\$ $PY -m discovery.server --serial $PORT --test-keys --state <outside repo> --scope $SCOPE  (pid $SRV)" >> "$CM"
sleep 3
kill -0 $SRV 2>/dev/null || { echo "ERROR: server exited:"; cat "$E/server.log"; exit 5; }
ln -sf "$STATE" "$SD/alias-$RUN.json"
"$PY" -B -m discovery.server --serial "$PORT" --port 8799 --test-keys --state "$SD/alias-$RUN.json" \
  --scope "$SCOPE" > "$E/second_owner_via_symlink.log" 2>&1 &
P2=$!; sleep 4
if kill -0 $P2 2>/dev/null; then kill $P2; echo "second owner via symlink: NOT REFUSED (FAIL)" | tee -a "$E/receiver.txt"
else wait $P2; echo "second owner via symlink: refused, exit=$? $(cat "$E/second_owner_via_symlink.log")" | tee -a "$E/receiver.txt"; fi
rm -f "$SD/alias-$RUN.json"
echo
echo "  >>> Open http://127.0.0.1:8765  ·  On the iPhone: C1 app, mode Rotating, tap Start, keep it in the FOREGROUND."
echo "  >>> Recording /api/beacons for 120 s (counts and receiver status only; no nearby device names)."
"$PY" - "$E/api_snapshots.jsonl" <<'PY'
import json, sys, time, urllib.request
out = open(sys.argv[1], "w")
for i in range(60):
    t = time.time()
    try:
        b = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/beacons", timeout=3))
        d = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/discovery", timeout=3))
        rec = dict(utc=t, beacons=b, discovery=dict(source=d["source"], status=d["status"], packets=d["packets"],
                   malformed=d["malformed"], active=d["active"], signals=len(d["signals"])))
    except Exception as e:
        rec = dict(utc=t, error=str(e))
    out.write(json.dumps(rec) + "\n"); out.flush()
    s = rec.get("beacons", {})
    print(f"\r  t={2*i:3d}s receiver={s.get('receiver', {}).get('status')} verified_cards={len(s.get('sightings', []))} "
          f"verified_tokens={s.get('counts', {}).get('verified:fresh', 0)}   ", end="", flush=True)
    time.sleep(max(0, 2 - (time.time() - t)))
print()
PY
echo "  >>> Capture done. The server is STILL RUNNING so the page can be checked in the browser."
read -r -p "  >>> Press Enter to stop the server... "
kill $SRV; wait $SRV 2>/dev/null

echo "== 5/5 Summary"
"$PY" - "$E" "$STATE" "$SCOPE" <<'PY' | tee "$E/summary.txt"
import json, sys
from ble_state import load_state
E, state, scope = sys.argv[1:4]
recs = [json.loads(l) for l in open(f"{E}/api_snapshots.jsonl")]
ok = [r for r in recs if "beacons" in r]
first = next((r for r in ok if r["beacons"]["sightings"]), None)
last = ok[-1]["beacons"] if ok else {}
print("mode:", last.get("mode_label"), "| source:", last.get("source"), "| scope:", scope)
print("snapshots:", len(recs), "ok:", len(ok), "errors:", len(recs) - len(ok))
print("first verified card at +%.1f s of capture" % (first["utc"] - recs[0]["utc"]) if first else "no verified card")
print("final sightings:", [(s["alias"], s["verified_tokens"], s["counter"], s["rssi"]) for s in last.get("sightings", [])])
print("final counts:", last.get("counts"))
print("receiver:", last.get("receiver"))
print("replay state on disk:", dict(load_state(state, scope=scope)))
PY
echo "Done. Tell Claude: $RUN"

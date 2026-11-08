#!/bin/bash
# C1 runner for macOS: records the environment, installs/pins the ESP32 toolchain
# through the arduino-cli bundled with Arduino IDE 2, builds both sides with
# logs, flashes the scanner, and runs three timed serial captures.
#   bash ~/Team-15/tools/c1/run_c1.sh
# Prerequisite: open ios/BeaconC1/BeaconC1.xcodeproj in Xcode once, pick your
# Team under Signing & Capabilities, and Run it on the iPhone.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${FQBN:?Set the confirmed board FQBN explicitly; this runner does not guess}"
: "${PORT:?Set the confirmed serial port explicitly}"
: "${DEVELOPMENT_TEAM:?Set the existing Xcode signing team}"
RUN="c1-$(date -u +%Y%m%dT%H%M%SZ)"
E="$ROOT/docs/ble-id/runs/$RUN"; mkdir -p "$E"
trap 'echo "FAILED: see logs in $E" >&2' ERR
CMDS="$E/commands.log"; : > "$CMDS"
run() {
  echo "\$ $*" >> "$CMDS"
  local rc=0
  "$@" || rc=$?
  echo "exit=$rc" >> "$CMDS"
  return "$rc"
}
mask() { sed -E 's/[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}/<id-masked>/g; s/(Serial Number: ).*/\1<masked>/'; }
echo "== Run $RUN  ->  $E"

echo "== 1/5 Environment"
{
  echo "utc: $(date -u +%FT%TZ)"; sw_vers
  system_profiler SPHardwareDataType | grep -E "Model Name|Model Identifier|Chip|Memory"
  xcodebuild -version; echo "--- devicectl"; xcrun devicectl list devices 2>&1
  echo "--- serial ports"; ls /dev/cu.* 2>&1
  echo "--- usb (esp32)"; system_profiler SPUSBDataType | grep -B2 -A10 -i -E "espressif|seeed|jtag|esp32"
  echo "--- repo"; git -C "$ROOT" rev-parse HEAD; git -C "$ROOT" status --short
} 2>&1 | mask > "$E/environment.txt"
cat "$E/environment.txt"

echo "== 2/5 iOS build log (BUILD ONLY; Xcode's Run installs it on the phone)"
run xcodebuild -project "$ROOT/ios/BeaconC1/BeaconC1.xcodeproj" -scheme BeaconC1 -sdk iphoneos \
  -configuration Debug -allowProvisioningUpdates DEVELOPMENT_TEAM="$DEVELOPMENT_TEAM" \
  -derivedDataPath "${TMPDIR:-/tmp}/beaconc1-build" build \
  > "$E/xcodebuild.log" 2>&1
echo "xcodebuild exit=$? (log: xcodebuild.log)"; tail -3 "$E/xcodebuild.log"

echo "== 3/5 ESP32 toolchain + firmware"
CLI=$(find "/Applications/Arduino IDE.app" -name arduino-cli -type f -perm -u+x 2>/dev/null | head -1)
[ -n "$CLI" ] || { echo "ERROR: bundled arduino-cli not found"; exit 3; }
URL=https://espressif.github.io/arduino-esp32/package_esp32_index.json
run "$CLI" version
if ! "$CLI" core list | grep -q '^esp32:esp32 *3.3.11 '; then
  run "$CLI" core update-index --additional-urls "$URL"
  run "$CLI" core install esp32:esp32@3.3.11 --additional-urls "$URL"
fi
"$CLI" lib list | grep -q '^NimBLE-Arduino *2.5.1 ' || run "$CLI" lib install "NimBLE-Arduino@2.5.1"
{ "$CLI" version; "$CLI" core list; "$CLI" lib list | grep -i nimble; } > "$E/toolchain_versions.txt" 2>&1
echo "FQBN: $FQBN" | tee -a "$E/toolchain_versions.txt"
[ -e "$PORT" ] || { echo "ERROR: selected port is absent: $PORT"; exit 5; }
echo "Port: $PORT" | tee -a "$E/toolchain_versions.txt"
BUILD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/beaconc1-firmware.XXXXXX")
run "$CLI" compile -v --fqbn "$FQBN" --output-dir "$BUILD_DIR" "$ROOT/firmware/esp32_scanner" > "$E/arduino_compile.log" 2>&1
echo "compile exit=$?"; tail -3 "$E/arduino_compile.log"
if [ "${BUILD_ONLY:-0}" = 1 ]; then echo "BUILD ONLY: no upload or capture"; exit 0; fi
run "$CLI" upload -v --fqbn "$FQBN" -p "$PORT" --input-dir "$BUILD_DIR" "$ROOT/firmware/esp32_scanner" > "$E/arduino_upload.log" 2>&1
echo "upload exit=$?"; tail -3 "$E/arduino_upload.log"
sleep 3
[ -e "$PORT" ] || { echo "ERROR: port changed after upload; select it explicitly"; exit 5; }

echo "== 4/5 Captures (start screen recording and the second-phone video now)"
cap() { run bash "$ROOT/tools/c1/capture_serial.sh" "$PORT" "$2" "$E/$1"; }
read -r -p "Stage A NEGATIVE CONTROL: app STOPPED on the phone. Press Enter to capture 30 s... "
cap capture_A_stopped.tsv 30
read -r -p "Stage B STATIC: set mode 'Static A1', tap Start. Press Enter to capture 60 s... "
cap capture_B_static.tsv 60
read -r -p "Stage C ROTATING: tap Stop, select 'Rotating', tap Start. Press Enter to capture 120 s... "
cap capture_C_rotating.tsv 120
run python3 "$ROOT/tools/c1/analyze_c1.py" "$E"

echo "== 5/5 Done. Evidence: $E"
echo "Tell Claude the run ID: $RUN"

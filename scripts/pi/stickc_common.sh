# Shared by the StickC scripts (sourced). Run on the Pi.
set -euo pipefail
P=/dev/serial/by-id/usb-Hades2001_M5stack_7D520E63EE-if00-port0
E=~/team15_rover/.venv-flash/bin/esptool.py
MAC=14:08:08:53:37:6c
BACKUP=~/Team15_evidence/stickc_flash_backup/stickc_7D520E63EE_full_20261108-094242_read1.bin
BACKUP_SHA=bc1366ef08dd4ff251dc64ad3daf896a037ec9f563ae3cfe7e6dd654215bf95d
LOG=~/Team15_evidence/stickc_flash_log_$(date +%Y%m%d-%H%M%S).txt
die() { echo "REFUSED: $*" | tee -a "$LOG" >&2; exit 2; }
port_free() { for p in /proc/[0-9]*; do ls -l "$p/fd" 2>/dev/null | grep -q ttyUSB0 && die "port held by $(tr '\0' ' ' < "$p/cmdline")"; done; true; }
same_chip() {
  out=$("$E" --chip esp32 --port "$P" --baud 115200 --after hard_reset flash_id 2>&1) || die "flash_id failed: $out"
  echo "$out" >> "$LOG"
  echo "$out" | grep -q "ESP32-PICO-D4" || die "chip is not ESP32-PICO-D4"
  echo "$out" | grep -qi "MAC: $MAC" || die "MAC differs from the identified board ($MAC)"
  echo "$out" | grep -q "Detected flash size: 4MB" || die "flash is not 4MB"
}

#!/usr/bin/env bash
# Flash the Team-15 bridge firmware. NEEDS EXPLICIT APPROVAL + CONFIRMED BOARD LABEL. RoverC power OFF.
#   ~/team15_rover/scripts/pi/stickc_flash_bridge.sh <stickc|stickc_plus> "<approved by>"
source "$(dirname "$0")/stickc_common.sh"
MODEL=${1:-}; WHO=${2:-}
case "$MODEL" in
  stickc)      IMG=bridge_m5stack_stickc.merged.bin ;;
  stickc_plus) IMG=bridge_m5stack_stickc_plus.merged.bin ;;
  *) die "model must be stickc or stickc_plus (from the board label)" ;;
esac
[ -n "$WHO" ] || die "name the person who approved flashing"
echo "flash $MODEL approved by $WHO at $(date -Is)" | tee -a "$LOG"
cd ~/team15_rover/firmware_staged
grep " $IMG\$" SHA256SUMS | sha256sum -c - | tee -a "$LOG" || die "staged image hash mismatch"
echo "$BACKUP_SHA  $BACKUP" | sha256sum -c - | tee -a "$LOG" || die "original-firmware backup missing or changed"
port_free
same_chip
"$E" --chip esp32 --port "$P" --baud 750000 write_flash --flash_mode dio --flash_freq 80m --flash_size 4MB 0x0 "$IMG" 2>&1 | tee -a "$LOG"
"$E" --chip esp32 --port "$P" --baud 750000 verify_flash --flash_mode dio --flash_freq 80m --flash_size 4MB 0x0 "$IMG" 2>&1 | tee -a "$LOG" | grep -a "verified" || die "verify_flash failed"
echo "FLASHED + VERIFIED $IMG. Expect the StickC screen: DISARMED on maroon. Log: $LOG" | tee -a "$LOG"

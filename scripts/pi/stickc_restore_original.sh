#!/usr/bin/env bash
# Put the ORIGINAL firmware back (the verified 2026-11-08 backup). Needs approval. RoverC power OFF.
source "$(dirname "$0")/stickc_common.sh"
WHO=${1:-}; [ -n "$WHO" ] || die "name the person who approved the restore"
echo "restore original approved by $WHO at $(date -Is)" | tee -a "$LOG"
echo "$BACKUP_SHA  $BACKUP" | sha256sum -c - | tee -a "$LOG" || die "backup missing or changed"
port_free
same_chip
"$E" --chip esp32 --port "$P" --baud 750000 write_flash --flash_size keep 0x0 "$BACKUP" 2>&1 | tee -a "$LOG"
"$E" --chip esp32 --port "$P" --baud 750000 verify_flash 0x0 "$BACKUP" 2>&1 | tee -a "$LOG" | grep -a "verified" || die "verify_flash failed"
echo "RESTORED original firmware. Expect: ROVER READY / MOVE - power 0 / btn A = lock/unlock" | tee -a "$LOG"

#!/bin/bash
# Python owns the serial port and deadline; there are no orphan capture pipes.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/capture_serial.py" "$@"

"""Bounded macOS serial capture using only the Python standard library.

Usage: python3 capture_serial.py PORT SECONDS OUTFILE
Timestamps are host read times, not RF timestamps or measured phone latency.
"""
import datetime as dt
import fcntl
import math
import os
import select
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path


def settle(fd, target):
    """Record a declared 2s startup drain and align to a complete serial line.

    USB/device queues can retain old rows even after a host tcflush. Preserve
    these bytes separately; do not grade them as observations from the new stage.
    """
    start = time.monotonic()
    print('STARTUP DRAIN · 2 seconds, retained in .warmup.txt (not graded)', flush=True)
    with Path(str(target) + '.warmup.txt').open('xb') as out:
        while time.monotonic() - start < 7:
            if not select.select([fd], [], [], .2)[0]:
                continue
            chunk = os.read(fd, 8192)
            if not chunk:
                raise RuntimeError('serial device disconnected during startup drain')
            if time.monotonic() - start >= 2 and b'\n' in chunk:
                prefix, pending = chunk.rsplit(b'\n', 1)
                out.write(prefix + b'\n')
                return pending
            out.write(chunk)
    raise RuntimeError('no complete serial line after startup drain')


def capture(port, seconds, target):
    if not math.isfinite(seconds) or not 1 <= seconds <= 3600:
        raise ValueError("duration must be finite, between 1 and 3600 seconds")
    busy = subprocess.run(["/usr/sbin/lsof", "-t", port], capture_output=True)
    if busy.returncode == 0 and busy.stdout.strip():
        raise RuntimeError("serial port busy: close Serial Monitor first")
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    previous = termios.tcgetattr(fd)
    try:
        fcntl.ioctl(fd, termios.TIOCEXCL)
        tty.setraw(fd)
        config = termios.tcgetattr(fd)
        config[4] = config[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, config)
        termios.tcflush(fd, termios.TCIFLUSH)
        pending = settle(fd, target)
        with Path(target).open("x", buffering=1) as out:
            start = time.monotonic()
            out.write(f"# capture_start_monotonic={start:.6f} requested_s={seconds}\n")
            out.write('# startup_drain_s=2 raw_bytes_retained_in_companion_warmup_file\n')
            print(f"LIVE SERIAL CAPTURE · {seconds:g} s · SYNTHETIC TEST KEYS", flush=True)
            count = 0
            while (remaining := seconds - (time.monotonic() - start)) > 0:
                if not select.select([fd], [], [], min(remaining, 1))[0]:
                    continue
                chunk = os.read(fd, 8192)
                if not chunk:
                    raise RuntimeError("serial device disconnected")
                pending += chunk
                if len(pending) > 65536:
                    raise RuntimeError("serial line exceeds capture bound")
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    utc = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                    text = line.rstrip(b"\r").decode("utf-8", errors="replace")
                    out.write(f"{utc}\t{time.monotonic():.6f}\t{text}\n")
                    count += 1
                    if text.startswith(("#HEARTBEAT", "#SCAN_ERROR")) or "01010390" in text.lower():
                        print(text, flush=True)
            out.write(f"# capture_end_monotonic={time.monotonic():.6f}\n")
            if pending:
                out.write(f"# partial_tail_bytes={len(pending)}\n")
        print(f"Saved {count} lines to {target}", flush=True)
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSANOW, previous)
        finally:
            os.close(fd)


if __name__ == "__main__":
    try:
        capture(sys.argv[1], float(sys.argv[2]), sys.argv[3])
    except (OSError, RuntimeError, ValueError, IndexError) as exc:
        print(f"CAPTURE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

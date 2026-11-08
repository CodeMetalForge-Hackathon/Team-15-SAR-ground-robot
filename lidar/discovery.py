"""Serial device discovery: LIST candidates only. Never opens a port, never auto-selects.

A USB-UART adapter's VID:PID (CP210x 10c4:ea60, CH340 1a86:7523, FTDI 0403:6001 ...) says what
the ADAPTER is, not what is behind it. It never proves a C1 is attached, so discovery
only reports candidates. The device to open is always given explicitly and must equal the
checklist's recorded ``/dev/serial/by-id/`` path (config.check_hardware_gate).
"""
from __future__ import annotations

import glob
import os
from typing import Callable, Optional

KNOWN_ADAPTER_CHIPS = {
    "10c4:ea60": "Silicon Labs CP210x (used by Slamtec USB adapters; NOT proof of a C1)",
    "1a86:7523": "WCH CH340 (generic; NOT proof of a C1)",
    "0403:6001": "FTDI FT232R (generic; NOT proof of a C1)",
}
PATTERNS = ("/dev/serial/by-id/*", "/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbserial*", "/dev/cu.SLAB*")


def _sysfs_vid_pid(dev: str) -> Optional[str]:
    try:
        real = os.path.realpath(dev)
        base = os.path.basename(real)
        p = os.path.realpath(f"/sys/class/tty/{base}/device")
        for _ in range(6):
            v, d = os.path.join(p, "idVendor"), os.path.join(p, "idProduct")
            if os.path.exists(v) and os.path.exists(d):
                return f"{open(v).read().strip()}:{open(d).read().strip()}"
            p = os.path.dirname(p)
    except OSError:
        pass
    return None


def discover(globber: Callable[[str], list] = glob.glob, vid_pid: Callable[[str], Optional[str]] = _sysfs_vid_pid,
             realpath: Callable[[str], str] = os.path.realpath) -> list[dict]:
    seen, out = set(), []
    for pat in PATTERNS:
        for dev in sorted(globber(pat)):
            real = realpath(dev)
            if dev in seen:
                continue
            seen.add(dev)
            vp = vid_pid(dev)
            out.append({"device": dev, "resolves_to": real, "by_id": dev.startswith("/dev/serial/by-id/"),
                        "vid_pid": vp, "adapter_hint": KNOWN_ADAPTER_CHIPS.get(vp or "", "unknown adapter"),
                        "is_rplidar_c1": None,
                        "note": "candidate only; identity is confirmed by GET_INFO after the hardware gate"})
    return out

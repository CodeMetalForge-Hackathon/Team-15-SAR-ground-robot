"""Identify the firmware on the RoverC StickC with the smallest possible serial interaction. Run ON THE PI.

NEEDS EXPLICIT APPROVAL (it opens the serial port). Preconditions it makes you confirm:
  * the RoverC power switch is OFF (motors unpowered: nothing can move even if a reset glitches),
  * a person is at the rover.

What it does, and nothing else:
  1. opens the by-id port with DTR and RTS deasserted (a kernel open may still pulse them; with the RoverC off,
     a reset only reboots the StickC),
  2. LISTENS for --listen-s seconds and records any boot banner / periodic output,
  3. optionally (--hello) sends exactly one line "HELLO\\n". In the PR #6 firmware (ROVERC_USB_V1) HELLO only
     reads status (and forces speed 0 if the base reports non-zero). It is not a command in the Team-15
     bridge protocol, which ignores lines without a valid CRC,
  4. records the reply, closes the port, and writes the transcript (JSON) to ~/Team15_evidence/stickc_identify/.
It never sends MOVE, M-frames, ARM, Wi-Fi commands or anything else; that is enforced by a fixed allow-list.
"""
from __future__ import annotations

import argparse
import json
import os
import time

DEFAULT_PORT = "/dev/serial/by-id/usb-Hades2001_M5stack_7D520E63EE-if00-port0"
ALLOWED_TX = {b"HELLO\n"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--listen-s", type=float, default=3.0)
    ap.add_argument("--hello", action="store_true", help="send the single read-only probe line HELLO")
    ap.add_argument("--approved-by", required=True, help="name of the person who approved opening the port")
    ap.add_argument("--roverc-power-off", action="store_true", required=True)
    a = ap.parse_args()
    if not a.port.startswith("/dev/serial/by-id/") or "7D520E63EE" not in a.port:
        ap.error("only the verified StickC by-id path (serial 7D520E63EE) is allowed")
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout, s.write_timeout = a.port, 115200, 0.05, 0.2
    s.dtr = False
    s.rts = False
    t0 = time.time()
    rx_listen, rx_hello, tx = b"", b"", []
    s.open()
    try:
        end = time.time() + a.listen_s
        while time.time() < end:
            rx_listen += s.read(512)
        if a.hello:
            line = b"HELLO\n"
            assert line in ALLOWED_TX
            s.write(line)
            tx.append(line.decode())
            end = time.time() + 1.5
            while time.time() < end:
                rx_hello += s.read(512)
    finally:
        s.close()
    txt = lambda b: b.decode("utf-8", errors="replace")
    out = {"t": t0, "port": a.port, "approved_by": a.approved_by, "roverc_power_off_confirmed": True,
           "listen_s": a.listen_s, "rx_while_listening": txt(rx_listen), "tx": tx, "rx_after_hello": txt(rx_hello)}
    r = out["rx_while_listening"] + out["rx_after_hello"]
    out["verdict"] = ("PR6_FAMILY (ROVERC_USB_V1 text protocol)" if "ROVERC_USB_V1" in r else
                      "TEAM15_BRIDGE (K/N frames)" if r.startswith(("K,", "N,")) or "\nK," in r else
                      "UNKNOWN (no recognised banner/reply)")
    d = os.path.expanduser("~/Team15_evidence/stickc_identify")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + ".json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))
    print("saved", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

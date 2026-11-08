"""Read-only status of the M5StickC / RoverC-Pro controller link, as seen from this Mac.

What it does: lists USB devices from the IORegistry (``ioreg -p IOUSB``) and the ``/dev/cu.*`` serial
nodes, and says whether anything looks like an M5StickC USB-UART bridge.

What it never does: open a serial port. On StickC boards DTR/RTS drive the ESP32 EN/G0 auto-reset
circuit, so even opening the port can reset the controller or hold it in download mode, where nothing
zeroes the motors. This module also has no motor path at all: it imports nothing from ``rover``.

Firmware state is therefore always UNVERIFIED here. Only an approved bench session that talks to the
bridge can verify it, and that session records its result in a JSON file this module only reads
(``TEAM15_WHEEL_TEST_RECORD``, default ~/Team15_evidence/wheel_tests/latest.json).
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

SCHEMA = "team15.controller_status/1"

# USB-UART bridge chips used on M5StickC-family boards. VID/PID only names the chip, not the board.
# The board model must be confirmed from its label.
KNOWN_BRIDGES = {
    (0x0403, 0x6001): ("FTDI FT231X", "M5StickC or M5StickC Plus (original): confirm from the board label"),
    (0x0403, 0x6015): ("FTDI FT231X/FT-X", "M5StickC or M5StickC Plus: confirm from the board label"),
    (0x1A86, 0x55D4): ("WCH CH9102", "M5StickC Plus2 (or later Plus revision): confirm from the board label"),
    (0x1A86, 0x7523): ("WCH CH340", "M5Stack board with CH340: confirm from the board label"),
    (0x10C4, 0xEA60): ("SiLabs CP210x", "M5Stack board with CP2104: confirm from the board label"),
    (0x303A, 0x1001): ("ESP32-S3 native USB", "ESP32-S3 board (not a classic StickC): confirm from the board label"),
}
SERIAL_GLOBS = ("/dev/cu.usbserial*", "/dev/cu.wchusbserial*", "/dev/cu.usbmodem*", "/dev/cu.SLAB_USBtoUART*")
DEFAULT_RECORD = "~/Team15_evidence/wheel_tests/latest.json"
WHEEL_TEST_REQUIRED = ("operator", "t", "result", "wheels_lifted", "observations")


def _run_ioreg() -> str:
    try:
        return subprocess.run(["ioreg", "-p", "IOUSB", "-l", "-w0"], capture_output=True, text=True,
                              timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_ioreg(text: str) -> list[dict]:
    """USB devices from ``ioreg -p IOUSB -l -w0`` output. Never raises."""
    devices: list[dict] = []
    cur: Optional[dict] = None
    for line in (text or "").splitlines():
        if "+-o " in line:
            if cur and ("vid" in cur or "product" in cur):
                devices.append(cur)
            m = re.search(r"\+-o (.+?)@", line)
            cur = {"node": m.group(1).strip() if m else line.strip()}
            continue
        if cur is None:
            continue
        m = re.search(r'"(idVendor|idProduct|USB Product Name|USB Vendor Name|USB Serial Number|locationID)"'
                      r"\s*=\s*(.+)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip().strip('"')
        key = {"idVendor": "vid", "idProduct": "pid", "USB Product Name": "product",
               "USB Vendor Name": "vendor", "USB Serial Number": "serial", "locationID": "location"}[k]
        if key in ("vid", "pid", "location"):
            try:
                cur[key] = int(v, 0)
            except ValueError:
                continue
        else:
            cur[key] = v
    if cur and ("vid" in cur or "product" in cur):
        devices.append(cur)
    return devices


def classify(devices: list[dict], ports: list[str]) -> dict:
    cands = []
    for d in devices:
        hit = KNOWN_BRIDGES.get((d.get("vid"), d.get("pid")))
        if hit:
            cands.append({"chip": hit[0], "model_hint": hit[1], "vid": f"0x{d['vid']:04x}",
                          "pid": f"0x{d['pid']:04x}", "product": d.get("product"), "vendor": d.get("vendor"),
                          "serial": d.get("serial")})
    if cands and ports:
        status = "DETECTED"
        text = f"{cands[0]['chip']} USB-UART enumerated, serial node {ports[0]} present (port NOT opened)"
    elif cands:
        status = "USB_ONLY"
        text = f"{cands[0]['chip']} enumerated but no /dev/cu serial node: driver missing?"
    elif ports:
        status = "UNKNOWN_SERIAL"
        text = f"serial node {ports[0]} present but no known StickC USB-UART chip enumerated"
    else:
        status = "NOT_DETECTED"
        text = ("no USB device enumerated on any Mac port. A powered StickC with a charge-only cable, "
                "a loose USB-C plug, or a StickC powered only from the RoverC battery all look like this")
    return {"usb_status": status, "usb_text": text, "candidates": cands}


def read_wheel_test(path: str) -> dict:
    """The last operator-recorded wheel test, or NOT_RUN. A record missing required fields is INVALID."""
    p = Path(os.path.expanduser(path))
    if not p.is_file():
        return {"result": "NOT_RUN", "text": "no supervised wheel test has been recorded", "record": str(p)}
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"result": "INVALID", "text": f"unreadable record: {type(e).__name__}", "record": str(p)}
    missing = [k for k in WHEEL_TEST_REQUIRED if not isinstance(rec, dict) or rec.get(k) in (None, "")]
    if missing:
        return {"result": "INVALID", "text": "record missing " + ", ".join(missing), "record": str(p)}
    return {"result": str(rec["result"]).upper(), "operator": rec["operator"], "t": rec["t"],
            "wheels_lifted": bool(rec["wheels_lifted"]), "observations": rec["observations"],
            "text": f"recorded by {rec['operator']}", "record": str(p)}


class ControllerProbe:
    """Cached read-only probe. ``on_change(old, new)`` is called when usb_status changes."""

    def __init__(self, ioreg: Callable[[], str] = _run_ioreg,
                 ports: Callable[[], list[str]] = lambda: sorted({p for g in SERIAL_GLOBS for p in glob.glob(g)}),
                 clock: Callable[[], float] = time.time, cache_s: float = 2.0,
                 record_path: Optional[str] = None,
                 on_change: Optional[Callable[[Optional[str], str, dict], None]] = None):
        self.ioreg, self.ports, self.clock, self.cache_s = ioreg, ports, clock, cache_s
        self.record_path = record_path or os.environ.get("TEAM15_WHEEL_TEST_RECORD") or DEFAULT_RECORD
        self.on_change = on_change
        self.lock = threading.Lock()
        self._last: Optional[dict] = None
        self._last_t = -1e18
        self._last_status: Optional[str] = None

    def status(self) -> dict:
        with self.lock:
            now = self.clock()
            if self._last is not None and now - self._last_t < self.cache_s:
                return self._last
            try:
                devices = parse_ioreg(self.ioreg())
                ports = list(self.ports())
                c = classify(devices, ports)
            except Exception as e:  # noqa: BLE001 - the panel must render, and must not read "connected"
                devices, ports = [], []
                c = {"usb_status": "PROBE_ERROR", "usb_text": f"probe failed: {type(e).__name__}",
                     "candidates": []}
            st = {
                "schema": SCHEMA, "t": round(now, 3), "source": "MAC_USB_PROBE (read-only)",
                **c,
                "serial_ports": ports,
                "usb_device_count": len(devices),
                "port_opened": False,
                "firmware_status": "UNVERIFIED",
                "firmware_text": ("Team-15 bridge firmware has never been flashed or run. The StickC's "
                                  "current firmware is unknown and is assumed NOT to speak the bridge "
                                  "protocol. This probe never opens the port."),
                "estop": {"software": "NO_MOTOR_SUPERVISOR_RUNNING",
                          "text": ("no motion supervisor is attached to this dashboard and no motor "
                                   "command has been sent from it. Physical stop: RoverC power switch. "
                                   "Bridge firmware (once flashed): StickC button A latches ESTOP."),
                          "physical": "RoverC power switch (operator)"},
                "command_state": "NONE: this dashboard has no motor path",
                "wheel_test": read_wheel_test(self.record_path),
            }
            if st["usb_status"] != self._last_status:
                old, self._last_status = self._last_status, st["usb_status"]
                if self.on_change:
                    try:
                        self.on_change(old, st["usb_status"], st)
                    except Exception:  # noqa: BLE001
                        pass
            self._last, self._last_t = st, now
            return st

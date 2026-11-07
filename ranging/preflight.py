"""Read-only Pi preflight for the Grove ranger. Never requests or drives a GPIO line.

python3 -m ranging preflight --config ~/Team15_config/grove_range.json

Every check is PASS, FAIL or SKIP. Exit code 0 only if nothing FAILs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Callable, List, Optional

from .config import ConfigError, SensorConfig, check_electrical

READ_ONLY_NOTE = "read-only: chip/line info queried, no line requested, nothing driven"


def _check(name: str, ok: Optional[bool], detail) -> dict:
    return {"check": name, "result": "SKIP" if ok is None else ("PASS" if ok else "FAIL"), "detail": detail}


def _run(cmd: List[str]) -> Optional[str]:
    if not shutil.which(cmd[0]):
        return None
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa
        return None


def run_preflight(cfg_raw: dict, gpiod_module=None, read_file: Callable[[str], str] = None,
                  run: Callable[[List[str]], Optional[str]] = _run) -> dict:
    read_file = read_file or (lambda p: open(p).read())
    checks = []
    # 1. platform
    try:
        model = read_file("/proc/device-tree/model").strip("\x00\n ")
    except OSError:
        model = None
    checks.append(_check("pi5_model", bool(model and "Raspberry Pi 5" in model), model))
    # 2. config + electrical gate
    cfg = None
    try:
        raw = dict(cfg_raw)
        raw.pop("obstacle", None)
        cfg = SensorConfig.from_dict(raw)
        if cfg.driver != "gpiod":
            checks.append(_check("electrical_gate", False, "config does not select driver 'gpiod'"))
        else:
            check_electrical(cfg.electrical)
            cfg.validate()
            checks.append(_check("electrical_gate", True, "all recorded checklist items pass"))
    except (ConfigError, TypeError) as e:
        checks.append(_check("electrical_gate", False, str(e)))
    pin = cfg.electrical.gpio_bcm if cfg else None
    chip_path = cfg.gpiochip if cfg else "/dev/gpiochip0"
    # 3. libgpiod
    g = gpiod_module
    if g is None:
        try:
            import gpiod as g  # noqa
        except ImportError:
            g = None
    ver = getattr(g, "__version__", None) if g else None
    checks.append(_check("libgpiod_v2", bool(ver and str(ver).split(".")[0].isdigit() and int(str(ver).split(".")[0]) >= 2), ver or "not importable"))
    # 4. device permission
    checks.append(_check("gpiochip_rw_access", os.access(chip_path, os.R_OK | os.W_OK) if g else None, chip_path))
    # 5. line identity (read-only)
    if g and pin is not None:
        try:
            with g.Chip(chip_path) as chip:
                label = chip.get_info().label
                info = chip.get_line_info(pin)
            checks.append(_check("chip_is_rp1", label == "pinctrl-rp1", label))
            checks.append(_check("line_name", info.name == f"GPIO{pin}", info.name))
            checks.append(_check("line_unused", not info.used, info.consumer))
        except Exception as e:  # noqa
            checks.append(_check("chip_is_rp1", False, f"{type(e).__name__}: {e}"))
    else:
        checks.append(_check("chip_is_rp1", None, "no libgpiod or no gpio_bcm"))
    # 6. pin mux (informational; 'none' or input expected, never an alt function)
    pc = run(["pinctrl", "get", str(pin)]) if pin is not None else None
    if pc is None:
        checks.append(_check("pinctrl_function", None, "pinctrl unavailable"))
    else:
        alt = any(f" a{n} " in f" {pc} " for n in range(9))
        checks.append(_check("pinctrl_function", not alt, pc))
    # 7. clock sync (cross-host consumers use wall-clock obs_time)
    ntp = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    checks.append(_check("ntp_synchronized", None if ntp is None else ntp == "yes", ntp))
    # 8. snapshot location
    checks.append(_check("dev_shm_writable", os.access("/dev/shm", os.W_OK) if os.path.isdir("/dev/shm") else False,
                         "/dev/shm"))
    ok = all(c["result"] != "FAIL" for c in checks)
    return {"kind": "GROVE_PREFLIGHT", "note": READ_ONLY_NOTE, "ok": ok, "checks": checks,
            "next": ("ready for WIRING.md section 7 powered runs (robot stationary, motors off)" if ok
                     else "GPIO stays locked: fix the FAIL items")}


def main_preflight(config_path: Optional[str]) -> int:
    raw = {}
    if config_path:
        with open(config_path) as f:
            raw = json.load(f)
    rep = run_preflight(raw)
    print(json.dumps(rep, indent=2))
    return 0 if rep["ok"] else 1

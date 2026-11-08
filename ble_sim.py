"""SIMULATED serial source for the BLE-ID dashboard. Never opens real hardware.

    python3 -m ble_sim serve [--port 8766] [--state-dir NEW_EMPTY_DIR]

Writes a fixed 40-second schedule into a private pseudo-terminal that the real
reader (discovery.server.serial_worker) consumes, so the full serial -> verifier
-> state -> API -> browser path runs. Simulator keys, a SIMULATED- scope and a
fresh state file in its own directory keep it apart from any live mission; the
API and page label everything SIMULATED. Schedule (seconds within each cycle):
  0-9, 20-39  alias 1 every second (one verified per 30 s window, then duplicates)
              and alias 2 every 3 s
  3 stale replay · 4 forged · 5 unknown alias · 6 malformed rows · 7 future token
  10-19       packet loss: no beacon rows at all (heartbeats continue)
"""
from __future__ import annotations

import argparse
import os
import pty
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ble_id import BeaconMonitor
from ble_keys import SIM_KEYS, keys_for
from ble_state import init_state
from ble_verify import make_token

PERIOD = 40
WRONG = b"\xa5" * 32
HEARTBEAT = "#HEARTBEAT,scanning=1,millis={ms},passive=1,discovery=1"
SIM_SIGNALS = [("02:5e:00:00:00:01", "0201060a0953494d204e4f444541"),     # name "SIM NODEA"
               ("02:5e:00:00:00:02", "02010607ff4c0010020b00")]            # Apple company ID hint


def row(rssi, payload):
    h = payload.hex()
    return f"{rssi},,{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def scenario(t: int, wall: float) -> list[str]:
    """Lines for second ``t`` of the run. Deterministic for a given (t, wall)."""
    phase, n = t % PERIOD, int(wall // 30)
    lines = [HEARTBEAT.format(ms=1000 * t)]
    lines += [f"#BLE,{-70 - i * 9},{a},1,{p}" for i, (a, p) in enumerate(SIM_SIGNALS)]
    if not 10 <= phase < 20:
        lines.append(row(-58 - t % 5, make_token(SIM_KEYS[1], n, alias=1)))
        if phase % 3 == 0:
            lines.append(row(-71, make_token(SIM_KEYS[2], n, alias=2)))
    if phase == 3:
        lines.append(row(-60, make_token(SIM_KEYS[1], n - 5, alias=1)))           # stale replay
    if phase == 4:
        lines.append(row(-61, make_token(WRONG, n, alias=1)))                     # forged
    if phase == 5:
        lines.append(row(-62, make_token(WRONG, n, alias=9)))                     # unknown alias
    if phase == 6:
        good = row(-63, make_token(SIM_KEYS[1], n, alias=1))
        lines += ["garbage", "-50,,NOT-A-UUID", "-500" + good[3:], good.upper(),
                  "-63,NAME" + good[4:], good + ",extra"]                          # malformed
    if phase == 7:
        lines.append(row(-64, make_token(SIM_KEYS[1], n + 3, alias=1)))           # future
    return lines


def serve(port: int, state_dir: str | None) -> int:
    from discovery.server import Discovery, make_server, serial_worker
    folder = Path(state_dir) if state_dir else Path(tempfile.mkdtemp(prefix="olf-ble-sim-"))
    folder.mkdir(parents=True, exist_ok=True)
    scope = "SIMULATED-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = folder / "replay_state.simulated.json"
    init_state(path, scope=scope)                         # refuses an existing file
    master, slave = pty.openpty()
    disc, stop = Discovery(source="SIMULATED"), threading.Event()
    mon = BeaconMonitor(keys_for("simulated", scope=scope), str(path), scope=scope, mode="simulated",
                        source="SIMULATED", receiver_ready=disc.ready)
    reader = threading.Thread(target=serial_worker, args=(disc, os.ttyname(slave), stop, (mon.ingest,)), daemon=True)

    def writer():
        t = 0
        while not stop.is_set():
            os.write(master, "".join(f"{x}\n" for x in scenario(t, time.time())).encode())
            t += 1
            stop.wait(1)

    server = make_server(disc, port=port, beacons=mon)
    reader.start()
    threading.Thread(target=writer, daemon=True).start()
    print(f"SIMULATED BLE-ID dashboard (not hardware): http://127.0.0.1:{server.server_port}\n"
          f"  simulator keys · scope {scope} · state {path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        reader.join(timeout=3)
        os.close(master)
        os.close(slave)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m ble_sim", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the SIMULATED dashboard on a private pseudo-terminal")
    s.add_argument("--port", type=int, default=8766)
    s.add_argument("--state-dir", help="new, separate folder for simulator replay state")
    a = p.parse_args(argv)
    return serve(a.port, a.state_dir)


if __name__ == "__main__":
    sys.exit(main())

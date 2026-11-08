"""C3 latency probe (SIMULATED): serial write -> verifier -> state save -> /api/beacons.

    python3 -I tools/c3/latency_probe.py REPO_ROOT OUT.json [TRIALS]

One fresh token per trial (a distinct synthetic alias each time), written to a
pseudo-terminal read by the real serial_worker; the clock stops when the HTTP API
first lists that alias. Harness polls every 5 ms, so resolution is about 5 ms.
Excludes radio, phone, USB, and browser polling (the page polls every 1 s).
"""
import hashlib, json, math, os, platform, pty, sys, tempfile, threading, time
from urllib.request import urlopen

sys.path.insert(0, os.path.abspath(sys.argv[1]))
from ble_id import BeaconMonitor  # noqa: E402
from ble_sim import row  # noqa: E402
from ble_state import init_state  # noqa: E402
from ble_verify import counter_at, make_token  # noqa: E402
from discovery.server import Discovery, make_server, serial_worker  # noqa: E402

TRIALS = int(sys.argv[3]) if len(sys.argv) > 3 else 50
KEYS = {a: hashlib.sha256(b"C3 LATENCY SYNTHETIC KEY %d" % a).digest() for a in range(1, TRIALS + 1)}
HB = "#HEARTBEAT,scanning=1,millis=1,passive=1,discovery=1\n"

d = tempfile.mkdtemp(prefix="c3-latency-")
scope = "SIMULATED-latency"
init_state(f"{d}/state.json", scope=scope)
master, slave = pty.openpty()
disc, stop = Discovery(source="SIMULATED"), threading.Event()
mon = BeaconMonitor(KEYS, f"{d}/state.json", scope=scope, mode="simulated", source="SIMULATED",
                    receiver_ready=disc.ready)
threading.Thread(target=serial_worker, args=(disc, os.ttyname(slave), stop, (mon.ingest,)), daemon=True).start()
server = make_server(disc, port=0, beacons=mon)
threading.Thread(target=server.serve_forever, daemon=True).start()
api = f"http://127.0.0.1:{server.server_port}/api/beacons"
time.sleep(2.3)
os.write(master, ("align\n" + HB).encode())
time.sleep(0.3)
samples = []
for alias in range(1, TRIALS + 1):
    os.write(master, HB.encode())
    line = row(-60, make_token(KEYS[alias], counter_at(time.time()), alias=alias)) + "\n"
    t0 = time.perf_counter()
    os.write(master, line.encode())
    while True:
        snap = json.load(urlopen(api))
        if any(s["alias"] == alias for s in snap["sightings"]):
            samples.append((time.perf_counter() - t0) * 1000)
            break
        if time.perf_counter() - t0 > 5:
            samples.append(None)
            break
        time.sleep(0.005)
    time.sleep(0.05)
stop.set()
server.shutdown()
ok = sorted(s for s in samples if s is not None)
pct = lambda q: ok[min(len(ok) - 1, math.ceil(q * len(ok)) - 1)]
out = {"trials": TRIALS, "succeeded": len(ok), "timeouts_5s": samples.count(None),
       "latency_ms": {"min": ok[0], "p50": pct(.5), "p95": pct(.95), "max": ok[-1]} if ok else None,
       "boundary": "os.write of one serial row to the pty -> first /api/beacons response listing the alias",
       "includes": "pty, serial_worker line framing, discovery ingest, row validation, HMAC verify, "
                   "atomic state save with fsync, HTTP JSON", "harness_poll_ms": 5,
       "excludes": "radio, phone advertising, ESP32, USB CDC, browser 1 s poll",
       "python": platform.python_version(), "platform": platform.platform(), "samples_ms": samples}
json.dump(out, open(sys.argv[2], "w"), indent=1)
print(json.dumps({k: out[k] for k in ("trials", "succeeded", "timeouts_5s", "latency_ms")}))
sys.exit(0 if len(ok) == TRIALS else 1)

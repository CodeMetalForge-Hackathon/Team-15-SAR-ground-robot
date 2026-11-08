"""C3 integration (SIMULATED): pseudo-terminal -> the real single serial reader ->
discovery + verifier -> durable state -> HTTP API and page. No hardware involved."""
import json
import os
import pty
import threading
import time
from urllib.request import urlopen

import pytest

from ble_id import BeaconMonitor
from ble_keys import SIM_KEYS, TEST_KEYS
from ble_sim import PERIOD, row, scenario
from ble_state import init_state, load_state
from ble_verify import counter_at, make_token
from discovery.server import Discovery, make_server, serial_worker

HB = "#HEARTBEAT,scanning=1,millis=1,passive=1,discovery=1"


def wait(pred, timeout=4.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = pred()
        if value:
            return value
        time.sleep(0.02)
    return pred()


@pytest.fixture
def stack(tmp_path):
    scope, path = "TESTKEY-integration", tmp_path / "state.json"
    init_state(path, scope=scope)
    master, slave = pty.openpty()
    disc, stop = Discovery(source="SIMULATED"), threading.Event()
    mon = BeaconMonitor(TEST_KEYS, str(path), scope=scope, mode="test-keys", source="SIMULATED",
                        receiver_ready=disc.ready)
    reader = threading.Thread(target=serial_worker, args=(disc, os.ttyname(slave), stop, (mon.ingest,)), daemon=True)
    server = make_server(disc, port=0, beacons=mon)
    web = threading.Thread(target=server.serve_forever, daemon=True)
    reader.start(), web.start()
    time.sleep(2.2)                                     # the reader drains startup bytes for 2 s
    s = dict(base=f"http://127.0.0.1:{server.server_port}", fd=master, path=path, scope=scope)
    s["send"] = lambda *lines: os.write(s["fd"], "".join(f"{x}\n" for x in ("align",) + lines).encode())
    s["api"] = lambda: json.load(urlopen(s["base"] + "/api/beacons"))
    yield s
    stop.set(), server.shutdown(), server.server_close(), web.join(), reader.join(timeout=3)
    if s["fd"] is not None:
        os.close(s["fd"])
    os.close(slave), os.close(mon.owner)


def test_full_path_serial_to_state_to_api_to_page(stack):
    n = counter_at(time.time())
    good = row(-57, make_token(TEST_KEYS[1], n, alias=1))
    stack["send"](HB, good, good, row(-60, make_token(b"\xa5" * 32, n, alias=1)),
                  row(-61, make_token(b"\xa5" * 32, n, alias=9)), "garbage")
    data = wait(lambda: (d := stack["api"]())["counts"].get("drop:framing") and d)
    assert data["source"] == "SIMULATED" and data["mode_label"] == "SYNTHETIC TEST KEYS"
    assert data["receiver"]["status"] == "scanning" and data["status"] == "verifying"
    [s] = data["sightings"]
    assert (s["alias"], s["counter"], s["rssi"], s["verified_tokens"]) == (1, n, -57, 1)
    assert {k: data["counts"][k] for k in data["counts"]} == {
        "verified:fresh": 1, "replay:duplicate": 1, "forged:bad_tag": 1,
        "unknown:unenrolled_alias": 1, "drop:framing": 1}
    assert dict(load_state(stack["path"], scope=stack["scope"])) == {1: n}   # persisted
    page = urlopen(stack["base"] + "/").read()
    assert b"Verified beacons" in page and b'src="/beacons.js"' in page and b"Nearby signals" in page
    assert b"AUTHENTICATED" in urlopen(stack["base"] + "/beacons.js").read()
    os.close(stack["fd"])                                # unplug the receiver
    stack["fd"] = None
    gone = wait(lambda: (d := stack["api"]())["receiver"]["status"] == "disconnected" and d)
    assert gone["status"] == "receiver_unavailable" and len(gone["sightings"]) == 1   # kept as history


def test_rows_before_a_fresh_heartbeat_are_not_verified(stack):
    n = counter_at(time.time())
    stack["send"](row(-57, make_token(TEST_KEYS[1], n, alias=1)))
    assert wait(lambda: stack["api"]()["counts"].get("ignored:receiver_not_ready")) == 1
    stack["send"](HB, row(-57, make_token(TEST_KEYS[1], n, alias=1)))
    assert wait(lambda: stack["api"]()["sightings"])


def test_missing_port_is_reported_not_simulated(tmp_path):
    disc, stop = Discovery(), threading.Event()
    t = threading.Thread(target=serial_worker, args=(disc, str(tmp_path / "no-such-port"), stop), daemon=True)
    t.start()
    try:
        assert wait(lambda: disc.snapshot()["status"] == "disconnected")
        assert disc.snapshot()["source"] == "LIVE-HW" and not disc.ready()
    finally:
        stop.set(), t.join(timeout=3)


def test_simulator_schedule_is_deterministic_and_covers_every_outcome(tmp_path):
    assert scenario(17, 1794077187.0) == scenario(17, 1794077187.0)
    for t in range(10, 20):                              # loss phase: no beacon rows at all
        assert all(x.startswith("#") for x in scenario(t, 1794077187.0 + t))
    scope, path = "SIMULATED-unit", tmp_path / "sim.json"
    init_state(path, scope=scope)
    clock = {"t": 0.0}
    disc = Discovery(lambda: clock["t"], source="SIMULATED")
    mon = BeaconMonitor(SIM_KEYS, str(path), scope=scope, mode="simulated", source="SIMULATED",
                        receiver_ready=disc.ready, wall=lambda: 1794077187.0 + clock["t"], mono=lambda: clock["t"])
    verified_at = []
    for t in range(2 * PERIOD):
        clock["t"] = float(t)
        before = mon.snapshot()["counts"].get("verified:fresh", 0)
        for line in scenario(t, 1794077187.0 + t):
            disc.ingest(line), mon.ingest(line)
        if mon.snapshot()["counts"].get("verified:fresh", 0) > before:
            verified_at.append(t)
    counts = mon.snapshot()["counts"]
    for k in ("verified:fresh", "replay:duplicate", "replay:stale", "replay:future", "forged:bad_tag",
              "unknown:unenrolled_alias", "drop:framing", "drop:rssi_out_of_range", "drop:name_present"):
        assert counts.get(k), k
    assert not any(10 <= t % PERIOD < 20 for t in verified_at)          # nothing verified during loss
    assert any(t % PERIOD >= 20 for t in verified_at)                    # recovery after loss


def test_simulator_tokens_cannot_contaminate_a_live_scope(tmp_path):
    init_state(tmp_path / "live.json", scope="TESTKEY-live")
    mon = BeaconMonitor(TEST_KEYS, str(tmp_path / "live.json"), scope="TESTKEY-live", mode="test-keys",
                        source="LIVE-HW", receiver_ready=lambda: True)
    for line in scenario(0, time.time()) + scenario(21, time.time()):
        mon.ingest(line)
    assert mon.snapshot()["sightings"] == [] and "verified:fresh" not in mon.snapshot()["counts"]
    assert dict(load_state(tmp_path / "live.json", scope="TESTKEY-live")) == {}

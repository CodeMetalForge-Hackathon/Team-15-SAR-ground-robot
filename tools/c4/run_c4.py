"""C4 baseline analyzer and interactive live-hardware experiment runner (<150 lines).

Modes:
  python3 tools/c4/run_c4.py baseline OUT_DIR
  python3 tools/c4/run_c4.py live --serial /dev/cu.usbmodem2101 --out OUT_DIR
"""
from __future__ import annotations

import argparse, json, os, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ble_id import STALE_S, BeaconMonitor  # noqa: E402
from ble_keys import TEST_KEYS  # noqa: E402
from ble_sim import row  # noqa: E402
from ble_state import init_state, load_state  # noqa: E402
from ble_verify import counter_at, make_token  # noqa: E402
from discovery.beacons import snapshot as beacon_snapshot  # noqa: E402
from discovery.server import Discovery  # noqa: E402
from tools.c1.capture_serial import capture as capture_tsv  # noqa: E402
from tools.c4.c4_analyze import analyze_run, replay_tsv_through_verifier  # noqa: E402


def sim_aging_and_recovery() -> dict:
    """Measure verified-card aging (70 s) and receiver-loss/recovery deterministically."""
    tmp = Path(tempfile.mkdtemp(prefix="c4-ar-")) / "state.json"
    scope = "TESTKEY-c4-aging-sim"
    init_state(tmp, scope=scope)
    clk = {"wall": 1_794_083_550.0, "mono": 1000.0}
    disc = Discovery(lambda: clk["mono"], source="SIMULATED")
    mon = BeaconMonitor(TEST_KEYS, str(tmp), scope=scope, mode="test-keys", source="SIMULATED",
                        receiver_ready=disc.ready, wall=lambda: clk["wall"], mono=lambda: clk["mono"])
    hb = "#HEARTBEAT,scanning=1,millis=1000,passive=1,discovery=1"
    c0 = counter_at(clk["wall"])
    disc.ingest(hb)
    mon.ingest(row(-62, make_token(TEST_KEYS[1], c0, alias=1)))
    clk["wall"] += 20.0; clk["mono"] += 20.0
    disc.ingest(hb)
    for _ in range(4):
        mon.ingest(row(-55, make_token(TEST_KEYS[1], c0, alias=1)))
    s_dup = beacon_snapshot(mon, disc)
    clk["wall"] += 55.0; clk["mono"] += 55.0
    disc.ingest(hb)
    s_stale = beacon_snapshot(mon, disc)
    disc.connection("disconnected", "USB receiver unplugged")
    s_loss = beacon_snapshot(mon, disc)
    clk["wall"] += 15.0; clk["mono"] += 15.0
    disc.ingest(hb)
    mon.ingest(row(-60, make_token(TEST_KEYS[1], counter_at(clk["wall"]), alias=1)))
    s_rec = beacon_snapshot(mon, disc)
    os.close(mon.owner)
    return {
        "source": "SIMULATED", "stale_after_s": STALE_S,
        "age_after_duplicates_s": s_dup["sightings"][0]["last_verified_age_s"],
        "verified_tokens_after_duplicates": s_dup["sightings"][0]["verified_tokens"],
        "duplicate_count_after_4_repeats": s_dup["counts"].get("replay:duplicate", 0),
        "stale_at_75s": s_stale["sightings"][0]["stale"],
        "age_at_75s": s_stale["sightings"][0]["last_verified_age_s"],
        "sightings_at_75s": len(s_stale["sightings"]),
        "loss_receiver_status": s_loss["receiver"]["status"],
        "loss_beacon_status": s_loss["status"], "loss_sightings": len(s_loss["sightings"]),
        "recovered_beacon_status": s_rec["status"],
        "recovered_verified_tokens": s_rec["sightings"][0]["verified_tokens"],
        "recovered_stale": s_rec["sightings"][0]["stale"],
    }


def run_baseline(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    c1_dir = ROOT / "docs/ble-id/runs/c1-capture-20261107T202438Z"
    c1_replay = {
        "A_stopped": replay_tsv_through_verifier(c1_dir / "capture_A_stopped.tsv", 30.0, scope="TESTKEY-c1-A", c1_hb=True),
        "B_static": replay_tsv_through_verifier(c1_dir / "capture_B_static.tsv", 60.0, scope="TESTKEY-c1-B", c1_hb=True),
        "C_rotating_retry": replay_tsv_through_verifier(c1_dir / "capture_C_rotating.tsv", 120.0, scope="TESTKEY-c1-C", c1_hb=True),
        "C_attempt1_failed": replay_tsv_through_verifier(c1_dir / "attempt1_capture_C_rotating.tsv", 120.0, scope="TESTKEY-c1-C1", c1_hb=True),
        "provenance_note": "Real C1 hardware captures (iPhone 14 Pro iOS 26.0 -> passive ESP32-C5, pre-discovery heartbeat format) replayed through C2/C3 BeaconMonitor + ble_state.",
    }
    (out_dir / "c1_verifier_replay.json").write_text(json.dumps(c1_replay, indent=2) + "\n")
    (out_dir / "aging_and_recovery.json").write_text(json.dumps(sim_aging_and_recovery(), indent=2) + "\n")
    analyze_run(out_dir)
    return 0


def run_live(serial_port: str, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    scope = f"TESTKEY-c4-{out_dir.name}"
    state_path = Path(os.path.expanduser("~/.olf-c4")) / f"{scope}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if not state_path.exists():
        init_state(state_path, scope=scope)
    print(f"== C4 Live Hardware Runner · port={serial_port} · scope={scope} ==")
    for stage, sec, prompt in [
        ("e3_1m", 60, "Place iPhone at measured 1.0 m unobstructed, Rotating ON (foreground). Press Enter..."),
        ("e3_3m", 60, "Place iPhone at measured 3.0 m unobstructed, Rotating ON (foreground). Press Enter..."),
        ("e3_5m", 60, "Place iPhone at measured 5.0 m unobstructed, Rotating ON (foreground). Press Enter..."),
        ("e3_obstruction", 60, "Place iPhone behind described obstruction, Rotating ON (foreground). Press Enter..."),
        ("e4_foreground", 60, "Lifecycle 1/4: iPhone in FOREGROUND with Rotating ON. Press Enter..."),
        ("e4_background", 60, "Lifecycle 2/4: Swipe iPhone to BACKGROUND now. Press Enter..."),
        ("e4_locked", 60, "Lifecycle 3/4: LOCK iPhone screen now. Press Enter..."),
        ("e4_force_quit", 60, "Lifecycle 4/4: FORCE-QUIT OLF C1 app now. Press Enter..."),
    ]:
        target = out_dir / f"{stage}.tsv"
        if not target.exists():
            input(f"\n>>> {prompt}")
            capture_tsv(serial_port, sec, str(target))
    e2_file = out_dir / "e2_trials.jsonl"
    done = len(e2_file.read_text().splitlines()) if e2_file.exists() else 0
    for idx in range(done + 1, 21):
        hw_b = dict(load_state(state_path, scope=scope)).get(1)
        while hw_b is not None and counter_at(time.time()) <= hw_b:
            print(f"\r  Trial {idx}/20: STOP iPhone app; waiting {30.5 - (time.time() % 30.0):4.1f}s for next 30s window...", end="", flush=True)
            time.sleep(0.5)
        input(f"\n  Trial {idx}/20: Tap START (Rotating) at 1.0 m and press Enter! ")
        t0 = time.monotonic()
        tsv = out_dir / f"e2_trial_{idx:02d}.tsv"
        capture_tsv(serial_port, 10, str(tsv))
        res = replay_tsv_through_verifier(tsv, 10.0, scope=scope, state_path=state_path)
        hw_a = dict(load_state(state_path, scope=scope)).get(1)
        ver = res["verified_windows"] >= 1
        rec = {"trial": idx, "scope": scope, "state_path": str(state_path), "state_reset": False,
               "high_water_before": hw_b, "high_water_after": hw_a, "verified": ver,
               "counter": res["verified_counters"][0] if ver else None,
               "latency_s": round(time.monotonic() - t0 - 2.0, 4) if ver else None,
               "failure_reason": None if ver else "timeout_10s",
               "timing_boundary": "operator_enter_after_2s_drain -> verified_persisted"}
        with e2_file.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    analyze_run(out_dir)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline").add_argument("out", type=Path)
    lv = sub.add_parser("live")
    lv.add_argument("--serial", required=True)
    lv.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    return run_baseline(a.out) if a.cmd == "baseline" else run_live(a.serial, a.out)


if __name__ == "__main__":
    sys.exit(main())

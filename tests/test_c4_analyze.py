"""Unit tests for C4 measurement grading (tools/c4/c4_analyze.py)."""
from __future__ import annotations

import json
from pathlib import Path

from ble_keys import TEST_KEYS
from ble_sim import row
from ble_verify import counter_at, make_token
from tools.c4.c4_analyze import (analyze_run, grade_aging_and_recovery,
                                 grade_e2_trials, replay_tsv_through_verifier, rssi_dist)

HB = "#HEARTBEAT,scanning=1,millis=1000,passive=1,discovery=1"
BASE_T = 1_794_083_550.0
C0 = counter_at(BASE_T)


def _write_tsv(path: Path, duration_s: float, rows: list[tuple[float, str]]) -> None:
    lines = [f"# capture_start_monotonic=100.000000 requested_s={duration_s}",
             "# startup_drain_s=2 raw_bytes_retained_in_companion_warmup_file"]
    from datetime import datetime, timezone
    for offset, text in rows:
        utc = datetime.fromtimestamp(BASE_T + offset, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        lines.append(f"{utc}\t{100.0 + offset:.6f}\t{text}")
    lines.append(f"# capture_end_monotonic={100.0 + duration_s:.6f}")
    path.write_text("\n".join(lines) + "\n")


def test_rssi_dist_never_substitutes_zero_for_empty():
    assert rssi_dist([]) is None
    d = rssi_dist([-90, -80, -70, -60, -50])
    assert d["count"] == 5 and d["min_dbm"] == -90 and d["median_dbm"] == -70 and d["max_dbm"] == -50


def test_e2_passes_at_19_of_20_with_monotonic_persistent_state(tmp_path):
    p = tmp_path / "e2_trials.jsonl"
    recs = []
    hw = C0 - 1
    for i in range(1, 21):
        ok = i != 7
        nxt = hw + 1 if ok else hw
        recs.append({"trial": i, "scope": "TESTKEY-c4-e2", "state_path": "/tmp/s.json",
                     "state_reset": False, "high_water_before": hw, "high_water_after": nxt,
                     "verified": ok, "counter": nxt if ok else None,
                     "latency_s": 1.25 + 0.05 * i if ok else None,
                     "failure_reason": None if ok else "timeout_10s"})
        hw = nxt
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    res = grade_e2_trials(p)
    assert res["status"] == "PASSED" and res["succeeded_within_10s"] == 19
    assert res["state_monotonic_ok"] is True and res["timeouts_10s"] == [7]


def test_e2_rejects_replay_state_reset_or_reused_counter(tmp_path):
    p = tmp_path / "e2_trials.jsonl"
    recs = []
    for i in range(1, 21):
        # Resetting high_water_before to C0 every trial is a replay-state reset violation!
        recs.append({"trial": i, "scope": "TESTKEY-c4-e2", "state_path": "/tmp/s.json",
                     "state_reset": False, "high_water_before": C0, "high_water_after": C0 + 1,
                     "verified": True, "counter": C0 + 1, "latency_s": 0.8})
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    res = grade_e2_trials(p)
    assert res["state_monotonic_ok"] is False and res["status"] == "FAILED"


def test_e2_fails_when_below_19_of_20(tmp_path):
    p = tmp_path / "e2_trials.jsonl"
    recs = []
    hw = C0
    for i in range(1, 21):
        ok = i <= 18
        nxt = hw + 1 if ok else hw
        recs.append({"trial": i, "scope": "TESTKEY-c4-e2", "state_path": "/tmp/s.json",
                     "state_reset": False, "high_water_before": hw, "high_water_after": nxt,
                     "verified": ok, "counter": nxt if ok else None,
                     "latency_s": 1.5 if ok else None, "failure_reason": None if ok else "timeout_10s"})
        hw = nxt
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    assert grade_e2_trials(p)["status"] == "FAILED"


def test_replay_tsv_verifies_rotations_and_counts_duplicates(tmp_path):
    tsv = tmp_path / "e3_1m.tsv"
    tok0 = row(-65, make_token(TEST_KEYS[1], C0, alias=1))
    tok1 = row(-61, make_token(TEST_KEYS[1], C0 + 1, alias=1))
    _write_tsv(tsv, 60.0, [(0.1, HB), (0.5, tok0), (1.0, tok0), (30.1, HB), (30.5, tok1)])
    res = replay_tsv_through_verifier(tsv, 60.0, scope="TESTKEY-e3-1m")
    assert res["status"] == "MEASURED" and res["duration_ok"] is True
    assert res["verified_windows"] == 2 and res["verified_counters"] == [C0, C0 + 1]
    assert res["decision_counts"] == {"verified:fresh": 2, "replay:duplicate": 1}
    assert res["rssi_dbm"]["count"] == 3 and res["persisted_high_water"] == {1: C0 + 1}


def test_aging_and_recovery_grading_and_incomplete_run_honesty(tmp_path):
    ar = tmp_path / "aging_and_recovery.json"
    ar.write_text(json.dumps({
        "source": "SIMULATED", "stale_after_s": 70,
        "age_after_duplicates_s": 20.0, "verified_tokens_after_duplicates": 1,
        "stale_at_75s": True, "sightings_at_75s": 1,
        "loss_receiver_status": "disconnected", "loss_beacon_status": "receiver_unavailable", "loss_sightings": 1,
        "recovered_beacon_status": "verifying", "recovered_verified_tokens": 2, "recovered_stale": False,
    }))
    assert grade_aging_and_recovery(ar)["status"] == "PASSED"
    summary = analyze_run(tmp_path)
    # Missing hardware E2/E3/E4 files and SIMULATED aging source must leave c4_hardware_complete False
    assert summary["e2_discovery_1m"]["status"] == "UNTESTED"
    assert summary["e3_distance_and_obstruction"]["1m"]["status"] == "UNTESTED"
    assert summary["c4_hardware_complete"] is False

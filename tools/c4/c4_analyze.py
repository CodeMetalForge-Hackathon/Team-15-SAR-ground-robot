"""Grade C4 hardware and system measurements (SENSOR_ID_SPEC.md & EXPERIMENT_PLAN.md).

Evaluates E2 (20 foreground Start-to-verified trials at 1 m without replay-state
resets), E3 (60 s reception captures at 1 m, 3 m, 5 m, obstruction), E4 (60 s
lifecycle captures: foreground, background, locked, force_quit), C1 real-capture
verifier replay, and verified-card aging / receiver-loss recovery.
Missing hardware stages are marked UNTESTED, never fabricated or zero-filled.
"""
from __future__ import annotations

from datetime import datetime
import json, math, os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ble_id import STALE_S, BeaconMonitor  # noqa: E402
from ble_keys import TEST_KEYS  # noqa: E402
from ble_state import init_state, load_state  # noqa: E402
from discovery.server import Discovery  # noqa: E402


def _pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def rssi_dist(values: list[int]) -> dict | None:
    if not values:
        return None
    s = sorted(values)
    return {"count": len(s), "min_dbm": s[0], "p10_dbm": _pct(s, 0.10),
            "median_dbm": _pct(s, 0.50), "p90_dbm": _pct(s, 0.90), "max_dbm": s[-1]}


def replay_tsv_through_verifier(tsv_path: Path, expected_s: float, *, scope: str,
                                state_path: Path | None = None) -> dict:
    """Replay a recorded capture_serial TSV through Discovery + BeaconMonitor."""
    if not tsv_path.is_file():
        return {"status": "UNTESTED", "file": tsv_path.name}
    if state_path is None:
        state_path = Path(tempfile.mkdtemp(prefix="c4-grade-")) / "state.json"
        init_state(state_path, scope=scope)
    clock = {"wall": 1_794_083_000.0, "mono": 0.0}
    disc = Discovery(lambda: clock["mono"], source="LIVE-HW")
    mon = BeaconMonitor(TEST_KEYS, str(state_path), scope=scope, mode="test-keys",
                        source="LIVE-HW", receiver_ready=disc.ready,
                        wall=lambda: clock["wall"], mono=lambda: clock["mono"])
    start_m = end_m = None
    heartbeats = scan_errors = bad_tsv = 0
    protocol_rssis, verified_counters = [], []
    for raw in tsv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("# capture_start_monotonic="):
            start_m = float(raw.split("=")[1].split()[0])
        elif raw.startswith("# capture_end_monotonic="):
            end_m = float(raw.split("=")[1].split()[0])
        elif raw and not raw.startswith("#"):
            parts = raw.split("\t", 2)
            if len(parts) != 3:
                bad_tsv += 1
                continue
            try:
                clock["wall"] = datetime.fromisoformat(parts[0].replace("Z", "+00:00")).timestamp()
                clock["mono"] = float(parts[1])
            except ValueError:
                bad_tsv += 1
                continue
            line = parts[2]
            heartbeats += line.startswith("#HEARTBEAT,scanning=1")
            scan_errors += line.startswith(("#SCAN_ERROR", "#SCAN_END"))
            before_v = mon.counts.get("verified:fresh", 0)
            disc.ingest(line)
            mon.ingest(line)
            seg = line.split(",") if not line.startswith("#") else []
            if len(seg) == 3 and seg[2].startswith("0101"):
                try:
                    protocol_rssis.append(int(seg[0]))
                except ValueError:
                    pass
            if mon.counts.get("verified:fresh", 0) > before_v:
                verified_counters.append(mon.sightings[1]["counter"])
    os.close(mon.owner)
    dur = (end_m - start_m) if (start_m is not None and end_m is not None) else 0.0
    snap = mon.snapshot()
    return {
        "status": "MEASURED", "file": tsv_path.name, "duration_s": round(dur, 6),
        "duration_ok": dur >= expected_s - 0.5, "heartbeats": heartbeats,
        "scan_errors": scan_errors, "bad_tsv_lines": bad_tsv,
        "protocol_rows": len(protocol_rssis), "verified_windows": len(verified_counters),
        "verified_counters": verified_counters, "rssi_dbm": rssi_dist(protocol_rssis),
        "decision_counts": snap["counts"], "halted": mon.halted,
        "persisted_high_water": dict(load_state(state_path, scope=scope)),
    }


def grade_e2_trials(jsonl_path: Path) -> dict:
    """Grade 20 foreground Start-to-first-verified trials at 1 m."""
    if not jsonl_path.is_file() or not jsonl_path.read_text().strip():
        return {"status": "UNTESTED", "target": ">=19/20 within 10.0 s"}
    trials = [json.loads(l) for l in jsonl_path.read_text().splitlines() if l.strip()]
    resets = sum(1 for t in trials if t.get("state_reset"))
    mono_ok = len({t.get("scope") for t in trials}) == 1 and len({t.get("state_path") for t in trials}) == 1 and resets == 0
    prev_hw, latencies, timeouts, failures = None, [], [], []
    for idx, t in enumerate(trials, 1):
        hw_b, hw_a, lat = t.get("high_water_before"), t.get("high_water_after"), t.get("latency_s")
        if prev_hw is not None and hw_b != prev_hw:
            mono_ok = False
        prev_hw = hw_a
        if t.get("verified") is True and isinstance(lat, (int, float)) and 0 < lat <= 10.0:
            if hw_b is not None and t.get("counter", -1) <= hw_b:
                mono_ok = False
            latencies.append(float(lat))
        else:
            reason = t.get("failure_reason", "timeout_10s")
            if "timeout" in reason:
                timeouts.append(idx)
            failures.append({"trial": idx, "reason": reason, "latency_s": lat})
    passed = len(trials) >= 20 and len(latencies) >= 19 and mono_ok
    dist = ({"min_s": round(min(latencies), 4), "p50_s": round(_pct(latencies, 0.50), 4),
             "p95_s": round(_pct(latencies, 0.95), 4), "max_s": round(max(latencies), 4),
             "mean_s": round(sum(latencies) / len(latencies), 4)} if latencies else None)
    return {"status": "PASSED" if passed else "FAILED", "trials_run": len(trials),
            "succeeded_within_10s": len(latencies), "target": "19/20 within 10.0 s",
            "state_monotonic_ok": mono_ok, "state_resets": resets, "timeouts_10s": timeouts,
            "failures": failures, "latency_s": dist,
            "timing_boundary": trials[-1].get("timing_boundary", "operator_start_mark -> verified_persisted")}


def grade_aging_and_recovery(path: Path) -> dict:
    if not path.is_file():
        return {"status": "UNTESTED"}
    d = json.loads(path.read_text())
    checks = {
        "duplicate_does_not_reset_age": d.get("age_after_duplicates_s", 0) >= 15.0 and d.get("verified_tokens_after_duplicates") == 1,
        "marks_stale_after_70s_and_keeps_card": d.get("stale_at_75s") is True and d.get("sightings_at_75s") == 1 and d.get("stale_after_s") == STALE_S,
        "receiver_loss_preserves_sighting": d.get("loss_receiver_status") in ("disconnected", "unavailable") and d.get("loss_beacon_status") == "receiver_unavailable" and d.get("loss_sightings") == 1,
        "receiver_recovery_resumes_verification": d.get("recovered_beacon_status") == "verifying" and d.get("recovered_verified_tokens", 0) >= 2 and d.get("recovered_stale") is False,
    }
    return {"status": "PASSED" if all(checks.values()) else "FAILED", "source": d.get("source", "UNKNOWN"), "checks": checks, "raw": d}


def analyze_run(run_dir: Path) -> dict:
    e2 = grade_e2_trials(run_dir / "e2_trials.jsonl")
    e3 = {k: replay_tsv_through_verifier(run_dir / f"e3_{k}.tsv", 60.0, scope=f"TESTKEY-e3-{k}") for k in ("1m", "3m", "5m", "obstruction")}
    e4 = {k: replay_tsv_through_verifier(run_dir / f"e4_{k}.tsv", 60.0, scope=f"TESTKEY-e4-{k}") for k in ("foreground", "background", "locked", "force_quit")}
    ar = grade_aging_and_recovery(run_dir / "aging_and_recovery.json")
    all_hw = (e2["status"] == "PASSED" and all(e3[k]["status"] == "MEASURED" and e3[k]["duration_ok"] for k in ("1m", "3m", "5m"))
              and all(e4[k]["status"] == "MEASURED" and e4[k]["duration_ok"] for k in e4)
              and ar["status"] == "PASSED" and ar.get("source") == "LIVE-HW")
    out = {"e2_discovery_1m": e2, "e3_distance_and_obstruction": e3, "e4_lifecycle": e4, "aging_and_recovery": ar, "c4_hardware_complete": all_hw}
    (run_dir / "c4_analysis.json").write_text(json.dumps(out, indent=2) + "\n")
    return out

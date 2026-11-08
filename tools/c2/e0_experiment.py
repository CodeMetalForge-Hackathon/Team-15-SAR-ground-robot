"""E0 software experiment (EXPERIMENT_PLAN.md): deterministic trials per class,
confusion matrix, and host verify() latency. SIMULATED; no radio involved.

    python3 -I tools/c2/e0_experiment.py REPO_ROOT OUTDIR [TRIALS]

Keys are synthetic (derived from a fixed label), never enrolled. Inputs are built
with make_token, so this measures classification stability and latency; the
fixed C0 vectors in tests/ are the independent correctness check.
"""
import csv, hashlib, json, math, platform, random, sys, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from ble_verify import counter_at, make_token, verify  # noqa: E402

SEED, TRIALS = 20261107, int(sys.argv[3]) if len(sys.argv) > 3 else 100
KEYS = {a: hashlib.sha256(b"E0 SYNTHETIC KEY %d" % a).digest() for a in range(1, 9)}
WRONG = hashlib.sha256(b"E0 SYNTHETIC WRONG KEY").digest()


def trial(cls, rng):
    """Returns (expected 'kind:reason', [(payload, now)], seen) for one trial."""
    now = 1794077187.0 + rng.uniform(0, 3e7); n = counter_at(now); a = rng.randint(1, 8)
    tok = lambda c, k=None, al=a: make_token(k or KEYS[al], c, alias=al)
    if cls == "verified":       return "verified:fresh", [(tok(n + rng.choice((-1, 0, 1))), now)], {}
    if cls == "replay_stale":   return "replay:stale", [(tok(n - rng.randint(2, 10**4)), now)], {}
    if cls == "replay_future":  return "replay:future", [(tok(n + rng.randint(2, 10**4)), now)], {}
    if cls == "replay_duplicate": return "replay:duplicate", [(tok(n), now)], {a: n}
    if cls == "replay_not_newer": return "replay:not_newer", [(tok(n - 1), now)], {a: n + 1}
    if cls == "forged_wrong_key": return "forged:bad_tag", [(tok(n, WRONG), now)], {}
    if cls == "forged_bit_flip":
        p = bytearray(tok(n)); p[rng.randint(6, 15)] ^= 1 << rng.randint(0, 7)
        return "forged:bad_tag", [(bytes(p), now)], {}
    if cls == "unknown":        return "unknown:unenrolled_alias", [(make_token(WRONG, n, alias=rng.randint(9, 255)), now)], {}
    if cls == "drop_length":    return "drop:length", [(tok(n)[:rng.choice((0, 1, 15))] + b"\0" * rng.choice((0, 2)), now)], {}
    if cls == "drop_version":   return "drop:unsupported_version", [(bytes([rng.choice((0, 2, 255))]) + tok(n)[1:], now)], {}
    if cls == "drop_reserved_alias": return "drop:reserved_alias", [(bytes([1, 0]) + tok(n)[2:], now)], {}
    if cls == "loss_then_recovery":  # windows n+1..n+k never received; next reception verifies
        k = rng.randint(1, 20); later = now + 30 * (k + 1)
        return "verified:fresh", [(tok(n), now), (tok(counter_at(later)), later)], {}
    raise ValueError(cls)


CLASSES = ["verified", "replay_stale", "replay_future", "replay_duplicate", "replay_not_newer",
           "forged_wrong_key", "forged_bit_flip", "unknown", "drop_length", "drop_version",
           "drop_reserved_alias", "loss_then_recovery"]


def main(out):
    out.mkdir(parents=True, exist_ok=True); rng = random.Random(SEED)
    confusion, lat, rows, invalid_verified = Counter(), [], [], 0
    for _ in range(10):                                     # warmup, excluded
        verify(make_token(KEYS[1], 1, alias=1), KEYS, {}, now=45.0)
    for cls in CLASSES:
        for i in range(TRIALS):
            exp, steps, seen = trial(cls, rng)
            for payload, now in steps:
                t0 = time.perf_counter_ns(); d, seen = verify(payload, KEYS, seen, now=now)
                lat.append(time.perf_counter_ns() - t0)
            got = f"{d.kind}:{d.reason}"
            confusion[(cls, exp, got)] += 1
            invalid_verified += d.kind == "verified" and not exp.startswith("verified")
            rows.append([cls, i, exp, got, payload.hex()])
    lat.sort(); pct = lambda q: lat[min(len(lat) - 1, math.ceil(q * len(lat)) - 1)] / 1000
    total = sum(confusion.values()); correct = sum(v for (c, e, g), v in confusion.items() if e == g)
    m = {"seed": SEED, "trials_per_class": TRIALS, "classes": len(CLASSES), "trials_total": total,
         "correct": correct, "accuracy": correct / total, "invalid_verified": invalid_verified,
         "verify_calls_timed": len(lat), "latency_us": {"p50": pct(0.50), "p95": pct(0.95), "max": lat[-1] / 1000},
         "timing_boundary": "perf_counter_ns around one verify() call; excludes serial, parsing, radio, phone",
         "warmup_calls_excluded": 10, "python": platform.python_version(), "machine": platform.machine(),
         "platform": platform.platform(),
         "confusion": [{"class": c, "expected": e, "observed": g, "count": v}
                       for (c, e, g), v in sorted(confusion.items())]}
    (out / "e0_metrics.json").write_text(json.dumps(m, indent=1))
    with open(out / "e0_decisions.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["class", "trial", "expected", "observed", "last_payload_hex"]); w.writerows(rows)
    print(f"{correct}/{total} as expected; invalid verified: {invalid_verified}; "
          f"latency p50 {m['latency_us']['p50']:.1f} us, p95 {m['latency_us']['p95']:.1f} us")
    for r in m["confusion"]:
        print(f"  {r['class']:<20} expected {r['expected']:<26} observed {r['observed']:<26} n={r['count']}")
    return 0 if correct == total and invalid_verified == 0 else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[2])))

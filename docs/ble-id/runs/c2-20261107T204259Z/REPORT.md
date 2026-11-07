# C2 report: pure verifier and durable replay state

Run: `c2-20261107T204259Z` · November 7, 2026 · tested commit `ec19d1a` (clean clone)
Kind of evidence: **SIMULATED / software only.** No radio, phone, or dashboard involved.

| Gate | Status |
| --- | --- |
| C2 software gate (verifier, vectors, classifications, clock edges, replay state) | **PASSED** |
| C2 software proof clip (screen recording of this run) | **PENDING**: not recorded; I can't record your screen |
| C1 physical video review (from run `c1-capture-20261107T202438Z`) | **PENDING**: still not received, played, or reviewed |
| C3 onward, dashboard integration, second spec | **ON HOLD**, not started |

## 1. What changed, and what can you observe?

Two small modules now exist on `culubo/sensor-id-specs`:

- **`ble_verify.py`** (127 lines) decides what a received 16-byte BLE ID is:
  - **verified:** genuine and new, so it may be reported.
  - **replay:** genuine but old or already seen.
  - **forged:** an enrolled ID with a wrong signature.
  - **unknown:** an ID that isn't enrolled.
  - **drop:** not our format at all.

  It is pure: no clock reads, no file access. It never changes the state you
  hand it; it returns a proposed new state, and only for verified.
- **`ble_state.py`** (119 lines) saves the "highest counter seen per ID" to
  disk so a restart can't be used to replay old IDs. It refuses to start from a
  missing or damaged file instead of quietly starting fresh.

Terms used below:
- **"Replay"** means this already-used ID was rejected.
- **"Window"** is the 30-second slot an ID belongs to.
- **"High-water mark"** is the newest counter accepted for that ID.

## 2. What did we actually try?

All SIMULATED, from a clean clone of `ec19d1a`:

| Check | Where | Command | Result |
| --- | --- | --- | --- |
| Full test suite | Your Mac's Linux VM, Python 3.10.12, pytest 8.3.4 | `python -B -m pytest -v tests` | 104 passed, exit 0 |
| Same suite, second environment | Cloud workspace, Python 3.13.18, pytest 9.1.1, byte-identical files | same | 104 passed, exit 0 |
| Each commit on its own | VM | pytest at `1e1da6d`, then `d8a5776` | 74 passed, then 104 passed |
| Mutation check (break code on purpose) | VM | `python -I tools/c2/mutation_check.py . <tmp>` | 10/10 breaks caught, exit 0 |
| E0 experiment | VM | `python -I tools/c2/e0_experiment.py . e0 100` | 1,200/1,200 as expected, exit 0 |

## 3. What happened? Expected vs observed

| What was tested | Expected | Observed | Pass |
| --- | --- | --- | --- |
| 11 authentication vectors from C0 (checksum-pinned file) | Each exact decision | All 11 match | PASS |
| 8 freshness vectors, 6 multi-step sequences | Each exact decision | All match | PASS |
| `make_token` vs every authentic C0 payload, and the max-counter payload | Identical bytes | Identical | PASS |
| Window edges: token 59.999 s old vs 60.000 s old | Accept, then reject as stale | Accepted, then `replay:stale` | PASS |
| Phone and verifier clocks 5 min apart (both directions) | `future` / `stale` | As expected | PASS |
| Every one of 80 tag-bit flips | forged, state unchanged | All forged, state untouched | PASS |
| Every one of 48 header-bit flips | Never verified | Never verified | PASS |
| Forged, unknown, truncated, future, stale inputs before a genuine one | Genuine one still verified (no poisoning) | Verified every time | PASS |
| Same ID heard in zone A then zone B (one process) | Second is `replay:duplicate` | As expected | PASS |
| Purity: clocks and `open()` made to fail during verify | verify still works, input unchanged | As expected | PASS |
| Restart after saving | Old ID rejected, next ID accepted | As expected | PASS |
| 19 kinds of damaged or missing state file | Refuse to load (fail closed) | All 19 refused | PASS |
| Write fails midway | Old state intact, no temp files left | As expected | PASS |
| **Negative control:** force the signature check to always succeed | A forged ID would verify | It did, so the tests can see a bypass | PASS |
| **Mutation check:** 10 deliberate bugs (listed in `mutation_check.log`) | Test suite fails for each | Failed for all 10 | PASS |

E0 experiment: 12 classes × 100 deterministic trials, seed 20261107, synthetic
keys. Every trial landed in its expected class: a perfect diagonal confusion
matrix, with zero invalid verified decisions. The classes:
- verified, and verified after 1 to 20 missed windows
- stale, future, duplicate, not_newer
- forged by wrong key, forged by bit flip
- unknown
- dropped for length, version, or alias 0

Host latency of one `verify()` call over 1,300 timed calls (10 warmup calls
excluded): p50 3.2 µs, p95 5.1 µs, max 57.2 µs. That was on the Linux VM
(aarch64) on your Mac. The timing covers only the function call; serial
parsing, radio, and phone delay are excluded, so this is not end-to-end
latency. The 100% figure is a finite fixture result, not a measured
cryptographic false-accept rate.

## 4. Where is the proof? (this directory)

- `environment.txt`: tested commit, clean-clone status, host, versions
- `commands.log`: every command and its exit code
- `pytest_vm_py310.log`, `pytest_cloud_py313.log`: verbose test output (104 test names each)
- `per_commit_tests.log`: each code commit green on its own
- `mutation_check.log`: the 10 deliberate bugs and how many tests caught each
- `e0/e0_metrics.json`, `e0/e0_decisions.csv`, `e0_run.log`: confusion matrix, per-trial decisions, latency
- `MANIFEST.sha256`: checksums of every file here
- Code: `ble_verify.py`, `ble_state.py`, `tests/`, `tools/c2/` at `ec19d1a`

Reproduce from the repo root (needs pytest):

```sh
python -B -m pytest -v tests
python -I -B tools/c2/mutation_check.py . /tmp/c2mut
python -I -B tools/c2/e0_experiment.py . /tmp/e0 100
```

## 5. What this establishes, what is unproven, what's next

**Established (software only):**
- The verifier follows the agreed classification order and the fixed C0 vectors.
- It handles window edges and clock skew as specified.
- It rejects tampering.
- Rejected input can't poison replay state.
- Replay protection survives restarts and fails closed on lost or damaged state.

**Unproven or not done in C2:**
- **The software proof clip:** not recorded.
- **C1 physical video review:** still PENDING.
- **Python 3.11 (CI's version):** not run. 3.10 and 3.13 were.
- **Key loading:** `keys.json` loading and the proposed production refusal of
  public test keys are not implemented. They belong with the adapter (C3) and
  depend on Amendment 1.
- **RSSI validation:** this is the adapter's job; the verifier never sees RSSI.
- **Cross-process locking:** none. One verifier process owns one state file.
- **The E0 caveat:** E0 builds its inputs with `make_token`, so it is not
  independent of the code. The independent check is the C0 vector set,
  generated earlier with Python's `hmac` and the OpenSSL CLI.
- **Out of scope by design:** rollback of the state file, compromised keys, and
  real-time relays (base spec).

**Layout note:** files follow the base spec's names (`ble_verify.py`,
`ble_state.py`, `tests/`), because Amendment 1's package layout (A5) is still
PROPOSED. Reports follow C1's `docs/ble-id/runs/` location.

**Next:** your review. C3 (adapter, simulator, dashboard posting) needs separate
authorization, and dashboard posting is still blocked on the owner questions.

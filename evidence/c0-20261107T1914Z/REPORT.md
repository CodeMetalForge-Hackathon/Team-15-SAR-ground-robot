# C0 report: baseline, interfaces, protocol vectors, experiment plan

Run ID: `c0-20261107T1914Z` · 2026-11-07, UTC 19:05 to 19:50 · revision 3

| Gate item (spec C0) | Status |
| --- | --- |
| Inspect real interfaces | **PASSED**, with the caveat that refs are from the 19:05 UTC fetch (see below) |
| Record baseline commands and results | **PASSED** (31 passed) |
| Protocol vectors | **PASSED** (33 payloads, two independent HMAC implementations agree) |
| Experiment plan | **PASSED** (written; nothing in it has been run) |
| Integration | **BLOCKED** on the contract mismatch; Amendment 1 is **PROPOSED**, not adopted |
| C1 and later | **NOT STARTED**, and not authorized |

This was inspection, documentation, and test-vector generation only. No module
code was written, no hardware was used, and no video was recorded (C0 doesn't
require one).

## The five questions

**1. What changed, and what can you observe now?**
There's no module code. You can now read:
- the team's actual sensor contract, and where our spec's assumptions differ
- a fixed set of 33 test payloads with the expected decision for each
- a step-by-step plan for the later hardware experiments
- a revised, still-proposed spec amendment
- draft questions for the dashboard and BLE owners (not sent)

**2. What did we actually try?**

| Step | Mode | Result |
| --- | --- | --- |
| Fetch remote branches | network | **FAILED**: no GitHub credentials in the shell, and no org access for the session. Uses refs from the last successful fetch at 19:05 UTC |
| Read `origin/main` 45e2659 and `origin/t2/dashboard-a-to-g` a36a658 | inspection | Done (paths in section "Actual contract") |
| Search all 5 remote branches and the PDF for `forge/`, `Reading`, `get_sensors`, Makefile | inspection | Not found anywhere |
| Teammates' tests in a throwaway clone | SIMULATED (their fixtures) | 31 passed, exit 0 |
| Read-only probe of their ingest/store with BLE-shaped data | SIMULATED | 8 checks, see table below |
| Generate protocol vectors (`gen_vectors.py`) | software only | 33 payloads; Python `hmac` equals OpenSSL CLI for every one; exit 0 |
| Shell-only recomputation of vector A1 (no Python) | software only | Tag `c438cfa7043609b9d1c4` matches |

Environment: Linux aarch64 VM on your computer, Python 3.10.12, OpenSSL 3.0.2.
This is not the bench Mac's native macOS, and not CI, which uses Python 3.11.

**3. What happened? (expected vs observed)**

| Check | Expected by our spec | Observed | Result |
| --- | --- | --- | --- |
| `forge/`, `Reading`, `get_sensors`, Makefile | Exist | Absent | MISMATCH |
| Real sensor contract | `Reading(sensor, zone, t, value, kind)` | Observation JSON to `POST /observations` | MISMATCH |
| Ingest checks `kind`/`sensor` | (assumed) | `kind="forged"` and `sensor="zzz"` accepted (P2, P3) | CONFLICT |
| BLE observation on dashboard | "beacon heard" | "Candidate in sector A (assigned)", becomes route target (P6) | CONFLICT |
| A posted `forged` decision | Shown as rejected | Became track T2 and moved the route to A→G 60 m (P6) | CONFLICT |
| RSSI visible | Yes | Not exported by `/state` (P7) | GAP |
| Duplicate erases a sighting | Must not | Tracks never deleted; stale after 120 s (P8) | OK |
| BLE stale TTL | n/a | Code 120 s vs build plan 60 s | TEAM INCONSISTENCY |
| `evidence/` committed | Yes | t2 `.gitignore` ignores all `evidence/` dirs | CONFLICT after merge |
| BLE ownership | Our module | Build plan gives `ble/` to Teammate D (Pi, plain UUID) | OPEN QUESTION |
| Vectors: Python vs OpenSSL | Identical | Identical for all 33 | PASS |
| Vectors: counter overflow | `make_token` errors at 2^32 | Errors | PASS |

Expected decisions in the vectors were written by hand from the spec's rules.
No verifier exists yet, so the vectors can't confirm their own expectations;
C2 must meet them. Sample sizes: one baseline run, one probe run, one
generation run. No timing was measured.

**4. Where is the proof?** (this directory)
- `refs.txt`: inspected hashes, ref times, t2 file list
- `baseline_pytest.log`: commands, verbose output, exit codes
- `environment.txt`: host and package versions
- `ingest_probe.py` and `ingest_probe.log`: probe source and output
- `gen_vectors.py`, `protocol_vectors_v1.json`, `vectors_run.log`: generator,
  vectors (SHA-256 `558467fd…3899` since r3; r2 was `e4ee626e…075b`, and only
  A9's label text differs), run log with checksums and the shell cross-check
- `EXPERIMENT_PLAN.md`, `OWNER_QUESTIONS.md`, `C1_READINESS.md`
- Tested revisions: teammates' `a36a658`; ours `31600f1`. This revision's own
  commit hash can't be cited inside it.

**5. What does this establish, what is unproven, and what's next?**
- **Established:**
  - The real integration point is observation JSON plus `POST /observations`.
  - Today's dashboard would show any posted observation as a person and route
    to it, so only verified detections may ever be posted.
  - The v1 byte layout and HMAC are pinned down by vectors two independent
    implementations agree on.
- **Unproven:**
  - Whether iOS carries the UUID intact. The on-air byte order is expected but
    unconfirmed.
  - Any radio, timing, or lifecycle result.
  - Branches pushed after 19:05 UTC.
- **Decided (r3):** alias 0 is malformed and dropped; the replay reason
  labels are `stale`, `future`, `duplicate`, and `not_newer`. Both are now in
  the base spec.
- **Next (needs you):**
  - Fill in the missing items in `C1_READINESS.md`.
  - Accept, edit, or reject the rest of Amendment 1 (A1 to A7).
  - Send or adapt the owner questions yourself.
  - Decide whether to authorize C1.

## Vector summary (synthetic keys; N = 59802572 = `0x039083cc`; now = 1794077187)

- **A1 to A11 (authentication):**
  - Valid tokens for aliases 1 and 2 are verified.
  - These are forged: wrong key, changed alias byte, changed counter, flipped
    tag bit.
  - An unenrolled alias 7 is unknown.
  - These are dropped: version 0x02, alias 0, 15 or 17 bytes.
- **F1 to F8 (freshness):**
  - Windows N−1, N, and N+1 are verified.
  - N−2 is stale and N+2 is future.
  - Edges are tested at the first instant of window N and at 0.001 s before
    window N+1. That last case gives a token about 59.999 s old, which shows
    why no exact 30 s freshness claim is made.
- **S1 to S6 (state):**
  - A duplicate in the same window is a replay.
  - Accepting the future window first makes the current window `not_newer`
    (the documented tradeoff).
  - A forged token doesn't poison state.
  - Aliases are isolated from each other.
  - A clock jump forward makes old tokens stale.
  - A clock jump back after a future accept stays locked out until the counter
    passes the high-water mark.

Reference payload (A1): UUID `01010390-83cc-c438-cfa7-043609b9d1c4`, expected
on-air (little-endian) `c4d1b9093604a7cf38c4cc8390030101`.

## Actual contract found (source paths, t2 at a36a658)

- **`core/ingest.py`:**
  - Requires `obs_id, drone_id, source_mode, sensor, kind, how, cell, obs_time`.
  - `obs_id` matches `^[A-Za-z0-9]+-[A-Za-z0-9]+-\d{6}$`, and its first part
    must equal `drone_id`.
  - `cell` must be a trail-map node A to Z.
  - `obs_time` is float Unix seconds; `rx_time` is overwritten by the server
    clock.
  - TTL defaults are rgb 300 s, ble 120 s, thermal 300 s. Extra keys are kept.
- **`core/store.py`:** in memory. Dedup by `obs_id`; one track per cell; the
  route targets the newest track; `/state` exports a fixed field set.
- **`dashboard/app.py`:** `POST /observations` (422 on invalid), `GET /state`,
  `GET /`, `GET /evidence/{obs_id}`. `index.html` polls every 500 ms.
  `dashboard/serve.py` preloads JSON/JSONL.
- **Build plan (`TEAM15_DRONE_SEARCH_BUILD.md`, main):** §8.2 contract, BLE kind
  `BLE_ENROLLED_BEACON`, and §9.3 "never 'a person is here'".

Teammates' code was not modified. The throwaway clone was outside the repo and
has been deleted.

# C0 report: baseline and interface inspection

Run ID: `c0-20261107T1914Z` · Date: 2026-11-07 (UTC 19:05 to 19:20)
Checkpoint: **C0, PARTIAL.** Interface inspection is done. Protocol vectors and
the experiment plan are deferred until the output contract is settled.
Integration is **BLOCKED** on the contract mismatch described below.
Kind of work: **inspection and documentation only.** No module code was written,
no BLE hardware was used, and no video was recorded. C0 does not require one.

## The five questions

**1. What changed, and what can you observe now?**
Nothing changed in the code. This report, its logs, and a proposed spec
amendment (`SENSOR_ID_SPEC_AMENDMENT_1.md`, status PROPOSED) were added to
`culubo/sensor-id-specs`. You can now see what the team's code actually expects
from a sensor and where our spec assumed something that doesn't exist.

**2. What did we actually try?** Labels: inspection, plus one BUILD ONLY-style
software baseline run. Nothing ran on REAL HARDWARE or under SIMULATED mode.
- Tried `git fetch --all --prune`. It **FAILED** (no GitHub credentials in the
  shell; the session's GitHub access also has no rights to this org). The
  inspection uses the remote-tracking refs from the last successful fetch,
  written 19:05 UTC, eight minutes before the request. Branches pushed after
  that are not reflected. See `refs.txt`.
- Read `origin/main` (`45e2659`) and `origin/t2/dashboard-a-to-g` (`a36a658`):
  the build plan, `core/ingest.py`, `core/store.py`, `dashboard/app.py`,
  `dashboard/serve.py`, `dashboard/static/index.html`, the dashboard tests,
  `perception/live_camera.py`, `planner/route.py`, CI, `pytest.ini`,
  `requirements.txt`, `.gitignore`.
- Searched every remote branch and the hackathon PDF for `forge/`, `Reading`,
  `get_sensors`, `packet.py`, `fuse.py`, `pipeline.py`, and a Makefile.
- Ran the teammates' test suite in a throwaway clone outside the repo.
- Ran a read-only probe (`ingest_probe.py`) that feeds BLE-shaped observations
  to their unchanged `core.ingest` / `core.store`.

**3. What happened?**

| Check | Expected (our spec) | Observed | Result |
| --- | --- | --- | --- |
| `forge/packet.py`, `Reading`, `get_sensors`, Makefile exist | Present on the integration branch | Absent on all 5 remote branches and in the PDF | MISMATCH |
| Teammate baseline `pytest -q` at `a36a658` | Record it | 31 passed, 0 failed, exit 0 (Python 3.10.12, Linux aarch64 VM) | RECORDED |
| `python -m planner.route A G` | Record it | `A-B-C-D-E-F-G`, 60 m, exit 0 | RECORDED |
| Sensor output contract | `Reading(sensor, zone, t, value, kind)` | Observation JSON posted to `POST /observations` (fields listed below) | MISMATCH |
| Ingest validates `kind` / `sensor` | (assumed) | Not validated. `kind="forged"` and `sensor="zzz"` were both accepted (probe P2, P3) | CONFLICT |
| How the store shows a BLE observation | "Verified BLE observation", not a person | Labelled "Candidate in sector A (assigned)" and becomes a route target (P6) | CONFLICT |
| Posting a non-verified decision | Shown as replay/forged/unknown | A `kind="forged"` post at G became track T2 and moved the active route to A→G, 60 m (P6) | CONFLICT |
| RSSI on the dashboard | Shown as value | Extra fields are kept in the store but not exported by `/state` (P7) | GAP |
| Dashboard expiry vs 30 s rotation | Must not erase a verified sighting on a duplicate | Never deletes. Marks stale after 120 s for `sensor="ble"` (P8). Compatible | OK |
| BLE stale TTL | n/a | Code says 120 s, build plan §9.6 says 60 s | TEAM INCONSISTENCY |
| Evidence path `evidence/<run-id>/` | Committed to Git | t2's `.gitignore` ignores every dir named `evidence/` (this would also hide the plan's `docs/evidence/`) | CONFLICT after merge |
| Who owns BLE | Our module (ESP32, HMAC) | Build plan §5.3 gives `ble/` to Teammate D: a bleak scanner on the Pi and a plain UUID with no authentication | OWNERSHIP QUESTION |

Sample sizes: one baseline run, one probe run. No timing was measured.

**4. Where is the proof?** (all in this directory)
- `refs.txt`: commit hashes inspected, ref timestamps, the t2 file list
- `baseline_pytest.log`: commands, verbose test output, exit codes
- `environment.txt`: host, Python and package versions
- `ingest_probe.py` and `ingest_probe.log`: probe source and output
- Tested revisions: teammates' `a36a658`. Our branch at inspection time:
  `40e56f2`, clean. This report's own commit hash can't be cited inside it.

**5. What does this establish, what is unproven, and what happens next?**
- **Established:** the team's real integration point is an observation JSON
  contract plus `POST /observations`, not a `Reading` class. Our spec's
  `forge/` names came from an assumption, not from the repo or the PDF. Today
  the dashboard treats any posted observation as a person candidate and as a
  route target, regardless of `kind`.
- **Unproven:** anything about BLE transport, iOS, ESP32, verification logic,
  or timing. The state of branches pushed after 19:05 UTC.
- **Next:** decide on the amendment questions (ownership, labelling, TTL,
  evidence path). After that, finish C0 (protocol vectors with synthetic keys,
  experiment plan) and only then start C1, if you authorize it.

## Actual contract found (source paths)

`core/ingest.py` (t2): required `obs_id, drone_id, source_mode, sensor, kind,
how, cell, obs_time`.
- `obs_id` must match `^[A-Za-z0-9]+-[A-Za-z0-9]+-\d{6}$` and its first part
  must equal `drone_id`.
- `source_mode` ∈ {SIMULATED, RECORDED-IMAGERY, LIVE-HW}; `platform` optional,
  ∈ {SIM, BENCH, AIRCRAFT}; `how` ∈ {SECTOR_ONLY, BEARING_ONLY, GROUND_PLANE,
  MULTI_VIEW}.
- `cell` must be a trail-map node (A to Z, from
  `fixtures/trail_graph_synthetic.json`).
- `obs_time` is a float in Unix epoch seconds. Ingest always overwrites
  `rx_time` with the base station's own clock. It fills in `boot_id`, `seq`,
  and `stale_after_s` (rgb 300 s, ble 120 s, thermal 300 s).
- Extra keys are preserved as-is.

`core/store.py` (t2): in memory, so a restart loses state. Dedup is by `obs_id`.
There is one track per cell. The responder route always targets the track with
the newest `obs_time`. `/state` exports a fixed set of `latest` fields
(`kind`, `sensor`, `confidence`, `evidence.detector*`, photo) and never RSSI.

`dashboard/app.py`: `POST /observations` returns 422 on `InvalidObservation`.
Other endpoints are `GET /state`, `GET /`, and `GET /evidence/{obs_id}`.
`dashboard/static/index.html` polls `/state` every 500 ms.
`dashboard/serve.py` preloads JSON/JSONL observation files.

Build plan `TEAM15_DRONE_SEARCH_BUILD.md` (main) §8.2 lists the same contract
plus `evidence`, `replay_of`, `ce_m`, `bearing_deg`, `xy_m`. Its BLE kind is
`BLE_ENROLLED_BEACON`. Its stated BLE meaning (§9.3) is that a beacon was
heard by a receiver, "never 'a person is here'".

Teammates' code was not modified. The throwaway clone lives outside the repo,
and the repo working tree only gained this report and the amendment.

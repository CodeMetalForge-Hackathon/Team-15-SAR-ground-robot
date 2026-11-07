# Sensor-ID spec, amendment 1: align with the team's real integration contract

Status: **PROPOSED. Not adopted. Implementation is still NOT authorized.**
Source: C0 inspection `evidence/c0-20261107T1914Z/REPORT.md` of
`origin/t2/dashboard-a-to-g` at `a36a658` and `origin/main` at `45e2659`.
This amends `SENSOR_ID_SPEC.md` only after the user accepts it. Every section of
the base spec not named here stays in force. `SENSOR_ID_VALIDATION_SPEC.md` is
unchanged and remains planning only.

## Why

The base spec assumes `forge/packet.py`, `forge/fuse.py`, `forge/pipeline.py`,
a `Reading(sensor, zone, t, value, kind)` type, a `get_sensors` registry, and
`make test` / `make sim`. None of these exist on any remote branch or in the
hackathon PDF. The team's real contract is an observation JSON object
validated by `core/ingest.py` and accepted at `POST /observations`
(`dashboard/app.py`).

## A1. Replace the output contract

Replace "Output contract and adapters" lines 143–149 in the base spec with the
following. Only **verified** decisions become observations:

| Observation field | Value from the BLE module | Replaces |
| --- | --- | --- |
| `obs_id` | `{receiver_id}-{boot_id}-{seq:06d}` | (new) |
| `drone_id` | `receiver_id`: alphanumeric only, e.g. `BLE1`. The field name is the team's; it identifies our receiver, not a drone. | `sensor="ble_id"` |
| `boot_id` | Alphanumeric, unique per verifier process start, persisted with replay state so `obs_id` never repeats across restarts | (new) |
| `seq` | Monotonic per boot, starting at 1. At 999999 the verifier stops posting and reports an error; it never wraps | (new) |
| `source_mode` / `platform` | `LIVE-HW` / `BENCH` in live mode; `SIMULATED` / `SIM` in sim mode | SIMULATED/LIVE banner |
| `sensor` | `ble` | (new) |
| `kind` | `BLE_ENROLLED_BEACON` (build plan §8.2) | `kind=verified` |
| `how` | `SECTOR_ONLY` | (new) |
| `cell` | Scanner's declared trail-map cell, A to Z. Required in live mode with no default. Sim fixtures declare it explicitly | `zone`, default "A" |
| `obs_time` | Host reception time, float Unix epoch seconds. Not the token counter | `t` |
| `confidence` | `null`. RSSI is not a confidence | (new) |
| `evidence` | `{"rssi_dbm": <finite float>, "receiver": "<receiver_id>", "auth": "HMAC-v1 verified"}` | `value` |

Alias, counter, tag, and key material are never placed in an observation.
They stay in the module's decision log, as the base spec already requires.

## A2. Non-verified decisions are not posted

`replay`, `forged`, `unknown`, and malformed input go only to the module's
decision log and reason counters. They are never sent to `POST /observations`.

Reason: the C0 probe (P2, P6) showed that ingest accepts any `kind`, and that
the store turns any accepted observation into "Candidate in sector X". It also
retargets the responder route to the newest one. A posted `forged` decision
would move the route.

Test, video, and report evidence for the four decision kinds therefore come
from the module's own decision log and console. Injected forged and replay
cases stay labelled INJECTED, as before. The table rows "Cover all four output
kinds" and "Exact Reading fields" become: all four decisions in the decision
log; exactly one observation per verified decision; zero observations for the
other three.

## A3. Transport into the base station

- **Live:** the adapter POSTs each verified observation as JSON to a base URL
  given explicitly on the command line (e.g. `--post http://127.0.0.1:8000`).
  A 422 response or a connection error is shown visibly and logged. Nothing
  is retried silently, and no observation is dropped without a log line.
- **Sim:** the same adapter, given an injected clock and a fixed-seed fixture,
  either POSTs or writes JSONL loadable with
  `python3 -m dashboard.serve --observation <file>`.
- Replaces "Wire only the existing get_sensors registry". There is no registry.

## A4. Requests to other owners (we do not edit their files)

These need the named owner's decision. Until R1 is resolved, posting live BLE
observations to the shared dashboard is **BLOCKED**. Module tests may use a
private `MissionStore` instance instead.

| # | Owner (build plan §5) | Request | Why |
| --- | --- | --- | --- |
| R1 | Integration (T2): `core/store.py`, dashboard | Show `kind=BLE_ENROLLED_BEACON` as "enrolled beacon heard by receiver at X", not "Candidate in sector X". Don't make it the route target unless the operator confirms | Build plan §9.3: never "a person is here". Our spec's honest-claims section |
| R2 | Integration | Whitelist `sensor` and `kind` values in `core/ingest.py` | P2/P3: arbitrary kinds are accepted |
| R3 | Integration | Export `evidence.rssi_dbm` in `/state` `latest` | P7: RSSI is not visible |
| R4 | Integration + plan author | Pick one BLE TTL: code says 120 s, plan §9.6 says 60 s. Either works with a 30 s rotation; we take whatever the team chooses | Consistency |
| R5 | Integration | Add `ble_id/tests` to `pytest.ini` `testpaths`; add `pyserial` to `requirements.txt` (pinned) | Both files are owned by T2 |
| R6 | Integration | The `.gitignore` entry `evidence/` hides every directory named `evidence` (including the plan's `docs/evidence/`) | See A6 |
| R7 | Pi/BLE (T4) and team | Decide BLE ownership: T4's plain-UUID bleak scanner on the Pi, our authenticated ESP32 module, or both as separate producers | Plan §5.3 assigns `ble/` to T4 |

## A5. File layout and acceptance commands

Replaces "Create ble_id.py ... tests/test_ble_id.py", to match the team's
per-package layout:

- `ble_id/verify.py` (pure protocol), `ble_id/adapter.py` (serial to
  observation), `ble_id/sim.py` (deterministic fixtures),
  `ble_id/tests/` (tests), `firmware/esp32_scanner/esp32_scanner.ino`,
  `ios/BeaconApp/`. The 150-line limit is unchanged. Nothing goes in `ble/`
  unless R7 assigns it to us.
- Acceptance commands, replacing `make test` / `make sim` (there is no Makefile):
  module `pytest -q ble_id/tests`; full suite `pytest -q` (what CI runs);
  sim `python3 -m ble_id.sim --fixture <file> --post <url>`, or JSONL plus
  `dashboard.serve`.
- CI runs Python 3.11. The C0 baseline ran on 3.10.12. Record the bench Mac's
  version at C1.
- Protected files, replacing "Do not edit forge/...": everything outside
  `ble_id/`, `firmware/`, `ios/`, our spec files, and our run reports.

## A6. Evidence location

Run reports move from `evidence/<run-id>/` to `docs/ble-id/runs/<run-id>/`, so
the team's `.gitignore` won't hide new ones after a merge. C0's own report stays
where it was committed. Large videos stay outside Git, as before.

## A7. Unchanged on purpose

Wire format v1, HMAC and replay semantics, passive receiver, foreground-only
baseline, experiment sample sizes, video requirements, checkpoint structure, and
honest-claims language are all unchanged. Duplicates within a window remain
`replay (duplicate)` in our log. With A2 they are simply never posted. The
dashboard never deletes tracks (probe P8), so a duplicate can't erase a prior
verified sighting.

## Decision needed from the user

Accept, edit, or reject A1 to A6. Get answers from teammates on R1 and R7.
After that: finish C0 (protocol vectors with synthetic keys, experiment plan),
then authorize C1 separately.

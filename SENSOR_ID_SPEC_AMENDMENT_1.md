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
| `boot_id` | A fresh random value generated at every process start: 8 lowercase hex characters from a CSPRNG (`secrets.token_hex(4)`). It is never persisted or reused, and it is logged at startup | (new) |
| `seq` | Monotonic within one boot, starting at 1, and starting over with each new `boot_id`. At 999999 the verifier stops posting and reports an error; it never wraps | (new) |
| `source_mode` / `platform` | `LIVE-HW` / `BENCH` in live mode; `SIMULATED` / `SIM` in sim mode | SIMULATED/LIVE banner |
| `sensor` | `ble` | (new) |
| `kind` | `BLE_ENROLLED_BEACON` (build plan §8.2) | `kind=verified` |
| `how` | `SECTOR_ONLY` | (new) |
| `cell` | The **receiver's declared location**: the trail-map cell, A to Z, where the operator says the scanner is placed. Required in live mode with no default. Sim fixtures declare it explicitly | `zone`, default "A" |
| `obs_time` | Host reception time, float Unix epoch seconds. Not the token counter | `t` |
| `confidence` | `null`. RSSI is not a confidence | (new) |
| `evidence` | `{"rssi_dbm": <finite float>, "receiver": "<receiver_id>", "auth": "HMAC-v1 verified"}` | `value` |

**The cell is not a survivor location.** An observation means "an enrolled
phone was heard by the receiver declared at cell X at `obs_time`." It is never
a measured or estimated position of a person. RSSI does not refine it.

**Boot ID versus replay state.** These are separate on purpose. `boot_id` exists
only to keep `obs_id` unique, and it is new on every start. Replay state (the
per-alias high-water counters) is stored durably on its own, under the base
spec's "Persist replay state" rules. It survives restarts and fails closed if
lost or corrupt. A restart therefore keeps replay protection but always gets a
new `boot_id`. Two random 32-bit boot IDs colliding is negligible over a
mission; a collision would make the store treat a post as a duplicate, which
loses that one observation but never forges one.

**Secret keys are never written outside their key stores.** That covers the
iOS Keychain and the ignored, permission-restricted `keys.json`. Key bytes, and
anything derived from them other than the 80-bit tag, must never appear in:
- observations
- decision logs, console or serial output, or error messages
- evidence, reports, test fixtures, or video

The decision log may record alias, counter, truncated tag, decision, and reason
for diagnostics. Those never go into an observation. Evidence and tests use
only the PUBLIC SYNTHETIC TEST KEYS in
`evidence/c0-20261107T1914Z/protocol_vectors_v1.json`. Those keys must never be
enrolled, and the verifier refuses to load any key equal to one of them.

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

**What "offline" means here.** At runtime, offline means no internet, cellular,
GPS, cloud service, or remote DNS. It does not forbid a local connection to the
team dashboard. The verifier host may POST to the dashboard on the same machine
over loopback (`127.0.0.1`, the default), or on the team's local wired network
(for example, Mac and Pi on the Ethernet switch). Neither needs internet access.
Proposed safeguard: the adapter refuses a `--post` URL whose host is not
loopback, a private or link-local address, or a `.local` name.

The ESP32 stays passive, as before. The serial-to-HTTP hop happens on the host,
never on the scanner, and the scanner still makes no Wi-Fi transmissions.

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

## A8. Protocol vectors are the fixed reference

C2 tests load `evidence/c0-20261107T1914Z/protocol_vectors_v1.json` unchanged
(SHA-256 recorded in that run's `vectors_run.log`). If the file is copied into
the test tree, the copy must keep that checksum. One interpretation is flagged
there for acceptance: alias 0 is treated as malformed, so it is dropped (vector
A9). The base spec reserves alias 0 but doesn't classify it. Reason labels
`stale`, `future`, `duplicate`, and `not_newer` are proposed diagnostics.

## Decision needed from the user

Accept, edit, or reject A1 to A8. Get answers from teammates on R1 and R7.
Questions for the dashboard and BLE owners are drafted in
`evidence/c0-20261107T1914Z/OWNER_QUESTIONS.md`, and have not been sent. C1
needs separate authorization.

Revision history: r1 (31600f1) initial proposal. r2: secret keys never logged;
cell is the receiver's declared location; fresh boot ID per start with separate
durable replay state; offline permits a local dashboard link; vectors (A8).

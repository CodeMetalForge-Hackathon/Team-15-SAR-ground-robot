# C3 report: serial reception → verifier → durable state → local dashboard

Run: `c3-20261107T205707Z` · November 7, 2026 · tested commit `f104439` (clean clone)

| Gate | Status |
| --- | --- |
| C3 software integration (serial → verifier → state → API → browser), SIMULATED | **PASSED** |
| C3 software proof clip (SIMULATED, playable) | **DELIVERED, with one gap**: `c3-software-proof-SIMULATED.mp4`, kept outside Git. Packet loss isn't visually distinguishable in it (covered by an automated test instead) |
| Browser shows an authenticated observation from **real iPhone + ESP32** data | **UNTESTED**: not run in this session |
| Shared mission-dashboard integration (`core/`, `dashboard/`, POST /observations) | **PENDING**: Amendment 1 is still PROPOSED; nothing posted, no teammate code edited |
| C1 physical video review | **PENDING** (unchanged) |
| C2 software proof clip | **PENDING** (unchanged; the C3 clip is not counted as C2's) |
| C4 onward, second spec | **NOT STARTED** |

## 1. What changed, and what can you observe?

The standalone discovery page now has a separate **Verified beacons** panel above
the existing views:

- **The verified-beacon card:** a card appears only when an enrolled phone's
  current token passes four steps in order:
  1. the signature check;
  2. the 30-second window check;
  3. the replay check;
  4. saving the new replay state to disk.

  The card shows when the last *authenticated* token arrived. Repeated
  advertisements of the same token never refresh that time and never remove the
  card.
- **Rejected outcomes:** replay, forged, unknown and malformed results stay in a
  "Rejected and diagnostic events" drawer. They never become cards or rescue
  targets.
- **Nearby signals and Apple hints:** these keep their UNVERIFIED labels and
  aren't connected to verified beacons. Beacons are identified by authenticated
  alias, never by MAC address.
- **Banners:** a red **SIMULATED** banner or an amber **SYNTHETIC TEST KEYS**
  banner appears whenever either applies. Receiver loss, verification halts and
  an unreachable server are shown as text.

Terms used below:
- **"Replay"** means the token was genuine but already used or outside its time
  window.
- **"Forged"** means an enrolled alias with the wrong signature.
- **"Unknown"** means an alias not enrolled on this receiver.
- **"Malformed"** means the serial row wasn't in the protocol's format.

How it's built (all new handwritten files are under 150 lines):

| Piece | What it does |
| --- | --- |
| `ble_keys.py` (104) | Explicit key modes. **production** loads only a named `keys.json` (owner-only permissions, one key per alias, no duplicates) and refuses every published synthetic key. **test-keys** and **simulated** use built-in synthetic keys only, and require `TESTKEY-` / `SIMULATED-` scopes, which production refuses |
| `ble_id.py` (149) | Validates each row: framing, canonical lowercase UUID, RSSI −127..20, no device name on protocol tokens, length, host clock. Then the C2 verifier, then **save state, then publish**. Any clock, verifier or save error **halts visibly**. One `flock` owner per state file. `python3 -m ble_id init-state` is the only way to create state |
| `ble_sim.py` (118) | Deterministic SIMULATED 40 s schedule on a private pseudo-terminal, with simulator keys, a `SIMULATED-` scope, a fresh state folder and port 8766 |
| `discovery/beacons.py` (52) + `static/beacons.js` (98) | Command-line wiring and the panel |
| `discovery/server.py` | Small hooks only. Still **one** serial reader (`TIOCEXCL`), now handing each line to discovery and then to the verifier. Adds `/api/beacons` |

## 2. What did we actually try? (all SIMULATED unless stated)

| Step | Where | Result |
| --- | --- | --- |
| Baseline before changes: C2 suite, discovery tests, JS syntax | Mac VM | 104 passed, 8 passed, OK (`baseline/`) |
| Preserved the discovery session's uncommitted work unchanged | git | Commit `02f035c` |
| Full suite at `f104439` | Mac VM, Python 3.10.12 | 186 passed, exit 0 |
| Same suite, byte-identical files (22 of 22 checksums) | Cloud, Python 3.13.18 | 186 passed, exit 0 |
| Each C3 commit on its own | Mac VM | 156 → 181 → 186 (all later commits) |
| C2 mutation check re-run | Mac VM | 10 of 10 deliberate bugs still caught |
| Serial-to-API latency, 50 trials | Mac VM and cloud | See measurements |
| Real headless Chrome against `ble_sim serve`, recorded | Cloud | 9 of 9 checks true, clip and 5 screenshots |
| Real iPhone and ESP32 in the browser | n/a | **Not run (UNTESTED)** |

## 3. Expected vs observed

| Test | Expected | Observed | Pass |
| --- | --- | --- | --- |
| Verified token through the real reader (pty) | Card appears; state file holds the counter before the card | As expected (`test_full_path_serial_to_state_to_api_to_page`) | PASS |
| Same token again (×5 in unit test) | `replay:duplicate`; card age and RSSI unchanged | As expected | PASS |
| Forged, unknown alias, stale, future | Diagnostics only; no card; state unchanged; genuine token still accepted afterward | As expected for all four | PASS |
| 13 malformed row types (bad framing, uppercase UUID, RSSI −500, `nan`, name on token, truncated, 300-char line…) | Dropped and counted; nothing verified | As expected | PASS |
| Rows before a fresh receiver heartbeat | Not verified ("ignored, receiver not ready") | As expected | PASS |
| Receiver unplugged (pty closed) | Status "disconnected"; sighting kept as history | As expected | PASS |
| Missing serial port | Reported as disconnected, still labelled LIVE-HW, **no fallback to simulation** | As expected | PASS |
| State save fails (simulated disk error) | Result withheld; verification halts visibly; state unchanged | As expected | PASS |
| Host clock invalid (NaN, ∞, 0, year 2001) | Halts | As expected | PASS |
| Restart with the same state file | Old token rejected as duplicate | As expected | PASS |
| Second process on the same state file | Refused (`OwnerError`) | As expected | PASS |
| Missing, corrupt or wrong-scope state | Refuses to start | As expected | PASS |
| All 15 published synthetic keys in production `keys.json` | Each refused; error never echoes the key | As expected | PASS |
| `keys.json` readable by group or others (4 modes) | Refused | As expected | PASS |
| Production without `--keys` | Error; never falls back to test keys | As expected | PASS |
| Test or sim scope used in production, and the reverse (9 cases) | Refused | As expected | PASS |
| Simulator tokens fed into a live-scope verifier | Zero verified; state untouched | As expected | PASS |
| Simulator schedule | Deterministic; every outcome type appears; nothing verified during loss; recovery after loss | As expected | PASS |
| **Negative check found by review:** header text in SIMULATED mode | Must not say LIVE | **First run said "LIVE USB"**. Fixed in `c21d90f`; the browser check now asserts it | PASS after fix |

### Measurements (SIMULATED, genuine runs)

**Serial write to API-visible latency.** Each trial writes one fresh
authenticated row to the pseudo-terminal and stops the clock when
`/api/beacons` first lists it. The path covers the real reader, row validation,
HMAC, the atomic state save with fsync, and the HTTP JSON. The harness polls
every 5 ms. Radio, phone, ESP32, USB, and the page's own 1 s poll are excluded,
so this is not end-to-end latency.

| Host | Trials | Succeeded | p50 | p95 | Max |
| --- | --- | --- | --- | --- | --- |
| Mac VM, Python 3.10.12 (aarch64) | 50 | 50 | 7.9 ms | 13.7 ms | 17.6 ms |
| Cloud, Python 3.13.18 (x86_64) | 50 | 50 | 3.0 ms | 4.8 ms | 9.1 ms |

**Browser run** (one sample): 6.92 s from simulator start to the first
AUTHENTICATED card in Chrome. That includes Chrome start-up, the reader's 2 s
startup drain, the simulator's 1 s cadence, and the page's 1 s poll.

**API counts at the end of the recorded run** (about 50 s):

| Outcome | Count |
| --- | --- |
| Verified | 4 |
| Replay: duplicate | 47 |
| Replay: stale | 2 |
| Replay: future | 2 |
| Forged | 2 |
| Unknown | 2 |
| Malformed: framing | 8 |
| Malformed: RSSI out of range | 2 |
| Malformed: name present | 2 |
| Ignored before the first heartbeat | 1 |

## 4. Where is the proof? (this directory)

- `baseline/`: state before changes, logs, exit codes
- `environment.txt`, `commands.log` (13 commands, all exit 0)
- `pytest_vm_py310.log`, `pytest_cloud_py313.log`, `discovery_unittest.log`
- `per_commit_tests.log`, `c2_mutation_recheck.log`, `line_counts.txt`
- `latency/`: raw samples (JSON) for both hosts
- `browser/`: `browser_checks.json` (9 assertions and the API snapshot), five
  screenshots, the run card, and the simulator log
- **Video:** `c3-software-proof-SIMULATED.mp4`
  - Location: `_media/c3/`, excluded from Git through `.git/info/exclude`.
  - Format: H.264, 1440×900, 57.3 s.
  - SHA-256: `6f4a2c1785d1ec3b0aea8311ae5c2193ba928ddbeef694a2d0f24b6e545f13aa`.
  - Playback: a full decode with ffmpeg passed.
  - Timestamps, checked against extracted frames:
    - 0–6 s: the run card, showing revision `f104439`, the actual test command,
      186 passed, exit 0, and the simulator schedule.
    - About 7 s: the first AUTHENTICATED cards under the SIMULATED banner.
    - 8–30 s: card ages climb 3 → 27 s while duplicate advertisements keep
      arriving, so repeated advertisements don't refresh authenticated freshness.
    - About 34 s: a new 30 s window brings a genuinely new token. The age
      resets, and each card shows 2 verified tokens.
    - About 11 s: the diagnostics drawer opens, near the bottom of the page.
    - 56 s: the drawer's counts and recent rejected events are on screen.
  - **Not shown in the video:** packet loss can't be told apart on screen,
    because no new window started during the loss phase. Loss and recovery are
    proven by `test_simulator_schedule_is_deterministic_and_covers_every_outcome`
    (nothing verified during loss, verified again after).
- `MANIFEST.sha256`: checksums of every file here, computed on the device
  copies. The transfer added a 5,758-byte `caBX` content-credentials chunk to
  each PNG. Decoded pixels match the originals (checked on two of the five).

## 5. What this establishes, what's unproven, what's next

**Established (software, SIMULATED):**
- One serial reader feeds both discovery and authenticated verification.
- Only verified tokens whose replay state was saved first are displayed as
  verified. Everything else stays in diagnostics.
- Restarts, persistence failures, missing or corrupt state, a second owner, bad
  clocks and bad keys all fail closed and visibly.
- Test and simulated keys can't enter production, and simulator data can't
  verify against a live scope.

**Unproven or open:**
- **Real hardware in the browser: UNTESTED.** Next step: the run steps below.
  1. Stop the plain discovery server, since only one reader may own the port.
  2. Run once: `python3 -m ble_id init-state --state ~/olf-testkey-state.json --scope TESTKEY-bench`
  3. Run `python3 -m discovery.server --serial /dev/cu.usbmodem2101 --test-keys --state ~/olf-testkey-state.json --scope TESTKEY-bench`
  4. Press Start (Rotating) in the C1 iPhone app.

  This would be labelled LIVE-HW · SYNTHETIC TEST KEYS. It needs the current
  firmware, which the discovery session already flashed.
- **Production end to end:**
  - The host side is ready.
  - The iPhone app still only has the public test key. There is no Keychain
    provisioning yet, so no phone can send a production-key token.
- **Shared mission integration:** pending Amendment 1, plus the dashboard owner's
  answer on labelling BLE observations.
- **Discovery firmware:** the `#BLE` channel still sends raw MAC addresses
  over USB. The discovery server hashes them per session and never stores or
  serves them, but the base spec's "no MAC identity in output" rule is still in
  tension with that firmware choice.
- **Untested environments:** Python 3.11 (CI's version) and native macOS were
  not run. The VM and cloud are Linux.
- **Static footer:** "USB ESP32 → local memory", from the discovery page, still
  shows in SIMULATED mode. The header and banners are correct.
- **Commit-message errata:** `fdf44c4` says 38 key tests; there are 44.
  `571ceaf` says 149 lines; the file was 150, which `1141a80` fixed.
- **Process note:** two file copies to the Mac carried stale content. Both were
  caught by checksum comparison and redone. Every file here was
  checksum-verified against the tested commit.

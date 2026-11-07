# Questions for other owners (DRAFT, not sent)

Context: our BLE module authenticates an enrolled iPhone by HMAC and reports
"enrolled phone heard by a receiver declared at cell X". It is never a survivor
location. Details are in `SENSOR_ID_SPEC_AMENDMENT_1.md` (PROPOSED).

## Dashboard / integration owner (Teammate B; core/, dashboard/, CI)

1. Today `core/store.py` turns every observation into "Candidate in sector X"
   and retargets the responder route to the newest one. Can
   `kind=BLE_ENROLLED_BEACON` be shown as "enrolled beacon heard by receiver at
   X" and kept out of route targeting unless an operator confirms it? If not,
   what label do you want?
2. Can `core/ingest.py` whitelist `sensor` and `kind`? A probe showed
   `kind="forged"` is accepted and moves the route. We will only post verified
   detections either way.
3. Would you export `evidence.rssi_dbm` in `/state`, or should RSSI stay off
   the dashboard?
4. BLE stale time: the code uses 120 s, the build plan §9.6 says 60 s. Which
   one? (Both work with our 30 s rotation.)
5. Will you add `ble_id/tests` to `pytest.ini` and a pinned `pyserial` to
   `requirements.txt`, or do you prefer we propose the diff in a PR for you to
   review?
6. `.gitignore` ignores every `evidence/` directory, including the plan's
   `docs/evidence/`. Is that intended? We plan to put reports under
   `docs/ble-id/runs/`.

## BLE / Pi owner (Teammate D; ble/, deploy/, hardware/)

1. Which owns live BLE for the demo: your plain-UUID bleak scanner on the Pi,
   our authenticated ESP32 module, or both as separate producers? We won't
   touch `ble/` unless you say so.
2. If both: should we agree on one service UUID scheme so the iPhone app isn't
   built twice?
3. What are the two Seeed boards (chip from the silkscreen or
   `esptool.py chip_id`)? Is one free for our ESP32 scanner?
4. Which iPhone model and iOS version will the demo use, and who signs the app?
5. The build plan gives BLE a 60-minute box with a STAND-IN fallback. Our
   validation needs several hours of hardware time. Which scope fits the team
   schedule?

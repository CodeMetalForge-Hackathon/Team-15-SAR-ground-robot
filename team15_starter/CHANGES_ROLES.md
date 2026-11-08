# Drone roles update (working copy for Aurora to review)

Run: `py homebase.py --sim --web` then open http://localhost:8080 (Windows: `py`, Linux/Mac: `python3`).

## Speed + easy missions (v2)
- **~80x faster planner**: the MCTS footprint maths was a Python loop over cells (99 % of CPU, the sim ran at
  only 0.6x real time, so the page lagged). Now numpy slices: 10x+ real time on a laptop.
  Sweepers/finder use 1/4 of the planning budget; the thermal hunter gets the full one.
- **Never waits for the internet**: missions start instantly on stand-in terrain; the real OpenStreetMap
  terrain downloads in the background and the mission restarts on it automatically (cached afterwards).
  Before, starting a mission could block for 1-2 minutes on map downloads (browser AND homebase).
- **Mission & location** button: search a place (or paste lat, lon), Move area, pick area size, victims,
  civilian/military, and the **drone mix** (sweepers / thermal / finders, 0-4 each), Start. New mission in < 1 s.
- Dashboard only redraws what changed (no more full-page rebuild 5x a second).

## What changed (v1)
- **4 drones in 3 roles** (default `--loadout "ble;ble;thermal;cv" --drones 4`, or set the mix in the dashboard):
  - **S1, S2 signal sweepers** (BLE/Wi-Fi scanner): fly highest and 1.6x faster, hear phones/beacons ~120 m away.
  - **T1 thermal hunter**: MCTS search, pulled toward phone-signal areas.
  - **F1 finder** (camera): flies to heat contacts, hovers at 12 m, watches ~12 s, reports moving / not moving / lying down.
- **Signals are areas, not points**: a BLE hit = sweeper position + RSSI range (+-25 %). Rings are combined into
  a "Phone P1 +-96 m" area that shrinks with more readings. A silent scan is weak evidence (pod 0.12).
- **No assumed vitals**: no radar in the default loadout. Heart rate only from a wearable/beacon, labelled "from wearable".
- **Confirmed person** = camera saw them, or heat where their phone is. Heat alone = "possible person".
- **Priority**: wearable vitals > lying down > not moving > unknown > moving.
- **Dashboard**: role colours/names, plain-words tasks, dashed phone-signal circles, pop-up banners for each find,
  pulsing new contacts, "People found" cards with Signal / Heat / Seen / Observed trail, clearer timeline.

## Shared-file changes (please check)
- `link/protocol.py` (+ firmware headers, comments only): BLE detections put the RANGE IN METRES in `range_dm`;
  camera detections may carry observation codes 4..6 in `status`. Byte layout unchanged (tests/test_link.py passes).
- Old 3-drone setup still works: `--drones 3 --loadout "thermal,ble;thermal,mmwave;cv,mmwave"`.

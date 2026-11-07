# C0 read-only probe, run from a throwaway clone of origin/t2/dashboard-a-to-g
# (a36a658) with that branch's pinned requirements. It calls the teammates'
# existing core.ingest / core.store code unchanged. Output: ingest_probe.log.
#   cd <clone> && python - < ingest_probe.py
# All values are SYNTHETIC. No BLE hardware, no keys, no module code involved.
import json
from core.ingest import normalise, InvalidObservation
from core.store import MissionStore
T=1794077000.0
class C:
    t=T+5
    def __call__(s): return s.t
base={"obs_id":"BLE1-b1-000001","drone_id":"BLE1","source_mode":"LIVE-HW","platform":"BENCH",
      "sensor":"ble","kind":"BLE_ENROLLED_BEACON","how":"SECTOR_ONLY","cell":"A","obs_time":T,"rssi":-61.0}
print("P1 normalise BLE obs:", {k:v for k,v in normalise(base,known_cells="ABCDEFG",rx_time=T+1).items() if k in("stale_after_s","rx_time","rssi","boot_id","seq")})
for name,patch in [("P2 kind=forged (unvalidated kind)",{"kind":"forged","obs_id":"BLE1-b1-000002"}),
                   ("P3 sensor=nonsense",{"sensor":"zzz","obs_id":"BLE1-b1-000003"}),
                   ("P4 receiver id with underscore",{"drone_id":"ESP32_A","obs_id":"ESP32_A-b1-000004"}),
                   ("P5 zone not a cell",{"cell":"zoneA","obs_id":"BLE1-b1-000005"})]:
    try: normalise({**base,**patch},known_cells="ABCDEFG"); print(name,"-> ACCEPTED")
    except InvalidObservation as e: print(name,"-> REJECTED:",e)
s=MissionStore(responder_node="A",clock=C())
s.add_observation(base)
s.add_observation({**base,"obs_id":"BLE1-b1-000002","kind":"forged","cell":"G","obs_time":T+1})
st=s.state()
print("P6 tracks:",[(t["track_id"],t["cell"],t["label"],t["latest"]["kind"],t["badge"]) for t in st["tracks"]])
print("P6 active route:",[(r["version"],r["from"],r["to"],r["track_id"],r["length_m"]) for r in st["routes"] if r["active"]])
print("P7 rssi exposed in /state:", "rssi" in json.dumps(st))
C.t=T+125; print("P8 BLE stale at age 125s:", s.state()["tracks"][0]["latest"]["stale"], "tracks still present:", len(s.state()["tracks"]))

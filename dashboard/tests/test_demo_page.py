"""Live-demo page: read-only controller probe, observed-event timeline, /demo wiring. No hardware."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from camera_mapping.pipeline import PerceptionPipeline
from camera_mapping.tests.helpers import cfg, floor_box
from dashboard import controller_status as CS
from dashboard.app import create_app
from dashboard.controller_status import ControllerProbe, classify, parse_ioreg, read_wheel_test
from dashboard.timeline import Timeline

ROOT = Path(__file__).resolve().parents[2]

IOREG_FTDI = """
+-o Root  <class IORegistryEntry, id 0x100000100>
  +-o AppleT8132USBXHCI@00000000  <class AppleT8132USBXHCI>
    +-o FT231X USB UART@00100000  <class IOUSBHostDevice, id 0x1000a1b2c>
        {
          "USB Product Name" = "FT231X USB UART"
          "USB Vendor Name" = "FTDI"
          "idVendor" = 1027
          "idProduct" = 24577
          "USB Serial Number" = "5D52ABCDEF"
          "locationID" = 1048576
        }
"""


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def scene(source_mode="LIVE-HW", person=True):
    c = cfg()
    p = PerceptionPipeline(c, source_mode=source_mode)
    dets = [floor_box(c, "chair", 1.2)]
    if person:
        dets.append(floor_box(c, "person", 2.5, y_m=-0.8, h_m=0.4, w_m=1.6))
    st = None
    for k in range(3):
        st = p.process(100 + k * 0.2, dets)
    return st


# ---- controller probe ---------------------------------------------------------------------------
def test_parse_ioreg_finds_ftdi_and_classifies_detected():
    devs = parse_ioreg(IOREG_FTDI)
    assert [(d["vid"], d["pid"]) for d in devs] == [(0x0403, 0x6001)]
    c = classify(devs, ["/dev/cu.usbserial-5D52ABCDEF"])
    assert c["usb_status"] == "DETECTED"
    assert "confirm from the board label" in c["candidates"][0]["model_hint"]   # chip != board model
    assert "NOT opened" in c["usb_text"]


def test_no_usb_device_is_not_detected_and_names_likely_causes():
    c = classify(parse_ioreg(""), [])
    assert c["usb_status"] == "NOT_DETECTED" and "charge-only" in c["usb_text"]
    assert classify([], ["/dev/cu.usbserial-X"])["usb_status"] == "UNKNOWN_SERIAL"
    assert classify(parse_ioreg(IOREG_FTDI), [])["usb_status"] == "USB_ONLY"


def test_probe_firmware_is_always_unverified_and_never_claims_a_port_open(tmp_path):
    pr = ControllerProbe(ioreg=lambda: IOREG_FTDI, ports=lambda: ["/dev/cu.usbserial-1"],
                         record_path=str(tmp_path / "none.json"))
    st = pr.status()
    assert st["firmware_status"] == "UNVERIFIED" and st["port_opened"] is False
    assert st["wheel_test"]["result"] == "NOT_RUN"
    assert "no motor path" in st["command_state"]


def test_probe_error_reads_as_fault_not_connected(tmp_path):
    def boom():
        raise OSError("ioreg missing")
    st = ControllerProbe(ioreg=boom, record_path=str(tmp_path / "x.json")).status()
    assert st["usb_status"] == "PROBE_ERROR"


def test_probe_caches_and_reports_usb_transitions(tmp_path):
    clk, text, changes = Clock(), {"v": ""}, []
    pr = ControllerProbe(ioreg=lambda: text["v"], ports=lambda: ["/dev/cu.usbserial-1"] if text["v"] else [],
                         clock=clk, cache_s=2.0, record_path=str(tmp_path / "n.json"),
                         on_change=lambda o, n, s: changes.append((o, n)))
    assert pr.status()["usb_status"] == "NOT_DETECTED"
    text["v"] = IOREG_FTDI
    assert pr.status()["usb_status"] == "NOT_DETECTED"      # cached
    clk.t += 2.5
    assert pr.status()["usb_status"] == "DETECTED"
    assert changes == [(None, "NOT_DETECTED"), ("NOT_DETECTED", "DETECTED")]


def test_wheel_test_record_must_name_operator_and_observations(tmp_path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"result": "pass", "t": "2026-11-08T12:00"}))
    assert read_wheel_test(str(p))["result"] == "INVALID"
    p.write_text("{not json")
    assert read_wheel_test(str(p))["result"] == "INVALID"
    p.write_text(json.dumps({"result": "pass", "t": "2026-11-08T12:00", "operator": "op1", "wheels_lifted": True,
                             "observations": "fwd 0.3 s: all four wheels forward; STOP < 250 ms"}))
    r = read_wheel_test(str(p))
    assert r["result"] == "PASS" and r["operator"] == "op1" and r["wheels_lifted"] is True


def test_controller_probe_source_never_opens_serial_or_imports_rover():
    src = Path(CS.__file__).read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]                       # skip the module docstring
    assert "import serial" not in body and "from rover" not in body and "import rover" not in body
    assert not re.search(r"\bopen\(\s*['\"]?/dev", body)
    assert "os.open" not in body


# ---- timeline -----------------------------------------------------------------------------------
def test_timeline_records_each_person_once_with_its_source_mode_then_lost():
    clk = Clock()
    tl = Timeline(clock=clk, lost_after_s=3.0)
    st = scene("RECORDED")
    tl.observe_frame(st)
    tl.observe_frame(st)
    kinds = [(e["kind"], e["source"]) for e in tl.view()["events"]]
    assert kinds.count(("PERSON_DETECTED", "RECORDED")) == len([p for p in st["persons"] if p["validity"] == "VALID"])
    assert ("CAMERA", "RECORDED") in kinds
    ev = next(e for e in tl.view()["events"] if e["kind"] == "PERSON_DETECTED")
    assert "bearing" in ev["detail"] and isinstance(ev["confidence"], float)
    clk.t += 5
    tl.observe_frame(scene("RECORDED", person=False))
    assert any(e["kind"] == "PERSON_LOST" and e["source"] == "RECORDED" for e in tl.view()["events"])


def test_timeline_uncalibrated_person_has_no_metric_distance_claim():
    tl = Timeline(clock=Clock())
    tl.observe_frame(scene("LIVE-HW"))
    evs = [e for e in tl.view()["events"] if e["kind"] == "PERSON_DETECTED"]
    assert evs
    for e in evs:   # a metre value always carries its estimate label; otherwise it says UNKNOWN
        assert re.search(r"\d m (UN)?CALIBRATED_ESTIMATE", e["detail"]) or "distance UNKNOWN" in e["detail"]


def test_conflict_events_are_throttled():
    clk = Clock()
    tl = Timeline(clock=clk)
    for _ in range(5):
        tl.observe_conflict("second runner")
    clk.t += 11
    tl.observe_conflict("second runner")
    assert [e["kind"] for e in tl.view()["events"]].count("PRODUCER_CONFLICT") == 2


# ---- app wiring ---------------------------------------------------------------------------------
def _client(tmp_path, ioreg=""):
    pr = ControllerProbe(ioreg=lambda: ioreg, ports=lambda: [], record_path=str(tmp_path / "n.json"))
    return TestClient(create_app(controller=pr))


def test_demo_page_and_apis(tmp_path):
    c = _client(tmp_path)
    r = c.get("/demo")
    assert r.status_code == 200 and "Robot-relative detection map" in r.text
    assert c.get("/api/controller").json()["usb_status"] == "NOT_DETECTED"
    assert c.post("/api/perception/frame", json={"producer": "mac:1:pi", "state": scene("LIVE-HW")}).status_code == 200
    kinds = [e["kind"] for e in c.get("/api/timeline").json()["events"]]
    assert "PERSON_DETECTED" in kinds and "CONTROLLER_USB" in kinds
    assert c.post("/api/perception/health", json={"camera_status": "DISCONNECTED", "source_mode": "LIVE-HW"}).status_code == 200
    assert any("DISCONNECTED" in e["detail"] for e in c.get("/api/timeline").json()["events"])


def test_demo_page_has_no_motor_or_write_path():
    html = (ROOT / "dashboard/static/demo.html").read_text()
    assert "method" not in html.lower().split("<script>", 1)[1]          # every fetch is a plain GET
    for bad in ('"/rover/', "/estop", "/approve", "/arm", "/api/motor", "<button", "<form"):
        assert bad not in html.lower()
    gets = set(re.findall(r'get\("(/api/[^"?]+)', html))
    assert gets == {"/api/perception", "/api/perception/health", "/api/controller",
                    "/api/perception/advisory", "/api/timeline", "/api/rover/state"}


def test_rover_state_simulation_must_be_labelled_and_autonomy_disabled(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/rover/state").json()["status"] == "NOT_RUNNING"
    base = {"schema": "team15.mac_host_status/1", "physical": False, "label": "SIMULATED (no wheel moves)",
            "autonomy": "DISABLED", "active_command": "STOP", "camera_verdict": {"action": "HOLD", "reason": "x"}}
    assert c.post("/api/rover/state", json=dict(base, label="PHYSICAL")).status_code == 422
    assert c.post("/api/rover/state", json=dict(base, autonomy="ENABLED")).status_code == 422
    assert c.post("/api/rover/state", json=dict(base, physical="yes")).status_code == 422
    assert c.post("/api/rover/state", json=base).status_code == 200
    v = c.get("/api/rover/state").json()
    assert v["status"] == "LIVE" and v["label"].startswith("SIMULATED")
    ev = [e for e in c.get("/api/timeline").json()["events"] if e["kind"] == "ROVER"]
    assert ev and ev[0]["source"] == "MAC_HOST:SIMULATED"

"""Compatibility with the merged Team-15 contracts: rover, dashboard card, Grove client, Qwen field.

These tests import rover/, core/ and ranging/ READ-ONLY: they pin today's behaviour, under which
LiDAR data can never authorize motion through any existing path.
"""
import ast
import json
import os
import pathlib
import socket
import time

import pytest

from lidar import adapters
from lidar.config import LidarConfig
from lidar.panel import ReplaySource, badge, panel_view
from lidar.processing import Connection, LidarAssessor
from lidar.scan import SourceMode
from lidar.simulation import generate, sim_config

ROOT = pathlib.Path(__file__).resolve().parents[2]


def last(name, cfg=None):
    a = LidarAssessor(cfg or sim_config())
    for scan, now in generate(name):
        r = a.update(scan, now_mono_ns=now)
    return r, scan, now


# ---- rover navigation (rover/sensors.py, rover/pi_io.py) ---------------------
def test_rover_rejects_lidar_fields_fail_closed():
    from rover.sensors import ERROR, Assessment, assess, from_rover_fields
    r, scan, now = last("00_clear_room_control")
    assert r.forward_motion_allowed                       # SIMULATED clear room
    f = adapters.to_rover_fields(r, now / 1e9, this_host=socket.gethostname())
    assert f["schema"] == "team15.rover_range_fields/1" and f["source"] == "rplidar-c1"
    rr = from_rover_fields(f, "time.monotonic@" + socket.gethostname())
    assert rr.status == ERROR and "source" in rr.reason   # not grove-ultrasonic: rejected
    a, why = assess(rr, now / 1e9, 0.3, 0.20)
    assert a is Assessment.UNKNOWN


def test_rover_fields_would_validate_if_source_allowlisted():
    """Stage D preview: with the source allowlisted, the fields are internally consistent."""
    import rover.sensors as rs
    r, scan, now = last("02_obstacle_ahead")
    f = adapters.to_rover_fields(r, now / 1e9, this_host="pi")
    f2 = dict(f, source=rs.GROVE_SOURCE)                   # test-only substitution, never done in code
    rr = rs.from_rover_fields(f2, "time.monotonic@pi")
    assert rr.status == "OK" and rr.forward_allowed is False and rr.service_status == "BLOCKED"
    a, _ = rs.assess(rr, now / 1e9, 0.3, 0.20)
    assert a is rs.Assessment.BLOCKED


def test_pi_robot_io_with_lidar_reader_is_unknown():
    from rover.pi_io import PiRobotIO
    from rover.sensors import Assessment, assess
    r, scan, now = last("00_clear_room_control")
    io = PiRobotIO(range_fields=lambda: adapters.to_rover_fields(r, now / 1e9, this_host="pi"),
                   clock=lambda: now / 1e9, host="pi")
    rr = io.read_range()
    assert assess(rr, io.clock(), 0.3, 0.20)[0] is Assessment.UNKNOWN


def test_rover_fields_stale_or_disconnected_are_error():
    a = LidarAssessor(sim_config())
    frames = generate("00_clear_room_control")
    for scan, now in frames:
        a.update(scan, now_mono_ns=now)
    r = a.status(Connection.DISCONNECTED, now_mono_ns=frames[-1][1] + 300_000_000)
    f = adapters.to_rover_fields(r, 0.0, this_host="pi")
    assert f["status"] == "ERROR" and f["forward_motion_allowed"] is False


def test_no_echo_mapping_never_ok():
    r, *_ = last("01_empty_incomplete_returns")
    f = adapters.to_rover_fields(r, 0.0, this_host="pi")
    assert f["status"] in ("NO_ECHO", "ERROR") and f["range_m"] is None and not f["forward_motion_allowed"]


def test_rover_freshness_constants_match():
    from rover.motion import MotionLimits
    from rover.navigator import NavConfig
    p = sim_config().processing
    nav = NavConfig.__dataclass_fields__["sensor_max_age_s"].default
    mot = MotionLimits.__dataclass_fields__["sensor_max_age_s"].default
    assert p.motion_max_age_s == nav == mot == 0.20


# ---- dashboard card (core/range_view.py, dashboard/range_source.py) ----------
def test_dashboard_card_renders_lidar_snapshot_simulated_and_never_clear():
    from core import range_view
    for name, want in (("02_obstacle_ahead", "BLOCKED"), ("00_clear_room_control", "UNKNOWN"),
                       ("01_empty_incomplete_returns", "UNKNOWN")):
        r, scan, now = last(name)
        snap = adapters.to_range_snapshot(r)
        assert snap["forward_motion_allowed"] is False and snap["provenance"]["driver"] == "rplidar-c1"
        v = range_view.from_snapshot(snap, now=time.time(), fixture=False)
        assert v["badge"] == "SIMULATED" and v["status"] == want, (name, v["status_text"])
        assert v["motion_text"] in ("BLOCKED", "UNKNOWN")


def test_dashboard_card_live_hw_claim_still_not_hardware():
    from core import range_view
    r, *_ = last("02_obstacle_ahead")
    snap = adapters.to_range_snapshot(r)
    snap["provenance"].update(source_mode="LIVE-HW", wiring_verified_by="someone")   # forged
    assert range_view.hardware_verified(snap, None) is False                        # driver != gpiod


def test_dashboard_range_source_reads_committed_lidar_fixture():
    from dashboard.range_source import RangeSource
    src = RangeSource(fixture=ROOT / "lidar/fixtures/dashboard_range_series_approach.json")
    views = [src.view(frame=i) for i in range(6)]
    assert all(v["badge"] == "SIMULATED" for v in views)
    assert views[-1]["status"] == "BLOCKED" and views[0]["status"] == "UNKNOWN"


def test_snapshot_refuses_grove_path(tmp_path):
    r, *_ = last("02_obstacle_ahead")
    with pytest.raises(ValueError):
        adapters.write_range_snapshot("/dev/shm/team15_range.json", adapters.to_range_snapshot(r))
    p = tmp_path / "lidar_range.json"
    adapters.write_range_snapshot(str(p), adapters.to_range_snapshot(r))
    assert json.loads(p.read_text())["sensor_type"] == "RPLIDAR_C1"


def test_grove_client_misdirected_at_lidar_snapshot_never_allows(tmp_path):
    """Semantic conflict: ranging.RangeClient accepts any team15.range_snapshot/1 and GroveRangeIO
    relabels it grove-ultrasonic. Our snapshot keeps that path stop-only."""
    from ranging.rover_io import GroveRangeIO
    from ranging.service import RangeClient
    for name in ("00_clear_room_control", "03_obstacle_behind"):
        r, *_ = last(name)
        p = tmp_path / "s.json"
        adapters.write_range_snapshot(str(p), adapters.to_range_snapshot(r))
        f = GroveRangeIO(client=RangeClient(path=str(p))).read_fields()
        assert f["forward_motion_allowed"] is False


# ---- panel ------------------------------------------------------------------
def test_panel_badges_and_spoofing():
    assert badge("SIMULATED") == "SIMULATED"
    assert badge("HARDWARE_UNVERIFIED") == "HARDWARE (UNVERIFIED)"
    assert badge("LIVE-HW") == "SIMULATED" and badge("HARDWARE") == "SIMULATED"
    r, scan, now = last("02_obstacle_ahead")
    r.source_mode = SourceMode.HARDWARE_VERIFIED.value               # forged in a fixture
    v = panel_view(r, scan, fixture=True)
    assert v["badge"] == "SIMULATED" and v["person_distance_m"] is None


def test_panel_stale_and_disconnected_greyed():
    src = ReplaySource("13_serial_disconnect")
    views = [src.view(frame=i) for i in range(3)]
    assert views[-1]["connection"] == "DISCONNECTED" and views[-1]["greyed"] and views[-1]["points"] == []
    v = ReplaySource("12_stale_timestamps").view(frame=1)
    assert v["greyed"] and v["front"]["status"] == "UNKNOWN" and v["closest"] is None


def test_panel_never_says_clear_path_or_person():
    for name in ("00_clear_room_control", "06_narrow_doorway"):
        src = ReplaySource(name)
        for i in range(3):
            v = src.view(frame=i)
            txt = json.dumps(v).lower()
            assert "path clear" not in txt and "motion allowed" not in txt and "person is" not in txt
            assert v["qualification"].startswith("nearest reflecting surfaces")


def test_unaligned_panel_draws_sensor_frame_with_warning():
    cfg = LidarConfig(mode="simulated")
    scan, now = generate("00_clear_room_control")[0]
    r = LidarAssessor(cfg).update(scan, now_mono_ns=now)
    v = panel_view(r, scan)
    assert v["points_frame"] == "SENSOR" and "forward direction unknown" in v["frame_warning"]


# ---- Qwen advisory optional field --------------------------------------------
def test_advisory_context_is_non_authoritative():
    r, *_ = last("02_obstacle_ahead")
    c = adapters.to_advisory_context(r)
    assert c["association"] == "NOT_ESTABLISHED" and c["person_distance_cm"] is None
    assert c["may_authorize_motion"] is False and c["may_authorize_release"] is False
    assert c["localization"] == "NONE" and c["source_mode"] == "SIMULATED"
    assert {s["facing"] for s in c["sectors"]} >= {"FRONT", "LEFT", "RIGHT", "REAR"}
    assert "clear" not in c["note"].lower().replace("a clear path", "")


def test_advisory_context_stale_is_unknown():
    v = ReplaySource("12_stale_timestamps")
    v.view(frame=1)
    c = adapters.to_advisory_context(v.last_assessment)
    assert c["stale"] and all(s["status"] == "UNKNOWN" and s["min_range_cm"] is None for s in c["sectors"])


# ---- safety: no actuation paths ----------------------------------------------
FORBIDDEN_IMPORTS = {"gpiod", "RPi", "smbus", "smbus2", "pigpio", "gpiozero", "rover.hardware", "rover.motion",
                     "rover.protocol", "serial"}


def test_lidar_package_imports_no_actuation_or_gpio():
    for path in (ROOT / "lidar").rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for n in names:
                bad = [f for f in FORBIDDEN_IMPORTS if n == f or n.startswith(f + ".")]
                if bad == ["serial"] and path.name == "transport.py":
                    continue          # pyserial, lazily, inside SerialTransport only
                assert not bad, f"{path}: imports {n}"


def test_cli_scan_once_refused_without_approval_and_gate(capsys):
    from lidar.cli import main
    cfgp = str(ROOT / "lidar/configs/c1_pi5.UNVERIFIED.json")
    assert main(["scan-once", "--config", cfgp]) == 3
    assert main(["scan-once", "--config", cfgp, "--approved-by", "x"]) == 2
    assert "refusing to open" in capsys.readouterr().out
    assert main(["check-config", "--config", cfgp, "--hardware"]) == 2


def test_discovery_lists_without_opening():
    from lidar.discovery import discover
    opened = []
    out = discover(globber=lambda pat: ["/dev/ttyUSB0"] if pat == "/dev/ttyUSB*" else [],
                   vid_pid=lambda d: "10c4:ea60", realpath=lambda d: d)
    assert out[0]["is_rplidar_c1"] is None and "NOT proof" in out[0]["adapter_hint"] and opened == []


def test_hardware_gate_complete_checklist_passes_and_partial_refuses():
    from lidar.config import HardwareChecklist, HardwareGateError, check_hardware_gate
    ok = HardwareChecklist(model_label_read="C1M1-R2", model_evidence_ref="photo.jpg", adapter_identified="X",
                           adapter_pinout_verified=True, adapter_usb_vid_pid="10c4:ea60",
                           supply_voltage_measured_v=5.05, startup_current_measured_a=0.4,
                           pi_supply_headroom_ok=True, pi_throttled_after_test="0x0", mount_scan_plane_clear=True,
                           cable_strain_relief_ok=True, usb_enumeration_ok=True,
                           device_path_by_id="/dev/serial/by-id/usb-X", independent_wiring_inspection_by="B",
                           emergency_power_cutoff_ok=True, stationary_test_location="bench", verified_by="A",
                           verified_at="2026-11-08")
    check_hardware_gate(ok)
    for k, v in (("model_label_read", "C1M1-R1"), ("independent_wiring_inspection_by", "a"),
                 ("pi_throttled_after_test", "0x50005"), ("device_path_by_id", "/dev/ttyUSB0"),
                 ("supply_voltage_measured_v", 4.6), ("adapter_pinout_verified", None)):
        bad = HardwareChecklist(**{**vars(ok), k: v})
        with pytest.raises(HardwareGateError):
            check_hardware_gate(bad)


def test_replay_server_endpoints():
    import threading
    import urllib.request
    from lidar.server import ReplayApp, make_server
    srv = make_server(ReplayApp("02_obstacle_ahead"), port=0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=2).read())
        assert get("/api/lidar")["badge"] == "SIMULATED"
        assert get("/api/range")["schema"] == "team15.range_snapshot/1"
        assert get("/api/advisory")["association"] == "NOT_ESTABLISHED"
        assert "13_serial_disconnect" in get("/api/scenarios")["scenarios"]
        assert b"LiDAR Scan Replay" in urllib.request.urlopen(base + "/", timeout=2).read()
        assert get("/api/lidar?scenario=13_serial_disconnect")["fixture"] is True
    finally:
        srv.shutdown()
        srv.server_close()

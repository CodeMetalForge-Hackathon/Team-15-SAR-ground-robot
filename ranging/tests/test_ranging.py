"""Ranging tests. No Pi, no sensor, no libgpiod needed (fake clock and fake gpiod)."""
from __future__ import annotations

import json
import threading
import time
import types
import urllib.request

import pytest

from ranging import cli
from ranging.config import ConfigError, ElectricalConfig, ElectricalInterfaceError, SensorConfig, check_electrical
from ranging.drivers import FALLING, RISING, GpiodDriver, SimulatedDriver, classify_echo, echo_from_events, make_driver
from ranging.obstacle import ObstacleAssessor, ObstacleConfig, ObstacleStatus as O
from ranging.reading import MeasurementStatus as S, RangeReading
from ranging.service import SCHEMA, RangeClient, RangeService, apply_freshness, make_http_server

C = 343.0


def echo_us_for(d):
    return 2 * d / C * 1e6


class FakeClock:
    def __init__(self, step_s=0.1):
        self.mono = 1_000_000_000_000
        self.wall = 1_794_000_000.0
        self.step = step_s

    def __call__(self):
        out = (self.wall, self.mono)
        self.mono += int(self.step * 1e9)
        self.wall += self.step
        return out

    def now(self):
        return self.mono


def sim(scene, clock=None, **kw):
    clock = clock or FakeClock()
    return SimulatedDriver(SensorConfig(), scene=scene, clock=clock, **kw), clock


def run(assessor, driver, n):
    return [assessor.update(driver.measure()) for _ in range(n)]


def good_elec(**over):
    d = dict(sensor_vcc_v=3.3, header_vcc_pin=1, gpio_bcm=5, series_resistor_ohm=1000, sensor_revision="V2.0",
             revision_evidence_ref="~/Team15_evidence/range/pcb.jpg", powered_off_while_wiring=True,
             continuity_checked=True, vcc_measured_v=3.31, sig_idle_measured_v=0.02, mount_verified=True,
             wiring_verified_by="hw-teammate", wiring_verified_at="2026-11-07T20:00:00Z")
    d.update(over)
    return ElectricalConfig(**d)


# ---------------------------------------------------------------- reading invariants

def test_invalid_reading_cannot_carry_distance():
    with pytest.raises(ValueError):
        RangeReading(S.NO_ECHO, 1.0, 0.0, 0)
    with pytest.raises(ValueError):
        RangeReading(S.VALID, None, 0.0, 0)


def test_reading_dict_shape():
    d = RangeReading(S.VALID, 0.85, 1794000000.0, 5, source="RASPBERRY_PI_5").to_dict()
    for k in ("sensor_type", "measurement_type", "distance_m", "valid", "timestamp", "sensor_mount",
              "measurement_status", "source"):
        assert k in d
    assert d["sensor_type"] == "GROVE_ULTRASONIC" and d["measurement_type"] == "FORWARD_OBSTACLE_RANGE"
    assert d["valid"] is True and d["measurement_status"] == "VALID" and d["timestamp"].endswith("+00:00")


# ---------------------------------------------------------------- echo conversion

@pytest.mark.parametrize("d", [0.10, 0.30, 0.50, 1.00, 1.50, 2.50])
def test_known_short_and_medium_distances(d):
    status, dist = classify_echo(echo_us_for(d), SensorConfig())
    assert status is S.VALID and dist == pytest.approx(d, abs=1e-6)


def test_seeed_formula_agreement():
    # Seeed: cm = echo_us / 29 / 2  -> 1160 us ~ 20 cm. Ours (343 m/s) within 1.5 %.
    _, d = classify_echo(1160, SensorConfig())
    assert d == pytest.approx(0.20, rel=0.015)


@pytest.mark.parametrize("echo,status", [(0, S.NO_ECHO), (float("nan"), S.NO_ECHO), (-5, S.NO_ECHO),
                                         (echo_us_for(0.01), S.BELOW_MIN_RANGE),
                                         (echo_us_for(3.2), S.OUT_OF_RANGE),
                                         (echo_us_for(6.0), S.OUT_OF_RANGE)])
def test_invalid_echoes_have_no_distance(echo, status):
    assert classify_echo(echo, SensorConfig()) == (status, None)


def test_echo_events_parsing():
    t0 = 10_000_000
    start_to = 2_000_000
    ok = echo_from_events(t0, [(RISING, t0 + 300_000), (FALLING, t0 + 300_000 + 5_831_000)], start_to)
    assert ok[0] is S.VALID and ok[1] == pytest.approx(5831.0)
    assert echo_from_events(t0, [], start_to)[0] is S.NO_ECHO
    assert echo_from_events(t0, [(FALLING, t0 + 4000)], start_to)[0] is S.MISSED_ECHO_START
    assert echo_from_events(t0, [(RISING, t0 + 300_000)], start_to)[0] is S.ECHO_TIMEOUT
    assert echo_from_events(t0, [(RISING, t0 + 5_000_000), (FALLING, t0 + 6_000_000)], start_to)[0] is S.NO_ECHO
    # an old edge from before the trigger is ignored
    assert echo_from_events(t0, [(FALLING, t0 - 1_000_000), (RISING, t0 + 300_000),
                                 (FALLING, t0 + 1_300_000)], start_to)[0] is S.VALID


# ---------------------------------------------------------------- simulator

def test_simulator_no_echo_and_disconnect_never_give_distance():
    for drv in (sim(None)[0], sim(1.0, disconnected=True)[0], sim(1.0, dropout_p=1.0)[0]):
        r = drv.measure()
        assert r.status is S.NO_ECHO and r.distance_m is None and not r.valid


def test_simulator_out_of_range():
    r = sim(4.0)[0].measure()
    assert r.status is S.OUT_OF_RANGE and r.distance_m is None


def test_make_driver_defaults_to_simulator():
    assert make_driver(SensorConfig()).name == "simulated"


# ---------------------------------------------------------------- obstacle assessment

def fresh_assessor(**kw):
    return ObstacleAssessor(ObstacleConfig(**kw))


def test_thresholds_follow_stopping_distance():
    c = ObstacleConfig(max_speed_mps=0.3, decel_mps2=0.5, control_latency_s=0.2, sample_interval_s=0.1,
                       safety_margin_m=0.1)
    assert c.stopping_distance_m() == pytest.approx(0.3 * 0.3 + 0.09 / 1.0)
    assert c.blocked_m() == pytest.approx(0.28)
    faster = ObstacleConfig(max_speed_mps=0.6)
    assert faster.blocked_m() > c.blocked_m()
    assert ObstacleConfig(sensor_setback_m=0.05).blocked_m() == pytest.approx(ObstacleConfig().blocked_m() + 0.05)


def test_geometry_reports_floor_intercept():
    g = ObstacleConfig(mount_height_m=0.08, beam_angle_deg=15).geometry()
    assert g["floor_intercept_m"] == pytest.approx(0.08 / 0.13165, rel=1e-3)
    assert ObstacleConfig(mount_pitch_deg=10).geometry()["floor_intercept_m"] is None


def test_starts_unknown_and_needs_full_window_to_clear():
    a = fresh_assessor()
    drv, _ = sim(2.0)
    out = run(a, drv, 6)
    assert [x.status for x in out[:4]] == [O.UNKNOWN] * 4
    assert out[-1].status is O.CLEAR and out[-1].forward_motion_allowed


@pytest.mark.parametrize("status", [S.NO_ECHO, S.ECHO_TIMEOUT, S.OUT_OF_RANGE, S.BELOW_MIN_RANGE,
                                    S.DRIVER_ERROR, S.LINE_STUCK_HIGH, S.MISSED_ECHO_START])
def test_any_invalid_latest_reading_is_unknown_and_stops(status):
    a = fresh_assessor()
    drv, _ = sim([2.0] * 8 + [status])
    out = run(a, drv, 9)
    assert out[7].status is O.CLEAR
    assert out[8].status is O.UNKNOWN and not out[8].forward_motion_allowed and out[8].nearest_range_m is None


def test_out_of_range_is_not_clear():
    a = fresh_assessor()
    out = run(a, sim(5.0)[0], 10)
    assert all(x.status is O.UNKNOWN and not x.forward_motion_allowed for x in out)


def test_stale_reading_is_unknown():
    a = fresh_assessor(stale_after_s=0.5)
    drv, clk = sim(2.0)
    out = run(a, drv, 8)
    assert out[-1].status is O.CLEAR
    later = a.assess(now_mono_ns=clk.now() + int(0.6e9))
    assert later.status is O.UNKNOWN and later.stale and not later.forward_motion_allowed


def test_rapid_approach_blocks_on_the_next_ping():
    a = fresh_assessor()
    drv, _ = sim([2.0] * 8 + [0.15])
    out = run(a, drv, 9)
    assert out[7].status is O.CLEAR
    assert out[8].status is O.BLOCKED and out[8].nearest_range_m == pytest.approx(0.15)


def test_single_long_spike_cannot_clear_a_block():   # false obstacle clearance
    a = fresh_assessor()
    drv, _ = sim([0.2] * 8 + [2.5] + [0.2] * 3)
    out = run(a, drv, 12)
    assert all(x.status is O.BLOCKED for x in out[3:]), [x.status for x in out]


def test_obstacle_removed_clears_only_after_confirmation():
    a = fresh_assessor(clear_confirm_samples=3)
    drv, _ = sim([0.2] * 6 + [2.0] * 10)
    out = run(a, drv, 16)
    statuses = [x.status for x in out[6:]]
    # median needs 3 of 5 to move, then 3 confirming readings
    assert statuses[0] is O.BLOCKED and statuses[1] is O.BLOCKED
    first_clear = statuses.index(O.CLEAR)
    assert first_clear >= 3
    assert all(s is O.CLEAR for s in statuses[first_clear:])


def test_no_echo_after_block_does_not_clear():
    a = fresh_assessor()
    drv, _ = sim([0.2] * 6 + [None] * 5)
    out = run(a, drv, 11)
    assert all(not x.forward_motion_allowed for x in out)
    assert out[-1].status is O.UNKNOWN


def test_noise_at_threshold_does_not_oscillate():
    cfg = ObstacleConfig()
    b = cfg.blocked_m()
    a = ObstacleAssessor(cfg)
    drv, _ = sim(b + 0.01, noise_sd_m=0.015, seed=3)
    out = run(a, drv, 200)
    changes = sum(1 for p, q in zip(out, out[1:]) if p.status is not q.status)
    assert changes <= 4, changes


def test_noise_far_away_stays_clear_with_spikes_filtered():
    a = fresh_assessor()
    drv, _ = sim(2.0, noise_sd_m=0.02, spike_p=0.05, seed=7)
    out = run(a, drv, 300)[10:]
    # long spikes never matter; short spikes may stop briefly (safe), but mostly CLEAR
    assert sum(x.status is O.CLEAR for x in out) / len(out) > 0.7
    assert all(x.nearest_range_m is None or x.nearest_range_m <= 2.2 for x in out)


def test_sampling_gap_empties_window():
    a = fresh_assessor()
    clk = FakeClock()
    drv, _ = sim(2.0, clock=clk)
    run(a, drv, 8)
    clk.mono += int(5e9)
    r = a.update(drv.measure())
    assert r.status is O.UNKNOWN and "valid readings" in r.reason


# ---------------------------------------------------------------- electrical gate

def test_good_wiring_passes():
    check_electrical(good_elec())
    SensorConfig(driver="gpiod", electrical=good_elec()).validate()


@pytest.mark.parametrize("over,msg", [
    (dict(sensor_vcc_v=5.0, header_vcc_pin=2), "5 V could reach"),
    (dict(sensor_vcc_v=5.0, header_vcc_pin=1, signal_level_shifter="BSS138"), "is 3.3 V"),
    (dict(header_vcc_pin=2), "is 5 V"),
    (dict(header_vcc_pin=6), "not a power pin"),
    (dict(gpio_bcm=2), "reserved"),
    (dict(gpio_bcm=0), "reserved"),
    (dict(gpio_bcm=28), "not a 40-pin header GPIO"),
    (dict(gpio_bcm=None), "not a 40-pin header GPIO"),
    (dict(sensor_vcc_v=None), "not recorded"),
    (dict(sensor_vcc_v=2.5), "outside spec"),
    (dict(sensor_revision=None), "must be read off the PCB as V2"),
    (dict(sensor_revision="V1.0"), "must be read off the PCB as V2"),
    (dict(sensor_revision="V1.0", sensor_vcc_v=5.0, header_vcc_pin=2, signal_level_shifter="BSS138",
          vcc_measured_v=5.0), "must be read off the PCB as V2"),
    (dict(revision_evidence_ref=None), "revision_evidence_ref"),
    (dict(powered_off_while_wiring=None), "hot plug"),
    (dict(powered_off_while_wiring=False), "hot plug"),
    (dict(continuity_checked=None), "continuity_checked"),
    (dict(mount_verified=False), "mount_verified"),
    (dict(vcc_measured_v=None), "vcc_measured_v not recorded"),
    (dict(vcc_measured_v=3.0), "outside 3.2-3.45"),
    (dict(vcc_measured_v=4.9), "outside 3.2-3.45"),
    (dict(sig_idle_measured_v=None), "sig_idle_measured_v not recorded"),
    (dict(sig_idle_measured_v=4.8), "must never reach a Pi GPIO"),
    (dict(wiring_verified_by=None), "wiring not verified"),
    (dict(wiring_verified_at=""), "wiring not verified"),
])
def test_invalid_electrical_configuration_is_refused(over, msg):
    with pytest.raises(ElectricalInterfaceError, match=msg):
        check_electrical(good_elec(**over))


def test_5v_with_level_shifter_is_allowed():
    check_electrical(good_elec(sensor_vcc_v=5.0, header_vcc_pin=2, signal_level_shifter="BSS138-bidirectional",
                               vcc_measured_v=5.02))


def test_gpiod_driver_refuses_unverified_wiring_before_importing_gpiod():
    boom = types.SimpleNamespace()   # any attribute access would fail
    with pytest.raises(ElectricalInterfaceError):
        GpiodDriver(SensorConfig(driver="gpiod", electrical=good_elec(wiring_verified_by=None)), gpiod_module=boom)
    with pytest.raises(ElectricalInterfaceError):
        make_driver(SensorConfig(driver="gpiod"))


def test_cli_requires_hardware_flag_and_verified_config(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"driver": "gpiod", "electrical": vars(good_elec())}))
    assert cli.main(["check-config", "--config", str(p)]) == 2              # no --hardware
    assert "pass --hardware" in capsys.readouterr().out
    assert cli.main(["check-config", "--config", str(p), "--hardware"]) == 0
    p.write_text(json.dumps({"driver": "gpiod", "electrical": vars(good_elec(sensor_vcc_v=5.0, header_vcc_pin=2,
                                                                              vcc_measured_v=5.0))}))
    assert cli.main(["check-config", "--config", str(p), "--hardware"]) == 2
    assert "5 V could reach" in capsys.readouterr().out
    assert cli.main(["check-config", "--hardware"]) == 2                      # --hardware with sim config


def test_shipped_unverified_pi_config_is_refused():
    import os
    path = os.path.join(os.path.dirname(cli.__file__), "configs", "pi5_gpio5.UNVERIFIED.json")
    with pytest.raises(ElectricalInterfaceError, match="wiring not verified"):
        SensorConfig.load(path)


def test_config_rejects_unknown_keys_and_bad_values():
    with pytest.raises(ConfigError):
        SensorConfig.from_dict({"drvier": "gpiod"})
    with pytest.raises(ConfigError):
        SensorConfig(sample_interval_s=0.01).validate()
    with pytest.raises(ConfigError):
        SensorConfig(max_range_m=5.0).validate()
    with pytest.raises(ConfigError):
        SensorConfig(trigger_pulse_us=5).validate()


# ---------------------------------------------------------------- gpiod driver with a fake libgpiod

class FakeGpiod:
    """Minimal libgpiod v2 surface. ``echo_plan`` per ping: None (no echo), ("ok", echo_us),
    ("stuck",) line high before trigger, ("raise",) OSError on request."""

    def __init__(self, plan):
        self.plan = list(plan)
        E = lambda *names: types.SimpleNamespace(**{n: n for n in names})  # noqa: E731
        self.line = types.SimpleNamespace(Direction=E("INPUT", "OUTPUT"), Bias=E("PULL_DOWN"),
                                          Edge=E("BOTH"), Clock=E("MONOTONIC"), Value=E("ACTIVE", "INACTIVE"))
        self.requests = 0
        self.fake = self

    chip_label = "pinctrl-rp1"
    line_name = None      # default GPIO<pin>
    line_used = False

    def LineSettings(self, **kw):  # noqa: N802
        return dict(kw)

    def Chip(self, path):  # noqa: N802
        g = self

        class _Chip:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_info(self):
                return types.SimpleNamespace(label=g.chip_label)

            def get_line_info(self, off):
                return types.SimpleNamespace(name=g.line_name or f"GPIO{off}", used=g.line_used,
                                             consumer="other" if g.line_used else None)
        return _Chip()

    def request_lines(self, chip, consumer, config):
        if self.plan and self.plan[0] == ("raise",):
            self.plan.pop(0)
            raise OSError("chip busy")
        self.requests += 1
        return FakeRequest(self, config)


class FakeEvent:
    class Type:
        RISING_EDGE, FALLING_EDGE = "R", "F"

    def __init__(self, t, ts):
        self.event_type, self.timestamp_ns = t, ts


class FakeRequest:
    def __init__(self, g, config):
        self.g, self.events, self.value, self.dirs, self.released = g, [], "INACTIVE", [], False
        self.cur = None

    def get_value(self, pin):
        self.cur = self.g.plan.pop(0) if self.g.plan else None
        return "ACTIVE" if self.cur == ("stuck",) else "INACTIVE"

    def reconfigure_lines(self, cfg):
        self.dirs.append(list(cfg.values())[0]["direction"])

    def set_value(self, pin, v):
        if self.value == "ACTIVE" and v == "INACTIVE" and self.cur and self.cur[0] == "ok":
            t = time.monotonic_ns()
            self.events = [FakeEvent("R", t + 250_000), FakeEvent("F", t + 250_000 + int(self.cur[1] * 1000))]
        self.value = v

    def wait_edge_events(self, timeout):
        if self.events:
            return True
        if timeout:
            time.sleep(min(timeout, 0.001))
        return False

    def read_edge_events(self):
        ev, self.events = self.events, []
        return ev

    def release(self):
        self.released = True


def gpiod_driver(plan):
    fake = FakeGpiod(plan)
    cfg = SensorConfig(driver="gpiod", source="RASPBERRY_PI_5", electrical=good_elec()).validate()
    return GpiodDriver(cfg, gpiod_module=fake), fake


def test_gpiod_valid_ping_and_line_is_input_between_pings():
    drv, fake = gpiod_driver([("ok", echo_us_for(0.5))])
    r = drv.measure()
    assert r.status is S.VALID and r.distance_m == pytest.approx(0.5, abs=1e-3)
    assert r.source == "RASPBERRY_PI_5" and r.driver == "gpiod"
    assert drv._req.dirs == ["OUTPUT", "INPUT"]   # driven only for the trigger, then released


def test_gpiod_disconnected_sensor_is_no_echo():
    drv, _ = gpiod_driver([None])
    r = drv.measure()
    assert r.status is S.NO_ECHO and r.distance_m is None


def test_gpiod_stuck_high_is_not_driven():
    drv, _ = gpiod_driver([("stuck",)])
    r = drv.measure()
    assert r.status is S.LINE_STUCK_HIGH and drv._req.dirs == []   # never switched to output


def test_gpiod_error_recovery_reopens():
    drv, fake = gpiod_driver([("raise",), ("ok", echo_us_for(1.0))])
    r1 = drv.measure()
    assert r1.status is S.DRIVER_ERROR and "chip busy" in r1.detail and drv.reopen_count == 1
    r2 = drv.measure()
    assert r2.status is S.VALID and fake.requests == 1


def test_gpiod_reading_records_sig_timing_evidence():
    drv, _ = gpiod_driver([("ok", echo_us_for(0.5))])
    x = drv.measure().extra
    assert x["edges"] == 2 and x["release_us"] >= 0 and x["echo_start_us"] == pytest.approx(250, abs=200)


@pytest.mark.parametrize("attr,val,msg", [("chip_label", "gpio-brcmstb@107d508500", "not the Pi 5 RP1"),
                                          ("line_name", "PCIE_RP1_WAKE", "expected GPIO5"),
                                          ("line_used", True, "already in use")])
def test_gpiod_refuses_wrong_chip_or_busy_line(attr, val, msg):
    drv, fake = gpiod_driver([("ok", echo_us_for(0.5))])
    setattr(fake, attr, val)
    r = drv.measure()
    assert r.status is S.DRIVER_ERROR and msg in r.detail and fake.requests == 0


def test_gpiod_out_of_range_echo():
    drv, _ = gpiod_driver([("ok", echo_us_for(3.4))])
    assert drv.measure().status is S.OUT_OF_RANGE


# ---------------------------------------------------------------- service, client, safe defaults

def make_service(tmp_path, scene=1.0, **kw):
    drv = SimulatedDriver(SensorConfig(), scene=scene, **kw)
    return RangeService(SensorConfig(), driver=drv, snapshot_path=str(tmp_path / "snap.json"),
                        evidence_dir=str(tmp_path / "ev"))


def test_service_snapshot_contract(tmp_path):
    svc = make_service(tmp_path, scene=2.0)
    for _ in range(6):
        svc.step()
    s = RangeClient(path=str(tmp_path / "snap.json")).get()
    assert s["schema"] == SCHEMA
    for k in ("obstacle_status", "forward_motion_allowed", "range_m", "valid", "obs_time", "latest",
              "assessment", "freshness", "health", "provenance", "geometry"):
        assert k in s, k
    assert s["obstacle_status"] == "CLEAR" and s["forward_motion_allowed"] is True
    assert s["provenance"]["source_mode"] == "SIMULATED" and s["provenance"]["platform"] == "SIM"
    assert "NOT a distance to a person" in s["assessment"]["range_semantics"]
    assert (tmp_path / "ev").is_dir() and len(list((tmp_path / "ev").glob("*.jsonl"))[0].read_text().splitlines()) == 6
    svc.stop()


def test_service_initial_snapshot_is_unknown(tmp_path):
    svc = make_service(tmp_path)
    s = svc.snapshot()
    assert s["obstacle_status"] == "UNKNOWN" and s["forward_motion_allowed"] is False
    assert s["health"]["state"] == "STARTING"


def test_service_health_faults_on_disconnect(tmp_path):
    svc = make_service(tmp_path, disconnected=True)
    for _ in range(RangeService.FAULT_AFTER):
        s = svc.step()
    assert s["health"]["state"] == "FAULT" and s["obstacle_status"] == "UNKNOWN"
    assert s["health"]["counts"]["NO_ECHO"] == RangeService.FAULT_AFTER


def test_client_safe_defaults_when_sensor_unavailable(tmp_path):
    assert RangeClient(path=str(tmp_path / "missing.json")).forward_motion_allowed() is False
    (tmp_path / "bad.json").write_text("{not json")
    assert RangeClient(path=str(tmp_path / "bad.json")).get()["obstacle_status"] == "UNKNOWN"
    (tmp_path / "other.json").write_text(json.dumps({"schema": "x", "forward_motion_allowed": True}))
    assert RangeClient(path=str(tmp_path / "other.json")).forward_motion_allowed() is False
    assert RangeClient(url="http://127.0.0.1:9/range", timeout_s=0.1).forward_motion_allowed() is False


def test_client_sees_dead_service_as_stale(tmp_path):
    svc = make_service(tmp_path, scene=2.0)
    for _ in range(6):
        svc.step()
    snap = json.loads((tmp_path / "snap.json").read_text())
    assert apply_freshness(snap, now_mono_ns=time.monotonic_ns())["forward_motion_allowed"] is True
    dead = apply_freshness(snap, now_mono_ns=time.monotonic_ns() + int(2e9))
    assert dead["obstacle_status"] == "UNKNOWN" and dead["forward_motion_allowed"] is False and dead["range_m"] is None
    # cross-host path uses wall clock obs_time
    snap["provenance"]["host"] = "elsewhere"
    assert apply_freshness(snap, now_wall=snap["obs_time"] + 5)["forward_motion_allowed"] is False


def test_client_cannot_be_talked_into_motion_by_inconsistent_snapshot(tmp_path):
    svc = make_service(tmp_path, scene=2.0)
    for _ in range(6):
        svc.step()
    snap = json.loads((tmp_path / "snap.json").read_text())
    snap["obstacle_status"] = "BLOCKED"          # allowed flag left True: status wins
    assert apply_freshness(snap, now_mono_ns=time.monotonic_ns())["forward_motion_allowed"] is False


def test_http_endpoints(tmp_path):
    svc = make_service(tmp_path, scene=0.2)
    for _ in range(4):
        svc.step()
    httpd = make_http_server(svc, port=0)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        s = RangeClient(url=f"http://127.0.0.1:{port}/range").get()
        assert s["obstacle_status"] == "BLOCKED" and s["forward_motion_allowed"] is False
        h = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/health"))
        assert h["health"]["state"] == "OK"
    finally:
        httpd.shutdown()
        svc.stop()


def test_background_sampler_runs(tmp_path):
    svc = make_service(tmp_path, scene=2.0).start()
    time.sleep(0.9)
    svc.stop()
    assert svc.counts["VALID"] >= 6
    assert RangeClient(path=str(tmp_path / "snap.json")).get()["latest"]["valid"] is True


def test_cli_read_and_calibrate_simulated(tmp_path, capsys):
    assert cli.main(["read", "--count", "3", "--interval", "0.06", "--sim-distance", "0.5"]) == 0
    assert capsys.readouterr().out.count("VALID") == 3
    out = tmp_path / "cal.json"
    assert cli.main(["calibrate", "--yes", "--targets", "0.3,1.0", "--samples", "5", "--interval", "0.06",
                     "--sim-distance", "0.5", "--sim-noise", "0", "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep["rows"][0]["error_m"] == pytest.approx(0.2) and rep["provenance"]["source_mode"] == "SIMULATED"


# ---------------------------------------------------------------- diagnosis (all still STOP)

def diag_after(tmp_path, scene, n):
    svc = make_service(tmp_path, scene=scene)
    for _ in range(n):
        s = svc.step()
    return s


@pytest.mark.parametrize("scene,code", [
    ([None], "NO_RESPONSE_EVER"),
    ([2.0] * 3 + [None], "NO_RESPONSE_AFTER_ECHOES"),
    ([S.ECHO_TIMEOUT], "ECHO_NOT_ENDING"),
    ([5.0], "TARGET_BEYOND_RANGE"),
    ([S.LINE_STUCK_HIGH], "LINE_FAULT"),
    ([S.MISSED_ECHO_START], "RELEASE_TOO_SLOW"),
    ([S.DRIVER_ERROR], "DRIVER_FAULT"),
    ([2.0], "NONE"),
])
def test_diagnosis_distinguishes_causes_but_always_stops(tmp_path, scene, code):
    s = diag_after(tmp_path, scene, 6)
    assert s["health"]["diagnosis"]["code"] == code
    if code != "NONE":
        assert s["obstacle_status"] == "UNKNOWN" and s["forward_motion_allowed"] is False
        assert s["health"]["diagnosis"]["motion"] == "STOP (UNKNOWN)"


def test_out_of_range_counts_as_echo_evidence_for_later_no_echo(tmp_path):
    s = diag_after(tmp_path, [5.0, 5.0, None, None], 4)
    assert s["health"]["diagnosis"]["code"] == "NO_RESPONSE_AFTER_ECHOES"


# ---------------------------------------------------------------- rover navigation adapter

from ranging.rover_io import GroveRangeIO, snapshot_to_rover_fields  # noqa: E402


def rover_fields(tmp_path, scene, n=6, now_offset_s=0.0):
    svc = make_service(tmp_path, scene=scene)
    for _ in range(n):
        svc.step()
    io = GroveRangeIO(RangeClient(path=str(tmp_path / "snap.json")))
    if now_offset_s:
        snap = json.loads((tmp_path / "snap.json").read_text())
        snap = apply_freshness(snap, now_mono_ns=time.monotonic_ns() + int(now_offset_s * 1e9))
        return snapshot_to_rover_fields(snap, time.monotonic() + now_offset_s, 3.0)
    return io.read_fields()


ROVER_KEYS = {"t", "status", "range_m", "max_range_m", "source", "seq"}


def test_rover_clear_is_ok_with_range_on_monotonic_clock(tmp_path):
    f = rover_fields(tmp_path, 2.0)
    assert ROVER_KEYS <= set(f) and f["status"] == "OK" and f["range_m"] == pytest.approx(2.0, abs=0.01)
    assert f["source"] == "grove-ultrasonic" and f["forward_motion_allowed"] is True
    assert 0 <= time.monotonic() - f["t"] < 1.0


@pytest.mark.parametrize("scene,n,status,obst", [
    (0.2, 6, "OK", "BLOCKED"),            # range reported honestly, but forward not allowed
    (2.0, 2, "ERROR", "UNKNOWN"),          # valid reading, filter window not full -> UNKNOWN
    (None, 6, "NO_ECHO", "UNKNOWN"),
    (5.0, 6, "NO_ECHO", "UNKNOWN"),        # out of range
    (S.ECHO_TIMEOUT, 6, "ERROR", "UNKNOWN"),
    (S.BELOW_MIN_RANGE, 6, "ERROR", "UNKNOWN"),
    (S.DRIVER_ERROR, 6, "ERROR", "UNKNOWN"),
])
def test_rover_mapping_never_allows_motion_unless_clear(tmp_path, scene, n, status, obst):
    f = rover_fields(tmp_path, scene, n)
    assert f["status"] == status and f["obstacle_status"] == obst and f["forward_motion_allowed"] is False
    if status != "OK":
        assert f["range_m"] is None


def test_rover_stale_and_unreachable_are_error(tmp_path):
    f = rover_fields(tmp_path, 2.0, now_offset_s=2.0)
    assert f["status"] == "ERROR" and f["forward_motion_allowed"] is False
    f = GroveRangeIO(RangeClient(path=str(tmp_path / "nope.json"))).read_fields()
    assert f["status"] == "ERROR" and f["forward_motion_allowed"] is False and f["range_m"] is None


def test_rover_other_host_snapshot_is_error(tmp_path):
    svc = make_service(tmp_path, scene=2.0)
    for _ in range(6):
        svc.step()
    snap = svc.snapshot()
    f = snapshot_to_rover_fields(snap, time.monotonic(), 3.0, this_host="some-other-host")
    assert f["status"] == "ERROR" and f["forward_motion_allowed"] is False


# ---------------------------------------------------------------- floor check and calibration analysis

def test_floor_check_detects_floor_echo_in_caution(tmp_path, capsys):
    out = tmp_path / "floor.json"
    rc = cli.main(["floor-check", "--yes", "--samples", "8", "--interval", "0.06", "--sim-noise", "0",
                   "--sim-distance", "0.6", "--out", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 1 and rep["verdict"] == "FAIL_FALSE_CAUTION" and rep["consistent_with_floor"] is True


def test_floor_check_open_space_records_no_target_signature(tmp_path):
    out = tmp_path / "floor.json"
    assert cli.main(["floor-check", "--yes", "--samples", "8", "--interval", "0.06", "--sim-scenario", "open",
                     "--out", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS_NO_ECHO" and rep["no_target_signature"] == "NO_ECHO"


def test_calibration_analysis_fit_and_margin():
    rows = [{"target_m": t, "n_valid": 30, "median_m": t * 1.02 + 0.01, "error_m": t * 0.02 + 0.01, "sd_m": 0.004}
            for t in (0.3, 0.5, 1.0, 1.5, 2.0)]
    a = cli.fit_and_thresholds(rows, ObstacleConfig(), 30)
    assert a["fit_true_vs_measured"]["scale"] == pytest.approx(1 / 1.02, rel=1e-3)
    assert a["recommended"]["safety_margin_m"] == pytest.approx(max(0.10, 0.05 + 0.012))
    assert a["calibration_complete"] is True
    rows[0]["n_valid"] = 10
    assert cli.fit_and_thresholds(rows, ObstacleConfig(), 30)["calibration_complete"] is False
    big = [dict(r, error_m=0.2) for r in rows]
    rec = cli.fit_and_thresholds(big, ObstacleConfig(), 30)["recommended"]
    assert rec["safety_margin_m"] == pytest.approx(0.212) and rec["blocked_m"] > ObstacleConfig().blocked_m()

"""Protocol codec and driver lifecycle against MockLidarDevice (no hardware, no pyserial)."""
import math

import pytest

from lidar import protocol as P
from lidar.config import HardwareGateError, LidarConfig
from lidar.driver import (DriverState, LidarDisconnected, LidarError, LidarHealthError, LidarTimeout,
                          RplidarC1Driver)
from lidar.scan import SampleStatus, ScanCompletion, SourceMode
from lidar.transport import MockLidarDevice


class FakeClock:
    def __init__(self):
        self.ns = 1_000_000_000

    def __call__(self):
        return self.ns

    def sleep(self, s):
        self.ns += int(s * 1e9)


def rev(n=400, d=1.5, q=40):
    return [(i * 360.0 / n, d, q) for i in range(n)]


def make(dev, **kw):
    clk = FakeClock()
    cfg = LidarConfig(mode="simulated", **kw)
    drv = RplidarC1Driver(cfg, transport_factory=dev.factory, clock_ns=clk, sleep=clk.sleep, wall=lambda: 1e9)
    return drv, clk


# ---- protocol -------------------------------------------------------------
@pytest.mark.parametrize("angle,dist,q,start", [(0.0, 0.0, 0, True), (359.98, 11.999, 63, False),
                                                (180.5, 0.25, 10, False), (90.0, 0.05, 47, True)])
def test_node_roundtrip(angle, dist, q, start):
    n = P.decode_node(P.encode_node(angle, dist, q, start))
    assert n.start_flag is start and n.quality == q
    assert abs(n.angle_deg - angle) <= 1 / 64 + 1e-9
    assert abs(n.distance_m - dist) <= 0.00025 + 1e-9    # q2 mm -> m: 0.25 mm resolution


def test_distance_conversion_q2_millimetres():
    # distance_q2 = 4000 -> 1000 mm -> 1.000 m; angle_q6 = 90*64
    a = 90 * 64
    b = bytes(((40 << 2) | 0b10, ((a & 0x7F) << 1) | 1, a >> 7, 4000 & 0xFF, 4000 >> 8))
    n = P.decode_node(b)
    assert n.distance_m == pytest.approx(1.0) and n.angle_deg == pytest.approx(90.0) and not n.start_flag


@pytest.mark.parametrize("mutate", [lambda b: bytes((b[0] | 0b11,)) + b[1:],      # S == !S
                                    lambda b: bytes((b[0] & ~0b11 & 0xFF,)) + b[1:],
                                    lambda b: b[:1] + bytes((b[1] & 0xFE,)) + b[2:]])  # C bit 0
def test_node_check_bits_rejected(mutate):
    with pytest.raises(P.ProtocolError):
        P.decode_node(mutate(P.encode_node(10.0, 1.0, 30, False)))


def test_descriptor_info_health():
    d = P.parse_descriptor(P.build_descriptor(5, 1, 0x81))
    assert (d.length, d.mode, d.data_type) == (5, 1, 0x81)
    with pytest.raises(P.ProtocolError):
        P.parse_descriptor(b"\xA5\x00" + b"\x00" * 5)
    info = P.parse_info(bytes((0x41, 1, 1, 18)) + bytes(range(16)))
    assert info.model == 0x41 and info.firmware == "1.01"
    h = P.parse_health(bytes((2, 0x34, 0x12)))
    assert h.name == "ERROR" and h.error_code == 0x1234 and not h.good


def test_requests_are_legacy_two_byte():
    assert P.request(P.CMD_STOP) == b"\xA5\x25" and P.request(P.CMD_SCAN) == b"\xA5\x20"
    with pytest.raises(ValueError):
        P.request(0x82)   # express scan: not implemented, never sent


# ---- driver lifecycle -----------------------------------------------------
def test_connect_scan_disconnect_cleanup():
    dev = MockLidarDevice([rev(), rev(), rev()])
    drv, clk = make(dev)
    with drv:
        assert drv.state is DriverState.CONNECTED and drv.info.model == 0x41 and drv.health.good
        assert dev.writes[0] == P.request(P.CMD_STOP)     # stop whatever was running first
        drv.start_scan()
        s1 = drv.read_scan()
        s2 = drv.read_scan()
        assert s1.seq == 1 and s2.seq == 2 and len(s1.samples) == 400
        assert s1.completion is ScanCompletion.COMPLETE and s1.source_mode is SourceMode.SIMULATED
        assert s2.capture_start_mono_ns >= s1.capture_start_mono_ns
        assert s1.provenance["driver"] == "rplidar-c1-legacy-scan"
    assert dev.closed and drv.state is DriverState.DISCONNECTED
    assert dev.writes[-1] == P.request(P.CMD_STOP)        # cleanup stopped the scan before closing


def test_cleanup_on_exception_stops_and_closes():
    dev = MockLidarDevice([rev()])
    drv, _ = make(dev)
    with pytest.raises(RuntimeError):
        with drv:
            drv.start_scan()
            raise RuntimeError("consumer crashed")
    assert dev.closed and P.request(P.CMD_STOP) in dev.writes[-2:]


def test_disconnect_idempotent_and_reconnect():
    dev = MockLidarDevice([rev(), rev()])
    drv, _ = make(dev)
    drv.connect()
    drv.disconnect()
    drv.disconnect()
    assert dev.closed
    drv.connect()
    assert dev.opened == 2 and drv.state is DriverState.CONNECTED
    drv.start_scan()
    assert drv.read_scan().seq == 1
    drv.disconnect()


def test_mid_revolution_join_discards_leading_nodes():
    # Stream starts mid-revolution: bytes before the first start flag are not a scan.
    dev = MockLidarDevice([rev(100, 1.0), rev(400, 2.0)])
    drv, _ = make(dev)
    drv.connect()
    drv.start_scan()
    drv._buf += P.encode_node(200.0, 0.3, 40, False) * 5    # orphan nodes before any start flag
    s = drv.read_scan()
    assert all(x.distance_m != 0.3 for x in s.samples)
    drv.disconnect()


def test_garbage_before_descriptor_is_skipped():
    dev = MockLidarDevice([rev()], garbage_prefix=b"\x00\x13\xA5\x00\xFF")
    drv, _ = make(dev)
    drv.connect()
    drv.start_scan()
    assert drv.read_scan().completion is ScanCompletion.COMPLETE
    drv.disconnect()


def test_19_corrupted_packets_resync_and_mark_partial():
    def corrupt(nb, idx):
        return bytes((nb[0] | 0b11,)) + nb[1:] if idx % 7 == 3 else nb     # ~14 % bad nodes
    dev = MockLidarDevice([rev(), rev()], corrupt=corrupt)
    drv, _ = make(dev)
    drv.connect()
    drv.start_scan()
    s = drv.read_scan()
    assert drv.corrupt_nodes_total > 0
    assert s.completion is ScanCompletion.PARTIAL and "corrupt" in s.detail
    drv.disconnect()


def test_19_light_corruption_tolerated():
    dev = MockLidarDevice([rev(), rev()], corrupt=lambda nb, i: (b"\x00" + nb[1:]) if i == 50 else nb)
    drv, _ = make(dev)
    drv.connect()
    drv.start_scan()
    s = drv.read_scan()
    assert s.completion is ScanCompletion.COMPLETE and s.provenance["corrupt_nodes"] >= 1
    drv.disconnect()


def test_13_serial_disconnect_mid_scan():
    dev = MockLidarDevice([rev(), rev()], disconnect_after_bytes=5 * 450)
    drv, _ = make(dev)
    drv.connect()
    drv.start_scan()
    drv.read_scan()
    with pytest.raises(LidarDisconnected):
        drv.read_scan()                      # the partial second revolution is NOT returned
    assert drv.state is DriverState.DISCONNECTED and dev.closed and drv.t is None
    with pytest.raises(LidarError):
        drv.read_scan()
    drv.disconnect()                          # still safe


def test_open_failure_is_disconnected():
    dev = MockLidarDevice(fail_on_open=True)
    drv, _ = make(dev)
    with pytest.raises(LidarDisconnected):
        drv.connect()
    assert drv.state is DriverState.DISCONNECTED


def test_14_device_timeout_no_complete_revolution():
    dev = MockLidarDevice([rev(), rev()], stall_after_bytes=5 * 450)
    drv, clk = make(dev)
    drv.connect()
    drv.start_scan()
    drv.read_scan()
    with pytest.raises(LidarTimeout):
        drv.read_scan()
    assert drv._pending == []                 # nothing half-built survives a timeout
    drv.disconnect()
    assert dev.closed


def test_health_error_refuses_scanning():
    dev = MockLidarDevice([rev()], health=P.HEALTH_ERROR, health_error=0x8001)
    drv, _ = make(dev)
    with pytest.raises(LidarHealthError):
        drv.connect()
    assert drv.state is DriverState.HEALTH_ERROR and dev.closed
    with pytest.raises(LidarError):
        drv.start_scan()


def test_model_mismatch_refused():
    dev = MockLidarDevice([rev()], model=0x18)
    drv, _ = make(dev, expected_model_id=0x41)
    with pytest.raises(LidarHealthError):
        drv.connect()
    assert dev.closed


def test_invalid_and_zero_samples_classified():
    pts = rev(400)
    pts[10] = (pts[10][0], 0.0, 0)          # no return
    pts[11] = (pts[11][0], 0.02, 40)        # below min range
    pts[12] = (pts[12][0], 1.0, 3)          # low quality
    dev = MockLidarDevice([pts, rev()])
    drv, _ = make(dev)
    drv.connect()
    drv.start_scan()
    s = drv.read_scan()
    st = [x.status for x in s.samples[10:13]]
    assert st == [SampleStatus.NO_RETURN, SampleStatus.BELOW_MIN_RANGE, SampleStatus.LOW_QUALITY]
    assert all(x.range_m is None for x in s.samples[10:13])
    drv.disconnect()


def test_hardware_mode_gate_refuses_before_any_io():
    called = []
    with pytest.raises(HardwareGateError):
        RplidarC1Driver(LidarConfig(mode="hardware", device="/dev/ttyUSB0"),
                        transport_factory=lambda *a: called.append(a))
    assert called == []


def test_simulated_mode_never_defaults_to_real_serial():
    with pytest.raises(LidarError):
        RplidarC1Driver(LidarConfig(mode="simulated"))


def test_driver_cannot_claim_verified_hardware():
    with pytest.raises(LidarError):
        RplidarC1Driver(LidarConfig(), transport_factory=MockLidarDevice().factory,
                        source_mode=SourceMode.HARDWARE_VERIFIED)


def test_xy_sensor_frame_convention():
    from lidar.scan import Sample
    s = Sample(90.0, 2.0, 40, SampleStatus.VALID)     # 90 deg clockwise = sensor -y
    x, y = s.xy_sensor()
    assert abs(x) < 1e-9 and y == pytest.approx(-2.0)
    assert Sample(0.0, 0.0, 0, SampleStatus.NO_RETURN).xy_sensor() is None
    assert not math.isnan(Sample(45.0, 1.0, 40, SampleStatus.VALID).xy_sensor()[0])

"""Gate 1 (protocol, from documentation) and the hardware gate. Nothing here touches hardware."""
import pytest

from rover.hardware import HardwareNotVerified, RecordingTransport, RoverCAdapter
from rover.motion import BodyVelocity
from rover.protocol import (I2C_ADDRESS, REG_MOTOR, STOP_BLOCK, HardwareVerification, WheelMapping,
                            body_to_motor_speeds, encode_motor_block, library_mix)


def test_documented_constants():
    assert I2C_ADDRESS == 0x38
    assert REG_MOTOR == (0x00, 0x01, 0x02, 0x03)
    assert STOP_BLOCK == b"\x00\x00\x00\x00"


@pytest.mark.parametrize("xyz,expected", [
    ((0, 50, 0), (50, 50, 50, 50)),          # pure y: all wheels equal
    ((50, 0, 0), (50, -50, -50, 50)),        # pure x
    ((0, 0, 40), (-40, 40, -40, 40)),        # pure z
    ((0, 100, 50), (0, 100, 0, 100)),        # y scaled by (100-50)/100 = 50, then mixed with z=50
    ((100, 100, 0), (100, 0, 0, 100)),       # clamped to +/-100 (200 -> 100)
])
def test_library_mix_matches_reference(xyz, expected):
    assert library_mix(*xyz) == expected


def test_encode_int8_twos_complement_and_bounds():
    assert encode_motor_block((1, -1, 127, -127)) == bytes([1, 0xFF, 0x7F, 0x81])
    for bad in [(128, 0, 0, 0), (0, -128, 0, 0), (0, 0, 0), (0.5, 0, 0, 0)]:
        with pytest.raises(ValueError):
            encode_motor_block(bad)


def test_unverified_mapping_refuses_conversion():
    with pytest.raises(PermissionError):
        body_to_motor_speeds(0.1, 0, 0, WheelMapping())


def test_adapter_refuses_unverified_hardware_and_writes_nothing():
    t = RecordingTransport()
    with pytest.raises(HardwareNotVerified) as e:
        RoverCAdapter(t, HardwareVerification())
    assert "wheel_mapping.forward_sign" in str(e.value) and "stop_on_link_loss_ms" in str(e.value)
    assert t.frames == []


def _test_fixture_verification():
    return HardwareVerification(
        controller_model="TEST", controller_firmware="TEST", roverc_revision="TEST", link="TEST",
        wiring_verified_by="TEST", power_verified_by="TEST", stop_on_link_loss_ms=300,
        wheel_mapping=WheelMapping(1, 1, 1, evidence="TEST FIXTURE - not a real bench result"))


def test_adapter_with_test_fixture_writes_zero_first_then_mixed_frame():
    t = RecordingTransport()
    a = RoverCAdapter(t, _test_fixture_verification())
    assert t.frames == [(0x38, 0x00, STOP_BLOCK)]        # default output is zero
    a.apply(BodyVelocity(vx=0.3))
    assert t.frames[-1] == (0x38, 0x00, encode_motor_block((30, 30, 30, 30)))
    a.stop()
    assert t.frames[-1] == (0x38, 0x00, STOP_BLOCK)
    assert all(reg == 0x00 for _, reg, _ in t.frames)    # motor registers only, never servo registers
    assert a.physical is False                           # RecordingTransport never reaches hardware

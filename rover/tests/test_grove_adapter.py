"""Gate 4: the PR #7 Grove reading format maps conservatively onto the navigator's RangeReading."""
import pytest

from rover.sensors import ERROR, NO_ECHO, OK, Assessment, assess, from_grove_reading

SAMPLE = {"schema": "team15.range_reading/1", "sensor_type": "GROVE_ULTRASONIC",
          "measurement_type": "FORWARD_OBSTACLE_RANGE", "sensor_id": "grove-us-front",
          "distance_m": 0.853, "valid": True, "timestamp": "2026-11-07T23:40:01.120+00:00",
          "obs_time": 1794094801.12, "mono_ns": 81234567890123, "seq": 412, "sensor_mount": "FRONT",
          "measurement_status": "VALID", "echo_us": 4974.0, "source": "RASPBERRY_PI_5",
          "driver": "gpiod", "detail": None}


def test_valid_reading():
    r = from_grove_reading(SAMPLE, max_range_m=3.5)
    assert (r.status, r.range_m, r.t, r.seq) == (OK, 0.853, 1794094801.12, 412)
    assert assess(r, r.t + 0.05, 1.0, 0.2)[0] == Assessment.BLOCKED
    assert assess(r, r.t + 0.05, 0.5, 0.2)[0] == Assessment.CLEAR
    assert assess(r, r.t + 0.5, 0.5, 0.2)[0] == Assessment.UNKNOWN  # stale by our stricter 0.2 s


@pytest.mark.parametrize("status,expected", [("NO_ECHO", NO_ECHO), ("OUT_OF_RANGE", NO_ECHO),
                                             ("ECHO_TIMEOUT", ERROR), ("LINE_STUCK_HIGH", ERROR),
                                             ("BELOW_MIN_RANGE", ERROR), ("NOT_STARTED", ERROR)])
def test_non_valid_statuses_are_never_clear(status, expected):
    r = from_grove_reading({**SAMPLE, "measurement_status": status, "distance_m": None, "valid": False}, 3.5)
    assert r.status == expected and r.range_m is None
    assert assess(r, r.t, 0.3, 0.2)[0] == Assessment.UNKNOWN


@pytest.mark.parametrize("bad", [{"schema": "x"}, {"obs_time": None}, {"distance_m": None},
                                 {"valid": False}, {"distance_m": -1}])
def test_malformed_raises(bad):
    with pytest.raises(ValueError):
        from_grove_reading({**SAMPLE, **bad}, 3.5)

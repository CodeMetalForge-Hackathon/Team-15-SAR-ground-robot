"""Grove Ultrasonic Ranger drivers: an abstraction, a simulator and a libgpiod (Pi 5) driver.

Protocol (Seeed wiki + grove.py ``grove_ultrasonic_ranger.py``), on the single SIG line:
  1. drive SIG low ~2 us, then high for > 10 us, then low   (trigger)
  2. release SIG (input); the sensor sends 8 x 40 kHz and raises SIG
  3. SIG stays high for the round-trip time:  distance = t_high * c / 2
"""
from __future__ import annotations

import logging
import math
import random
import time
from typing import Callable, Iterable, List, Optional, Sequence, Tuple, Union

from .config import SensorConfig, check_electrical
from .reading import MeasurementStatus as S
from .reading import RangeReading

log = logging.getLogger("ranging.driver")


def classify_echo(echo_us: float, cfg: SensorConfig) -> Tuple[S, Optional[float]]:
    """Echo high time -> (status, distance). Out-of-spec echoes carry no distance."""
    if not math.isfinite(echo_us) or echo_us <= 0:
        return S.NO_ECHO, None
    d = echo_us * 1e-6 * cfg.speed_of_sound_mps / 2.0
    if d < cfg.min_range_m:
        return S.BELOW_MIN_RANGE, None
    if d > cfg.max_range_m:
        return S.OUT_OF_RANGE, None
    return S.VALID, d


class RangeDriver:
    """One call to measure() = one ping. Must never raise; failures become invalid readings."""

    name = "base"

    def __init__(self, cfg: SensorConfig):
        self.cfg = cfg
        self._seq = 0

    def measure(self) -> RangeReading:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def _reading(self, status: S, distance_m: Optional[float], wall: float, mono: int,
                 echo_us: Optional[float] = None, detail: Optional[str] = None) -> RangeReading:
        self._seq += 1
        return RangeReading(status=status, distance_m=distance_m, wall_time=wall, mono_ns=mono,
                            echo_us=echo_us, seq=self._seq, source=self.cfg.source,
                            sensor_mount=self.cfg.sensor_mount, sensor_id=self.cfg.sensor_id,
                            driver=self.name, detail=detail)


# ---------------------------------------------------------------------------- simulator

Scene = Union[None, float, S]   # a true distance in m, None for "nothing in range", or a forced status


class SimulatedDriver(RangeDriver):
    """Simulated sensor for CI and development.

    ``scene`` is a callable ``t -> Scene`` (t = seconds since start) or a sequence
    consumed one value per ping (the last value repeats). Optional Gaussian
    noise, random dropouts and spikes model a real sensor. ``disconnected=True``
    models an unplugged SIG line (no echo, ever).
    """

    name = "simulated"

    def __init__(self, cfg: SensorConfig, scene: Union[Callable[[float], Scene], Sequence[Scene], float, None] = 1.0,
                 noise_sd_m: float = 0.0, dropout_p: float = 0.0, spike_p: float = 0.0,
                 seed: int = 0, disconnected: bool = False,
                 clock: Callable[[], Tuple[float, int]] = None):
        super().__init__(cfg)
        self.rng = random.Random(seed)
        self.noise_sd_m, self.dropout_p, self.spike_p = noise_sd_m, dropout_p, spike_p
        self.disconnected = disconnected
        self._clock = clock or (lambda: (time.time(), time.monotonic_ns()))
        self._t0 = None
        if callable(scene):
            self._scene_fn = scene
            self._script = None
        elif isinstance(scene, (list, tuple)):
            self._scene_fn, self._script, self._i = None, list(scene), 0
        else:
            self._scene_fn, self._script = (lambda t, v=scene: v), None

    def _scene(self, t: float) -> Scene:
        if self._script is not None:
            v = self._script[min(self._i, len(self._script) - 1)]
            self._i += 1
            return v
        return self._scene_fn(t)

    def measure(self) -> RangeReading:
        wall, mono = self._clock()
        if self._t0 is None:
            self._t0 = mono
        truth = self._scene((mono - self._t0) / 1e9)
        if self.disconnected:
            return self._reading(S.NO_ECHO, None, wall, mono, detail="simulated: SIG disconnected")
        if isinstance(truth, S):
            return self._reading(truth, None, wall, mono, detail="simulated forced status")
        if truth is None or self.rng.random() < self.dropout_p:
            return self._reading(S.NO_ECHO, None, wall, mono, detail="simulated: no echo")
        d = float(truth) + self.rng.gauss(0.0, self.noise_sd_m) if self.noise_sd_m else float(truth)
        if self.spike_p and self.rng.random() < self.spike_p:
            d *= self.rng.choice((0.3, 2.5))
        echo_us = 2.0 * d / self.cfg.speed_of_sound_mps * 1e6
        status, dist = classify_echo(echo_us, self.cfg)
        return self._reading(status, dist, wall, mono, echo_us=echo_us)


# ---------------------------------------------------------------------------- libgpiod (Pi 5)

RISING, FALLING = "RISING", "FALLING"


def echo_from_events(trigger_end_ns: int, events: Iterable[Tuple[str, int]],
                     echo_start_timeout_ns: int) -> Tuple[S, Optional[float], str]:
    """Turn kernel edge events (kind, monotonic ns) after a trigger into (status, echo_us, detail).

    Pure function so the timing logic is tested without a Pi.
    """
    evs = sorted(((k, ts) for k, ts in events if ts >= trigger_end_ns - 50_000), key=lambda e: e[1])
    rise = next((ts for k, ts in evs if k == RISING), None)
    if rise is None:
        if any(k == FALLING for k, _ in evs):
            return S.MISSED_ECHO_START, None, "falling edge without a rising edge"
        return S.NO_ECHO, None, "no rising edge"
    if rise - trigger_end_ns > echo_start_timeout_ns:
        return S.NO_ECHO, None, f"echo started {(rise - trigger_end_ns) / 1e3:.0f} us after trigger"
    fall = next((ts for k, ts in evs if k == FALLING and ts > rise), None)
    if fall is None:
        return S.ECHO_TIMEOUT, None, "echo did not end"
    return S.VALID, (fall - rise) / 1e3, "ok"


class GpiodDriver(RangeDriver):
    """Raspberry Pi 5 driver using libgpiod v2 (python3-libgpiod >= 2.0) on the RP1 gpiochip.

    Edges are timestamped by the kernel (CLOCK_MONOTONIC), so Python scheduling
    jitter does not enter the distance. Between pings SIG is an input with a
    pull-down: an unplugged sensor reads low and gives NO_ECHO, never a distance.
    The line is only driven (for the trigger pulse) after it has been read low,
    so the Pi never fights the sensor's echo output.
    """

    name = "gpiod"

    def __init__(self, cfg: SensorConfig, gpiod_module=None):
        super().__init__(cfg)
        check_electrical(cfg.electrical)          # hard gate, even if validate() was skipped
        self.pin = cfg.electrical.gpio_bcm
        self._gpiod = gpiod_module
        self._req = None
        self.reopen_count = 0
        self.last_error: Optional[str] = None

    # -- line handling ------------------------------------------------------
    def _mod(self):
        if self._gpiod is None:
            import gpiod  # noqa: deferred so CI never needs libgpiod
            self._gpiod = gpiod
        return self._gpiod

    def _input_settings(self):
        g = self._mod()
        return g.LineSettings(direction=g.line.Direction.INPUT, bias=g.line.Bias.PULL_DOWN,
                              edge_detection=g.line.Edge.BOTH, event_clock=g.line.Clock.MONOTONIC)

    def _output_settings(self):
        g = self._mod()
        return g.LineSettings(direction=g.line.Direction.OUTPUT, output_value=g.line.Value.INACTIVE)

    def _open(self):
        if self._req is None:
            g = self._mod()
            self._req = g.request_lines(self.cfg.gpiochip, consumer="team15-grove-ranger",
                                        config={self.pin: self._input_settings()})
            log.info("opened %s line %d", self.cfg.gpiochip, self.pin)
        return self._req

    def close(self) -> None:
        if self._req is not None:
            try:
                self._req.reconfigure_lines({self.pin: self._input_settings()})
            except Exception:  # noqa: best effort, leave line as input
                pass
            try:
                self._req.release()
            except Exception:
                pass
            self._req = None

    @staticmethod
    def _busy_wait_us(us: float) -> None:
        end = time.perf_counter_ns() + int(us * 1000)
        while time.perf_counter_ns() < end:
            pass

    def _drain(self, req) -> None:
        while req.wait_edge_events(0):
            req.read_edge_events()

    # -- one ping -----------------------------------------------------------
    def measure(self) -> RangeReading:
        wall, mono = time.time(), time.monotonic_ns()
        try:
            req = self._open()
            g = self._mod()
            self._drain(req)
            if req.get_value(self.pin) == g.line.Value.ACTIVE:
                return self._reading(S.LINE_STUCK_HIGH, None, wall, mono,
                                     detail="SIG high before trigger (echo still running, or wiring fault)")
            req.reconfigure_lines({self.pin: self._output_settings()})
            self._busy_wait_us(2)
            req.set_value(self.pin, g.line.Value.ACTIVE)
            self._busy_wait_us(self.cfg.trigger_pulse_us)
            req.set_value(self.pin, g.line.Value.INACTIVE)
            trig_end = time.monotonic_ns()
            req.reconfigure_lines({self.pin: self._input_settings()})
            events: List[Tuple[str, int]] = []
            deadline = trig_end + int((self.cfg.echo_start_timeout_s + self.cfg.echo_end_timeout_s) * 1e9)
            while True:
                remaining = (deadline - time.monotonic_ns()) / 1e9
                if remaining <= 0 or not req.wait_edge_events(remaining):
                    break
                for ev in req.read_edge_events():
                    kind = RISING if ev.event_type == ev.Type.RISING_EDGE else FALLING
                    events.append((kind, ev.timestamp_ns))
                if any(k == FALLING for k, _ in events) and any(k == RISING for k, _ in events):
                    break
            status, echo_us, detail = echo_from_events(trig_end, events,
                                                       int(self.cfg.echo_start_timeout_s * 1e9))
            self.last_error = None
            if status is not S.VALID:
                return self._reading(status, None, wall, mono, detail=detail)
            status, dist = classify_echo(echo_us, self.cfg)
            return self._reading(status, dist, wall, mono, echo_us=echo_us)
        except Exception as e:  # noqa: any GPIO failure is an invalid reading + reopen next time
            self.last_error = f"{type(e).__name__}: {e}"
            log.warning("gpio error, will reopen: %s", self.last_error)
            self.close()
            self.reopen_count += 1
            return self._reading(S.DRIVER_ERROR, None, wall, mono, detail=self.last_error)


def make_driver(cfg: SensorConfig, **sim_kwargs) -> RangeDriver:
    cfg.validate()
    if cfg.driver == "gpiod":
        return GpiodDriver(cfg)
    return SimulatedDriver(cfg, **sim_kwargs)

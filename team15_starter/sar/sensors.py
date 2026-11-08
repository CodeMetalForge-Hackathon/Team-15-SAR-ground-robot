"""sensors.py — sim presets grounded in the hackathon hardware kit.
fov is footprint radius in cells (cell_m=20m): fov=2 => ~100m swath.
pod values are demo-calibrated starting points — tune against real gear."""

SENSORS = {
    # name        fov  pod   passive  what it is
    "thermal":  dict(fov=2, pod=0.90, passive=True,
                     note="Thermal cam: wide area, needs line-of-sight"),
    "depth_ai": dict(fov=1, pod=0.82, passive=True,
                     note="AI/depth cam on Pi 5 26 TOPS: person detector"),
    "noir":     dict(fov=1, pod=0.40, passive=True,
                     note="Low-light/NoIR: weak at night"),
    "mmwave":   dict(fov=0, pod=0.95, passive=False,
                     note="60GHz radar: vitals <=1.5m, CONFIRM only"),
    "acoustic": dict(fov=2, pod=0.55, passive=True,
                     note="Mic array: hears shouts, noisy"),
}

def apply(world, name):
    s = SENSORS[name]
    world.pod = s["pod"]
    world.fov = s["fov"]
    return s

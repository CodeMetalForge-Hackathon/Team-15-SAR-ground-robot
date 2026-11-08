"""``python -m lidar <command>``

    discover                       list candidate serial devices (never opens one)
    check-config --config F        validate a config; --hardware also runs the hardware gate
    replay --scenario NAME         print SIMULATED panel JSON; --serve starts the replay server
    export-fixtures --out DIR      write the SIMULATED scenario fixtures as JSON
    bench                          time scan processing on SIMULATED scans (processing latency only)
    scan-once --config F           FIRST PHYSICAL SCAN: refused unless the gate passes AND
                                   --approved-by names the person who approved it (LIDAR_C1_DEMO_RUNBOOK.md)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .config import DEFAULT_SIM_PORT, HardwareGateError, LidarConfig, LidarConfigError


def _cmd_discover(a) -> int:
    from .discovery import discover
    print(json.dumps({"candidates": discover(), "auto_selected": None,
                      "note": "pick one explicitly and record it in checklist.device_path_by_id"}, indent=2))
    return 0


def _cmd_check(a) -> int:
    try:
        cfg = LidarConfig.load(a.config)
        if a.hardware and cfg.mode != "hardware":
            raise HardwareGateError("--hardware given but config mode is not 'hardware'")
    except (LidarConfigError, OSError, ValueError, TypeError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps({"ok": True, "mode": cfg.mode, "alignment_verified": cfg.mount.aligned}, indent=2))
    return 0


def _cmd_replay(a) -> int:
    from .panel import ReplaySource
    if a.serve:
        from .server import ReplayApp, make_server
        srv = make_server(ReplayApp(a.scenario, a.seed), a.host, a.port)
        print(f"SIMULATED LiDAR replay on http://{a.host}:{a.port}/  (scenario {a.scenario}); Ctrl-C to stop",
              file=sys.stderr)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
        return 0
    src = ReplaySource(a.scenario, a.seed)
    for i in range(len(src.frames)):
        v = src.view(frame=i)
        v.pop("points", None)
        print(json.dumps(v))
    return 0


def _cmd_export(a) -> int:
    from .processing import LidarAssessor
    from .simulation import SCENARIOS, SIM_LABEL, generate, sim_config
    os.makedirs(a.out, exist_ok=True)
    index = {}
    for name in SCENARIOS:
        frames = generate(name, a.seed)
        cfg = sim_config()
        if name == "15_incorrect_orientation":
            cfg.mount.forward_offset_deg = 0.0
        asr = LidarAssessor(cfg)
        out = []
        for scan, now in frames:
            exp = asr.update(scan, now_mono_ns=now).to_dict()
            out.append({"scan": scan.to_dict(include_samples=False),
                        "points": [[round(x.angle_deg, 3), round(x.distance_m, 4), x.quality] for x in scan.samples],
                        "assess_at_mono_ns": now,
                        "expected": {k: exp[k] for k in ("forward_motion_allowed", "forward_status", "connection",
                                                         "completion", "alignment_verified", "source_mode")}
                        | {"sectors": {x["name"]: x["status"] for x in exp["sectors"]}}})
        doc = {"label": SIM_LABEL, "source_mode": "SIMULATED", "scenario": name, "seed": a.seed,
               "generator": "python -m lidar export-fixtures", "mount": "SIM_MOUNT (sensor 0 = robot rear, CW)",
               "frames": out}
        path = os.path.join(a.out, f"{name}.json")
        with open(path, "w") as f:
            json.dump(doc, f, separators=(",", ":"))
        index[name] = os.path.basename(path)
    # Existing dashboard card (core/range_view.py) fixture: {"series": [team15.range_snapshot/1, ...]}
    from . import adapters
    asr = LidarAssessor(sim_config())
    series = []
    for scan, now in generate("08_obstacle_approaching", a.seed):
        snap = adapters.to_range_snapshot(asr.update(scan, now_mono_ns=now), now_wall=scan.capture_start_wall
                                          + (now - scan.capture_start_mono_ns) / 1e9, now_mono_ns=now)
        snap["freshness"] = {"age_s": round((now - scan.capture_start_mono_ns) / 1e9, 3), "stale": False,
                             "stale_after_s": snap["stale_after_s"]}
        series.append(snap)
    with open(os.path.join(a.out, "dashboard_range_series_approach.json"), "w") as f:
        json.dump({"label": SIM_LABEL, "note": "LiDAR FRONT sector as team15.range_snapshot/1 (display only)",
                   "series": series}, f, indent=1)
    index["dashboard_range_series_approach"] = "dashboard_range_series_approach.json"
    with open(os.path.join(a.out, "index.json"), "w") as f:
        json.dump({"label": SIM_LABEL, "seed": a.seed, "scenarios": index}, f, indent=2)
    print(json.dumps({"written": len(index), "dir": a.out}))
    return 0


def _cmd_bench(a) -> int:
    from .processing import LidarAssessor
    from .simulation import cast, make_scan, room, sim_config, World
    import random
    cfg = sim_config()
    rng = random.Random(1)
    pts = cast(World(room()), rng)
    asr = LidarAssessor(cfg)
    times = []
    for k in range(a.n):
        t0 = time.perf_counter_ns()
        scan = make_scan(pts, k + 1, 1_000_000_000 + k * 100_000_000, cfg)
        asr.update(scan, now_mono_ns=scan.capture_end_mono_ns)
        times.append((time.perf_counter_ns() - t0) / 1e6)
    times.sort()
    print(json.dumps({"label": "SIMULATED processing only (build_scan + assess); excludes serial transfer "
                               "and the ~100 ms revolution itself", "points_per_scan": len(pts), "n": a.n,
                      "p50_ms": round(times[len(times) // 2], 3), "p95_ms": round(times[int(len(times) * .95)], 3),
                      "max_ms": round(times[-1], 3)}, indent=2))
    return 0


def _cmd_scan_once(a) -> int:
    """Physical stationary scan. Not executed in this PR: needs gate + explicit approval."""
    if not (a.approved_by or "").strip():
        print(json.dumps({"ok": False, "error": "refused: --approved-by <name> is required for the first physical "
                          "scan (LIDAR_C1_DEMO_RUNBOOK.md, Stage C)"}))
        return 3
    try:
        cfg = LidarConfig.load(a.config)
        if cfg.mode != "hardware":
            raise HardwareGateError("config mode must be 'hardware'")
    except (LidarConfigError, OSError, ValueError, TypeError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    from .driver import RplidarC1Driver
    from .processing import LidarAssessor
    out = {"ok": False, "approved_by": a.approved_by, "scans": []}
    with RplidarC1Driver(cfg) as drv:           # __exit__: STOP + close, always
        out["info"] = drv.info.to_dict() if drv.info else None
        out["health"] = drv.health.to_dict() if drv.health else None
        drv.start_scan()
        asr = LidarAssessor(cfg)
        for _ in range(a.scans):
            scan = drv.read_scan()
            t_proc = time.monotonic_ns()
            res = asr.update(scan).to_dict()
            out["scans"].append({"seq": scan.seq, "points": len(scan.samples), "valid_coverage": scan.valid_coverage,
                                 "completion": scan.completion.value, "duration_s": scan.duration_s,
                                 "capture_start_to_processed_s": (t_proc - scan.capture_start_mono_ns) / 1e9,
                                 "closest": res["closest"], "scan_rate_hz": res["scan_rate_hz"]})
        out["ok"] = True
    print(json.dumps(out, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m lidar", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover").set_defaults(fn=_cmd_discover)
    c = sub.add_parser("check-config")
    c.add_argument("--config", required=True)
    c.add_argument("--hardware", action="store_true")
    c.set_defaults(fn=_cmd_check)
    r = sub.add_parser("replay")
    r.add_argument("--scenario", default="08_obstacle_approaching")
    r.add_argument("--seed", type=int, default=15)
    r.add_argument("--serve", action="store_true")
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--port", type=int, default=DEFAULT_SIM_PORT)
    r.set_defaults(fn=_cmd_replay)
    e = sub.add_parser("export-fixtures")
    e.add_argument("--out", default="lidar/fixtures")
    e.add_argument("--seed", type=int, default=15)
    e.set_defaults(fn=_cmd_export)
    b = sub.add_parser("bench")
    b.add_argument("-n", type=int, default=200)
    b.set_defaults(fn=_cmd_bench)
    s = sub.add_parser("scan-once")
    s.add_argument("--config", required=True)
    s.add_argument("--approved-by", default=None)
    s.add_argument("--scans", type=int, default=20)
    s.set_defaults(fn=_cmd_scan_once)
    a = p.parse_args(argv)
    return a.fn(a)

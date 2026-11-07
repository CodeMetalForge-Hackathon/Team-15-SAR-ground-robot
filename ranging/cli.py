"""python3 -m ranging <command>

  check-config  validate a config (incl. the electrical gate) and print geometry. Never opens GPIO.
  read          take readings and print them (simulated unless --hardware + verified config)
  serve         run the range service: snapshot file + HTTP /range,/health + evidence log
  watch         print what a consumer (navigation/dashboard) sees, via RangeClient
  calibrate     tape-measure demo: read N samples at each known distance, report error

Hardware access needs BOTH a config with driver "gpiod" that passes the
electrical gate (ranging/WIRING.md) AND the --hardware flag.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time

from .config import ConfigError, SensorConfig
from .drivers import SimulatedDriver
from .obstacle import ObstacleAssessor, ObstacleConfig
from .service import (DEFAULT_EVIDENCE_DIR, DEFAULT_PORT, DEFAULT_SNAPSHOT_PATH, RangeClient, RangeService,
                      make_http_server, setup_logging)


def _load(args) -> tuple:
    if args.config:
        with open(args.config) as f:
            raw = json.load(f)
    else:
        raw = {}
    ocfg = ObstacleConfig(**raw.pop("obstacle", {}))
    cfg = SensorConfig.from_dict(raw)
    if getattr(args, "interval", None):
        cfg.sample_interval_s = args.interval
    if cfg.driver == "gpiod" and not getattr(args, "hardware", False):
        raise ConfigError("config selects the gpiod hardware driver: pass --hardware to confirm")
    if getattr(args, "hardware", False) and cfg.driver != "gpiod":
        raise ConfigError("--hardware given but the config does not select driver 'gpiod'")
    return cfg.validate(), ocfg.validate()


def _sim_driver(cfg, args):
    if cfg.driver != "simulated":
        return None
    if args.sim_scenario == "approach":       # wall approaching at 0.25 m/s from 2 m, then stops at 0.2 m
        scene = lambda t: max(0.2, 2.0 - 0.25 * t)  # noqa: E731
    elif args.sim_scenario == "open":         # nothing within range
        scene = None
    else:
        scene = args.sim_distance
    return SimulatedDriver(cfg, scene=scene, noise_sd_m=args.sim_noise, dropout_p=args.sim_dropout,
                           disconnected=args.sim_scenario == "disconnected", seed=1)


def _add_common(p, sim=True):
    p.add_argument("--config", help="JSON config (see ranging/configs/)")
    p.add_argument("--hardware", action="store_true", help="allow the gpiod driver (wiring must be verified)")
    p.add_argument("--interval", type=float, help="sample interval s (>= 0.06)")
    p.add_argument("--log-level", default="WARNING")
    if sim:
        g = p.add_argument_group("simulator (driver=simulated only)")
        g.add_argument("--sim-distance", type=float, default=1.0)
        g.add_argument("--sim-noise", type=float, default=0.01)
        g.add_argument("--sim-dropout", type=float, default=0.0)
        g.add_argument("--sim-scenario", choices=["static", "approach", "open", "disconnected"], default="static")


def cmd_check_config(args) -> int:
    try:
        cfg, ocfg = _load(args)
    except ConfigError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps({"ok": True, "driver": cfg.driver, "sensor": cfg.to_dict(),
                      "geometry": ocfg.geometry()}, indent=2))
    return 0


def _fmt(snap: dict) -> str:
    lt = snap.get("latest") or {}
    d = lt.get("distance_m")
    rng = snap.get("range_m")
    fr = snap.get("freshness") or {}
    return (f"{lt.get('timestamp', '-'):29s} seq={lt.get('seq', '-'):<5} "
            f"raw={'%.3f m' % d if d is not None else '   --  ':9s} {lt.get('measurement_status', '-'):17s} "
            f"decision={'%.3f m' % rng if rng is not None else '  --   ':9s} {snap['obstacle_status']:8s} "
            f"fwd={'YES' if snap['forward_motion_allowed'] else 'NO '} age={fr.get('age_s')}s "
            f"health={snap.get('health', {}).get('state')}")


def cmd_read(args) -> int:
    cfg, ocfg = _load(args)
    svc = RangeService(cfg, ocfg, driver=_sim_driver(cfg, args), snapshot_path=None)
    try:
        n = 0
        while args.count <= 0 or n < args.count:
            svc.step()
            snap = svc.snapshot()
            print(json.dumps(snap) if args.json else _fmt(snap), flush=True)
            n += 1
            time.sleep(cfg.sample_interval_s)
    except KeyboardInterrupt:
        pass
    finally:
        svc.stop()
        print(json.dumps({"summary": svc._health()}), file=sys.stderr)
    return 0


def cmd_serve(args) -> int:
    cfg, ocfg = _load(args)
    ev = None if args.no_evidence else args.evidence_dir
    svc = RangeService(cfg, ocfg, driver=_sim_driver(cfg, args), snapshot_path=args.snapshot, evidence_dir=ev)
    httpd = make_http_server(svc, host=args.host, port=args.port, cors_origin=args.cors_origin)
    svc.start()
    print(json.dumps({"serving": f"http://{args.host}:{args.port}/range", "snapshot": args.snapshot,
                      "evidence_dir": ev, "provenance": svc.provenance}), file=sys.stderr, flush=True)
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        svc.stop()
    return 0


def cmd_watch(args) -> int:
    client = RangeClient(path=None if args.url else args.snapshot, url=args.url)
    try:
        while True:
            s = client.get()
            print(json.dumps(s) if args.json else
                  (_fmt(s) if s.get("latest") else f"UNKNOWN fwd=NO  {s.get('error')}"), flush=True)
            time.sleep(args.period)
    except KeyboardInterrupt:
        return 0


def cmd_calibrate(args) -> int:
    """Robot stationary. For each tape-measured distance, collect N valid readings and report error."""
    cfg, ocfg = _load(args)
    targets = [float(x) for x in args.targets.split(",")]
    svc = RangeService(cfg, ocfg, driver=_sim_driver(cfg, args), snapshot_path=None)
    rows = []
    try:
        for tgt in targets:
            if not args.yes:
                input(f"\nPlace a flat target (>= 0.5 m^2, perpendicular) at {tgt:.3f} m from the sensor face "
                      f"(tape measure), keep the robot stationary, press Enter... ")
            vals, statuses = [], {}
            deadline = time.monotonic() + args.timeout
            while len(vals) < args.samples and time.monotonic() < deadline:
                r = svc.driver.measure()
                statuses[r.status.value] = statuses.get(r.status.value, 0) + 1
                if r.valid:
                    vals.append(r.distance_m)
                time.sleep(cfg.sample_interval_s)
            row = {"target_m": tgt, "n_valid": len(vals), "statuses": statuses}
            if vals:
                med = statistics.median(vals)
                row.update(median_m=round(med, 4), mean_m=round(statistics.fmean(vals), 4),
                           sd_m=round(statistics.pstdev(vals), 4), min_m=round(min(vals), 4),
                           max_m=round(max(vals), 4), error_m=round(med - tgt, 4),
                           error_pct=round(100 * (med - tgt) / tgt, 2))
            rows.append(row)
            print(json.dumps(row), flush=True)
    finally:
        svc.stop()
    report = {"kind": "GROVE_RANGE_CALIBRATION", "provenance": svc.provenance, "speed_of_sound_mps":
              cfg.speed_of_sound_mps, "robot_stationary": True, "rows": rows, "time": time.time()}
    errs = [abs(r["error_m"]) for r in rows if "error_m" in r]
    report["max_abs_error_m"] = round(max(errs), 4) if errs else None
    report["rms_error_m"] = round(math.sqrt(sum(e * e for e in errs) / len(errs)), 4) if errs else None
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
    print(json.dumps({k: report[k] for k in ("max_abs_error_m", "rms_error_m")}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m ranging", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-config"); _add_common(p, sim=False); p.set_defaults(fn=cmd_check_config)
    p = sub.add_parser("read"); _add_common(p)
    p.add_argument("--count", type=int, default=0, help="readings to take (0 = until Ctrl-C)")
    p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_read)
    p = sub.add_parser("serve"); _add_common(p)
    p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--snapshot", default=DEFAULT_SNAPSHOT_PATH)
    p.add_argument("--evidence-dir", default=DEFAULT_EVIDENCE_DIR); p.add_argument("--no-evidence", action="store_true")
    p.add_argument("--cors-origin", help="e.g. http://127.0.0.1:8000 for the dashboard"); p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("watch")
    p.add_argument("--snapshot", default=DEFAULT_SNAPSHOT_PATH); p.add_argument("--url")
    p.add_argument("--period", type=float, default=0.2); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_watch)
    p = sub.add_parser("calibrate"); _add_common(p)
    p.add_argument("--targets", default="0.30,0.50,1.00,1.50")
    p.add_argument("--samples", type=int, default=30); p.add_argument("--timeout", type=float, default=15)
    p.add_argument("--yes", action="store_true", help="do not prompt (simulator / scripted runs)")
    p.add_argument("--out", help="write report JSON here (keep outside Git, e.g. ~/Team15_evidence/range/)")
    p.set_defaults(fn=cmd_calibrate)
    args = ap.parse_args(argv)
    setup_logging(getattr(args, "log_level", "WARNING"))
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

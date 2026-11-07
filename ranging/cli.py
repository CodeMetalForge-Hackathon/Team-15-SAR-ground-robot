"""python3 -m ranging <command>

  check-config  validate a config (incl. the electrical gate) and print geometry. Never opens GPIO.
  read          take readings and print them (simulated unless --hardware + verified config)
  serve         run the range service: snapshot file + HTTP /range,/health + evidence log
  watch         print what a consumer (navigation/dashboard) sees, via RangeClient
  calibrate     tape-measure demo: read N samples at each known distance, report error + thresholds
  floor-check   installed height/angle, clear floor ahead: are there floor echoes? no-target signature
  diagnose      N pings: status counts, SIG release timing, echo start, health diagnosis
  preflight     READ-ONLY Pi checks (model, gate, libgpiod, chip/line identity, pinctrl, NTP). No GPIO request.

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


def _collect(driver, n: int, timeout_s: float, interval_s: float):
    """Up to n pings (or timeout). Returns (valid distances, status counts, readings)."""
    vals, statuses, readings = [], {}, []
    deadline = time.monotonic() + timeout_s
    while len(readings) < n and time.monotonic() < deadline:
        r = driver.measure()
        readings.append(r)
        statuses[r.status.value] = statuses.get(r.status.value, 0) + 1
        if r.valid:
            vals.append(r.distance_m)
        time.sleep(interval_s)
    return vals, statuses, readings


def _write(path, obj):
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            json.dump(obj, f, indent=2)


def fit_and_thresholds(rows: list, ocfg: ObstacleConfig, samples: int) -> dict:
    """Linear fit true ~ a*measured + b, and thresholds whose margin covers the measured error."""
    pts = [(r["median_m"], r["target_m"]) for r in rows if "median_m" in r]
    out = {"n_targets_with_data": len(pts)}
    if len(pts) >= 2:
        mx = statistics.fmean(p[0] for p in pts); my = statistics.fmean(p[1] for p in pts)
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        a = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx else 1.0
        out["fit_true_vs_measured"] = {"scale": round(a, 4), "offset_m": round(my - a * mx, 4)}
        # scale ~ 343/c_effective: suggests a speed-of-sound correction
        out["suggested_speed_of_sound_mps"] = round(SensorConfig().speed_of_sound_mps * a, 1)
    errs = [abs(r["error_m"]) for r in rows if "error_m" in r]
    sds = [r["sd_m"] for r in rows if "sd_m" in r]
    dropout = [r["target_m"] for r in rows if r["n_valid"] < 0.9 * samples]
    complete = len(pts) == len(rows) and not dropout
    if errs:
        margin = max(ocfg.safety_margin_m, max(errs) + 3 * max(sds))
        cal = ObstacleConfig(**{**vars(ocfg), "safety_margin_m": round(margin, 3)})
        out["recommended"] = {"safety_margin_m": round(margin, 3), "blocked_m": round(cal.blocked_m(), 3),
                              "caution_m": round(cal.caution_m(), 3),
                              "basis": "margin = max(configured, max|error| + 3*max SD); stopping distance still "
                                       "uses the PLACEHOLDER speed/decel/latency unless measured"}
    out["targets_with_dropouts"] = dropout
    out["calibration_complete"] = complete
    return out


def cmd_floor_check(args) -> int:
    """Robot stationary at its installed height/pitch on the real floor, nothing ahead for >= 3 m."""
    cfg, ocfg = _load(args)
    svc = RangeService(cfg, ocfg, driver=_sim_driver(cfg, args), snapshot_path=None)
    if not args.yes:
        input("Robot stationary at its installed mount height/angle, on the demo floor, nothing within 3 m "
              "ahead (walls, legs, cables). Press Enter... ")
    try:
        vals, statuses, _ = _collect(svc.driver, args.samples, args.timeout, cfg.sample_interval_s)
    finally:
        svc.stop()
    g = ocfg.geometry()
    fi = g["floor_intercept_m"]
    near = sorted(vals)
    in_blocked = [v for v in near if v <= ocfg.blocked_m()]
    in_caution = [v for v in near if ocfg.blocked_m() < v <= ocfg.caution_m()]
    if in_blocked:
        verdict = "FAIL_FALSE_BLOCKED"
    elif in_caution:
        verdict = "FAIL_FALSE_CAUTION"
    elif near:
        verdict = "PASS_ECHOES_BEYOND_CAUTION"
    else:
        verdict = "PASS_NO_ECHO"
    invalid = {k: v for k, v in statuses.items() if k != "VALID"}
    rep = {"kind": "GROVE_FLOOR_CHECK", "provenance": svc.provenance, "robot_stationary": True,
           "mount_height_m": ocfg.mount_height_m, "mount_pitch_deg": ocfg.mount_pitch_deg,
           "predicted_floor_intercept_m": fi, "thresholds": {"blocked_m": round(ocfg.blocked_m(), 3),
                                                             "caution_m": round(ocfg.caution_m(), 3)},
           "n_pings": sum(statuses.values()), "statuses": statuses, "verdict": verdict,
           "valid_fraction": round(len(vals) / max(1, sum(statuses.values())), 3),
           "nearest_valid_m": round(near[0], 3) if near else None,
           "median_valid_m": round(statistics.median(near), 3) if near else None,
           "consistent_with_floor": bool(near and fi and abs(near[0] - fi) <= 0.3 * fi),
           # What this board reports with no target: evidence for the NO_ECHO vs OUT_OF_RANGE diagnosis.
           "no_target_signature": max(invalid, key=invalid.get) if invalid else None,
           "time": time.time()}
    _write(args.out, rep)
    print(json.dumps(rep, indent=2))
    return 0 if verdict.startswith("PASS") else 1


def cmd_diagnose(args) -> int:
    cfg, ocfg = _load(args)
    svc = RangeService(cfg, ocfg, driver=_sim_driver(cfg, args), snapshot_path=None)
    try:
        for _ in range(args.samples):
            snap = svc.step()
            time.sleep(cfg.sample_interval_s)
    finally:
        svc.stop()
    rep = {"kind": "GROVE_DIAGNOSE", "provenance": svc.provenance, "health": snap["health"],
           "last_reading": snap["latest"], "time": time.time()}
    _write(args.out, rep)
    print(json.dumps(rep, indent=2))
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
            vals, statuses, _ = _collect(svc.driver, args.samples, args.timeout, cfg.sample_interval_s)
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
    report["analysis"] = fit_and_thresholds(rows, ocfg, args.samples)
    _write(args.out, report)
    print(json.dumps({k: report[k] for k in ("max_abs_error_m", "rms_error_m", "analysis")}, indent=2))
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
    p = sub.add_parser("floor-check"); _add_common(p)
    p.add_argument("--samples", type=int, default=100); p.add_argument("--timeout", type=float, default=30)
    p.add_argument("--yes", action="store_true"); p.add_argument("--out")
    p.set_defaults(fn=cmd_floor_check)
    p = sub.add_parser("diagnose"); _add_common(p)
    p.add_argument("--samples", type=int, default=50); p.add_argument("--out")
    p.set_defaults(fn=cmd_diagnose)
    p = sub.add_parser("preflight"); p.add_argument("--config"); p.add_argument("--log-level", default="WARNING")
    p.set_defaults(fn=lambda a: __import__("ranging.preflight", fromlist=["main_preflight"]).main_preflight(a.config))
    args = ap.parse_args(argv)
    setup_logging(getattr(args, "log_level", "WARNING"))
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

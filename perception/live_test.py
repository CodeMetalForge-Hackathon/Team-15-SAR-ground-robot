"""Consent-gated live Pi camera test with a 10 s countdown (LIVE-HW, BENCH).

    python3 -B -m perception.live_test --scene person --consent all-consented \\
        --pi-host team15-pi \\
      | python3 -B -m core.camera_bridge --post http://127.0.0.1:8792/observations

Order: consent check -> press Enter (Start) -> countdown 10..1 -> camera opens.
Ctrl-C before the countdown ends cancels the test; the camera is never opened
and nothing is captured, streamed, saved or processed.

Scenes (existing pipeline, unchanged):
  empty   perception.live_camera person pipeline, nobody in view. Run with
          --min-box-frac 1.01, so it can raise no sighting and store no image
          (nobody consented). Person boxes are logged per frame without pixels;
          false detections are counted from that log by replaying the trigger.
  person  same pipeline, consenting person in view (may move slightly).
          Sightings go to stdout as JSON lines, for core.camera_bridge.
  object  the same Faster R-CNN weights with all COCO labels; one reference
          frame saved with SHA-256 and provenance. Nothing goes to the dashboard
          (it only takes person sightings).
Consent:
  no-people      allows empty and object; the operator states nobody is in view.
                 If the model returns any person box, the object frame is withheld.
                 (A person the model misses entirely cannot be caught: keep the
                 area clear.)
  all-consented  allows every scene; everyone who may appear has agreed.

While a scene runs, Pi temperature, throttling and memory are sampled over SSH
every 2 s. Throttling, temperature >= 80 C or 3 failed samples in a row stop the
scene; logs are kept. Each run writes to a new folder under --out-dir.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import signal
import statistics
import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional, Sequence

SCENES = ("empty", "person", "object")
CONSENT = {"no-people": {"empty", "object"},
           "all-consented": {"empty", "person", "object"}}
MIN_COUNTDOWN_S = 10
EXIT_OK, EXIT_NOTHING, EXIT_STOPPED, EXIT_REFUSED, EXIT_CANCELLED = 0, 2, 4, 5, 130
TEMP_LIMIT_C = 80.0
DEFAULT_OUT = os.path.expanduser("~/Team15_evidence/camera_live_test")
OBJECT_THRESH = 0.5
# Object scene under consent 'no-people': any person box the model returns
# (it returns boxes from OBJECT_THRESH up) withholds the image.
PERSON_WITHHOLD_THRESH = OBJECT_THRESH
# Empty scene: no box can be taller than 101% of the frame, so the pipeline
# can never raise a sighting and never saves an image. Every person box is
# still logged per frame (no pixels), which is what the empty-scene false
# detection count is computed from (see empty_scene_analysis).
EMPTY_SCENE_NO_SAVE_MIN_BOX_FRAC = "1.01"
TRIGGER_MIN_BOX_FRAC = 0.15  # live_camera default: the real trigger height


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


class Cancelled(Exception):
    pass


def check_consent(scene: str, consent: Optional[str]) -> Optional[str]:
    """Return a refusal reason, or None if this scene is covered by consent."""
    if consent not in CONSENT:
        return f"--consent must be one of {sorted(CONSENT)}"
    if scene not in CONSENT[consent]:
        return (f"scene '{scene}' is not covered by consent '{consent}' "
                f"(allowed: {sorted(CONSENT[consent])})")
    return None


def wait_for_start(prompt: Callable[[str], str]) -> None:
    try:
        prompt("Press Enter to START the countdown (Ctrl-C to cancel) ")
    except (KeyboardInterrupt, EOFError):
        raise Cancelled from None


CONSENT_TEXT = (
    "CONSENT: this scene photographs people. The image is stored on this Mac and shown on "
    "the local Team-15 test dashboard only (not shared publicly). Everyone who may appear "
    "in view, including anyone in the background, must have agreed.\n"
    "Type YES and press Enter to confirm consent and START the countdown "
    "(anything else cancels): ")


def wait_for_consent(prompt: Callable[[str], str]) -> str:
    """Person scene: the person in view confirms consent at capture time."""
    try:
        answer = prompt(CONSENT_TEXT)
    except (KeyboardInterrupt, EOFError):
        raise Cancelled from None
    if (answer or "").strip().upper() != "YES":
        log("consent not confirmed (expected YES; an empty Enter does not count)")
        raise Cancelled
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    log(f"consent confirmed by the operator at {stamp}")
    return stamp


def countdown(seconds: int, sleep: Callable[[float], None] = time.sleep) -> None:
    """Visible countdown. The camera is not touched. Ctrl-C raises Cancelled."""
    try:
        for n in range(seconds, 0, -1):
            log(f"  starting in {n:2d} s ... (Ctrl-C to cancel; camera is OFF)")
            sleep(1.0)
    except KeyboardInterrupt:
        raise Cancelled from None
    log("  countdown done: camera ON")


# -- Pi health -------------------------------------------------------------
HEALTH_CMD = ("vcgencmd measure_temp; vcgencmd get_throttled; "
              "vcgencmd pmic_read_adc EXT5V_V 2>/dev/null | tail -1; "
              "free -m | awk '/^Mem:/{print \"mem_used_mb=\"$3}'")


def ssh_argv(a: argparse.Namespace, remote: str) -> List[str]:
    cmd = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if a.pi_key:
        cmd += ["-i", os.path.expanduser(a.pi_key), "-o", "IdentitiesOnly=yes"]
    target = f"{a.pi_user}@{a.pi_host}" if a.pi_user else a.pi_host
    return cmd + [target, remote]


def parse_health(text: str) -> dict:
    h: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("temp="):
            h["temp_c"] = float(line[5:].split("'")[0])
        elif line.startswith("throttled="):
            h["throttled"] = line.split("=", 1)[1]
        elif "EXT5V_V" in line and "=" in line:
            h["ext5v_v"] = round(float(line.rsplit("=", 1)[1].rstrip("V")), 3)
        elif line.startswith("mem_used_mb="):
            h["mem_used_mb"] = int(line.split("=", 1)[1])
    return h


def health_breach(h: dict) -> Optional[str]:
    if h.get("throttled") not in (None, "0x0"):
        return f"Pi throttling/undervoltage flags {h['throttled']}"
    if h.get("temp_c") is not None and h["temp_c"] >= TEMP_LIMIT_C:
        return f"Pi temperature {h['temp_c']} C >= {TEMP_LIMIT_C}"
    return None


class HealthMonitor(threading.Thread):
    def __init__(self, a: argparse.Namespace, path: str, period_s: float = 2.0):
        super().__init__(daemon=True)
        self.a, self.path, self.period_s = a, path, period_s
        self.samples: List[dict] = []
        self.stop_reason: Optional[str] = None
        self._halt = threading.Event()

    def sample(self) -> Optional[dict]:
        t0 = time.perf_counter()
        try:
            r = subprocess.run(ssh_argv(self.a, HEALTH_CMD), capture_output=True,
                               text=True, timeout=8)
        except subprocess.TimeoutExpired:
            return None
        if r.returncode != 0:
            return None
        # whole SSH session (connect + command): an upper bound on network RTT
        return {**parse_health(r.stdout), "ssh_session_s": round(time.perf_counter() - t0, 3)}

    def run(self) -> None:
        fails = 0
        with open(self.path, "a") as f:
            while not self._halt.is_set():
                h = self.sample()
                rec = {"t": round(time.time(), 3), **(h or {"error": "ssh sample failed"})}
                f.write(json.dumps(rec) + "\n"); f.flush()
                self.samples.append(rec)
                fails = 0 if h else fails + 1
                reason = health_breach(h or {}) or (
                    "lost SSH to the Pi (3 health samples failed)" if fails >= 3 else None)
                if reason and not self.stop_reason:
                    self.stop_reason = reason
                    log(f"HEALTH STOP: {reason}")
                self._halt.wait(self.period_s)

    def halt(self) -> None:
        self._halt.set()


def health_summary(samples: List[dict]) -> dict:
    ok = [s for s in samples if "error" not in s]
    temps = [s["temp_c"] for s in ok if "temp_c" in s]
    volts = [s["ext5v_v"] for s in ok if "ext5v_v" in s]
    mem = [s["mem_used_mb"] for s in ok if "mem_used_mb" in s]
    ssh = sorted(s["ssh_session_s"] for s in ok if "ssh_session_s" in s)
    return {"samples": len(samples), "failed_samples": len(samples) - len(ok),
            "temp_c": [min(temps), max(temps)] if temps else None,
            "ext5v_v": [min(volts), max(volts)] if volts else None,
            "mem_used_mb_max": max(mem) if mem else None,
            "throttled_values": sorted({s.get("throttled") for s in ok} - {None}),
            "ssh_session_s": ([ssh[len(ssh) // 2], ssh[-1]] if ssh else None)}


# -- scenes ----------------------------------------------------------------
def pi_args(a: argparse.Namespace) -> List[str]:
    out = ["--source", "pi", "--pi-host", a.pi_host, "--pi-rotation", str(a.pi_rotation)]
    if a.pi_user:
        out += ["--pi-user", a.pi_user]
    if a.pi_key:
        out += ["--pi-key", a.pi_key]
    return out


def latency_stats(frames_path: str) -> dict:
    rows = [json.loads(l) for l in open(frames_path) if l.strip()]
    if not rows:
        return {"frames": 0}
    transport = [r["rx"] - r["t"] for r in rows]
    span = rows[-1]["rx"] - rows[0]["rx"]
    return {"frames": len(rows),
            "processed_fps": round((len(rows) - 1) / span, 2) if span > 0 else None,
            "capture_to_rx_s_median": round(statistics.median(transport), 3),
            "capture_to_rx_s_max": round(max(transport), 3)}


def person_pipeline_cmd(a: argparse.Namespace, run_dir: str) -> List[str]:
    cmd = [sys.executable, "-B", "-m", "perception.live_camera", *pi_args(a),
           "--sector", a.sector, "--operator", a.operator, "--declare-drone", "D1",
           "--duration-s", str(a.duration_s), "--out-dir", run_dir, "--label", a.scene]
    if a.scene == "empty":
        # consent enforcement: nobody consented, so no person image may be stored
        cmd += ["--min-box-frac", EMPTY_SCENE_NO_SAVE_MIN_BOX_FRAC]
    return cmd


def empty_scene_analysis(frames_path: str, frame_h: int, confirm_frames: int = 3,
                         rearm_s: float = 60.0) -> dict:
    """False person detections in an empty scene, from the per-frame log only.
    Replays the pipeline's own trigger rule (person box >= 15% of the frame
    height, SightingGate) to count the sightings it *would* have raised."""
    from .sightings import SightingGate
    rows = [json.loads(l) for l in open(frames_path) if l.strip()]
    gate = SightingGate(confirm_frames=confirm_frames, rearm_s=rearm_s)
    min_h = TRIGGER_MIN_BOX_FRAC * frame_h
    any_box = trig = would = 0
    best = 0.0
    for r in rows:
        boxes = [d for d in r["all"] if d["family"] == "PERSON_DETECTOR"]
        any_box += bool(boxes)
        big = [d for d in boxes if d["bbox"][3] >= min_h]
        trig += bool(big)
        best = max([best] + [d["score"] or 0.0 for d in boxes])
        would += gate.update(r["t"], bool(big))
    return {"frames": len(rows), "frames_with_person_box": any_box,
            "frames_with_trigger_size_person_box": trig,
            "false_sightings_pipeline_would_raise": would,
            "max_person_score": round(best, 4), "images_saved": 0}


SAME_PERSON_OVERLAP = 0.5   # share of the smaller box covered by the other box


def _inside_frac(a: Sequence[int], b: Sequence[int]) -> float:
    """Intersection over the smaller box's area: 1.0 when one box contains the other."""
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    area = min(a[2] * a[3], b[2] * b[3])
    return ix * iy / area if area else 0.0


def distinct_people(boxes: Sequence[dict]) -> int:
    """Analysis only (no effect on alerts): person boxes in one frame are joined
    when their overlap covers at least SAME_PERSON_OVERLAP of the smaller box,
    and joined boxes chain (a part box inside the whole-body box links to every
    other box on that body). Returns the number of groups: an estimate of
    distinct people, not a head count. The box count is an upper bound."""
    n = len(boxes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if _inside_frac(boxes[i]["bbox"], boxes[j]["bbox"]) >= SAME_PERSON_OVERLAP:
                parent[find(i)] = find(j)
    return len({find(i) for i in range(n)})


def person_scene_analysis(frames_path: str, sightings: Sequence[dict]) -> dict:
    """Per-frame person detection in a person scene: frequency, scores, boxes,
    missed frames, per-frame detector time, and how long the 3-frame gate took."""
    rows = [json.loads(l) for l in open(frames_path) if l.strip()]
    best = [r["best"]["PERSON_DETECTOR"] for r in rows]
    hits = [b for b in best if b]
    out = {"frames": len(rows), "person_frames": len(hits),
           "missed_frames": len(rows) - len(hits),
           "hog_frames": sum(1 for r in rows if r["counts"].get("FULL_BODY_HOG")),
           "max_person_boxes_in_frame": max((r["counts"]["PERSON_DETECTOR"] for r in rows),
                                            default=0)}
    if rows and "all" in rows[0]:
        per = [[d for d in r["all"] if d["family"] == "PERSON_DETECTOR"] for r in rows]
        groups = [distinct_people(b) for b in per]
        out["frames_with_extra_boxes"] = sum(len(b) > 1 for b in per)
        out["frames_with_extra_boxes_same_person"] = sum(len(b) > 1 and g == 1
                                                         for b, g in zip(per, groups))
        out["frames_with_separate_person_boxes"] = sum(g > 1 for g in groups)
        out["max_distinct_people_estimate"] = max(groups, default=0)
        if out["frames_with_separate_person_boxes"]:
            out["separate_person_box_frames_rel_s"] = [r.get("rel_s") for r, g in
                                                       zip(rows, groups) if g > 1][:20]
    if hits:
        sc = [b["score"] for b in hits]
        out["score_min_median_max"] = [min(sc), round(statistics.median(sc), 4), max(sc)]
        out["bbox_range"] = {k: [min(b["bbox"][i] for b in hits), max(b["bbox"][i] for b in hits)]
                             for i, k in enumerate(("x", "y", "w", "h"))}
    det = [sum(r["detect_s"].values()) for r in rows if r.get("detect_s")]
    frc = [v for r in rows for k, v in (r.get("detect_s") or {}).items() if "frcnn" in k]
    if det:
        out["detect_s_total_median_max"] = [round(statistics.median(det), 3), round(max(det), 3)]
    if frc:
        out["frcnn_s_median_max"] = [round(statistics.median(frc), 3), round(max(frc), 3)]
    first = next((r["t"] for r, b in zip(rows, best) if b), None)
    if first is not None and sightings:
        out["first_person_frame_to_sighting_s"] = round(sightings[0]["obs_time"] - first, 3)
    return out


def run_person_pipeline(a: argparse.Namespace, run_dir: str, mon: HealthMonitor) -> dict:
    cmd = person_pipeline_cmd(a, run_dir)
    log("running: " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    sightings: List[dict] = []

    def pump() -> None:
        for line in proc.stdout:
            s = json.loads(line)
            sightings.append(s)
            ev = s["evidence"]
            if a.scene == "person":
                print(line.rstrip("\n"), flush=True)     # to core.camera_bridge
                log(f"RESULT person sighting {s['obs_id']} score={ev['detector_score']} "
                    f"bbox={ev['bbox']} (UNCONFIRMED; sent to dashboard)")
            else:
                log(f"RESULT FALSE POSITIVE in empty scene: {s['obs_id']} "
                    f"score={ev['detector_score']} bbox={ev['bbox']} (not sent)")
    t = threading.Thread(target=pump, daemon=True)
    t.start()
    stopped = None
    try:
        while proc.poll() is None:
            if mon.stop_reason:
                stopped = mon.stop_reason
                proc.send_signal(signal.SIGINT)
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        stopped = "operator pressed Ctrl-C"
        proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait()
    t.join(timeout=5)
    summ = sorted(glob.glob(os.path.join(run_dir, "*_summary.json")))
    frames = sorted(glob.glob(os.path.join(run_dir, "*_frames.jsonl")))
    extra = {}
    if a.scene == "person" and frames:
        extra["person_scene"] = person_scene_analysis(frames[-1], sightings)
        log("RESULT person scene: " + json.dumps(extra["person_scene"]))
    if a.scene == "empty":
        images = sorted(glob.glob(os.path.join(run_dir, "*.png")) +
                        glob.glob(os.path.join(run_dir, "*.jpg")))
        if images or sightings:
            stopped = stopped or "CONSENT VIOLATION: empty scene stored an image"
            log(f"CONSENT VIOLATION: {len(images)} image(s) stored in an empty scene: {images}")
        if frames:
            h = (json.load(open(summ[-1])).get("camera") or {}).get("stream_size", [0, 720])[1] \
                if summ else 720
            extra["empty_scene"] = empty_scene_analysis(frames[-1], h)
            extra["empty_scene"]["images_saved"] = len(images)
            log("RESULT empty scene: " + json.dumps(extra["empty_scene"]))
    return {**extra, "pipeline_exit": proc.returncode, "stopped": stopped,
            "summary": json.load(open(summ[-1])) if summ else None,
            "latency": latency_stats(frames[-1]) if frames else None,
            "sightings": [{"obs_id": s["obs_id"], "obs_time": s["obs_time"],
                           "score": s["evidence"]["detector_score"],
                           "bbox": s["evidence"]["bbox"],
                           "frame_sha256": s["evidence"]["frame_sha256"],
                           "frame_ref": s["evidence"]["frame_ref"]} for s in sightings]}


def class_frequency(rows: Sequence[dict]) -> dict:
    """Per predicted class: frames containing it, fraction of frames, raw scores."""
    out: dict = {}
    for lab in sorted({d["label"] for r in rows for d in r["detections"]}):
        per = [max(d["score"] for d in r["detections"] if d["label"] == lab)
               for r in rows if any(d["label"] == lab for d in r["detections"])]
        out[lab] = {"frames": len(per), "frac_frames": round(len(per) / len(rows), 3),
                    "score_min": min(per), "score_median": round(statistics.median(per), 4),
                    "score_max": max(per)}
    return out


def withhold_reason(dets: Sequence[dict], consent: str) -> Optional[str]:
    if consent == "all-consented":
        return None
    p = [d for d in dets if d["label"] == "person" and d["score"] >= PERSON_WITHHOLD_THRESH]
    return (f"person detected (score {max(d['score'] for d in p):.2f}) under consent "
            "'no-people': image not saved") if p else None


def run_object(a: argparse.Namespace, run_dir: str, mon: HealthMonitor) -> dict:
    import cv2
    import torch
    from torchvision.models import detection as tvd

    from .detectors import DEFAULT_DNN_MODEL, DNN_MODELS, TorchPersonDetector
    from .orientation_check import frame_stats
    from .pi_source import open_pi_camera
    from .sightings import iso_utc

    t_load = time.perf_counter()
    det = TorchPersonDetector(DEFAULT_DNN_MODEL, score_thresh=OBJECT_THRESH)
    weights = getattr(tvd, DNN_MODELS[DEFAULT_DNN_MODEL][1]).COCO_V1
    cats = weights.meta["categories"]
    load_s = time.perf_counter() - t_load
    supported = a.object_label in cats and a.object_label not in ("__background__", "N/A")
    if supported:
        ref_rule = f"frame with the highest '{a.object_label}' score"
    else:
        ref_rule = ("first frame after the halfway point (the label is not a model class, "
                    "so no frame is preferred by score)")
        log(f"NOTE: '{a.object_label}' is NOT a class of {det.name}; the model cannot "
            "name it. Every predicted class is logged as-is.")

    def infer(frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        x = torch.from_numpy(rgb).permute(2, 0, 1).float().div_(255.0).to(det.device)
        t0 = time.perf_counter()
        with torch.no_grad():
            r = det.model([x])[0]
        if det.device == "mps":
            torch.mps.synchronize()
        dt = time.perf_counter() - t0
        out = [{"label": cats[int(l)], "score": round(float(s), 4),
                "bbox": [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]}
               for (x1, y1, x2, y2), l, s in zip(r["boxes"].cpu().numpy(),
                                                 r["labels"].cpu().numpy(),
                                                 r["scores"].cpu().numpy())]
        return out, dt

    cap = open_pi_camera(host=a.pi_host, user=a.pi_user, key=a.pi_key,
                         rotation=a.pi_rotation, startup_timeout_s=30)
    rows, best, last = [], None, None
    stopped = None
    t_mid = None
    try:
        ok, f0 = cap.read(timeout_s=5)
        if ok:
            infer(f0)  # warm-up, discarded
        t_end = time.time() + a.duration_s
        t_mid = time.time() + a.duration_s / 2
        while time.time() < t_end:
            if mon.stop_reason:
                stopped = mon.stop_reason
                break
            ok, frame = cap.read(timeout_s=5)
            if not ok:
                if not cap.isOpened():
                    stopped = "Pi stream closed"
                    break
                continue
            cam = cap.camera_info()
            dets, dt = infer(frame)
            t_res = time.time()
            row = {"t_capture": cam["capture_time"], "rx": cam["rx_time"],
                   "result_time": round(t_res, 3), "inference_s": round(dt, 3),
                   "capture_to_result_s": round(t_res - cam["capture_time"], 3),
                   "detections": dets}
            rows.append(row)
            top = ", ".join(f"{d['label']} {d['score']:.2f}" for d in dets[:5]) or "nothing"
            log(f"  frame {len(rows):3d}: {top}  (inference {dt * 1000:.0f} ms)")
            last = (0.0, frame, row, cam)
            if supported:
                score = max([d["score"] for d in dets if d["label"] == a.object_label] or [0.0])
                if best is None or score > best[0]:
                    best = (score, frame, row, cam)
            elif best is None and time.time() >= t_mid:
                best = last
    except KeyboardInterrupt:
        stopped = "operator pressed Ctrl-C"
    finally:
        cap.release()
    with open(os.path.join(run_dir, "object_frames.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    best = best or last
    res: dict = {"stopped": stopped, "frames": len(rows), "model_load_s": round(load_s, 2),
                 "model": det.name, "device": det.device, "object_label": a.object_label,
                 "object_label_supported": supported, "ground_truth": a.ground_truth,
                 "model_weights": os.path.basename(weights.url),
                 "model_categories": [c for c in cats if c not in ("__background__", "N/A")],
                 "detection_threshold": OBJECT_THRESH, "reference_frame_rule": ref_rule,
                 "pi_stream": dict(cap.stats)}
    if rows:
        inf = [r["inference_s"] for r in rows]
        c2r = [r["capture_to_result_s"] for r in rows]
        span = rows[-1]["result_time"] - rows[0]["result_time"]
        hits = [max([d["score"] for d in r["detections"] if d["label"] == a.object_label]
                    or [0.0]) for r in rows]
        res.update({
            "inference_s_median": round(statistics.median(inf), 3),
            "inference_s_max": round(max(inf), 3),
            "capture_to_result_s_median": round(statistics.median(c2r), 3),
            "processed_fps": round((len(rows) - 1) / span, 2) if span > 0 else None,
            "frames_with_object": sum(h >= OBJECT_THRESH for h in hits),
            "frames_with_person": sum(any(d["label"] == "person" and d["score"] >= 0.6
                                          for d in r["detections"]) for r in rows),
            "labels_seen": sorted({d["label"] for r in rows for d in r["detections"]}),
            "frames_with_no_detection": sum(not r["detections"] for r in rows),
            "class_frequency": class_frequency(rows)})
    if best is not None:
        score, frame, row, cam = best
        ref = {"capture_time": cam["capture_time"],
               "capture_time_iso": iso_utc(cam["capture_time"]),
               "frame_size": [int(frame.shape[1]), int(frame.shape[0])],
               "stats": frame_stats(frame), "camera": cam,
               "detections": row["detections"], "inference_s": row["inference_s"]}
        why = withhold_reason(row["detections"], a.consent)
        if why:
            ref["image"] = why
            log(f"WITHHELD: {why}")
        else:
            import hashlib
            ann = frame.copy()
            for d in row["detections"]:
                x, y, w, h = d["bbox"]
                cv2.rectangle(ann, (x, y), (x + w, y + h), (0, 200, 255), 2)
                cv2.putText(ann, f"{d['label']} {d['score']:.2f}", (x, max(15, y - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
            for name, img, ext in (("reference", frame, ".png"),
                                   ("reference_annotated", ann, ".jpg")):
                data = cv2.imencode(ext, img)[1].tobytes()
                path = os.path.join(run_dir, f"object_{name}{ext}")
                with open(path, "xb") as fh:
                    fh.write(data)
                ref[name] = {"path": path, "sha256": hashlib.sha256(data).hexdigest()}
        res["reference_frame"] = ref
    return res


def main(argv: Optional[Sequence[str]] = None,
         prompt: Callable[[str], str] = None, sleep: Callable[[float], None] = time.sleep,
         scene_runner: Optional[Callable] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--scene", choices=SCENES, required=True)
    p.add_argument("--consent", choices=sorted(CONSENT), required=True)
    p.add_argument("--countdown-s", type=int, default=MIN_COUNTDOWN_S)
    p.add_argument("--duration-s", type=float, default=20.0)
    p.add_argument("--pi-host", default=os.environ.get("TEAM15_PI_HOST"))
    p.add_argument("--pi-user", default=os.environ.get("TEAM15_PI_USER"))
    p.add_argument("--pi-key", default=os.environ.get("TEAM15_PI_KEY"))
    p.add_argument("--pi-rotation", type=int, default=180, choices=(0, 90, 180, 270))
    p.add_argument("--sector", default="G", help="operator-assigned sector (not measured)")
    p.add_argument("--operator", default="bench-validation")
    p.add_argument("--object-label", default="chair",
                   help="object to look for; may be a class the model does not have "
                        "(e.g. drone): then nothing is relabelled and every prediction is logged")
    p.add_argument("--ground-truth", default=None,
                   help="operator's description of the physical test object, e.g. "
                        "'small quadcopter, powered off'")
    p.add_argument("--out-dir", default=DEFAULT_OUT)
    a = p.parse_args(argv)

    why = check_consent(a.scene, a.consent)
    if why:
        log(f"REFUSED: {why}. Camera not activated.")
        return EXIT_REFUSED
    if a.countdown_s < MIN_COUNTDOWN_S:
        log(f"REFUSED: --countdown-s must be at least {MIN_COUNTDOWN_S}. Camera not activated.")
        return EXIT_REFUSED
    if not a.pi_host:
        log("REFUSED: no --pi-host. Camera not activated.")
        return EXIT_REFUSED
    if not 5 <= a.duration_s <= 60:
        log("REFUSED: --duration-s must be 5-60 s (bounded test). Camera not activated.")
        return EXIT_REFUSED

    from .sightings import ensure_evidence_dir
    try:
        base = ensure_evidence_dir(a.out_dir)     # refuses Git work trees
    except ValueError as e:
        log(f"REFUSED: {e}. Camera not activated.")
        return EXIT_REFUSED

    log(f"Scene '{a.scene}' (consent '{a.consent}'), {a.duration_s:.0f} s, "
        f"rotation {a.pi_rotation}, sector {a.sector} (OPERATOR-ASSIGNED, not measured).")
    if prompt is None:
        def prompt(msg: str) -> str:
            # stdout may be piped to the bridge, so talk to the terminal directly.
            # Separate handles: a tty is not seekable, so "r+" fails on macOS.
            try:
                with open("/dev/tty", "w") as out, open("/dev/tty") as inp:
                    out.write(msg); out.flush()
                    return inp.readline()
            except OSError as e:
                log(f"no terminal for the Start prompt ({e})")
                raise KeyboardInterrupt from None
    try:
        consent_at = None
        if a.scene == "person":
            consent_at = wait_for_consent(prompt)
        else:
            wait_for_start(prompt)
        countdown(a.countdown_s, sleep)
    except Cancelled:
        log("CANCELLED: camera not activated; nothing captured or saved.")
        return EXIT_CANCELLED

    run_dir = os.path.join(base, f"{a.scene}-{time.strftime('%Y%m%dT%H%M%S')}")
    os.makedirs(run_dir, exist_ok=False)          # fresh folder per run
    mon = HealthMonitor(a, os.path.join(run_dir, "pi_health.jsonl"))
    started = time.time()
    mon.start()
    try:
        runner = scene_runner or (run_object if a.scene == "object" else run_person_pipeline)
        res = runner(a, run_dir, mon)
    finally:
        mon.halt()
        mon.join(timeout=10)
    res.update({"scene": a.scene, "consent": a.consent, "consent_confirmed_at": consent_at,
                "countdown_s": a.countdown_s,
                "duration_s": a.duration_s, "started": round(started, 3),
                "ended": round(time.time(), 3), "run_dir": run_dir,
                "sector": a.sector, "sector_source": "OPERATOR_ASSIGNED (not measured)",
                "pi_health": health_summary(mon.samples),
                "health_stop": mon.stop_reason})
    with open(os.path.join(run_dir, "run_report.json"), "x") as f:
        json.dump(res, f, indent=1)
    log("RESULT " + json.dumps({k: v for k, v in res.items() if k != "summary"}, indent=1))
    if res.get("stopped") or mon.stop_reason:
        return EXIT_STOPPED
    if a.scene == "person":
        return EXIT_OK if res.get("sightings") else EXIT_NOTHING
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

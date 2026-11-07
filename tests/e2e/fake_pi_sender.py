"""Fake Pi camera sender for tests: writes the contracts/pi_frame_stream.py wire format.

    python fake_pi_sender.py --frames 20 --fps 50 --t0 1794090000.0 [--same-image]

Each frame is a synthetic upright 1280x720 JPEG with a white block in the
TOP-LEFT corner (so a receiver can check it did not rotate again) and the
frame number drawn in it. ``capture_time = t0 + seq * 0.2`` so tests can check
that the exact Pi capture time survives to the dashboard.
"""
import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contracts.pi_frame_stream import encode_record  # noqa: E402


def frame_jpeg(seq: int, w: int, h: int, same: bool) -> bytes:
    img = np.full((h, w, 3), 90, np.uint8)
    img[0:120, 0:200] = 255                      # top-left marker = upright
    if not same:
        cv2.putText(img, f"#{seq}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok
    return buf.tobytes()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--frames", type=int, default=10)
    p.add_argument("--fps", type=float, default=50.0)
    p.add_argument("--t0", type=float, default=1794090000.0)
    p.add_argument("--w", type=int, default=1280)
    p.add_argument("--h", type=int, default=720)
    p.add_argument("--same-image", action="store_true")
    p.add_argument("--garbage-after", type=int, default=-1,
                   help="write junk bytes after this many frames")
    a = p.parse_args()
    out = sys.stdout.buffer
    for seq in range(a.frames):
        if seq == a.garbage_after:
            out.write(b"NOPE" + b"\x00" * 16)
            out.flush()
            return 0
        hdr = {"seq": seq, "capture_time": a.t0 + seq * 0.2, "sensor_ts_ns": 300_000_000_000 + seq,
               "sent_time": a.t0 + seq * 0.2 + 0.03, "w": a.w, "h": a.h, "rotation": 180,
               "host": "fake-pi"}
        out.write(encode_record(hdr, frame_jpeg(seq, a.w, a.h, a.same_image)))
        out.flush()
        time.sleep(1.0 / a.fps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

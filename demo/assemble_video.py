"""Assemble frames captured by demo/record_demo.py into an H.264 MP4 at real-time speed.

    python3 demo/assemble_video.py <frames_dir> demo/videos/Team15_Dual_Robot_Rescue_Demo.mp4

Each captured frame is held for the real time until the next frame (Chrome screencast timestamps), so the
video plays at the speed the browser actually rendered. The output is constant 30 fps, yuv420p, CRF 21,
with faststart for web playback. Needs ffmpeg on PATH.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

frames = Path(sys.argv[1])
out = Path(sys.argv[2])
meta = json.loads((frames / "timestamps.json").read_text())
st = meta["stamps"]
files = sorted(frames.glob("f*.jpg"))
assert len(files) == len(st), (len(files), len(st))
lines = []
for i, f in enumerate(files):
    dur = (st[i + 1] - st[i]) if i + 1 < len(st) else 1 / 30
    lines.append(f"file '{f.resolve()}'\nduration {max(dur, 0.001):.6f}")
lines.append(f"file '{files[-1].resolve()}'")
lst = frames / "concat.txt"
lst.write_text("\n".join(lines) + "\n")
out.parent.mkdir(parents=True, exist_ok=True)
cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
       "-vf", "fps=30,scale=1920:1080:flags=lanczos:out_range=tv,format=yuv420p", "-pix_fmt", "yuv420p", "-color_range", "tv", "-c:v", "libx264", "-preset", "slow",
       "-crf", "21", "-profile:v", "high", "-movflags", "+faststart", "-metadata",
       "title=Team-15 dual-robot rescue SIMULATION demo (no physical robot movement)", str(out)]
subprocess.run(cmd, check=True)
print(out, out.stat().st_size)

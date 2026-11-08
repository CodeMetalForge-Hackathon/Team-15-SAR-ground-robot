"""Explicitly enabled inference on the latest camera frame; no disk recording."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import threading
import time


class Vision:
    def __init__(self, camera, python=None):
        self.camera, self.python = camera, python or sys.executable
        self.lock = threading.Lock()
        self.worker = self.process = None
        self.stop = threading.Event()
        self.detail, self.running = 'Vision stopped', False
        self.result, self.received = None, 0
        self.profile, self.sequence = 'fast', 0
        self.completed = []

    def start(self, profile=None):
        if profile is not None and profile not in ('fast', 'accurate'):
            raise ValueError('Unknown detector profile')
        if profile is not None and profile != self.profile:
            self.close()
            self.profile = profile
        with self.lock:
            if self.worker and self.worker.is_alive():
                return
            self.stop.clear()
            self.result = None
            self.completed = []
            self.running, self.detail = True, 'Loading detector…'
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()

    def _run(self):
        process = None
        try:
            process = subprocess.Popen(
                [self.python, '-u', '-m', 'mission_control.vision_worker', '--profile', self.profile],
                cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            with self.lock:
                self.process = process
            if self.stop.is_set():
                return
            ready = json.loads(process.stdout.readline(8192))
            if ready.get('error'):
                raise ValueError(ready['error'])
            last = None
            while not self.stop.is_set():
                frame = self.camera.snapshot()
                if frame['frame'] is None or frame['sequence'] == last:
                    with self.lock:
                        self.detail = 'Waiting for camera frames · ' + frame['detail'] if frame['frame'] is None else 'Detecting objects'
                    self.stop.wait(.01)
                    continue
                last = frame['sequence']
                process.stdin.write(base64.b64encode(frame['frame']) + b'\n')
                process.stdin.flush()
                raw = process.stdout.readline(6 * 1024 * 1024)
                data = json.loads(raw)
                if data.get('error'):
                    raise ValueError(data['error'])
                annotated = base64.b64decode(data.pop('jpeg'), validate=True)
                with self.lock:
                    self.sequence += 1
                    now = time.monotonic()
                    self.completed = (self.completed + [now])[-30:]
                    fps = (len(self.completed)-1)/(now-self.completed[0]) if len(self.completed)>1 else 0
                    self.result = dict(data, frame=annotated, source=frame['source'],
                                       camera_sequence=last, sequence=self.sequence, detection_fps=round(fps, 1))
                    self.received, self.detail = now, 'Detecting objects'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            with self.lock:
                self.detail = 'Vision stopped' if self.stop.is_set() else str(exc)[:240] or 'Detector stopped unexpectedly'
        finally:
            if process:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                process.stdin.close()
                process.stdout.close()
            with self.lock:
                self.process, self.running = None, False

    def snapshot(self):
        frame = self.camera.snapshot()
        with self.lock:
            age = time.monotonic() - self.received if self.result else None
            fresh = bool(self.running and self.result and age <= 2 and frame['frame'] is not None)
            data = {k: v for k, v in (self.result or {}).items() if k != 'frame'} if fresh else {}
            return dict(data, running=self.running, fresh=fresh, age_s=age,
                        detail=self.detail, profile=self.profile, frame=self.result['frame'] if fresh else None)

    def close(self):
        self.stop.set()
        with self.lock:
            process, worker = self.process, self.worker
            self.result = None
            self.detail, self.running = 'Vision stopped', False
        if process and process.poll() is None:
            process.terminate()
        if worker:
            worker.join(timeout=4)

"""Bounded latest-frame buffer for a Pi camera; no video is written to disk."""
import os
import shutil
import subprocess
import threading
import time

MAX_FRAME = 2 * 1024 * 1024


class PiCamera:
    source = 'PI CAMERA'

    def __init__(self, clock=time.monotonic):
        self.clock, self.lock = clock, threading.Lock()
        self.frame, self.received, self.sequence = None, None, 0
        self.pending, self.process, self.worker = b'', None, None
        self.detail = 'Camera not connected'

    def ingest(self, chunk):
        """The rpicam MJPEG output contains concatenated JPEG frames."""
        self.pending += chunk
        while True:
            start = self.pending.find(b'\xff\xd8')
            if start < 0:
                self.pending = self.pending[-1:]
                return
            self.pending = self.pending[start:]
            end = self.pending.find(b'\xff\xd9', 2)
            if end < 0:
                if len(self.pending) > MAX_FRAME:
                    self.pending = self.pending[-1:]
                return
            frame, self.pending = self.pending[:end + 2], self.pending[end + 2:]
            if len(frame) > MAX_FRAME:
                continue
            with self.lock:
                self.frame, self.received = frame, self.clock()
                self.sequence += 1
                self.detail = 'Live'

    def snapshot(self):
        with self.lock:
            age = None if self.received is None else self.clock() - self.received
            fresh = age is not None and age <= 1
            return dict(frame=self.frame if fresh else None, sequence=self.sequence,
                        age_s=age, source=self.source,
                        detail=self.detail if age is None or fresh else 'Camera signal lost')

    def start(self):
        binary = shutil.which('rpicam-vid')
        if not binary:
            raise ValueError('rpicam-vid not found; use --pi-camera on the Raspberry Pi with rpicam-apps installed')
        self.detail = 'Connecting camera'
        self.process = subprocess.Popen([binary, '--timeout', '0', '--nopreview',
            '--codec', 'mjpeg', '--width', '1280', '--height', '720', '--framerate', '15',
            '--output', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        def consume():
            try:
                while True:
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    self.ingest(chunk)
            finally:
                with self.lock:
                    self.frame, self.received = None, None
                    self.detail = 'Camera stopped; check camera connection'

        self.worker = threading.Thread(target=consume, daemon=True)
        self.worker.start()

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=1)
            if self.worker:
                self.worker.join(timeout=1)
            self.process.stdout.close()

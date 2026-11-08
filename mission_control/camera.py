"""Bounded latest-frame buffer for a Pi camera; no video is written to disk."""
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

MAX_FRAME = 2 * 1024 * 1024


class PiCamera:
    source = 'PI CAMERA'

    def __init__(self, clock=time.monotonic):
        self.clock, self.lock = clock, threading.Lock()
        self.frame, self.received, self.sequence = None, None, 0
        self.pending, self.process, self.worker = b'', None, None
        self.detail = 'Camera not connected'
        self.publisher, self.publisher_last = None, 0

    def publish(self, frame, publisher):
        """Explicit browser camera sharing: JPEG transport only, no detection."""
        if not isinstance(publisher, str) or not 8 <= len(publisher) <= 80:
            raise ValueError('Camera publisher ID required')
        if len(frame) > MAX_FRAME or not frame.startswith(b'\xff\xd8') or not frame.endswith(b'\xff\xd9'):
            raise ValueError('Expected a complete JPEG frame under 2 MiB')
        with self.lock:
            now = self.clock()
            if self.process is not None or (self.publisher and self.publisher != publisher and now-self.publisher_last < 2):
                raise ValueError('Another camera source is active')
            self.publisher, self.publisher_last = publisher, now
            self.frame, self.received = bytes(frame), now
            self.sequence += 1
            self.source, self.detail = 'SHARED DEVICE CAMERA', 'Live'

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

    def start_local(self, python):
        """Use a host USB/built-in webcam when no Pi/browser source owns the feed."""
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return
            # Explicit "Use host / Pi feed" replaces a browser publisher. Its
            # next upload is refused, so that view releases its camera tracks.
            self.publisher, self.frame, self.received = None, None, None
            self.source, self.detail = 'HOST WEBCAM', 'Connecting host webcam'
            self.process = subprocess.Popen([python, '-u', '-m', 'mission_control.camera_worker'],
                cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
        self._consume()

    def stop_local(self):
        if self.source == 'HOST WEBCAM':
            self.close()
            with self.lock:
                self.process, self.worker = None, None
                self.frame, self.received, self.publisher = None, None, None
                self.detail = 'Host webcam stopped'

    def start(self):
        binary = shutil.which('rpicam-vid')
        if not binary:
            raise ValueError('rpicam-vid not found; use --pi-camera on the Raspberry Pi with rpicam-apps installed')
        self.detail = 'Connecting camera'
        self.process = subprocess.Popen([binary, '--timeout', '0', '--nopreview',
            '--codec', 'mjpeg', '--width', '1280', '--height', '720', '--framerate', '15',
            '--output', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._consume()

    def _consume(self):
        process = self.process
        def consume():
            try:
                while True:
                    chunk = os.read(process.stdout.fileno(), 65536)
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

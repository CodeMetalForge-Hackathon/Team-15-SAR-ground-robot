"""Explicit local capture/label storage and an isolated robot-training job."""
import base64
from collections import Counter
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time

DEFAULT_DATASET = Path.home() / '.local/share/team15/vision-training'


class Training:
    def __init__(self, python=None, directory=None):
        self.python, self.directory = python or sys.executable, Path(directory or DEFAULT_DATASET)
        self.lock, self.process = threading.Lock(), None

    def records(self):
        records = []
        for path in sorted(self.directory.glob('samples/*.json')):
            records.append(json.loads(path.read_text()))
        return records

    def snapshot(self):
        records = self.records()
        counts = Counter(label for row in records for label in {box['label'] for box in row['boxes']})
        sessions = {label: len({row['session'] for row in records if any(b['label'] == label for b in row['boxes'])}) for label in ('drone', 'rover')}
        ready_classes = [label for label in sessions if counts[label] >= 20 and sessions[label] >= 2]
        ready = bool(ready_classes)
        progress = self.directory / 'progress.json'
        try:
            job = json.loads(progress.read_text()) if progress.exists() else {'status': 'Not trained'}
        except (ValueError, OSError):
            job = {'status': 'Waiting for training progress'}
        with self.lock:
            running = self.process is not None and self.process.poll() is None
        if not running and job.get('status') == 'Training':
            job['status'] = 'Training interrupted; previous validated model preserved'
        return dict(counts={label: counts[label] for label in sessions}, sessions=sessions,
                    total=len(records), ready=ready, ready_classes=ready_classes, running=running, job=job,
                    trained=(self.directory / 'robots.pt').exists())

    def save(self, data):
        if not isinstance(data, dict):
            raise ValueError('Expected a labeled frame')
        session, boxes = data.get('session'), data.get('boxes')
        if not isinstance(session, str) or not 8 <= len(session) <= 80 or not session.replace('-', '').isalnum():
            raise ValueError('Invalid capture session')
        if not isinstance(boxes, list) or len(boxes) > 20 or (not boxes and data.get('background') is not True):
            raise ValueError('Draw at least one robot box')
        cleaned = []
        for box in boxes:
            if not isinstance(box, dict):
                raise ValueError('Invalid box')
            label, bounds = box.get('label'), box.get('bbox')
            if label not in ('drone', 'rover') or not isinstance(bounds, list) or len(bounds) != 4:
                raise ValueError('Choose Crazyflie or RoverC and draw its box')
            if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in bounds):
                raise ValueError('Invalid box coordinates')
            x, y, width, height = bounds
            if min(x, y) < 0 or min(width, height) <= .002 or x+width > 1.000001 or y+height > 1.000001:
                raise ValueError('Box must lie inside the image')
            cleaned.append(dict(label=label, bbox=bounds))
        encoded = data.get('jpeg')
        if not isinstance(encoded, str) or len(encoded) > 2800000:
            raise ValueError('Frame is too large')
        try:
            jpeg = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise ValueError('Invalid JPEG encoding') from None
        if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
            raise ValueError('Expected a complete JPEG frame')
        from PIL import Image
        from io import BytesIO
        try:
            image = Image.open(BytesIO(jpeg))
            width, height = image.size
            if image.format != 'JPEG' or width * height > 1920 * 1080:
                raise ValueError('Expected JPEG up to 1920 × 1080')
            image.verify()
        except (OSError, Image.DecompressionBombError):
            raise ValueError('JPEG could not be decoded') from None
        with self.lock:
            folder = self.directory / 'samples'
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            sample_id = secrets.token_hex(12)
            row = dict(id=sample_id, session=session, saved_at=time.time(),
                       image=sample_id+'.jpg', width=width, height=height, boxes=cleaned)
            for suffix, content in (('.jpg', jpeg), ('.json', json.dumps(row).encode())):
                fd = os.open(folder / (sample_id+suffix+'.tmp'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
                (folder / (sample_id+suffix+'.tmp')).replace(folder / (sample_id+suffix))
        return dict(saved=sample_id, **self.snapshot())

    def start(self, classes=None):
        available = self.snapshot()['ready_classes']
        classes = classes or available
        if not classes or not isinstance(classes, list) or any(label not in available for label in classes):
            raise ValueError('Need 20 labeled frames of the selected robot across at least two capture sessions')
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            (self.directory / 'progress.json').write_text(json.dumps({'status': 'Training', 'epoch': 0}))
            self.process = subprocess.Popen([self.python, '-u', '-m', 'perception.train',
                '--dataset', str(self.directory), '--epochs', '20', '--classes', *classes, '--activate'],
                cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self):
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

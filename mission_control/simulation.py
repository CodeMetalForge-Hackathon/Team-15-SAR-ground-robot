"""Run the software-only fleet simulator behind the dashboard's same origin."""
import json
from pathlib import Path
import select
import subprocess
import sys
import threading


class Simulation:
    def __init__(self, python=None):
        self.python = python or sys.executable
        self.process = None
        self.port = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return self.port
            self.process = subprocess.Popen(
                [self.python, '-u', '-m', 'mission_control.simulation_worker'],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if not select.select([self.process.stdout], [], [], 8)[0]:
                self._close()
                raise ValueError('Simulator startup timed out')
            line = self.process.stdout.readline(4096)
            try:
                self.port = int(json.loads(line)['port'])
            except (ValueError, KeyError, TypeError):
                self._close()
                raise ValueError('Simulator unavailable. Install numpy in the runtime Python.') from None
            return self.port

    def _close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process.stdout.close()
        self.process, self.port = None, None

    def close(self):
        with self.lock:
            self._close()

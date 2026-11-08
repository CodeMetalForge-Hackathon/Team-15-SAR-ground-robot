"""Authenticated Mac -> Pi rover link: HMAC-SHA256 request signing. Pure; no I/O except reading the key file.

Signed string: METHOD \\n PATH \\n TIMESTAMP \\n COUNTER \\n BODY. Headers X-T15-Time, X-T15-Ctr, X-T15-Sig.
The verifier refuses: a missing/bad signature (constant-time compare), a timestamp more than `window_s` from the
Pi clock, and any counter not strictly greater than the last accepted one (replay). The Mac counter is seeded
from time_ns so a restarted Mac process still counts upward.

Key: 32+ random bytes in a file only its owner can read (chmod 600), e.g. ~/.config/team15/rover_link.key on
both machines. It authenticates the Mac; it does not encrypt (Tailscale already does).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import stat
import threading
import time
from typing import Callable

HDR_T, HDR_C, HDR_S = "X-T15-Time", "X-T15-Ctr", "X-T15-Sig"
DEFAULT_KEY = "~/.config/team15/rover_link.key"


class AuthError(PermissionError):
    pass


def load_key(path: str = DEFAULT_KEY) -> bytes:
    p = os.path.expanduser(path)
    st = os.stat(p)
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise AuthError(f"{p} must be readable by its owner only (chmod 600)")
    key = open(p, "rb").read().strip()
    if len(key) < 32:
        raise AuthError("link key must be at least 32 bytes")
    return key


def _mac(key: bytes, method: str, path: str, ts: str, ctr: str, body: bytes) -> str:
    msg = f"{method.upper()}\n{path}\n{ts}\n{ctr}\n".encode() + (body or b"")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


class Signer:
    def __init__(self, key: bytes, clock: Callable[[], float] = time.time):
        self.key, self.clock = key, clock
        self.ctr = time.time_ns() // 1000
        self.lock = threading.Lock()

    def headers(self, method: str, path: str, body: bytes = b"") -> dict:
        with self.lock:
            self.ctr += 1
            ctr = str(self.ctr)
        ts = f"{self.clock():.3f}"
        return {HDR_T: ts, HDR_C: ctr, HDR_S: _mac(self.key, method, path, ts, ctr, body)}


class Verifier:
    def __init__(self, key: bytes, clock: Callable[[], float] = time.time, window_s: float = 5.0):
        self.key, self.clock, self.window_s = key, clock, window_s
        self.last_ctr = -1
        self.lock = threading.Lock()

    def check(self, method: str, path: str, headers, body: bytes = b"") -> None:
        ts, ctr, sig = headers.get(HDR_T), headers.get(HDR_C), headers.get(HDR_S)
        if not (ts and ctr and sig):
            raise AuthError("unsigned request")
        if not hmac.compare_digest(_mac(self.key, method, path, ts, ctr, body), sig):
            raise AuthError("bad signature")
        try:
            t, c = float(ts), int(ctr)
        except ValueError:
            raise AuthError("malformed auth headers") from None
        if abs(self.clock() - t) > self.window_s:
            raise AuthError(f"timestamp outside +/-{self.window_s:.0f} s (clock skew or replay)")
        with self.lock:
            if c <= self.last_ctr:
                raise AuthError("replayed or out-of-order counter")
            self.last_ctr = c

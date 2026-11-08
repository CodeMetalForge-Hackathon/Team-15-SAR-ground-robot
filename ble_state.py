"""Durable replay state for the BLE-ID verifier (standard library only).

The state is the per-alias high-water counter, scoped to one enrollment/mission
(``scope``). It survives verifier restarts and fails closed:
  * missing state is allowed only through an explicit ``init_state`` call;
  * a missing, truncated, corrupt, wrong-scope or wrong-version file raises
    StateError on load, and nothing is guessed or reset;
  * writes are atomic (temp file, fsync, os.replace, directory fsync), so a
    crash leaves either the old state or the new state, never a mix.
The checksum detects accidental corruption only. It is not authentication:
rollback of the state file, compromised keys, and real-time relays are outside
the prototype's protection (base spec). There is no cross-process lock: one
verifier process owns one state file.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

SCHEMA = "olf-ble-id-replay-state/1"
MAX_COUNTER = 0xFFFFFFFF
MAX_BYTES = 64 * 1024


class StateError(Exception):
    """Replay state cannot be trusted; the verifier must not run."""


def _canonical(scope: str, high: Mapping[int, int]) -> bytes:
    body = {"schema": SCHEMA, "scope": scope,
            "high_water": {str(a): high[a] for a in sorted(high)}}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def _validate(scope: str, high: Mapping[int, int]) -> None:
    if not isinstance(scope, str) or not scope.strip():
        raise StateError("scope must be a non-empty string")
    for a, c in high.items():
        if not isinstance(a, int) or isinstance(a, bool) or not 1 <= a <= 255:
            raise StateError(f"invalid alias in state: {a!r}")
        if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= MAX_COUNTER:
            raise StateError(f"invalid counter for alias {a}")


def _write_atomic(path: Path, data: bytes) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def save_state(path, high: Mapping[int, int], *, scope: str) -> None:
    """Atomically persist ``high``. Call before emitting a verified observation."""
    _validate(scope, high)
    body = _canonical(scope, high)
    doc = {"body": json.loads(body), "sha256": hashlib.sha256(body).hexdigest()}
    _write_atomic(Path(path), json.dumps(doc, sort_keys=True, indent=1).encode() + b"\n")


def init_state(path, *, scope: str) -> Mapping[int, int]:
    """Explicit first initialization. Refuses to overwrite any existing file."""
    if os.path.lexists(path):
        raise StateError(f"refusing to initialize: {path} already exists")
    save_state(path, {}, scope=scope)
    return MappingProxyType({})


def load_state(path, *, scope: str) -> Mapping[int, int]:
    """Load and check the state. Every problem raises StateError (fail closed)."""
    p = Path(path)
    if not p.is_file():
        raise StateError(f"replay state missing: {p} (use init_state only for a new mission)")
    raw = p.read_bytes()
    if len(raw) > MAX_BYTES:
        raise StateError("replay state file is implausibly large")
    try:
        doc = json.loads(raw)
        body, digest = doc["body"], doc["sha256"]
        if set(doc) != {"body", "sha256"} or set(body) != {"schema", "scope", "high_water"}:
            raise StateError("unexpected fields in replay state")
    except (ValueError, KeyError, TypeError) as e:
        raise StateError(f"replay state is corrupt: {e.__class__.__name__}") from None
    if body["schema"] != SCHEMA:
        raise StateError(f"unsupported replay state schema {body['schema']!r}")
    if body["scope"] != scope:
        raise StateError("replay state belongs to a different enrollment/mission scope")
    hw = body["high_water"]
    if not isinstance(hw, dict):
        raise StateError("replay state high_water is not an object")
    high = {}
    for k, v in hw.items():
        if not (isinstance(k, str) and k.isdigit() and k == str(int(k))):
            raise StateError(f"invalid alias key {k!r}")
        high[int(k)] = v
    _validate(scope, high)
    if not isinstance(digest, str) or digest != hashlib.sha256(_canonical(scope, high)).hexdigest():
        raise StateError("replay state checksum mismatch")
    return MappingProxyType(high)

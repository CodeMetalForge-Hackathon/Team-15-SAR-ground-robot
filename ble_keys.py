"""Explicit key loading for the BLE-ID verifier. Never prints key material.

Modes (chosen explicitly on the command line; nothing falls back silently):
  production  keys from a keys.json the operator names; every PUBLISHED synthetic
              test key is refused; scope must not look like a test/sim scope
  test-keys   built-in PUBLIC SYNTHETIC TEST KEYS (C0 vectors, aliases 1-2);
              scope must start with TESTKEY- (labelled experiments only)
  simulated   built-in simulator keys; scope must start with SIMULATED-
Separate scopes keep test and simulated replay state from mixing with a mission.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional

FORMAT = "olf-ble-id-keys/1"
MODES = ("production", "test-keys", "simulated")
PREFIX = {"test-keys": "TESTKEY-", "simulated": "SIMULATED-"}
MODE_LABEL = {"production": "PRODUCTION KEYS", "test-keys": "SYNTHETIC TEST KEYS",
              "simulated": "SIMULATED"}

# PUBLIC SYNTHETIC keys: the C0 vector keys, E0 experiment keys, simulator keys.
TEST_KEYS = MappingProxyType({1: bytes(range(0x00, 0x20)), 2: bytes(range(0x20, 0x40))})
SIM_KEYS = MappingProxyType({a: hashlib.sha256(b"OLF SIMULATOR KEY %d" % a).digest() for a in (1, 2, 3)})
PUBLIC_SYNTHETIC = frozenset([
    *TEST_KEYS.values(), b"\xa5" * 32, *SIM_KEYS.values(),
    *(hashlib.sha256(b"E0 SYNTHETIC KEY %d" % a).digest() for a in range(1, 9)),
    hashlib.sha256(b"E0 SYNTHETIC WRONG KEY").digest(),
])


class KeyConfigError(Exception):
    """Keys or mode are not acceptable; verification must not start."""


def check_scope(mode: str, scope: str) -> None:
    if mode not in MODES:
        raise KeyConfigError(f"unknown mode {mode!r}")
    if not isinstance(scope, str) or not scope.strip() or len(scope) > 100:
        raise KeyConfigError("scope must be a non-empty string up to 100 characters")
    if mode == "production":
        if scope.startswith(tuple(PREFIX.values())):
            raise KeyConfigError("production scope must not use a TESTKEY-/SIMULATED- prefix")
    elif not scope.startswith(PREFIX[mode]):
        raise KeyConfigError(f"{mode} scope must start with {PREFIX[mode]}")


def _alias(text) -> int:
    if not (isinstance(text, str) and text.isdigit() and text == str(int(text)) and 1 <= int(text) <= 255):
        raise KeyConfigError(f"invalid alias {text!r} in keys file")
    return int(text)


def load_production_keys(path, *, scope: str) -> Mapping[int, bytes]:
    p = Path(path)
    try:
        st = os.stat(p)
    except OSError:
        raise KeyConfigError(f"keys file not found: {p}") from None
    if not stat.S_ISREG(st.st_mode):
        raise KeyConfigError("keys file must be a regular file")
    if st.st_mode & 0o077:
        raise KeyConfigError("keys file must not be readable by group or others (chmod 600)")
    try:
        doc = json.loads(p.read_bytes())
    except ValueError:
        raise KeyConfigError("keys file is not valid JSON") from None
    if not isinstance(doc, dict) or set(doc) != {"format", "scope", "keys"}:
        raise KeyConfigError("keys file must contain exactly: format, scope, keys")
    if doc["format"] != FORMAT:
        raise KeyConfigError(f"keys file format must be {FORMAT}")
    if doc["scope"] != scope:
        raise KeyConfigError("keys file belongs to a different enrollment/mission scope")
    if not isinstance(doc["keys"], dict) or not doc["keys"]:
        raise KeyConfigError("keys file has no enrolled aliases")
    keys = {}
    for text, value in doc["keys"].items():
        alias = _alias(text)
        if not (isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)):
            raise KeyConfigError(f"alias {alias}: key must be 64 lowercase hex characters")
        key = bytes.fromhex(value)
        if key in PUBLIC_SYNTHETIC:
            raise KeyConfigError(f"alias {alias}: a published synthetic test key is refused in production")
        if key in keys.values():
            raise KeyConfigError(f"alias {alias}: key duplicates another alias's key")
        keys[alias] = key
    return MappingProxyType(keys)


def keys_for(mode: str, *, scope: str, path: Optional[str] = None) -> Mapping[int, bytes]:
    """The only entry point: explicit mode, explicit scope, explicit file for production."""
    check_scope(mode, scope)
    if mode == "production":
        if path is None:
            raise KeyConfigError("production mode requires --keys PATH")
        return load_production_keys(path, scope=scope)
    if path is not None:
        raise KeyConfigError(f"{mode} mode uses built-in synthetic keys; do not pass --keys")
    return TEST_KEYS if mode == "test-keys" else SIM_KEYS

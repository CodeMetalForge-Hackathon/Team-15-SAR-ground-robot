import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VECTORS = ROOT / "evidence" / "c0-20261107T1914Z" / "protocol_vectors_v1.json"
VECTORS_SHA256 = "558467fdd4c0ee16e1f99d0a21b5c2bcecac2c9b63da075b68379b4dd6703899"


@pytest.fixture(scope="session")
def vec():
    """The C0 reference vectors (PUBLIC SYNTHETIC TEST KEYS; never enroll)."""
    return json.loads(VECTORS.read_bytes())


@pytest.fixture(scope="session")
def keys(vec):
    return {1: bytes.fromhex(vec["keys_hex"]["1"]), 2: bytes.fromhex(vec["keys_hex"]["2"])}


def expected(label):
    """'replay:stale (note)' -> ('replay', 'stale'); 'verified (note)' -> ('verified', None)."""
    kind, _, reason = label.split(" ")[0].partition(":")
    return kind, reason or None

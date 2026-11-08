"""tests/test_link.py — proves the Python homebase and the ESP32 firmware speak
the same bytes. Run from team15_starter/:

    python tests/test_link.py

Needs a C compiler (cc/gcc/clang) for the cross-language half; skips it if none.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from link import protocol as P  # noqa: E402

KEY = b"team15-test-key"

TEL = P.Telemetry(12.5, -3.25, 1.5, 0.75, 0.5, 87, 1, P.sensor_bit("thermal") | P.sensor_bit("mmwave"), 41)
DET = P.Detection(30.0, 42.5, P.SENSOR_IDS["mmwave"], 240, 2, 118, 22, 12, 7, 0xDEADBEEF)
WPT = P.Waypoint(20.0, 40.0, 1.25, 0.0, P.CMD_GOTO, 5, 6, 99)

PY_SAMPLES = [
    P.encode(TEL, 2, 0, 1000, 123456),
    P.encode(TEL, 2, 0, 1001, 123457, key=KEY),
    P.encode(DET, 3, 0, 77, 5000),
    P.encode(DET, 3, 0, 78, 5001, key=KEY),
    P.encode(WPT, 0, 1, 4242, 9),
    P.encode(WPT, 0, 1, 4243, 10, key=KEY),
]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("  ok  ", msg)


def python_only():
    print("python side")
    for raw in PY_SAMPLES:
        pk = P.decode(raw, key=KEY)
        check(P.encode(pk.body, pk.src, pk.dst, pk.seq, pk.t_ms,
                       key=KEY if pk.flags & P.FLAG_AUTH else None) == raw,
              f"roundtrip type {pk.type} auth={bool(pk.flags & 1)} ({len(raw)} B)")
    check(max(len(r) for r in PY_SAMPLES) <= 64, "largest packet fits ESP-NOW (<= 250 B) and T15_MAX_PKT")

    bad = bytearray(PY_SAMPLES[1]); bad[16] ^= 0x01
    try:
        P.decode(bytes(bad), key=KEY); check(False, "bit flip caught")
    except P.PacketError as e:
        check("crc" in str(e), "bit flip -> bad crc")

    forged = bytearray(PY_SAMPLES[1][:-2]); forged[16] ^= 0x01
    forged = bytes(forged) + P.crc16(bytes(forged)).to_bytes(2, "little")
    try:
        P.decode(forged, key=KEY); check(False, "forgery caught")
    except P.PacketError as e:
        check("auth" in str(e), "attacker fixes crc but can't fix HMAC -> rejected")

    try:
        P.decode(PY_SAMPLES[0], key=KEY, require_auth=True); check(False, "unsigned caught")
    except P.PacketError as e:
        check("unauth" in str(e), "military mode rejects unsigned packets")

    g = P.ReplayGuard()
    check(g.ok(2, 10) and g.ok(2, 11) and not g.ok(2, 11) and not g.ok(2, 5), "replayed seq rejected")

    rng = random.Random(1)
    for n in (0, 1, 2, 253, 254, 255, 300, 600):
        for _ in range(20):
            d = bytes(rng.choice([0, 0, 1, 7, 255, rng.randrange(256)]) for _ in range(n))
            e = P.cobs_encode(d)
            assert 0 not in e and P.cobs_decode(e) == d, (n, d)
    check(True, "COBS roundtrip, 160 random buffers incl. zeros and 254-byte runs")

    fr = P.FrameReader()
    stream = b"\x13\x37garbage" + b"\x00" + b"".join(P.frame(b"\x05" + r) for r in PY_SAMPLES)
    got = []
    for i in range(0, len(stream), 7):          # dribble bytes in like a UART
        got += fr.feed(stream[i:i + 7])
    check([g[1:] for g in got if len(g) > 1 and g[0] == 5] == PY_SAMPLES, "framed stream survives 7-byte chunks + leading garbage")


def cross_language():
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        print("C side: no compiler found, skipped")
        return
    print("C side (" + os.path.basename(cc) + ")")
    tmp = tempfile.mkdtemp()
    exe = os.path.join(tmp, "xcheck")
    subprocess.check_call([cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-O2",
                           os.path.join(HERE, "xcheck.c"), "-o", exe])

    def run(*args):
        return subprocess.check_output([exe] + list(args)).decode().split("\n")

    c_hex = [x for x in run("enc") if x]
    for i, (c, p) in enumerate(zip(c_hex, PY_SAMPLES)):
        check(bytes.fromhex(c) == p, f"C encode == Python encode, sample {i} ({len(p)} B)")

    for raw in PY_SAMPLES:
        auth = bool(raw[3] & P.FLAG_AUTH)
        out = run("dec", KEY.decode() if auth else "-", raw.hex())[:2]
        pk = P.decode(raw, key=KEY)
        hdr = [int(v) for v in out[0].split()[1:]]
        vals = [float(v) for v in out[1].split()[1:]]
        want = [float(v) for v in vars(pk.body).values()]
        check(hdr == [pk.type, pk.flags, pk.src, pk.dst, pk.seq, pk.t_ms]
              and all(abs(a - b) < 1e-3 for a, b in zip(vals, want)) and len(vals) == len(want),
              f"C decodes Python type {pk.type} auth={auth}: every field matches")
        if auth:
            wrong = run("dec", "wrong-key", raw.hex())[0]
            check(wrong.startswith("ERR -6"), "C rejects a packet signed with another key")

    for n in (0, 1, 55, 56, 63, 64, 65, 119, 120, 130):
        b = bytes(i & 0xFF for i in range(n))
        sha, mac = run("sha", str(n))[:2]
        assert sha == hashlib.sha256(b).hexdigest(), n
        assert mac == hmac.new(KEY, b, hashlib.sha256).hexdigest(), n
    check(True, "C SHA-256 and HMAC match hashlib at 10 lengths (padding edge cases)")

    rng = random.Random(2)
    for n in (0, 1, 254, 255, 600):
        d = bytes(rng.choice([0, 1, 255, rng.randrange(256)]) for _ in range(n))
        enc, rt = run("cobs", d.hex() if d else "")[:2]
        assert rt == "RT_OK" and bytes.fromhex(enc) == P.cobs_encode(d), n
    check(True, "C COBS == Python COBS")
    shutil.rmtree(tmp)


if __name__ == "__main__":
    python_only()
    cross_language()
    print("ALL LINK TESTS PASSED")

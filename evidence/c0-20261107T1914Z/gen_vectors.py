"""C0 protocol-vector generator for wire format v1 (SENSOR_ID_SPEC.md).

Evidence tooling, NOT module code: the BLE module must never import this file.
It computes payload bytes two independent ways (Python stdlib hmac and the
OpenSSL CLI) and fails if they differ. Expected decisions are literals written
by hand from the spec's classification order, not produced by any verifier.
All keys here are PUBLIC SYNTHETIC TEST KEYS: never enroll them.

    python3 -I gen_vectors.py OUT.json
"""
import hashlib, hmac, json, math, subprocess, sys, uuid

DOMAIN, WINDOW = b"OLF/BLE-ID/v1", 30
KEYS = {1: bytes(range(0x00, 0x20)), 2: bytes(range(0x20, 0x40))}  # synthetic
K_WRONG = bytes([0xA5]) * 32                                          # synthetic
NOW = 1794077187.0
N = math.floor(NOW / WINDOW)


def tag_py(key, header):
    return hmac.new(key, DOMAIN + header, hashlib.sha256).digest()[:10]


def tag_openssl(key, header):
    out = subprocess.run(["openssl", "dgst", "-sha256", "-mac", "HMAC", "-macopt",
                          "hexkey:" + key.hex(), "-hex"], input=DOMAIN + header,
                         capture_output=True, check=True).stdout.decode()
    return bytes.fromhex(out.strip().split("= ")[-1])[:10]


def token(alias, counter, key):
    if not 0 <= counter <= 0xFFFFFFFF:
        raise OverflowError("counter does not fit in 32 bits")
    header = bytes([0x01, alias]) + counter.to_bytes(4, "big")
    a, b = tag_py(key, header), tag_openssl(key, header)
    if a != b:
        sys.exit(f"MISMATCH alias={alias} counter={counter}: {a.hex()} != {b.hex()}")
    return header + a


def enc(p):
    d = {"payload_hex": p.hex(), "len": len(p)}
    if len(p) == 16:
        d["uuid_text"] = str(uuid.UUID(bytes=p))
        d["on_air_le_hex"] = p[::-1].hex()
    return d


def flip(p, i, x=0x01):
    b = bytearray(p); b[i] ^= x; return bytes(b)


v1 = token(1, N, KEYS[1])
auth = [  # (id, description, payload, expected decision)
    ("A1", "valid alias 1, counter N", v1, "verified"),
    ("A2", "valid alias 2, counter N", token(2, N, KEYS[2]), "verified"),
    ("A3", "alias 1 header, tag made with alias 2's key", token(1, N, KEYS[2]), "forged"),
    ("A4", "A1 with alias byte changed 1->2 (enrolled)", bytes([1, 2]) + v1[2:], "forged"),
    ("A5", "A1 with counter changed to N+1, tag kept", v1[:2] + (N + 1).to_bytes(4, "big") + v1[6:], "forged"),
    ("A6", "A1 with last tag bit flipped", flip(v1, 15), "forged"),
    ("A7", "alias 7 (not enrolled), wrong-key tag", token(7, N, K_WRONG), "unknown"),
    ("A8", "A1 with version byte 0x02", flip(v1, 0, 0x03), "drop:unsupported_version"),
    ("A9", "alias 0 (reserved), valid-looking tag", token(0, N, K_WRONG), "drop:reserved_alias (PROPOSED reading)"),
    ("A10", "A1 truncated to 15 bytes", v1[:15], "drop:length"),
    ("A11", "A1 plus one byte (17 bytes)", v1 + b"\x00", "drop:length"),
]
fresh = [  # (id, token counter offset from N, now, expected) with empty state
    ("F1", 0, NOW, "verified"),
    ("F2", -1, NOW, "verified"),
    ("F3", +1, NOW, "verified (future window accepted)"),
    ("F4", -2, NOW, "replay:stale"),
    ("F5", +2, NOW, "replay:future"),
    ("F6", -1, 30.0 * N, "verified (now = first instant of window N)"),
    ("F7", -2, 30.0 * N, "replay:stale (now = first instant of window N)"),
    ("F8", -1, 30.0 * (N + 1) - 0.001, "verified (age ~59.999 s from token window start)"),
]
seqs = [  # (id, description, [(alias, offset, key_alias_or_wrong, now, expected)])
    ("S1", "duplicate in same window", [(1, 0, 1, NOW, "verified"), (1, 0, 1, NOW, "replay:duplicate")]),
    ("S2", "out of order: future first", [(1, 1, 1, NOW, "verified"), (1, 0, 1, NOW, "replay:not_newer")]),
    ("S3", "forged must not poison state", [(1, 1, "wrong", NOW, "forged"), (1, 0, 1, NOW, "verified")]),
    ("S4", "per-alias isolation", [(1, 0, 1, NOW, "verified"), (2, 0, 2, NOW, "verified")]),
    ("S5", "clock jumps forward 3600 s", [(1, 0, 1, NOW, "verified"), (1, 0, 1, NOW + 3600, "replay:stale"),
                                          (1, 120, 1, NOW + 3600, "verified")]),
    ("S6", "clock jumps back 300 s after future accept",
     [(1, 1, 1, NOW, "verified"), (1, -10, 1, NOW - 300, "replay:not_newer")]),
]

out = {
    "format": "OLF BLE-ID wire format v1", "domain_ascii": DOMAIN.decode(), "window_s": WINDOW,
    "tag_bytes": 10, "now_unix_s": NOW, "N": N, "N_hex": f"{N:08x}",
    "keys_note": "PUBLIC SYNTHETIC TEST KEYS. Never enroll. Real keys never appear in logs or evidence.",
    "keys_hex": {"1": KEYS[1].hex(), "2": KEYS[2].hex(), "wrong": K_WRONG.hex()},
    "enrolled_aliases": [1, 2],
    "uuid_text_case": "lowercase here; CBUUID.uuidString is uppercase; compare case-insensitively",
    "on_air_note": "on_air_le_hex is the expected little-endian AD byte order; C1 raw capture must confirm",
    "auth": [{"id": i, "desc": d, **enc(p), "expected": e} for i, d, p, e in auth],
    "freshness": [{"id": i, "counter": N + o, "now_unix_s": t, **enc(token(1, N + o, KEYS[1])), "expected": e}
                  for i, o, t, e in fresh],
    "sequences": [{"id": i, "desc": d, "steps": [
        {"alias": a, "counter": N + o, "now_unix_s": t,
         **enc(token(a, N + o, K_WRONG if k == "wrong" else KEYS[k])), "expected": e}
        for a, o, k, t, e in steps]} for i, d, steps in seqs],
    "boundary": {"max_counter": enc(token(1, 0xFFFFFFFF, KEYS[1])),
                 "make_token_at_unix_s": 30 * 2**32, "make_token_expected": "error: counter overflow"},
}
try:
    token(1, 2**32, KEYS[1]); sys.exit("overflow check failed")
except OverflowError:
    pass
json.dump(out, open(sys.argv[1], "w"), indent=1)
n = len(auth) + len(fresh) + sum(len(s[2]) for s in seqs) + 1
print(f"wrote {sys.argv[1]}: {n} payloads, python hmac == openssl for all 16-byte tokens; N={N}")

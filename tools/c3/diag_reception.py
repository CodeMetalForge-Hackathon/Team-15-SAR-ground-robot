"""Reception diagnostic: is the C1 iPhone token on the air, and does the firmware report it?

    python3 tools/c3/diag_reception.py /dev/cu.usbmodemXXXX OUT_DIR [SECONDS]

Reads the receiver directly (stop the dashboard first; one reader owns the port) and
looks for OLF v1 tokens in three firmware channels: #BLE raw advertisements (AD types
0x06/0x07, 128-bit UUIDs, little-endian), "rssi,name,uuid" rows, and #RAW rows. Each
token's tag is checked with the PUBLIC SYNTHETIC TEST KEY for alias 1 (C1 app). Saves
only OLF tokens and counts: never device addresses or other devices' payloads.
"""
import fcntl, json, os, re, select, sys, termios, time, tty
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from ble_keys import TEST_KEYS  # noqa: E402
from ble_verify import verify  # noqa: E402

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def ad_uuids128(payload_hex):
    data, i, out = bytes.fromhex(payload_hex), 0, []
    while i < len(data) and data[i]:
        end = i + data[i] + 1
        if end > len(data):
            break
        if data[i + 1] in (0x06, 0x07):
            v = data[i + 2:end]
            out += [v[j:j + 16][::-1] for j in range(0, len(v) - 15, 16)]
        i = end
    return out


def classify(payload, now):
    d, _ = verify(payload, TEST_KEYS, {}, now=now)
    return f"{d.kind}:{d.reason}"


def main(port, out_dir, secs):
    os.makedirs(out_dir, exist_ok=True)
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    fcntl.ioctl(fd, termios.TIOCEXCL)
    tty.setraw(fd)
    c = termios.tcgetattr(fd); c[4] = c[5] = termios.B115200; termios.tcsetattr(fd, termios.TCSANOW, c)
    termios.tcflush(fd, termios.TCIFLUSH)
    n, tokens, buf, start = Counter(), [], b"", time.monotonic()
    drain_until, aligned, last_print = start + 2, False, 0
    print(f"Listening on {port} for {secs} s (first 2 s discarded). Keep the C1 app open, Rotating, Start, screen ON.")
    while time.monotonic() - start < secs + 2:
        if not select.select([fd], [], [], 0.25)[0]:
            continue
        chunk = os.read(fd, 8192)
        if not chunk:
            n["disconnect"] += 1
            break
        if time.monotonic() < drain_until:
            continue
        if not aligned:
            if b"\n" not in chunk:
                continue
            chunk, aligned = chunk.split(b"\n", 1)[1], True
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line, now = raw.decode("utf-8", "replace").strip(), time.time()
            n["lines"] += 1
            if line.startswith("#HEARTBEAT"):
                n["heartbeats"] += 1
                n["heartbeat_discovery_fields"] += ",passive=1,discovery=1" in line
            elif line.startswith(("#SCAN_END", "#SCAN_ERROR")):
                n["scan_interruptions"] += 1
            elif line.startswith("#BLE,"):
                n["ble_adverts"] += 1
                parts = line.split(",")
                try:
                    found = ad_uuids128(parts[4]) if len(parts) == 5 else []
                except ValueError:
                    n["ble_unparsable"] += 1
                    continue
                n["ble_adverts_with_uuid128"] += bool(found)
                for u in found:
                    if u[0] == 1:
                        n["ble_olf_v1"] += 1
                        h = u.hex()
                        tokens.append(dict(utc=now, ch="BLE", rssi=int(parts[1]), d=classify(u, now),
                                           uuid=f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"))
            elif line.startswith("#RAW,"):
                n["raw_rows"] += 1
                m = UUID.search(line)
                n["raw_olf_v1"] += bool(m and m[0].startswith("01"))
            elif UUID.search(line):
                n["uuid_rows"] += 1
                f = line.split(",")
                if len(f) == 3 and f[2].startswith("01"):
                    n["uuid_rows_olf_v1"] += 1
                    p = bytes.fromhex(f[2].replace("-", ""))
                    tokens.append(dict(utc=now, ch="ROW", rssi=int(f[0]), uuid=f[2], d=classify(p, now)))
            if time.monotonic() - last_print > 2:
                last_print = time.monotonic()
                print(f"\r  {time.monotonic() - start - 2:5.0f}s adverts={n['ble_adverts']:5d} "
                      f"OLF tokens: in raw adverts={n['ble_olf_v1']:4d}  in uuid rows={n['uuid_rows_olf_v1']:4d}   ",
                      end="", flush=True)
    os.close(fd)
    print()
    ok = Counter(t["d"] for t in tokens)
    if n["ble_olf_v1"] and not n["uuid_rows_olf_v1"]:
        verdict = "FIRMWARE: OLF tokens are in the raw advertisements but no uuid rows were printed"
    elif not n["ble_olf_v1"] and not n["uuid_rows_olf_v1"]:
        verdict = ("NO OLF TOKENS RECEIVED: the receiver works but heard no OLF advertisement; check the app "
                   "shows 'advertising: yes' in the foreground with the screen on, Bluetooth on, phone nearby")
    else:
        verdict = "RECEPTION OK: OLF tokens reached the serial output; any remaining fault is downstream"
    summary = dict(port=port, seconds=secs, utc_start=datetime.fromtimestamp(time.time() - secs, timezone.utc).isoformat(),
                   counts=dict(n), token_decisions_single_shot=dict(ok),
                   distinct_tokens=len({t["uuid"] for t in tokens}), verdict=verdict)
    json.dump(dict(summary=summary, olf_tokens=tokens), open(os.path.join(out_dir, "diag_reception.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 60))

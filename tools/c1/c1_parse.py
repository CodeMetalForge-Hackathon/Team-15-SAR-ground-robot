"""Strict evidence parsing for C1. No evidence source is inferred from content."""
import csv
import datetime as dt
import math
import uuid
from pathlib import Path


def canonical(value):
    parsed = str(uuid.UUID(value))
    if parsed != value.lower():
        raise ValueError("noncanonical 128-bit UUID")
    return parsed


def has_service(payload, identifier):
    """Match an AD structure, not an arbitrary substring of radio data."""
    data, expected = bytes.fromhex(payload), uuid.UUID(identifier).bytes[::-1]
    index, found = 0, False
    while index < len(data):
        length = data[index]
        if length == 0:
            return found
        end = index + length + 1
        if end > len(data):
            return False
        if data[index + 1] in (0x06, 0x07):
            values = data[index + 2:end]
            if len(values) % 16:
                return False
            found |= expected in [values[i:i + 16] for i in range(0, len(values), 16)]
        index = end
    return found


def load(path, minimum_s):
    result = dict(rows=[], raws=[], beats=[], bad=0, errors=[], start=None, end=None)
    previous = float("-inf")
    for line in Path(path).read_text().splitlines():
        try:
            if line.startswith("# capture_start_monotonic="):
                result['start'] = float(line.split("=", 1)[1].split()[0])
                continue
            if line.startswith("# capture_end_monotonic="):
                result['end'] = float(line.split("=", 1)[1])
                continue
            if line.startswith("#"):
                continue
            stamp, mono, text = line.split("\t", 2)
            mono = float(mono)
            when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if when.utcoffset() != dt.timedelta(0) or not math.isfinite(mono) or mono < previous:
                raise ValueError("bad capture timestamp")
            previous = mono
            if text.startswith("#HEARTBEAT,scanning=1,"):
                result['beats'].append(mono)
            elif text.startswith(("#SCAN_ERROR", "#SCAN_END", "#HEARTBEAT,scanning=0")):
                result['errors'].append(text)
            elif text.startswith("#RAW,"):
                _, payload, identifier = text.split(",")
                identifier = canonical(identifier)
                bytes.fromhex(payload)
                result['raws'].append((mono, payload, identifier))
            elif text and not text.startswith("#"):
                rssi, name, identifier = next(csv.reader([text]))
                rssi = int(rssi)
                if not -127 <= rssi <= 20:
                    raise ValueError("invalid RSSI")
                result['rows'].append(dict(t=when.timestamp(), mono=mono, rssi=rssi,
                                           name=name, uuid=canonical(identifier)))
        except (ValueError, TypeError, OverflowError):
            result['bad'] += 1
    start, end = result['start'], result['end']
    result['duration_s'] = None if start is None or end is None else end - start
    good = start is not None and end is not None and all(map(math.isfinite, (start, end)))
    good = good and end - start >= minimum_s - 0.1 and result['bad'] == 0 and not result['errors']
    if good:
        beats = [start] + result['beats'] + [end]
        good = bool(result['beats']) and all(0 <= b - a <= 5 for a, b in zip(beats, beats[1:]))
        good = good and all(start <= r['mono'] <= end for r in result['rows'])
        good = good and all(start <= m <= end for m, _, _ in result['raws'])
    result['capture_valid'] = bool(good)
    return result

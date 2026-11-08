"""Grade C1 captures; fixture tests are SOFTWARE ONLY, never hardware proof.

Usage: python3 tools/c1/analyze_c1.py RUN_DIR
A failed/incomplete experiment exits nonzero. Video/build gates are separate.
"""
import hashlib
import hmac
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c1_parse import has_service, load

DOMAIN, KEY = b"OLF/BLE-ID/v1", bytes(range(32))  # PUBLIC SYNTHETIC TEST KEY
A1 = "01010390-83cc-c438-cfa7-043609b9d1c4"


def tag(identifier):
    data = bytes.fromhex(identifier.replace("-", ""))
    expected = hmac.new(KEY, DOMAIN + data[:6], hashlib.sha256).digest()[:10]
    return hmac.compare_digest(expected, data[6:]), int.from_bytes(data[2:6], "big")


def matched_raw(row, capture):
    return any(identifier == row['uuid'] and 0 <= mono - row['mono'] <= 1
               and has_service(payload, identifier)
               for mono, payload, identifier in capture['raws'])


def assess(directory):
    results = {}
    for stage, seconds in [('A_stopped', 30), ('B_static', 60), ('C_rotating', 120)]:
        capture = load(Path(directory) / f"capture_{stage}.tsv", seconds)
        ours = [r for r in capture['rows'] if r['uuid'].startswith('0101')]
        result = dict(capture_valid=capture['capture_valid'], duration_s=capture['duration_s'],
                      rows_ours=len(ours), malformed_lines=capture['bad'], scan_errors=capture['errors'])
        if stage == 'A_stopped':
            raw_ours = any(identifier.startswith('0101') and has_service(payload, identifier)
                           for _, payload, identifier in capture['raws'])
            passed = not ours and not raw_ours
        elif stage == 'B_static':
            exact = [r for r in ours if r['uuid'] == A1 and not r['name']]
            result['exact_A1_rows'] = len(exact)
            passed = bool(exact) and len(exact) == len(ours) and any(matched_raw(r, capture) for r in exact)
        else:
            counters, rejected, raw_count = set(), 0, 0
            for row in ours:
                valid, counter = tag(row['uuid'])
                # A batch of cached previous/current/next tokens is not rotation.
                # Require each counted token in its own host time window.
                if not valid or abs(counter - int(row['t'] // 30)) > 1 or row['name']:
                    rejected += 1
                    continue
                if counter == int(row['t'] // 30) and matched_raw(row, capture):
                    counters.add(counter)
                    raw_count += 1
            ordered = sorted(counters)
            longest = run = 1 if ordered else 0
            for first, second in zip(ordered, ordered[1:]):
                run = run + 1 if second == first + 1 else 1
                longest = max(longest, run)
            result.update(current_window_counters=ordered, longest_consecutive_run=longest,
                          rejected_rows=rejected, current_rows_with_raw=raw_count)
            passed = longest >= 3 and rejected == 0
        result['pass'] = bool(passed and capture['capture_valid'])
        results[stage] = result
    results['C1_E1_capture_pass'] = all(r['pass'] for r in results.values())
    results['limitation'] = 'Capture checks only; provenance, phone state, builds, and video need separate review.'
    return results


def main(directory):
    try:
        results = assess(directory)
    except (OSError, ValueError) as exc:
        results = dict(C1_E1_capture_pass=False, error=str(exc))
    (Path(directory) / 'c1_analysis.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
    return 0 if results['C1_E1_capture_pass'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))

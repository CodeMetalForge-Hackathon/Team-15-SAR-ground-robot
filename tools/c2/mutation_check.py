"""C2 mutation check: deliberately break the verifier/state code in a throwaway
copy and confirm the test suite fails for every break. Evidence tooling only.

    python3 -I tools/c2/mutation_check.py REPO_ROOT WORKDIR
"""
import shutil
import subprocess
import sys
from pathlib import Path

MUTANTS = [
    ("M1 skip HMAC tag check", "ble_verify.py",
     "if not hmac.compare_digest(", "if False and not hmac.compare_digest("),
    ("M2 skip high-water (replay) check", "ble_verify.py",
     "if high is not None and counter <= high:", "if False:"),
    ("M3 accept tokens two windows old", "ble_verify.py",
     "if counter < current - 1:", "if counter < current - 2:"),
    ("M4 accept tokens two windows ahead", "ble_verify.py",
     "if counter > current + 1:", "if counter > current + 2:"),
    ("M5 allow an exact duplicate", "ble_verify.py",
     "counter <= high:", "counter < high:"),
    ("M6 mutate caller's state in place", "ble_verify.py",
     "nxt = dict(seen)", "nxt = seen"),
    ("M7 accept reserved alias 0", "ble_verify.py",
     "if alias == 0:", "if False:"),
    ("M8 state: ignore checksum", "ble_state.py",
     "digest != hashlib.sha256(_canonical(scope, high)).hexdigest()", "False"),
    ("M9 state: treat missing file as empty", "ble_state.py",
     'raise StateError(f"replay state missing:', 'return MappingProxyType({}); raise StateError(f"'),
    ("M10 state: init may overwrite existing", "ble_state.py",
     "if os.path.lexists(path):", "if False:"),
]


def run(repo, work):
    rows = []
    for name, fname, old, new in MUTANTS:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        for f in ("ble_verify.py", "ble_state.py"):
            shutil.copy2(repo / f, work / f)
        shutil.copytree(repo / "tests", work / "tests")
        (work / "evidence" / "c0-20261107T1914Z").mkdir(parents=True)
        shutil.copy2(repo / "evidence/c0-20261107T1914Z/protocol_vectors_v1.json",
                     work / "evidence/c0-20261107T1914Z/protocol_vectors_v1.json")
        src = (work / fname).read_text()
        assert src.count(old) == 1, f"{name}: pattern not found exactly once"
        (work / fname).write_text(src.replace(old, new))
        r = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            "tests"], cwd=work, capture_output=True, text=True)
        summary = [l for l in r.stdout.splitlines() if " passed" in l or " failed" in l or "error" in l]
        caught = r.returncode != 0
        rows.append((name, caught, summary[-1] if summary else r.stdout[-200:]))
        print(f"{'CAUGHT ' if caught else 'MISSED '} {name}: {rows[-1][2]}")
    shutil.rmtree(work)
    missed = [r for r in rows if not r[1]]
    print(f"\n{len(rows) - len(missed)}/{len(rows)} mutants caught")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(run(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))

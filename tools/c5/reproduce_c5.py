"""Zero-dependency C5 clean-checkout reproduction and evidence audit (<150 lines).

    python3 -B tools/c5/reproduce_c5.py [OUT_JSON]

Runs from any clean checkout with only the Python 3.10+ standard library:
  1. Line-count audit (<150 lines for handwritten BLE-ID modules/scripts/tests).
  2. Full unit/property/vector/state/ownership/ignore/C4/discovery test suite.
  3. C1 analyzer/capture unit tests (12) + C1 real-hardware pass & attempt-1 fail grading.
  4. C2 1,200-trial E0 deterministic software experiment.
  5. C4 real-hardware TSV verifier replay and 70 s aging/recovery verification.
  6. SHA-256 manifest audit across docs/ble-id/runs/* and C0 vector checksum check.
  7. Relative markdown link audit across README.md, discovery/README.md, and run reports.
"""
from __future__ import annotations

import contextlib, hashlib, importlib.util, inspect, json, pathlib, re, shutil, socket, subprocess, sys, tempfile, types, unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

HANDWRITTEN_150 = [
    "ble_id.py", "ble_keys.py", "ble_owner.py", "ble_sim.py", "ble_state.py", "ble_verify.py",
    "discovery/beacons.py", "discovery/static/app.js", "discovery/static/beacons.js",
    "firmware/esp32_scanner/esp32_scanner.ino", "ios/BeaconC1/BeaconC1/Advertiser.swift",
    "ios/BeaconC1/BeaconC1/BeaconC1App.swift", "ios/BeaconC1/BeaconC1/Token.swift",
    "tools/c3/native_macos_check.sh", "tools/c4/c4_analyze.py", "tools/c4/run_c4.py",
    "tools/c5/reproduce_c5.py", "tests/conftest.py", "tests/test_ble_c3_integration.py",
    "tests/test_ble_id_monitor.py", "tests/test_ble_keys.py", "tests/test_ble_state.py",
    "tests/test_ble_state_ownership.py", "tests/test_ble_verify_properties.py",
    "tests/test_ble_verify_vectors.py", "tests/test_c4_analyze.py", "tests/test_discovery.py",
    "tests/test_repo_ignores.py",
]


def _can_bind_loopback() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False


def _install_pytest_shim() -> None:
    if "pytest" in sys.modules: return
    m = types.ModuleType("pytest")
    @contextlib.contextmanager
    def raises(exc, match=None):
        info = types.SimpleNamespace(value=None)
        try: yield info
        except exc as e:
            info.value = e
            if match and not re.search(match, str(e)): raise AssertionError(f"{match!r} not in {e!r}")
            return
        raise AssertionError(f"DID NOT RAISE {exc}")
    class MP:
        def __init__(self): self._u = []
        def setattr(self, t, n, v): self._u.append((t, n, getattr(t, n))); setattr(t, n, v)
        def undo(self):
            for t, n, o in reversed(self._u): setattr(t, n, o)
    class Mark:
        @staticmethod
        def parametrize(names, vals, ids=None):
            ns = [x.strip() for x in names.split(",")] if isinstance(names, str) else list(names)
            return lambda fn: setattr(fn, "_params", getattr(fn, "_params", []) + [(ns, list(vals))]) or fn
        @staticmethod
        def skipif(cond, reason=""):
            return lambda fn: (setattr(fn, "_skip", reason) or fn) if cond else fn
    m.raises, m.MonkeyPatch, m.mark = raises, MP, Mark()
    m.fixture = lambda fn=None, **_k: (lambda f: setattr(f, "_fix", True) or f) if fn is None else (setattr(fn, "_fix", True) or fn)
    sys.modules["pytest"] = m


def run_all_tests() -> dict:
    _install_pytest_shim()
    import pytest, conftest as cmod
    can_bind = _can_bind_loopback()
    base_fix = {k: v for k, v in vars(cmod).items() if getattr(v, "_fix", False)}
    passed = failed = skipped_socket = 0
    for f in sorted((ROOT / "tests").glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(f.stem, f)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        fix = {**base_fix, **{k: v for k, v in vars(mod).items() if getattr(v, "_fix", False)}}
        for name, obj in list(vars(mod).items()):
            if inspect.isclass(obj) and issubclass(obj, unittest.TestCase):
                for case in unittest.defaultTestLoader.loadTestsFromTestCase(obj):
                    if not can_bind and "http" in case._testMethodName:
                        skipped_socket += 1; continue
                    res = unittest.TestResult(); case.run(res)
                    passed += res.wasSuccessful(); failed += not res.wasSuccessful()
            elif inspect.isfunction(obj) and name.startswith("test_"):
                if not can_bind and "stack" in inspect.signature(obj).parameters:
                    skipped_socket += 1; continue
                combos = [{}]
                for ns, vals in reversed(getattr(obj, "_params", [])):
                    combos = [{**b, **(dict(zip(ns, v)) if len(ns) > 1 else {ns[0]: v})} for b in combos for v in vals]
                for pkw in combos:
                    with contextlib.ExitStack() as st:
                        cache = {"tmp_path": pathlib.Path(st.enter_context(tempfile.TemporaryDirectory()))}
                        def res_arg(a):
                            if a in pkw: return pkw[a]
                            if a in cache: return cache[a]
                            if a == "monkeypatch":
                                mp_i = pytest.MonkeyPatch(); st.callback(mp_i.undo); cache[a] = mp_i; return mp_i
                            ff = fix[a]; fa = [res_arg(x) for x in inspect.signature(ff).parameters]
                            val = next(g := ff(*fa)) if inspect.isgeneratorfunction(ff) else ff(*fa)
                            if inspect.isgeneratorfunction(ff): st.callback(lambda g=g: next(g, None))
                            cache[a] = val; return val
                        obj(**{a: res_arg(a) for a in inspect.signature(obj).parameters})
                        passed += 1
    return {"passed": passed, "failed": failed, "skipped_loopback_socket_in_sandbox": skipped_socket}


def audit_repo() -> dict:
    lines = {p: len((ROOT / p).read_text().splitlines()) for p in HANDWRITTEN_150}
    over_150 = {p: n for p, n in lines.items() if n >= 150}
    c1_unit = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tools/c1", "-p", "test_*.py"], cwd=ROOT, capture_output=True)
    from tools.c1.analyze_c1 import assess as assess_c1
    c1_dir = ROOT / "docs/ble-id/runs/c1-capture-20261107T202438Z"
    c1_pass = assess_c1(c1_dir)["C1_E1_capture_pass"]
    with tempfile.TemporaryDirectory() as td:
        for fn in ("capture_A_stopped.tsv", "capture_B_static.tsv"): shutil.copy2(c1_dir / fn, pathlib.Path(td) / fn)
        shutil.copy2(c1_dir / "attempt1_capture_C_rotating.tsv", pathlib.Path(td) / "capture_C_rotating.tsv")
        c1_attempt1_fails = not assess_c1(td)["C1_E1_capture_pass"]
        e0 = subprocess.run([sys.executable, "-I", "-B", "tools/c2/e0_experiment.py", ".", f"{td}/e0", "100"], cwd=ROOT, capture_output=True)
        from tools.c4.run_c4 import run_baseline
        run_baseline(pathlib.Path(td) / "c4")
        c4_ok = json.loads((pathlib.Path(td) / "c4/c1_verifier_replay.json").read_text())["C_rotating_retry"]["verified_windows"] == 5
    bad_hashes = [str((mf.parent / rel.strip()).relative_to(ROOT)) for mf in sorted((ROOT / "docs/ble-id/runs").glob("*/MANIFEST.sha256"))
                  for raw in mf.read_text().splitlines() if raw.strip() for h, rel in [raw.split(None, 1)]
                  if not (mf.parent / rel.strip()).is_file() or hashlib.sha256((mf.parent / rel.strip()).read_bytes()).hexdigest() != h]
    bad_links = [f"{md.relative_to(ROOT)} -> {m.group(1)}" for md in [ROOT / "README.md", ROOT / "discovery/README.md", *sorted((ROOT / "docs/ble-id/runs").glob("*/*.md"))]
                 for m in re.finditer(r"\[[^\]]+\]\(([^)#]+)\)", md.read_text()) if not m.group(1).startswith(("http://", "https://", "mailto:")) and not (md.parent / m.group(1)).exists()]
    vec_sha = hashlib.sha256((ROOT / "evidence/c0-20261107T1914Z/protocol_vectors_v1.json").read_bytes()).hexdigest()
    tests = run_all_tests()
    ok = (not over_150 and tests["failed"] == 0 and c1_unit.returncode == 0 and c1_pass and c1_attempt1_fails
          and e0.returncode == 0 and c4_ok and not bad_hashes and not bad_links
          and vec_sha == "27a27820be4f1983d82770bd794ff7bf7aa86dc8fc8d39278a472df5c8e35ef7")
    return {"all_reproducible_checks_pass": ok, "max_handwritten_lines": max(lines.values()), "over_150_lines": over_150,
            "tests": tests, "c1_unittest_exit": c1_unit.returncode, "c1_retry_grades_pass": c1_pass,
            "c1_attempt1_grades_fail": c1_attempt1_fails, "c2_e0_exit": e0.returncode,
            "c4_c1_rotating_verified_windows": 5 if c4_ok else 0, "bad_manifest_hashes": bad_hashes, "broken_markdown_links": bad_links}


if __name__ == "__main__":
    res = audit_repo()
    if len(sys.argv) > 1: pathlib.Path(sys.argv[1]).write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["all_reproducible_checks_pass"] else 1)

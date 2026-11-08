"""Qwen LiDAR advisory contract: deterministic policy on SIMULATED fixtures, guard, and the never-raising client."""
import json
import time
from pathlib import Path

import pytest

from qwen_advisory import lidar as L
from qwen_advisory.client import lidar_advisory

CASES = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "lidar_advisory_cases.json").read_text())


def test_fixtures_are_labelled_simulated():
    assert CASES["label"] == "SIMULATED" and CASES["hardware"] is False


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["case"] for c in CASES["cases"]])
def test_deterministic_policy_matches_fixture(case):
    out = L.reference_policy(case["context"])
    assert out == case["expected"]
    assert out["association"] == "NOT_ESTABLISHED" and not L.schema_errors(out)


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["case"] for c in CASES["cases"]])
def test_unusable_or_blocked_lidar_never_allows_motion(case):
    out = L.reference_policy(case["context"])
    lf = L.lidar_facts(case["context"].get("lidar"))
    if lf["status"] != "USABLE" or lf["front"] != "CLEAR" or (lf.get("corridor") not in (None, "CLEAR")):
        assert out["forward_motion_recommendation"] != "OPERATOR_MAY_CONSIDER_BOUNDED_MOVE"


def test_guard_rejects_person_distance_and_overpermissive_motion():
    c = CASES["cases"][0]["context"]
    ref = L.reference_policy(c)
    assert any(x.startswith("person_distance") for x in L.guard(dict(ref, explanation="The person is 90 cm away."), c, set())["critical"])
    loose = dict(ref, forward_motion_recommendation="OPERATOR_MAY_CONSIDER_BOUNDED_MOVE")
    if ref["forward_motion_recommendation"] != "OPERATOR_MAY_CONSIDER_BOUNDED_MOVE":
        assert any("unsafe_motion" in x for x in L.guard(loose, c, set())["critical"])


def test_guard_allows_negated_statements():
    c = CASES["cases"][0]["context"]
    ref = dict(L.reference_policy(c), explanation="No person is confirmed; this is not a clear path.")
    assert not L.guard(ref, c, set())["critical"]


def test_client_without_model_is_deterministic():
    c = CASES["cases"][0]["context"]
    r = lidar_advisory(c)
    assert r["source"] == "DETERMINISTIC" and r["authority"] == "NONE" and r["advisory"] == L.reference_policy(c)


def test_client_falls_back_on_error_timeout_and_unsafe_output():
    c = CASES["cases"][0]["context"]
    ref = L.reference_policy(c)

    def boom(ctx):
        raise RuntimeError("down")

    def slow(ctx):
        time.sleep(2)
        return ref

    def unsafe(ctx):
        return dict(ref, explanation="Drive forward to the person, who is 90 cm away.")
    for model, t in ((boom, 1.0), (slow, 0.2), (unsafe, 1.0), (lambda ctx: ["not", "an", "object"], 1.0)):
        r = lidar_advisory(c, model=model, timeout_s=t)
        assert r["source"] == "DETERMINISTIC_FALLBACK" and r["advisory"] == ref


def test_client_accepts_valid_guarded_model_output():
    c = CASES["cases"][0]["context"]
    r = lidar_advisory(c, model=lambda ctx: L.reference_policy(ctx))
    assert r["source"] == "QWEN_GUARDED"


def test_malformed_lidar_context_is_fault_not_clear():
    assert L.lidar_facts({"schema": "team15.lidar_advisory_context/1", "sectors": []})["status"] == "DISCONNECTED_OR_FAULT"

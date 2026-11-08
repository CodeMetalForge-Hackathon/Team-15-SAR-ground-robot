"""Audit: route total, remaining planned distance and distance actually driven are reported separately and stay consistent.

All planned values are SYNTHETIC graph metres. "traveled" is simulator ground truth (an odometer in
the sim world). It is never computed from the plan.
"""
import pytest

from planner.route import compute_route
from rover.simrun import scenario

TOL = 0.06  # node arrival tolerance (node_tol 0.05) plus one sim step


def sample(name, every_s=0.25):
    s = scenario(name)
    rows = []

    def until(sim):
        if round(sim.world.t / every_s, 6).is_integer():
            st = sim.nav.status()
            rows.append((sim.world.t, st["distances"], st["state"], len(st["reroutes"])))
        return False

    s.run(until=until) if False else None
    end = s.world.t + 1200
    while s.world.t < end and s.nav.running:
        s.nav.tick()
        s.world.step(s.driver.velocity)
        until(s)
    return s, rows


@pytest.mark.parametrize("name", list("ABCDEF"))
def test_completed_plus_remaining_equals_total(name):
    s, rows = sample(name)
    assert rows
    for t, d, state, _ in rows:
        if d["route_total_m"] is None or d["route_remaining_m"] is None:
            continue
        if d["retreating_to"] is None:
            assert d["route_completed_m"] + d["route_remaining_m"] == pytest.approx(d["route_total_m"], abs=1e-6), t
            assert -TOL <= d["route_remaining_m"] <= d["route_total_m"] + TOL, t
        else:
            assert d["route_completed_m"] is None   # not part of the current route while retreating
        assert d["traveled"]["kind"] == "SIMULATED_GROUND_TRUTH"


@pytest.mark.parametrize("name", list("BCD"))
def test_remaining_only_increases_at_a_reroute(name):
    s, rows = sample(name)
    prev = None
    for t, d, state, n_rr in rows:
        rem = d["route_remaining_m"]
        if rem is None:
            continue
        if prev is not None and n_rr == prev[1]:
            assert rem <= prev[0] + 1e-6, (t, rem, prev)
        prev = (rem, n_rr)


def test_retreat_remaining_is_distance_back_plus_new_route():
    s, rows = sample("C")
    retreat = [d for _, d, _, _ in rows if d["retreating_to"] == "D"]
    assert retreat, "expected samples during the retreat"
    for d in retreat:
        assert 46 <= d["route_remaining_m"] <= 46 + 4.0 + TOL


EXPECTED_DRIVEN = {
    # scenario: (synthetic metres actually driven) = completed edges + retreats out and back
    "A": 60,
    "B": 30 + 2 * 4.0 + 46,
    "C": 30 + 2 * 4.0 + 46,
    "D": 30 + 2 * 4.0 + 2 * 2.0 + 64,
    "E": 30 + 2 * 4.0 + 12 + 10 + 10 + 5.0,   # no route left: safe-stops 5 m into M-G, no retreat
    "F": 30,
}


@pytest.mark.parametrize("name", list(EXPECTED_DRIVEN))
def test_traveled_matches_independent_hand_count(name):
    s, _ = sample(name)
    st = s.nav.status()
    assert st["distances"]["traveled"]["value_m"] == pytest.approx(EXPECTED_DRIVEN[name], abs=0.5)


@pytest.mark.parametrize("name,original,final", [("A", 60, 60), ("C", 60, 46), ("D", 60, 64), ("F", 30, 30)])
def test_original_and_final_route_lengths_from_dijkstra(name, original, final):
    s, _ = sample(name)
    d = s.nav.status()["distances"]
    assert d["original_route_m"] == original and d["route_total_m"] == final
    assert d["route_remaining_m"] == 0 and d["route_completed_m"] == final
    start = s.nav.route.path[0]
    assert compute_route(start, "G", blocked=s.log.blocked_edges()).length_m == final


def test_driven_differs_from_plan_when_rerouted():
    """The detour drives more than either plan length. The fields must not be merged or derived from each other."""
    s, _ = sample("C")
    d = s.nav.status()["distances"]
    assert d["traveled"]["value_m"] > d["original_route_m"] > d["route_total_m"]

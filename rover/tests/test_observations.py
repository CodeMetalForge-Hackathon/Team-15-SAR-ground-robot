"""Incremental map: freshness, dynamic obstacles, human review, independent clearing, viewpoints."""
import pytest

from planner.graph import load_graph
from rover.observations import (CONFIRMED, REJECTED, UNCONFIRMED, ObservationLog, canonical_edge,
                                suggest_viewpoints)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def log():
    c = Clock()
    lg = ObservationLog(c, dynamic_ttl_s=30, recheck_after_s=300)
    lg.c = c
    return lg


def test_canonical_edge():
    assert canonical_edge("K-J") == "J-K" == canonical_edge(("J", "K"))


def test_static_confirmed_blocks_until_cleared_and_goes_stale_not_clear(log):
    log.add("ultrasonic_obstacle", "sim-ultrasonic", CONFIRMED, dynamic=False, edge="E-D")
    assert log.blocked_edges() == ["D-E"]
    log.c.t = 1000
    assert log.blocked_edges() == ["D-E"]            # old static blocks stay conservative...
    assert log.blockers()[0]["stale"] is True        # ...but are flagged for a re-check


def test_dynamic_obstacle_expires_to_stale(log):
    log.add("camera_person", "cam", CONFIRMED, dynamic=True, edge="C-D")
    assert log.blocked_edges() == ["C-D"]
    log.c.t = 31
    assert log.blocked_edges() == []
    assert log.edge_status("C-D") == "STALE"         # not "clear": nobody has looked again


def test_unconfirmed_never_blocks_and_review_flow(log):
    o = log.add("camera_person", "cam", UNCONFIRMED, dynamic=True, edge="C-D")
    assert log.blocked_edges() == [] and log.edge_status("C-D") == "UNCONFIRMED_HAZARD"
    with pytest.raises(PermissionError):
        log.review(o.obs_id, "", True)
    log.c.t = 10
    log.review(o.obs_id, "op", True)
    assert o.status == CONFIRMED and o.t == 10 and log.blocked_edges() == ["C-D"]
    o2 = log.add("camera_person", "cam", UNCONFIRMED, dynamic=True, edge="A-B")
    log.review(o2.obs_id, "op", False)
    assert o2.status == REJECTED and "A-B" not in log.blocked_edges()


def test_clear_needs_independent_source(log):
    log.add("ultrasonic_obstacle", "grove", CONFIRMED, dynamic=False, edge="D-E")
    with pytest.raises(PermissionError):
        log.clear_edge("D-E", "grove", "op", "same sensor again")
    with pytest.raises(ValueError):
        log.clear_edge("A-B", "cam", "op", "not blocked")
    log.clear_edge("D-E", "cam", "op", "fresh frame")
    assert log.blocked_edges() == [] and log.edge_status("D-E") == "CLEAR_OBSERVED"


def test_suggest_viewpoints_reachable_and_excludes_blocked(log):
    g = load_graph()
    log.add("ultrasonic_obstacle", "grove", CONFIRMED, dynamic=False, edge="D-E")
    vps = suggest_viewpoints(g, log, "A", k=50)
    nodes = {v["node"] for v in vps}
    assert "Q" not in nodes                           # unreachable: no edges
    assert all(v["route_m"] is not None for v in vps)
    e = next(v for v in vps if v["node"] == "E")      # reachable only the long way round, via G
    assert e["path"] == list("ABCJKLMGFE") and e["route_m"] == 94

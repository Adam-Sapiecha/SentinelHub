import networkx as nx
import pytest
from shapely.geometry import LineString

from src.core.router import EvacRouter, SnapDistanceExceededError


def _graph() -> nx.Graph:
    graph = nx.Graph()
    first = (52.0, 21.0)
    second = (52.0, 21.001)
    graph.add_edge(
        first,
        second,
        length_m=123.0,
        geometry=LineString([(first[1], first[0]), (second[1], second[0])]),
        blocked=False,
    )
    return graph


def test_router_returns_length_sum_and_measured_metadata():
    result = EvacRouter(_graph()).find_route((52.0, 21.0), (52.0, 21.001))

    assert result is not None
    _, metadata = result
    assert metadata["length_m"] == 123.0
    assert metadata["segments"] == 1
    assert metadata["calc_time_ms"] >= 0


def test_router_handles_start_and_end_on_same_node():
    result = EvacRouter(_graph()).find_route((52.0, 21.0), (52.0, 21.0))

    assert result is not None
    route, metadata = result
    assert len(route.coords) == 2
    assert metadata["length_m"] == 0
    assert metadata["segments"] == 0


def test_router_rejects_point_too_far_from_graph():
    with pytest.raises(SnapDistanceExceededError):
        EvacRouter(_graph(), max_snap_distance_m=100).find_route(
            (50.0, 20.0),
            (52.0, 21.001),
        )


def test_router_returns_none_when_every_edge_is_blocked():
    graph = _graph()
    graph.edges[(52.0, 21.0), (52.0, 21.001)]["blocked"] = True
    assert EvacRouter(graph).find_route((52.0, 21.0), (52.0, 21.001)) is None


def test_router_never_snaps_away_from_an_origin_isolated_by_flood():
    graph = _graph()
    first, second, third = (52.0, 21.0), (52.0, 21.001), (52.0, 21.002)
    graph.edges[first, second]["blocked"] = True
    graph.add_edge(second, third, length_m=100, blocked=False)
    assert EvacRouter(graph).find_route(first, third) is None

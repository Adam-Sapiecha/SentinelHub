import networkx as nx
import pytest
from shapely.geometry import LineString, Polygon

import src.core.flood_intersector as flood_intersector
from src.core.flood_intersector import FloodDataUnavailableError, mark_blocked_edges
from src.core.io_utils import write_json_atomic


def test_mark_blocked_edges_blocks_when_overlap_large_enough():
    G = nx.Graph()

    a = (0.0, 0.0)
    b = (0.0, 10.0)

    G.add_node(a)
    G.add_node(b)

    # krawędź jako linia od lon=0 do lon=10 na lat=0
    geom = LineString([(0.0, 0.0), (10.0, 0.0)])
    G.add_edge(a, b, geometry=geom, blocked=False, length_m=1000)

    # flood przecina ~60% długości
    flood_poly = Polygon([(2.0, -1.0), (8.0, -1.0), (8.0, 1.0), (2.0, 1.0)])

    blocked = mark_blocked_edges(G, [flood_poly], min_overlap_ratio=0.2)

    assert blocked == 1
    assert G.edges[a, b]["blocked"] is True


def test_mark_blocked_edges_does_not_block_when_overlap_too_small():
    G = nx.Graph()

    a = (0.0, 0.0)
    b = (0.0, 10.0)

    geom = LineString([(0.0, 0.0), (10.0, 0.0)])
    G.add_edge(a, b, geometry=geom, blocked=False, length_m=1000)

    # flood przecina malutki kawałek ~5%
    flood_poly = Polygon([(0.0, -1.0), (0.5, -1.0), (0.5, 1.0), (0.0, 1.0)])
    blocked = mark_blocked_edges(G, [flood_poly], min_overlap_ratio=0.2)

    assert blocked == 0
    assert G.edges[a, b]["blocked"] is False


def test_mark_blocked_edges_combines_overlap_from_multiple_polygons():
    graph = nx.Graph()
    first = (0.0, 0.0)
    second = (0.0, 10.0)
    graph.add_edge(
        first,
        second,
        geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
        blocked=False,
    )
    flood_data = [
        Polygon([(1, -1), (2.5, -1), (2.5, 1), (1, 1)]),
        Polygon([(7.5, -1), (9, -1), (9, 1), (7.5, 1)]),
    ]

    assert mark_blocked_edges(graph, flood_data, min_overlap_ratio=0.2) == 1


def test_mark_blocked_edges_rejects_non_wgs84_geojson(tmp_path):
    path = tmp_path / "flood.geojson"
    write_json_atomic(
        path,
        {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [],
        },
    )
    with pytest.raises(FloodDataUnavailableError):
        mark_blocked_edges(nx.Graph(), path)


def test_mark_blocked_edges_fails_closed_for_missing_file(tmp_path):
    with pytest.raises(FloodDataUnavailableError):
        mark_blocked_edges(nx.Graph(), tmp_path / "missing.geojson")


@pytest.mark.parametrize("ratio", [-0.1, 1.1])
def test_mark_blocked_edges_validates_overlap_ratio(ratio):
    with pytest.raises(ValueError):
        mark_blocked_edges(
            nx.Graph(),
            [],
            min_overlap_ratio=ratio,
        )


def test_mark_blocked_edges_falls_back_when_spatial_index_is_unavailable(monkeypatch):
    graph = nx.Graph()
    first = (0.0, 0.0)
    second = (0.0, 10.0)
    graph.add_edge(
        first,
        second,
        geometry=LineString([(0.0, 0.0), (10.0, 0.0)]),
        blocked=False,
    )

    def unavailable_index(_):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(flood_intersector, "STRtree", unavailable_index)
    polygon = Polygon([(2, -1), (8, -1), (8, 1), (2, 1)])
    assert mark_blocked_edges(graph, [polygon], min_overlap_ratio=0.2) == 1


def test_bidirectional_edges_count_as_one_physical_blocked_segment():
    graph = nx.MultiDiGraph()
    first = (0.0, 0.0)
    second = (0.0, 10.0)
    forward = LineString([(0.0, 0.0), (10.0, 0.0)])
    graph.add_edge(first, second, geometry=forward, blocked=False)
    graph.add_edge(
        second,
        first,
        geometry=LineString(list(forward.coords)[::-1]),
        blocked=False,
    )
    polygon = Polygon([(2, -1), (8, -1), (8, 1), (2, 1)])

    assert mark_blocked_edges(graph, [polygon], min_overlap_ratio=0.2) == 1
    assert all(data["blocked"] for _, _, data in graph.edges(data=True))


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"type": "FeatureCollection"},
        {"type": "FeatureCollection", "features": None},
        {"type": "FeatureCollection", "features": [None]},
        {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None}]},
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[21, 52], [21.1, 52]]},
                }
            ],
        },
        {"type": "FeatureCollection", "features": [], "crs": "EPSG:3857"},
    ],
)
def test_malformed_flood_never_means_no_flood(tmp_path, payload):
    path = tmp_path / "flood.geojson"
    write_json_atomic(path, payload)
    with pytest.raises(FloodDataUnavailableError):
        mark_blocked_edges(nx.Graph(), path)


def test_flood_outside_wgs84_fails_closed():
    with pytest.raises(FloodDataUnavailableError):
        mark_blocked_edges(nx.Graph(), [Polygon([(200, 52), (201, 52), (201, 53)])])

import pytest

from src.core.graph_builder import RoadGraphBuilder
from src.core.osm_to_geojson import osm_to_roads_geojson


def test_osm_oneway_is_preserved_in_directed_graph():
    osm = """
    <osm>
      <node id="1" lat="52.0" lon="21.0" />
      <node id="2" lat="52.0" lon="21.001" />
      <way id="10">
        <nd ref="1"/><nd ref="2"/>
        <tag k="highway" v="residential"/><tag k="oneway" v="yes"/>
      </way>
    </osm>
    """
    graph = RoadGraphBuilder.from_geojson(osm_to_roads_geojson(osm)).build_graph()

    assert graph.has_edge(("osm", "1"), ("osm", "2"))
    assert not graph.has_edge(("osm", "2"), ("osm", "1"))


def test_distinct_osm_nodes_at_same_coordinates_are_not_merged():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "highway": "residential",
                    "osm_node_ids": ["bridge-a", "bridge-b"],
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.001, 52.001]],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "highway": "residential",
                    "osm_node_ids": ["ground-a", "ground-b"],
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [20.999, 52.001]],
                },
            },
        ],
    }

    graph = RoadGraphBuilder.from_geojson(geojson).build_graph()
    assert graph.number_of_nodes() == 4


def test_non_drivable_and_private_ways_are_excluded():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"highway": "footway"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.001, 52.0]],
                },
            },
            {
                "type": "Feature",
                "properties": {"highway": "service", "access": "private"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.1], [21.001, 52.1]],
                },
            },
        ],
    }
    assert RoadGraphBuilder.from_geojson(geojson).build_graph().number_of_edges() == 0


def test_missing_osm_node_does_not_create_edge_across_gap():
    osm = """
    <osm>
      <node id="1" lat="52.0" lon="21.0" />
      <node id="2" lat="52.0" lon="21.002" />
      <way id="10">
        <nd ref="1"/><nd ref="missing"/><nd ref="2"/>
        <tag k="highway" v="residential"/>
      </way>
    </osm>
    """
    geojson = osm_to_roads_geojson(osm)
    assert geojson["features"] == []


@pytest.mark.parametrize("oneway,forward,reverse", [("no", True, True), ("-1", False, True)])
def test_roundabout_respects_explicit_oneway(oneway, forward, reverse):
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "highway": "residential",
                    "junction": "roundabout",
                    "oneway": oneway,
                },
                "geometry": {"type": "LineString", "coordinates": [[21, 52], [21.001, 52]]},
            }
        ],
    }
    graph = RoadGraphBuilder.from_geojson(geojson).build_graph()
    a, b = ("coord", 21, 52), ("coord", 21.001, 52)
    assert graph.has_edge(a, b) is forward
    assert graph.has_edge(b, a) is reverse

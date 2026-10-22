import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import networkx as nx
from shapely.geometry import LineString, shape

from .utils import haversine_distance_m

NON_DRIVABLE_HIGHWAYS = {
    "bridleway",
    "construction",
    "corridor",
    "cycleway",
    "footway",
    "path",
    "pedestrian",
    "proposed",
    "raceway",
    "steps",
}
RESTRICTED_ACCESS = {"no", "private"}
ONEWAY_FORWARD = {"1", "true", "yes"}
ONEWAY_REVERSE = {"-1", "reverse"}


def _is_drivable(properties: Mapping[str, Any]) -> bool:
    highway = str(properties.get("highway", "")).lower()
    if highway in NON_DRIVABLE_HIGHWAYS:
        return False

    for key in ("motorcar", "motor_vehicle", "vehicle", "access"):
        value = str(properties.get(key, "")).lower()
        if value in RESTRICTED_ACCESS:
            return False
        if value in {"yes", "designated", "permissive"}:
            return True
    return True


def _node_key(
    properties: Mapping[str, Any],
    coordinate_index: int,
    longitude: float,
    latitude: float,
) -> tuple[str, str] | tuple[str, float, float]:
    osm_node_ids = properties.get("osm_node_ids")
    if isinstance(osm_node_ids, list) and coordinate_index < len(osm_node_ids):
        return "osm", str(osm_node_ids[coordinate_index])
    return "coord", round(longitude, 7), round(latitude, 7)


def _add_linestring_to_graph(
    graph: nx.MultiDiGraph,
    line: LineString,
    properties: Mapping[str, Any] | None = None,
) -> None:
    """Add a road as directed segments while retaining relevant OSM metadata."""
    properties = properties or {}
    coordinates = list(line.coords)
    if len(coordinates) < 2 or not _is_drivable(properties):
        return

    oneway = str(properties.get("oneway", "")).lower()
    is_roundabout = str(properties.get("junction", "")).lower() == "roundabout"
    add_forward = oneway not in ONEWAY_REVERSE
    add_reverse = oneway not in ONEWAY_FORWARD and (
        not is_roundabout or oneway in {"no", "0", "false"} or oneway in ONEWAY_REVERSE
    )

    edge_metadata = {
        "highway": properties.get("highway"),
        "name": properties.get("name"),
        "osm_way_id": properties.get("osm_way_id"),
    }

    for index, (first, second) in enumerate(zip(coordinates, coordinates[1:], strict=False)):
        lon1, lat1 = first[:2]
        lon2, lat2 = second[:2]
        first_node = _node_key(properties, index, lon1, lat1)
        second_node = _node_key(properties, index + 1, lon2, lat2)

        graph.add_node(first_node, lat=lat1, lon=lon1, pos=(lat1, lon1))
        graph.add_node(second_node, lat=lat2, lon=lon2, pos=(lat2, lon2))

        length_m = haversine_distance_m((lat1, lon1), (lat2, lon2))
        forward_geometry = LineString([(lon1, lat1), (lon2, lat2)])
        common = {"length_m": length_m, "blocked": False, **edge_metadata}

        if add_forward:
            graph.add_edge(
                first_node,
                second_node,
                geometry=forward_geometry,
                **common,
            )
        if add_reverse:
            graph.add_edge(
                second_node,
                first_node,
                geometry=LineString(list(forward_geometry.coords)[::-1]),
                **common,
            )


class RoadGraphBuilder:
    """Build a driving graph from a GeoJSON file or an in-memory mapping."""

    def __init__(self, source: Path | Mapping[str, Any]):
        self.source = source

    @classmethod
    def from_geojson(cls, geojson: Mapping[str, Any]) -> "RoadGraphBuilder":
        return cls(geojson)

    def _load_geojson(self) -> Mapping[str, Any]:
        if isinstance(self.source, Path):
            if not self.source.exists():
                return {"type": "FeatureCollection", "features": []}
            with self.source.open("r", encoding="utf-8") as stream:
                return json.load(stream)
        return self.source

    def build_graph(self) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph()
        data = self._load_geojson()
        if data.get("type") != "FeatureCollection":
            raise ValueError("Road data must be a GeoJSON FeatureCollection")

        for feature in data.get("features", []):
            geometry_data = feature.get("geometry")
            if not geometry_data:
                continue

            geometry = shape(geometry_data)
            properties = feature.get("properties") or {}
            if isinstance(geometry, LineString):
                _add_linestring_to_graph(graph, geometry, properties)
            elif geometry.geom_type == "MultiLineString":
                for line in geometry.geoms:
                    _add_linestring_to_graph(graph, line, properties)

        return graph

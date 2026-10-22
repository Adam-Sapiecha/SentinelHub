"""Bounded, user-supplied GeoJSON processed by the real routing engine."""

import math
from time import perf_counter

from shapely import get_coordinates
from shapely.errors import GEOSException
from shapely.geometry import mapping, shape

from src.core.flood_intersector import load_flood_geometries, mark_blocked_edges
from src.core.graph_builder import RoadGraphBuilder
from src.core.router import EvacRouter
from src.services.demo_service import collection, feature, route_feature
from src.services.workspace_store import encode

MAX_DATASET_BYTES = 1024 * 1024
MAX_FEATURES = 500
MAX_COORDINATES = 10000
MAX_SEGMENTS = 2000


def roads_inside_coverage(roads: dict, bbox: tuple) -> dict:
    """Keep complete OSM segments inside WMS coverage, retaining node identities.

    Overpass returns whole ways extending beyond bbox. Boundary-crossing
    segments are dropped conservatively rather than given invented coverage.
    """
    south, west, north, east = bbox
    features = []
    for item in roads["features"]:
        coordinates = item["geometry"]["coordinates"]
        properties = item.get("properties") or {}
        ids = properties["osm_node_ids"]
        run, node_ids = [], []

        def append_run(run, node_ids, properties=properties):
            if len(run) >= 2:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": run},
                        "properties": {**properties, "osm_node_ids": node_ids},
                    }
                )

        for index, point in enumerate(coordinates):
            if west <= point[0] <= east and south <= point[1] <= north:
                run.append(point)
                node_ids.append(ids[index])
            else:
                append_run(run, node_ids)
                run, node_ids = [], []
        append_run(run, node_ids)
    return collection(features)


def validate_dataset(payload: dict, kind: str) -> dict:
    if len(encode(payload).encode()) > MAX_DATASET_BYTES:
        raise ValueError("Jeden zbiór danych nie może przekroczyć 1 MiB")
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("Wymagana kolekcja GeoJSON FeatureCollection z listą features")
    if len(payload["features"]) > MAX_FEATURES:
        raise ValueError("Limit 500 obiektów na zbiór")
    crs = payload.get("crs")
    if crs is not None:
        raise ValueError("Usuń deklarację CRS; wymagane RFC 7946 / WGS84 lon,lat")
    coordinates = 0
    segments = 0
    for item in payload["features"]:
        if not isinstance(item, dict) or item.get("type") != "Feature":
            raise ValueError("Nieprawidłowy Feature")
        geometry = item.get("geometry")
        allowed = (
            {"LineString", "MultiLineString"} if kind == "roads" else {"Polygon", "MultiPolygon"}
        )
        if not isinstance(geometry, dict) or geometry.get("type") not in allowed:
            raise ValueError(f"Nieprawidłowy typ geometrii dla {kind}")
        try:
            parsed = shape(geometry)
            if parsed.is_empty or not parsed.is_valid:
                raise ValueError("Geometria musi być niepusta i poprawna topologicznie")
            coords = get_coordinates(parsed)
            if kind == "roads":
                lines = [parsed] if parsed.geom_type == "LineString" else parsed.geoms
                segments += sum(len(line.coords) - 1 for line in lines)
                if segments > MAX_SEGMENTS:
                    raise ValueError("Limit 2000 fizycznych odcinków")
            coordinates += len(coords)
            if coordinates > MAX_COORDINATES:
                raise ValueError("Limit 10000 współrzędnych na zbiór")
            for longitude, latitude in coords:
                if not (
                    math.isfinite(longitude)
                    and math.isfinite(latitude)
                    and -180 <= longitude <= 180
                    and -90 <= latitude <= 90
                ):
                    raise ValueError("Współrzędne poza WGS84 lub niebędące liczbami skończonymi")
        except (GEOSException, TypeError, KeyError) as error:
            raise ValueError("Nieprawidłowa geometria GeoJSON") from error
        properties = item.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise ValueError("properties musi być obiektem lub null")
        if kind == "roads" and properties and "osm_node_ids" in properties:
            ids = properties["osm_node_ids"]
            if (
                geometry["type"] != "LineString"
                or not isinstance(ids, list)
                or len(ids) != len(coords)
            ):
                raise ValueError("osm_node_ids musi odpowiadać wszystkim wierzchołkom LineString")
            if any(not isinstance(value, (str, int)) or isinstance(value, bool) for value in ids):
                raise ValueError("Nieprawidłowe identyfikatory węzłów OSM")
    if kind == "roads":
        graph = RoadGraphBuilder.from_geojson(payload).build_graph()
        if graph.number_of_edges() == 0:
            raise ValueError("Brak przejezdnych odcinków drogowych")
        if graph.number_of_edges() > MAX_SEGMENTS * 2:
            raise ValueError("Limit 2000 fizycznych odcinków")
        bounds = [
            min(data["lon"] for _, data in graph.nodes(data=True)),
            min(data["lat"] for _, data in graph.nodes(data=True)),
            max(data["lon"] for _, data in graph.nodes(data=True)),
            max(data["lat"] for _, data in graph.nodes(data=True)),
        ]
        # Restrict expensive inputs to a local area, including sparse datasets.
        if bounds[2] - bounds[0] > 0.5 or bounds[3] - bounds[1] > 0.5:
            raise ValueError("Zakres sieci nie może przekraczać 0,5° w żadnej osi")
        # Contradictory coordinates for one OSM node corrupt topology.
        known = {}
        for item in payload["features"]:
            props = item.get("properties") or {}
            for key, coord in zip(
                props.get("osm_node_ids", []), item["geometry"]["coordinates"], strict=False
            ):
                key = str(key)
                if key in known and known[key] != coord[:2]:
                    raise ValueError("Ten sam węzeł OSM ma różne współrzędne")
                known[key] = coord[:2]
    else:
        load_flood_geometries(payload)
    return payload


def analyze_datasets(datasets: dict, start: tuple, end: tuple) -> dict:
    started_at = perf_counter()
    roads, flood = datasets["roads"], datasets["flood"]
    graph = RoadGraphBuilder.from_geojson(roads).build_graph()
    baseline = EvacRouter(graph, max_snap_distance_m=100).find_route(start, end)
    count = mark_blocked_edges(graph, flood, min_overlap_ratio=0)
    route = EvacRouter(graph, max_snap_distance_m=100).find_route(start, end)
    blocked = {}
    for _, _, data in graph.edges(data=True):
        if data["blocked"]:
            geometry = data["geometry"]
            blocked[geometry.normalize().wkb] = feature(mapping(geometry), name=data["name"])
    original = baseline[1]["length_m"] if baseline else None
    actual = route[1]["length_m"] if route else None
    extra = max(0, actual - original) if actual is not None and original is not None else None
    return {
        "data_mode": datasets["data_mode"],
        "source": datasets["source"],
        "observed_at": datasets["observed_at"],
        "status": "found" if route else "unreachable",
        "start": start,
        "end": end,
        "roads": roads,
        "flood": flood,
        "blocked": collection(list(blocked.values())),
        "baseline": route_feature(baseline),
        "route": route_feature(route),
        "metrics": {
            "baseline_length_m": original,
            "route_length_m": actual,
            "extra_distance_m": extra,
            "extra_distance_percent": round(extra / original * 100, 1)
            if original and extra is not None
            else None,
            "blocked_segments": count,
            "total_segments": len(
                {data["geometry"].normalize().wkb for _, _, data in graph.edges(data=True)}
            ),
            "nodes": graph.number_of_nodes(),
            "calc_time_ms": round((perf_counter() - started_at) * 1000, 3),
        },
    }

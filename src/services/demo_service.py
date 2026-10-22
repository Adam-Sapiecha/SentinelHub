"""Deterministic synthetic inputs; all results use the production routing core.

No external requests, filesystem writes or mutable shared graphs. Coordinates
only provide a metric scale; this is not a reconstruction of actual roads.
"""

from time import perf_counter
from typing import Literal

from shapely.geometry import box, mapping

from src.core.flood_intersector import mark_blocked_edges
from src.core.graph_builder import RoadGraphBuilder
from src.core.router import EvacRouter

ScenarioId = Literal["clear", "detour", "cutoff"]
PointId = Literal["west", "east", "north", "center"]
SCENARIOS = [
    {"id": "clear", "title": "01 / Bez zalania", "description": "Sieć jest w pełni dostępna."},
    {
        "id": "detour",
        "title": "02 / Zalane skrzyżowanie",
        "description": "Woda odcina centralny węzeł. Sprawdź, którędy prowadzi objazd.",
    },
    {
        "id": "cutoff",
        "title": "03 / Odcięta dzielnica",
        "description": "Zalanie przecina wszystkie połączenia między zachodem i wschodem.",
    },
]


def coordinate(column: float, row: float) -> tuple[float, float]:
    """Return synthetic (longitude, latitude), WGS84."""
    return round(16.98 + column * 0.004, 6), round(51.10 + row * 0.003, 6)


POINTS = [
    {"id": "west", "label": "Osiedle Zachodnie", "coordinates": coordinate(0, 1)},
    {"id": "east", "label": "Punkt zbiórki Wschód", "coordinates": coordinate(4, 1)},
    {"id": "north", "label": "Punkt zbiórki Północ", "coordinates": coordinate(4, 2)},
    {"id": "center", "label": "Centralne skrzyżowanie", "coordinates": coordinate(2, 1)},
]


def feature(geometry: dict, **properties) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def collection(features: list) -> dict:
    return {"type": "FeatureCollection", "features": features}


def sample_roads() -> dict:
    roads = []
    for row in range(3):
        for column in range(5):
            for other_column, other_row in ((column + 1, row), (column, row + 1)):
                if other_column >= 5 or other_row >= 3:
                    continue
                roads.append(
                    feature(
                        {
                            "type": "LineString",
                            "coordinates": [
                                coordinate(column, row),
                                coordinate(other_column, other_row),
                            ],
                        },
                        highway="residential",
                        name=f"Syntetyczny odcinek {len(roads) + 1:02d}",
                        source="synthetic",
                    )
                )
    return collection(roads)


def sample_flood(scenario: ScenarioId) -> dict:
    if scenario == "clear":
        return collection([])
    if scenario == "detour":
        west, south = coordinate(1.6, 0.65)
        east, north = coordinate(2.4, 1.35)
    else:
        west, south = coordinate(1.6, -0.5)
        east, north = coordinate(2.4, 2.5)
    return collection([feature(mapping(box(west, south, east, north)), source="synthetic")])


def route_feature(result) -> dict | None:
    if result is None:
        return None
    geometry, metadata = result
    return feature(mapping(geometry), **metadata)


def analyze(scenario: ScenarioId, origin: PointId, destination: PointId) -> dict:
    started_at = perf_counter()
    roads = sample_roads()
    flood = sample_flood(scenario)
    graph = RoadGraphBuilder.from_geojson(roads).build_graph()
    points = {point["id"]: point["coordinates"] for point in POINTS}
    start, end = tuple(reversed(points[origin])), tuple(reversed(points[destination]))
    baseline = EvacRouter(graph).find_route(start, end)
    # Any positive flooded length blocks the synthetic road. This is not a
    # hydraulic model or an assurance that the remaining roads are safe.
    blocked_count = mark_blocked_edges(graph, flood, min_overlap_ratio=0)
    result = EvacRouter(graph).find_route(start, end)
    seen = set()
    blocked = []
    for _, _, data in graph.edges(data=True):
        geometry = data["geometry"]
        signature = geometry.normalize().wkb
        if data["blocked"] and signature not in seen:
            seen.add(signature)
            blocked.append(feature(mapping(geometry), name=data["name"]))
    baseline_length = baseline[1]["length_m"] if baseline else None
    route_length = result[1]["length_m"] if result else None
    extra_m = max(0, route_length - baseline_length) if result and baseline else None
    return {
        "scenario": scenario,
        "origin": origin,
        "destination": destination,
        "data_mode": "sample",
        "source": "Ręcznie zdefiniowana, syntetyczna siatka 15 węzłów i 22 odcinków.",
        "status": "found" if result else "unreachable",
        "roads": roads,
        "flood": flood,
        "blocked": collection(blocked),
        "baseline": route_feature(baseline),
        "route": route_feature(result),
        "metrics": {
            "baseline_length_m": baseline_length,
            "route_length_m": route_length,
            "extra_distance_m": extra_m,
            "extra_distance_percent": (
                round(extra_m / baseline_length * 100, 1) if baseline_length and result else None
            ),
            "blocked_segments": blocked_count,
            "total_segments": len(roads["features"]),
            "nodes": graph.number_of_nodes(),
            "calc_time_ms": round((perf_counter() - started_at) * 1000, 3),
        },
    }

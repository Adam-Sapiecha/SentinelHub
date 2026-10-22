import json
import logging
from pathlib import Path
from threading import RLock
from typing import Any

import networkx as nx
from shapely.geometry import LineString, mapping

from src.core.config import FLOOD_PATH, ROADS_PATH
from src.core.flood_intersector import (
    FloodDataUnavailableError,
    load_flood_geometries,
    mark_blocked_edges,
)
from src.core.graph_builder import RoadGraphBuilder
from src.core.io_utils import write_json_atomic
from src.core.router import EvacRouter, RoadDataUnavailableError

logger = logging.getLogger(__name__)
Coordinate = tuple[float, float]


class EvacService:
    """Coordinate persistent road/flood data and thread-safe route calculation."""

    def __init__(self, roads_path: Path, flood_path: Path):
        self.roads_path = roads_path
        self.flood_path = flood_path
        self._lock = RLock()
        try:
            self.graph = RoadGraphBuilder(self.roads_path).build_graph()
        except (OSError, ValueError, json.JSONDecodeError):
            logger.exception("Nie udało się wczytać grafu dróg z %s", roads_path)
            self.graph = nx.MultiDiGraph()

        logger.info(
            "Graf gotowy: %d węzłów, %d krawędzi",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )

    def reload_graph(self, geojson: dict[str, Any], *, persist: bool = True) -> None:
        new_graph = RoadGraphBuilder.from_geojson(geojson).build_graph()
        if new_graph.number_of_edges() == 0:
            raise ValueError("Pobrane dane nie zawierają przejezdnych dróg")

        with self._lock:
            if persist:
                write_json_atomic(self.roads_path, geojson)
            self.graph = new_graph

        logger.info(
            "Graf przeładowany: %d węzłów, %d krawędzi",
            new_graph.number_of_nodes(),
            new_graph.number_of_edges(),
        )

    def set_flood_geojson(self, geojson: dict[str, Any]) -> None:
        load_flood_geometries(geojson)
        with self._lock:
            write_json_atomic(self.flood_path, geojson)

    def get_flood_geojson(self) -> dict[str, Any]:
        with self._lock:
            if not self.flood_path.exists():
                raise FloodDataUnavailableError("Brak aktualnych danych o strefach zalania")
            try:
                with self.flood_path.open("r", encoding="utf-8") as stream:
                    payload = json.load(stream)
            except (OSError, json.JSONDecodeError) as error:
                raise FloodDataUnavailableError(
                    "Nie można odczytać danych o strefach zalania"
                ) from error
        load_flood_geometries(payload)
        return payload

    def get_route(
        self,
        start: Coordinate,
        end: Coordinate,
    ) -> tuple[LineString, dict[str, Any]] | None:
        with self._lock:
            if self.graph.number_of_edges() == 0:
                raise RoadDataUnavailableError("Brak załadowanych danych drogowych")
            blocked_edges_count = mark_blocked_edges(self.graph, self.flood_path)
            result = EvacRouter(self.graph).find_route(start, end)

        if result is None:
            return None
        route_line, metadata = result
        metadata["blocked_edges_count"] = blocked_edges_count
        return route_line, metadata

    def get_blocked_edges_geojson(self) -> dict[str, Any]:
        with self._lock:
            if self.graph.number_of_edges() == 0:
                raise RoadDataUnavailableError("Brak załadowanych danych drogowych")
            mark_blocked_edges(self.graph, self.flood_path)

            features = []
            seen_geometries: set[bytes] = set()
            for _, _, data in self.graph.edges(data=True):
                geometry = data.get("geometry")
                if not data.get("blocked") or geometry is None:
                    continue
                canonical_geometry = geometry.normalize()
                signature = canonical_geometry.wkb
                if signature in seen_geometries:
                    continue
                seen_geometries.add(signature)
                features.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(geometry),
                        "properties": {
                            "highway": data.get("highway"),
                            "name": data.get("name"),
                        },
                    }
                )

        return {"type": "FeatureCollection", "features": features}


evac_service_singleton = EvacService(ROADS_PATH, FLOOD_PATH)

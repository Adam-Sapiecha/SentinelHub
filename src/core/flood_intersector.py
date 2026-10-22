import json
import logging
import math
from collections.abc import Iterable
from pathlib import Path

from shapely import get_coordinates, make_valid
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .config import FLOOD_PATH, MIN_FLOOD_OVERLAP_RATIO

logger = logging.getLogger(__name__)
FloodSource = str | Path | dict | Iterable[BaseGeometry]
WGS84_CRS_NAMES = {
    "EPSG:4326",
    "OGC:CRS84",
    "urn:ogc:def:crs:OGC:1.3:CRS84",
    "urn:ogc:def:crs:EPSG::4326",
}


class FloodDataUnavailableError(RuntimeError):
    pass


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [part for item in geometry.geoms for part in _polygon_parts(item)]
    return []


def _validate_geojson_crs(payload: dict) -> None:
    crs = payload.get("crs")
    if crs is None:
        return
    if not isinstance(crs, dict) or not isinstance(crs.get("properties"), dict):
        raise FloodDataUnavailableError("Nieprawidłowa deklaracja CRS flood")
    name = str(crs["properties"].get("name", ""))
    if name not in WGS84_CRS_NAMES:
        raise FloodDataUnavailableError(
            "GeoJSON flood musi używać współrzędnych WGS84 (longitude, latitude)"
        )


def load_flood_geometries(flood_source: FloodSource | None = None) -> list[Polygon]:
    payload = flood_source if isinstance(flood_source, dict) else None
    if isinstance(flood_source, (str, Path)) or flood_source is None:
        path = Path(flood_source) if flood_source is not None else FLOOD_PATH
        if not path.exists():
            raise FloodDataUnavailableError("Brak aktualnych danych o strefach zalania")
        try:
            with path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, json.JSONDecodeError) as error:
            raise FloodDataUnavailableError(
                "Nie można odczytać danych o strefach zalania"
            ) from error
        if not isinstance(payload, dict):
            raise FloodDataUnavailableError("Flood wymaga obiektu GeoJSON")

    if payload is not None:
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise FloodDataUnavailableError(
                "Dane flood muszą być kolekcją GeoJSON FeatureCollection"
            )
        _validate_geojson_crs(payload)
        if not isinstance(payload.get("features"), list):
            raise FloodDataUnavailableError("Brak prawidłowej listy features flood")
        try:
            source_geometries = []
            for feature in payload["features"]:
                if not isinstance(feature, dict) or feature.get("type") != "Feature":
                    raise ValueError("Nieprawidłowy Feature flood")
                geometry = feature.get("geometry")
                if not isinstance(geometry, dict) or geometry.get("type") not in {
                    "Polygon",
                    "MultiPolygon",
                }:
                    raise ValueError("Flood wymaga geometrii Polygon lub MultiPolygon")
                source_geometries.append(shape(geometry))
        except (KeyError, TypeError, ValueError, AttributeError, GEOSException) as error:
            raise FloodDataUnavailableError(
                "Dane flood zawierają nieprawidłową geometrię GeoJSON"
            ) from error
    else:
        source_geometries = list(flood_source)

    polygons: list[Polygon] = []
    try:
        for geometry in source_geometries:
            if not isinstance(geometry, BaseGeometry):
                raise TypeError("Flood geometry is not a Shapely geometry")
            if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty:
                raise ValueError("Flood wymaga niepustego poligonu")
            if not all(math.isfinite(value) for value in geometry.bounds):
                raise ValueError("Flood zawiera nieskończone współrzędne")
            if not all(
                math.isfinite(value) for pair in get_coordinates(geometry) for value in pair
            ):
                raise ValueError("Flood zawiera nieprawidłowe współrzędne")
            west, south, east, north = geometry.bounds
            if west < -180 or east > 180 or south < -90 or north > 90:
                raise ValueError("Flood znajduje się poza WGS84")
            normalized = geometry if geometry.is_valid else make_valid(geometry)
            parts = _polygon_parts(normalized)
            if not parts:
                raise ValueError("Flood nie zawiera powierzchni poligonu")
            polygons.extend(parts)
    except Exception as error:
        raise FloodDataUnavailableError(
            "Dane o strefach zalania mają nieprawidłową geometrię"
        ) from error
    return polygons


def _edge_data(graph):
    if graph.is_multigraph():
        yield from graph.edges(keys=True, data=True)
    else:
        for source, target, data in graph.edges(data=True):
            yield source, target, None, data


def mark_blocked_edges(
    graph,
    flood: FloodSource | None = None,
    min_overlap_ratio: float = MIN_FLOOD_OVERLAP_RATIO,
) -> int:
    """Mark edges whose combined flooded portion reaches the configured ratio."""
    if not 0 <= min_overlap_ratio <= 1:
        raise ValueError("min_overlap_ratio musi należeć do przedziału 0..1")

    polygons = load_flood_geometries(flood)
    for _, _, _, data in _edge_data(graph):
        data["blocked"] = False

    if not polygons:
        logger.info("Dane flood są aktualne, ale nie zawierają stref zalania.")
        return 0

    try:
        spatial_index = STRtree(polygons)
    except Exception:
        logger.warning("Brak indeksu przestrzennego; używam pełnego skanowania.")
        spatial_index = None

    blocked_geometries: set[bytes] = set()
    for _, _, _, data in _edge_data(graph):
        geometry: BaseGeometry | None = data.get("geometry")
        if geometry is None or geometry.is_empty or geometry.length == 0:
            continue

        if spatial_index is None:
            candidates = polygons
        else:
            candidates = [polygons[int(index)] for index in spatial_index.query(geometry)]
        if not candidates:
            continue

        try:
            overlap_length = geometry.intersection(unary_union(candidates)).length
        except Exception as error:
            raise FloodDataUnavailableError(
                "Nie udało się porównać geometrii drogi i zalania"
            ) from error

        overlap_ratio = overlap_length / geometry.length
        if overlap_length > 0 and overlap_ratio >= min_overlap_ratio:
            data["blocked"] = True
            blocked_geometries.add(geometry.normalize().wkb)

    blocked_count = len(blocked_geometries)
    logger.info("Zablokowano %d krawędzi grafu.", blocked_count)
    return blocked_count

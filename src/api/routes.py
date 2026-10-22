import logging
import math
import secrets
from functools import lru_cache
from typing import Annotated, Literal
from xml.etree.ElementTree import ParseError

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from shapely.geometry import box, mapping

from src.core.config import MAX_BBOX_AREA_KM2, get_admin_api_key
from src.core.flood_intersector import FloodDataUnavailableError
from src.core.osm_downloader import download_osm_roads
from src.core.osm_to_geojson import osm_to_roads_geojson
from src.core.router import RoadDataUnavailableError, SnapDistanceExceededError
from src.core.sentinel_flood_ogc_client import (
    SentinelHubServiceError,
    SentinelOGCFloodClient,
    create_default_ogc_client,
)
from src.core.utils import haversine_distance_m
from src.services.evac_service import evac_service_singleton

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evacuation"])
MIN_ADMIN_KEY_LENGTH = 32


class BBox(BaseModel):
    south: float = Field(ge=-90, le=90, allow_inf_nan=False)
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    north: float = Field(ge=-90, le=90, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds_and_area(self) -> "BBox":
        if self.south >= self.north:
            raise ValueError("south musi być mniejsze od north")
        if self.west >= self.east:
            raise ValueError("west musi być mniejsze od east")

        middle_latitude = (self.south + self.north) / 2
        height_m = haversine_distance_m((self.south, self.west), (self.north, self.west))
        width_m = (
            6_371_000
            * math.radians(self.east - self.west)
            * math.cos(math.radians(middle_latitude))
        )
        area_km2 = height_m * width_m / 1_000_000
        if area_km2 > MAX_BBOX_AREA_KM2:
            raise ValueError(f"Obszar BBOX przekracza limit {MAX_BBOX_AREA_KM2:g} km²")
        return self

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.south, self.west, self.north, self.east


class LineStringGeometry(BaseModel):
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]]


class RouteProperties(BaseModel):
    length_m: float
    segments: int


class RouteFeature(BaseModel):
    type: Literal["Feature"]
    geometry: LineStringGeometry
    properties: RouteProperties


class RouteMetadata(BaseModel):
    calc_time_ms: float
    blocked_edges_count: int
    start_snap_distance_m: float
    end_snap_distance_m: float


class RouteResponse(BaseModel):
    route: RouteFeature
    meta: RouteMetadata


class RoadUpdateResponse(BaseModel):
    status: Literal["OK"]
    roads: int
    bbox: BBox


class FloodUpdateResponse(BaseModel):
    status: Literal["OK"]
    polygons: int
    bbox: BBox


def require_admin_key(
    provided_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None,
) -> None:
    expected_key = get_admin_api_key()
    if not expected_key or len(expected_key) < MIN_ADMIN_KEY_LENGTH:
        raise HTTPException(
            status_code=503,
            detail="Operacje administracyjne nie są skonfigurowane",
        )
    if not provided_key or not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(status_code=401, detail="Nieprawidłowy klucz administratora")


def parse_latlon(param: str) -> tuple[float, float]:
    parts = param.split(",")
    if len(parts) != 2:
        raise HTTPException(
            status_code=422,
            detail="Współrzędne muszą być zapisane w formacie lat,lon",
        )
    try:
        latitude, longitude = (float(part.strip()) for part in parts)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="Szerokość i długość geograficzna muszą być liczbami",
        ) from error

    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise HTTPException(status_code=422, detail="Współrzędne muszą być skończone")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise HTTPException(status_code=422, detail="Współrzędne są poza zakresem WGS84")
    return latitude, longitude


@router.get("/evac/route", response_model=RouteResponse)
def get_evac_route(
    start: str = Query(..., description="Punkt startowy w formacie 'lat,lon'"),
    end: str = Query(..., description="Punkt końcowy w formacie 'lat,lon'"),
):
    start_coordinate = parse_latlon(start)
    end_coordinate = parse_latlon(end)

    try:
        result = evac_service_singleton.get_route(start_coordinate, end_coordinate)
    except SnapDistanceExceededError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (RoadDataUnavailableError, FloodDataUnavailableError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Nie udało się znaleźć bezpiecznej trasy między punktami",
        )

    route_line, metadata = result
    return {
        "route": {
            "type": "Feature",
            "geometry": route_line.__geo_interface__,
            "properties": {
                "length_m": metadata["length_m"],
                "segments": metadata["segments"],
            },
        },
        "meta": {
            "calc_time_ms": metadata["calc_time_ms"],
            "blocked_edges_count": metadata["blocked_edges_count"],
            "start_snap_distance_m": metadata["start_snap_distance_m"],
            "end_snap_distance_m": metadata["end_snap_distance_m"],
        },
    }


@router.post(
    "/admin/update-roads",
    dependencies=[Depends(require_admin_key)],
    response_model=RoadUpdateResponse,
)
def update_roads(bbox: BBox):
    try:
        osm_xml = download_osm_roads(bbox.as_tuple())
        geojson = osm_to_roads_geojson(osm_xml)
        evac_service_singleton.reload_graph(geojson)
    except requests.RequestException as error:
        logger.error("Overpass request failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail="Nie udało się pobrać danych drogowych z Overpass API",
        ) from error
    except (ValueError, OSError, ParseError) as error:
        logger.error("Road update failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail="Pobrane dane drogowe są nieprawidłowe",
        ) from error

    return {
        "status": "OK",
        "roads": len(geojson["features"]),
        "bbox": bbox.model_dump(),
    }


@router.post(
    "/admin/set-test-flood-rect",
    dependencies=[Depends(require_admin_key)],
    response_model=FloodUpdateResponse,
)
def set_test_flood_rect(bbox: BBox):
    longitude_margin = (bbox.east - bbox.west) * 0.25
    latitude_margin = (bbox.north - bbox.south) * 0.25
    geometry = box(
        bbox.west + longitude_margin,
        bbox.south + latitude_margin,
        bbox.east - longitude_margin,
        bbox.north - latitude_margin,
    )
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"source": "test-rect"},
                "geometry": mapping(geometry),
            }
        ],
    }
    evac_service_singleton.set_flood_geojson(feature_collection)
    return {"status": "OK", "polygons": 1, "bbox": bbox.model_dump()}


@lru_cache(maxsize=1)
def get_sentinel_client() -> SentinelOGCFloodClient:
    return create_default_ogc_client()


@router.post(
    "/admin/update-flood",
    dependencies=[Depends(require_admin_key)],
    response_model=FloodUpdateResponse,
)
def update_flood(bbox: BBox):
    try:
        client = get_sentinel_client()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    try:
        count = client.update_flood_for_bbox(bbox.as_tuple())
    except SentinelHubServiceError as error:
        logger.warning("Sentinel Hub rejected the flood update: %s", error)
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (requests.RequestException, RuntimeError, OSError) as error:
        logger.error("Sentinel update failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail="Nie udało się zaktualizować stref zalania z Sentinel Hub",
        ) from error

    return {"status": "OK", "polygons": count, "bbox": bbox.model_dump()}


@router.get("/debug/flood-geojson")
def get_flood_geojson():
    try:
        return evac_service_singleton.get_flood_geojson()
    except FloodDataUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/debug/blocked-edges")
def get_blocked_edges():
    try:
        return evac_service_singleton.get_blocked_edges_geojson()
    except (RoadDataUnavailableError, FloodDataUnavailableError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

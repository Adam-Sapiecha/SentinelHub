import logging
import math
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import BoundedSemaphore
from typing import Annotated, Literal
from xml.etree.ElementTree import ParseError

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from shapely.errors import GEOSException

from src.core.config import get_admin_api_key
from src.core.flood_intersector import FloodDataUnavailableError
from src.core.osm_downloader import download_osm_roads
from src.core.osm_to_geojson import osm_to_roads_geojson
from src.core.router import SnapDistanceExceededError
from src.core.sentinel_flood_ogc_client import (
    SentinelHubServiceError,
    SentinelOGCConfig,
    SentinelOGCFloodClient,
)
from src.services.dataset_service import analyze_datasets, roads_inside_coverage, validate_dataset
from src.services.workspace_store import (
    CapacityError,
    RevisionConflict,
    StoreError,
    WorkspaceStore,
    now,
)

router = APIRouter(prefix="/workspaces", tags=["private workspaces"])
logger = logging.getLogger(__name__)
processing_slots = BoundedSemaphore(2)
integration_slot = BoundedSemaphore(1)
bearer = HTTPBearer(
    auto_error=False,
    scheme_name="WorkspaceKey",
    description="Prywatny klucz właściciela przestrzeni",
)


@contextmanager
def bounded(slot):
    if not slot.acquire(blocking=False):
        raise HTTPException(429, "Trwa inna operacja; spróbuj ponownie za chwilę")
    try:
        yield
    finally:
        slot.release()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceCreate(StrictModel):
    name: str = Field(default="Moja analiza", min_length=1, max_length=80)


class DatasetPair(StrictModel):
    revision: int = Field(ge=0)
    roads: dict
    flood: dict
    source: str = Field(min_length=1, max_length=160)
    observed_at: AwareDatetime
    sample: bool = False

    @model_validator(mode="after")
    def observation_not_in_future(self):
        if self.observed_at.timestamp() > datetime.now(UTC).timestamp() + 300:
            raise ValueError("Data obserwacji nie może być w przyszłości")
        return self


class Coordinate(StrictModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


class RouteInput(StrictModel):
    revision: int = Field(ge=1)
    start: Coordinate
    end: Coordinate


class ImportArea(StrictModel):
    south: float = Field(ge=-90, le=90, allow_inf_nan=False)
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    north: float = Field(ge=-90, le=90, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def local_area(self):
        height, width = self.north - self.south, self.east - self.west
        area = height * width * 111.2**2 * math.cos(math.radians((self.north + self.south) / 2))
        if not (0 < height <= 0.5 and 0 < width <= 0.5) or area > 100:
            raise ValueError("Import wymaga lokalnego obszaru do 100 km² i 0,5° na oś")
        return self

    def as_tuple(self):
        return self.south, self.west, self.north, self.east


class ExternalImport(StrictModel):
    revision: int = Field(ge=0)
    bbox: ImportArea
    provider: Literal["overpass", "sentinel"]


def store(request: Request) -> WorkspaceStore:
    repository = getattr(request.app.state, "store", None)
    if repository is None:
        raise HTTPException(503, "Magazyn nie jest gotowy")
    return repository


Store = Annotated[WorkspaceStore, Depends(store)]


def owner(
    workspace_id: str,
    repository: Store,
    authorization: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> str:
    key = authorization.credentials if authorization else ""
    if not authorization or authorization.scheme.lower() != "bearer" or len(key) > 128:
        raise HTTPException(401, "Podaj prawidłowy klucz przestrzeni w nagłówku Bearer")
    if not repository.authenticate(workspace_id, key):
        raise HTTPException(401, "Nieprawidłowy identyfikator lub klucz przestrzeni")
    return workspace_id


Owner = Annotated[str, Depends(owner)]


def operator(key: Annotated[str | None, Header(alias="X-Admin-Key")] = None):
    expected = get_admin_api_key()
    if not expected or len(expected) < 32:
        raise HTTPException(503, "Import zewnętrzny wymaga konfiguracji operatora")
    if not key or not secrets.compare_digest(key, expected):
        raise HTTPException(403, "Import zewnętrzny wymaga uprawnień operatora")


@router.post("", status_code=201)
def create_workspace(data: WorkspaceCreate, repository: Store):
    return repository.create(data.name)


@router.get("/{workspace_id}")
def get_workspace(workspace_id: Owner, repository: Store):
    return repository.get(workspace_id)


@router.put("/{workspace_id}/datasets")
def set_datasets(workspace_id: Owner, data: DatasetPair, repository: Store):
    with bounded(processing_slots):
        try:
            validate_dataset(data.roads, "roads")
            validate_dataset(data.flood, "flood")
        except (ValueError, FloodDataUnavailableError, GEOSException) as error:
            raise HTTPException(422, str(error)) from error
        return repository.replace_datasets(
            workspace_id,
            data.revision,
            {
                "roads": data.roads,
                "flood": data.flood,
                "source": data.source,
                "observed_at": data.observed_at.isoformat(),
                "data_mode": "sample" if data.sample else "user",
                "saved_at": now(),
            },
        )


@router.post("/{workspace_id}/analyses", status_code=201)
def calculate(workspace_id: Owner, data: RouteInput, repository: Store):
    with bounded(processing_slots):
        workspace = repository.get(workspace_id)
        if workspace["revision"] != data.revision:
            raise RevisionConflict("Dane zmieniły się. Odczytaj przestrzeń przed obliczeniem")
        if workspace["datasets"] is None:
            raise HTTPException(409, "Najpierw zapisz oba zbiory: drogi i zalanie")
        if workspace["datasets"].get("roads") is None or workspace["datasets"].get("flood") is None:
            raise HTTPException(409, "Brakuje dróg lub zalania; brak danych nie oznacza braku wody")
        coverage = workspace["datasets"].get("coverage")
        if coverage:
            for point in [data.start, data.end]:
                if not (
                    coverage["south"] <= point.lat <= coverage["north"]
                    and coverage["west"] <= point.lon <= coverage["east"]
                ):
                    raise HTTPException(422, "Punkt leży poza wspólnym obszarem importu")
        try:
            result = analyze_datasets(
                workspace["datasets"],
                (data.start.lat, data.start.lon),
                (data.end.lat, data.end.lon),
            )
        except SnapDistanceExceededError as error:
            raise HTTPException(422, str(error)) from error
        return repository.save_analysis(workspace_id, data.revision, result)


@router.get("/{workspace_id}/analyses")
def list_analyses(workspace_id: Owner, repository: Store):
    return repository.history(workspace_id)


@router.get("/{workspace_id}/analyses/{analysis_id}")
def read_analysis(workspace_id: Owner, analysis_id: str, repository: Store):
    result = repository.analysis(workspace_id, analysis_id)
    if result is None:
        raise HTTPException(404, "Analiza nie istnieje w tej przestrzeni")
    return result


@router.delete("/{workspace_id}/analyses/{analysis_id}", status_code=204)
def remove_analysis(workspace_id: Owner, analysis_id: str, repository: Store):
    repository.delete_analysis(workspace_id, analysis_id)


@router.delete("/{workspace_id}", status_code=204)
def remove_workspace(workspace_id: Owner, repository: Store):
    repository.delete(workspace_id)


@router.post("/{workspace_id}/rotate-key")
def rotate_key(workspace_id: Owner, repository: Store):
    return {"key": repository.rotate_key(workspace_id)}


@router.post("/{workspace_id}/imports", dependencies=[Depends(operator)])
def import_external(workspace_id: Owner, data: ExternalImport, repository: Store):
    with bounded(integration_slot), bounded(processing_slots):
        workspace = repository.get(workspace_id)
        if workspace["revision"] != data.revision:
            raise RevisionConflict("Dane zmieniły się. Odczytaj przestrzeń")
        datasets = workspace["datasets"] or {
            "roads": None,
            "flood": None,
            "data_mode": "live",
            "providers": {},
        }
        # Never combine a fresh provider result with an unrelated or sample dataset.
        # Each provider must be imported for the exact same area.
        area = data.bbox.model_dump()
        if datasets.get("coverage") != area or datasets.get("data_mode") != "live":
            datasets = {"roads": None, "flood": None, "providers": {}, "data_mode": "live"}
        try:
            if data.provider == "overpass":
                roads = osm_to_roads_geojson(download_osm_roads(data.bbox.as_tuple()))
                roads = roads_inside_coverage(roads, data.bbox.as_tuple())
                validate_dataset(roads, "roads")
                datasets["roads"] = roads
            else:
                instance = os.getenv("SENTINELHUB_INSTANCE_ID")
                if not instance:
                    raise HTTPException(503, "Brak aktywnej instancji Sentinel WMS / warstwy FLOOD")
                config = SentinelOGCConfig(
                    instance_id=instance, time=os.getenv("SENTINELHUB_TIME_RANGE") or None
                )
                client = SentinelOGCFloodClient(
                    config, repository.path.parent / "unused-flood.geojson"
                )
                flood = client.fetch_flood_geojson(data.bbox.as_tuple())
                validate_dataset(flood, "flood")
                datasets["flood"] = flood
                datasets["wms_time_range"] = config.effective_time
        except SentinelHubServiceError as error:
            raise HTTPException(502, str(error)) from error
        except requests.RequestException as error:
            logger.warning("External import failed: %s", type(error).__name__)
            raise HTTPException(
                502, "Usługa zewnętrzna jest niedostępna; poprzedni zapis zachowano"
            ) from error
        except (ValueError, RuntimeError, ParseError) as error:
            logger.warning("External input rejected: %s", type(error).__name__)
            raise HTTPException(
                502, "Usługa zwróciła nieprawidłowe dane; poprzedni zapis zachowano"
            ) from error
        datasets.update(
            {
                "source": "OpenStreetMap / Sentinel Hub WMS FLOOD",
                "coverage": area,
                "observed_at": None,
                "saved_at": now(),
            }
        )
        datasets.setdefault("providers", {})[data.provider] = {"retrieved_at": now(), "bbox": area}
        return repository.replace_datasets(workspace_id, data.revision, datasets)


def install_error_handlers(app):
    @app.exception_handler(StoreError)
    async def store_unavailable(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"detail": "Magazyn jest niedostępny; skontaktuj się z operatorem"}, 503
        )

    @app.exception_handler(RevisionConflict)
    async def conflict(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(error)}, 409)

    @app.exception_handler(CapacityError)
    async def capacity(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(error)}, 507)

    @app.exception_handler(sqlite3.Error)
    async def storage_failure(request, error):
        from fastapi.responses import JSONResponse

        logger.error("Workspace storage failed: %s", type(error).__name__)
        return JSONResponse({"detail": "Magazyn chwilowo niedostępny; ponów operację"}, 503)

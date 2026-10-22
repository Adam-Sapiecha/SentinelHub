from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from src.services.demo_service import POINTS, SCENARIOS, PointId, ScenarioId, analyze

router = APIRouter(prefix="/demo", tags=["public demo"])


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: ScenarioId = "detour"
    origin: PointId = "west"
    destination: PointId = "east"


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"]
    geometry: dict[str, Any]
    properties: dict[str, Any]


class GeoJSONCollection(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[GeoJSONFeature]


class AnalysisMetrics(BaseModel):
    baseline_length_m: float | None
    route_length_m: float | None
    extra_distance_m: float | None
    extra_distance_percent: float | None
    blocked_segments: int
    total_segments: int
    nodes: int
    calc_time_ms: float


class AnalysisResponse(BaseModel):
    scenario: ScenarioId
    origin: PointId
    destination: PointId
    data_mode: Literal["sample"]
    source: str
    status: Literal["found", "unreachable"]
    roads: GeoJSONCollection
    flood: GeoJSONCollection
    blocked: GeoJSONCollection
    baseline: GeoJSONFeature | None
    route: GeoJSONFeature | None
    metrics: AnalysisMetrics


@router.get("/scenarios")
def scenarios() -> dict:
    return {"data_mode": "sample", "scenarios": SCENARIOS, "points": POINTS}


@router.post("/analyze", response_model=AnalysisResponse)
def run_analysis(request: AnalysisRequest) -> dict:
    return analyze(request.scenario, request.origin, request.destination)

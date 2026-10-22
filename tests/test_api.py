import os

import networkx as nx
import pytest
import requests
from fastapi.testclient import TestClient
from shapely.geometry import LineString

TEST_ADMIN_KEY = "test-admin-key-with-at-least-32-chars"
os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY

from src.api.routes import get_sentinel_client  # noqa: E402
from src.main import create_app  # noqa: E402
from src.services.evac_service import evac_service_singleton  # noqa: E402

client = TestClient(create_app("live"))
ADMIN_HEADERS = {"X-Admin-Key": TEST_ADMIN_KEY}


@pytest.fixture(autouse=True)
def isolated_service_state(tmp_path):
    service = evac_service_singleton
    original_graph = service.graph
    original_roads_path = service.roads_path
    original_flood_path = service.flood_path

    service.graph = nx.MultiDiGraph()
    service.roads_path = tmp_path / "roads.geojson"
    service.flood_path = tmp_path / "flood.geojson"
    get_sentinel_client.cache_clear()
    yield service

    service.graph = original_graph
    service.roads_path = original_roads_path
    service.flood_path = original_flood_path
    get_sentinel_client.cache_clear()


def _empty_flood(service) -> None:
    service.set_flood_geojson({"type": "FeatureCollection", "features": []})


def _simple_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    first = (52.0, 21.0)
    second = (52.0, 21.001)
    graph.add_node(first)
    graph.add_node(second)
    geometry = LineString([(21.0, 52.0), (21.001, 52.0)])
    graph.add_edge(
        first,
        second,
        length_m=68.5,
        geometry=geometry,
        blocked=False,
    )
    graph.add_edge(
        second,
        first,
        length_m=68.5,
        geometry=LineString(list(geometry.coords)[::-1]),
        blocked=False,
    )
    return graph


def test_system_endpoints_are_available():
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200


def test_admin_endpoint_requires_key():
    response = client.post(
        "/api/admin/update-roads",
        json={"south": 52.2, "west": 20.9, "north": 52.3, "east": 21.0},
    )
    assert response.status_code == 401


def test_admin_endpoint_rejects_weak_server_configuration(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "too-short")
    response = client.post(
        "/api/admin/set-test-flood-rect",
        json={"south": 52.2, "west": 20.9, "north": 52.3, "east": 21.0},
        headers={"X-Admin-Key": "too-short"},
    )
    assert response.status_code == 503


def test_update_roads_rejects_invalid_payload():
    response = client.post(
        "/api/admin/update-roads",
        json={},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"south": 52.3, "west": 20.9, "north": 52.2, "east": 21.0},
        {"south": -91, "west": 20.9, "north": 52.2, "east": 21.0},
        {"south": -80, "west": -170, "north": 80, "east": 170},
        {"south": 0, "west": -180, "north": 1, "east": 180},
    ],
)
def test_admin_endpoint_rejects_invalid_bbox(payload):
    response = client.post(
        "/api/admin/set-test-flood-rect",
        json=payload,
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 422


def test_set_test_flood_rect_writes_to_configured_path(isolated_service_state):
    response = client.post(
        "/api/admin/set-test-flood-rect",
        json={"south": 52.2, "west": 20.9, "north": 52.3, "east": 21.0},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["polygons"] == 1
    assert isolated_service_state.flood_path.exists()


def test_route_without_roads_returns_service_unavailable(isolated_service_state):
    _empty_flood(isolated_service_state)
    response = client.get(
        "/api/evac/route",
        params={"start": "52.229,21.012", "end": "52.231,21.015"},
    )
    assert response.status_code == 503


@pytest.mark.parametrize(
    "start,end",
    [
        ("invalid", "52.2,21.0"),
        ("nan,21", "52.2,21.0"),
        ("91,21", "52.2,21.0"),
    ],
)
def test_route_rejects_invalid_coordinates(start, end):
    response = client.get(
        "/api/evac/route",
        params={"start": start, "end": end},
    )
    assert response.status_code == 422


def test_route_returns_geojson_and_measured_metadata(isolated_service_state):
    isolated_service_state.graph = _simple_graph()
    _empty_flood(isolated_service_state)

    response = client.get(
        "/api/evac/route",
        params={"start": "52.0,21.0", "end": "52.0,21.001"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"]["geometry"]["type"] == "LineString"
    assert payload["route"]["properties"]["length_m"] == pytest.approx(68.5)
    assert payload["meta"]["calc_time_ms"] >= 0
    assert payload["meta"]["start_snap_distance_m"] == 0


def test_missing_flood_data_does_not_fail_open(isolated_service_state):
    isolated_service_state.graph = _simple_graph()
    response = client.get(
        "/api/evac/route",
        params={"start": "52.0,21.0", "end": "52.0,21.001"},
    )
    assert response.status_code == 503


def test_missing_sentinel_configuration_returns_503(monkeypatch):
    monkeypatch.delenv("SENTINELHUB_INSTANCE_ID", raising=False)
    monkeypatch.delenv("INSTANCE_ID", raising=False)
    response = client.post(
        "/api/admin/update-flood",
        json={"south": 52.2, "west": 20.9, "north": 52.3, "east": 21.0},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 503
    assert "Brak SENTINELHUB_INSTANCE_ID" in response.json()["detail"]


def test_upstream_failure_does_not_replace_existing_roads(monkeypatch, isolated_service_state):
    isolated_service_state.graph = _simple_graph()
    before = list(isolated_service_state.graph.edges())

    def unavailable(*args, **kwargs):
        raise requests.Timeout("private upstream URL must not reach the response")

    monkeypatch.setattr("src.api.routes.download_osm_roads", unavailable)
    response = client.post(
        "/api/admin/update-roads",
        json={"south": 52.2, "west": 20.9, "north": 52.3, "east": 21.0},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 502
    assert "private upstream" not in response.text
    assert list(isolated_service_state.graph.edges()) == before


def test_invalid_flood_update_preserves_last_valid_snapshot(isolated_service_state):
    _empty_flood(isolated_service_state)
    before = isolated_service_state.flood_path.read_bytes()
    from src.core.flood_intersector import FloodDataUnavailableError

    with pytest.raises(FloodDataUnavailableError):
        isolated_service_state.set_flood_geojson({"type": "FeatureCollection"})
    assert isolated_service_state.flood_path.read_bytes() == before

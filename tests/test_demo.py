from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import shape

from src.main import create_app

client = TestClient(create_app("demo"))


def analyze(scenario="detour", origin="west", destination="east"):
    response = client.post(
        "/api/demo/analyze",
        json={"scenario": scenario, "origin": origin, "destination": destination},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_demo_runs_without_external_services_keys_or_writable_data(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Demo must not call external services or write runtime data")

    monkeypatch.delenv("SENTINELHUB_INSTANCE_ID", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("requests.get", forbidden)
    monkeypatch.setattr("requests.post", forbidden)
    monkeypatch.setattr("src.core.io_utils.write_json_atomic", forbidden)
    result = analyze()
    assert result["status"] == "found"
    assert result["data_mode"] == "sample"
    assert not list(tmp_path.iterdir())


def test_clear_scenario_has_identical_routes_and_no_blocked_edges():
    result = analyze("clear")
    assert result["route"]["geometry"] == result["baseline"]["geometry"]
    assert result["metrics"]["extra_distance_m"] == 0
    assert result["metrics"]["blocked_segments"] == 0
    assert result["flood"]["features"] == []


def test_detour_is_longer_and_does_not_cross_flood():
    result = analyze()
    metrics = result["metrics"]
    flood = shape(result["flood"]["features"][0]["geometry"])
    route = shape(result["route"]["geometry"])
    baseline = shape(result["baseline"]["geometry"])
    assert baseline.intersection(flood).length > 0
    assert not route.intersects(flood)
    assert metrics["blocked_segments"] == len(result["blocked"]["features"]) == 4
    assert metrics["route_length_m"] > metrics["baseline_length_m"] > 0
    assert metrics["extra_distance_m"] == pytest.approx(
        metrics["route_length_m"] - metrics["baseline_length_m"]
    )
    assert metrics["nodes"] == 15
    assert metrics["total_segments"] == 22
    assert result["route"]["geometry"]["coordinates"][0] == [16.98, 51.103]
    assert result["route"]["geometry"]["coordinates"][-1] == [16.996, 51.103]


def test_cutoff_returns_explicit_unreachable_result_instead_of_inventing_route():
    result = analyze("cutoff")
    assert result["status"] == "unreachable"
    assert result["route"] is None
    assert result["baseline"] is not None
    assert result["metrics"]["route_length_m"] is None
    assert result["metrics"]["extra_distance_m"] is None


def test_isolated_origin_is_not_moved_to_reachable_neighbor():
    result = analyze("detour", origin="center")
    assert result["status"] == "unreachable"
    assert result["route"] is None


def test_same_point_returns_zero_distance_without_division_by_zero():
    result = analyze("clear", origin="west", destination="west")
    assert result["status"] == "found"
    assert result["metrics"]["route_length_m"] == 0
    assert result["metrics"]["extra_distance_percent"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"scenario": "unknown"},
        {"origin": "not-a-node"},
        {"destination": [16, 51]},
        {"scenario": None},
        {"admin_key": "ignored-field-must-not-be-accepted"},
    ],
)
def test_demo_rejects_unknown_scenarios_points_and_extra_fields(payload):
    assert client.post("/api/demo/analyze", json=payload).status_code == 422


def test_public_demo_does_not_register_live_or_admin_routes():
    schema = client.get("/openapi.json").json()
    assert not any("/admin/" in path or "/debug/" in path for path in schema["paths"])
    assert "/api/evac/route" not in schema["paths"]
    assert client.post("/api/admin/update-roads", json={}).status_code == 405
    assert client.get("/api/debug/flood-geojson").status_code == 404


def test_request_body_limit_also_applies_to_chunked_input():
    response = client.post("/api/demo/analyze", content=iter([b"x" * 3000, b"x" * 3000]))
    assert response.status_code == 413


def test_sample_scenarios_are_isolated_under_concurrent_requests():
    scenarios = ["detour", "cutoff", "clear"] * 4
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(analyze, scenarios))
    for scenario, result in zip(scenarios, results, strict=True):
        assert result["scenario"] == scenario
        assert result["status"] == ("unreachable" if scenario == "cutoff" else "found")
        if scenario == "clear":
            assert result["metrics"]["blocked_segments"] == 0
    assert analyze("detour")["route"]["geometry"] == results[0]["route"]["geometry"]


def test_app_and_assets_available_with_security_headers():
    assert client.get("/health").json()["mode"] == "demo"
    for path in ["/", "/app.js", "/styles.css"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert client.get("/api/demo/scenarios").json()["data_mode"] == "sample"


def test_invalid_mode_fails_with_configuration_error():
    with pytest.raises(RuntimeError, match="APP_MODE"):
        create_app("typo")

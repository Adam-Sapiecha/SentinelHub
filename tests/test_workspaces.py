import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
from fastapi.testclient import TestClient
from shapely.geometry import shape

from src.main import create_app
from src.manage import restore
from src.services.workspace_store import StoreError, WorkspaceStore


@pytest.fixture
def application(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    with TestClient(create_app("application", db_path=path)) as client:
        yield client, path


def create(client, name="Prywatna analiza"):
    response = client.post("/api/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def headers(owner):
    return {"Authorization": "Bearer " + owner["key"]}


def test_retention_expires_only_new_public_workspaces(tmp_path, monkeypatch):
    path = tmp_path / "retention.sqlite3"
    persistent = WorkspaceStore(path)
    persistent.initialize()
    existing = persistent.create("Owner data")
    monkeypatch.setenv("WORKSPACE_TTL_HOURS", "24")
    public = WorkspaceStore(path)
    visitor = public.create("Temporary visitor")
    with public.connection(write=True) as db:
        db.execute(
            "UPDATE workspaces SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (visitor["id"],),
        )
    assert not public.authenticate(visitor["id"], visitor["key"])
    assert public.cleanup_expired() == 1
    assert public.authenticate(existing["id"], existing["key"])
    assert public.get(existing["id"])["name"] == "Owner data"
    assert public.cleanup_expired() == 0


def test_v1_migration_keeps_existing_data_and_does_not_expire_it(tmp_path, monkeypatch):
    from src.services.workspace_store import MIGRATIONS

    path = tmp_path / "previous-version.sqlite3"
    with sqlite3.connect(path) as db:
        for statement in MIGRATIONS[1]:
            db.execute(statement)
        db.execute(
            "INSERT INTO workspaces(id,name,owner_hash,created_at) "
            "VALUES('old','Existing','hash','2026-01-01')"
        )
        db.execute("PRAGMA user_version=1")
    monkeypatch.setenv("WORKSPACE_TTL_HOURS", "24")
    store = WorkspaceStore(path)
    store.initialize()
    store.initialize()
    assert store.get("old")["name"] == "Existing"
    assert store.cleanup_expired() == 0
    with store.connection() as db:
        assert (
            db.execute("SELECT expires_at FROM workspaces WHERE id=?", ("old",)).fetchone()[0]
            is None
        )


def url(owner, suffix=""):
    return f"/api/workspaces/{owner['id']}{suffix}"


def pair(revision=0):
    def road(a, b):
        return {
            "type": "Feature",
            "properties": {"highway": "residential"},
            "geometry": {"type": "LineString", "coordinates": [a, b]},
        }

    a, b, c, d = [21, 52], [21.002, 52], [21, 52.002], [21.002, 52.002]
    roads = {
        "type": "FeatureCollection",
        "features": [road(a, b), road(a, c), road(c, d), road(d, b)],
    }
    flood = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [21.0008, 51.9998],
                            [21.0012, 51.9998],
                            [21.0012, 52.0002],
                            [21.0008, 52.0002],
                            [21.0008, 51.9998],
                        ]
                    ],
                },
            }
        ],
    }
    return {
        "revision": revision,
        "roads": roads,
        "flood": flood,
        "source": "Test własnego wejścia",
        "observed_at": "2026-01-01T10:00:00+00:00",
    }


def seed(client, owner):
    response = client.put(url(owner, "/datasets"), json=pair(), headers=headers(owner))
    assert response.status_code == 200, response.text


def route(client, owner, revision=1):
    return client.post(
        url(owner, "/analyses"),
        json={
            "revision": revision,
            "start": {"lat": 52, "lon": 21},
            "end": {"lat": 52, "lon": 21.002},
        },
        headers=headers(owner),
    )


def test_user_input_runs_real_algorithm_and_persists_snapshot(application):
    client, path = application
    owner = create(client)
    seed(client, owner)
    response = route(client, owner)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["data_mode"] == "user"
    assert result["metrics"]["blocked_segments"] == 1
    assert result["metrics"]["route_length_m"] > result["metrics"]["baseline_length_m"]
    assert not shape(result["route"]["geometry"]).intersects(
        shape(pair()["flood"]["features"][0]["geometry"])
    )
    assert owner["key"].encode() not in path.read_bytes()
    saved = client.get(url(owner, f"/analyses/{result['analysis_id']}"), headers=headers(owner))
    assert saved.json() == result


def test_restart_preserves_data_ownership_and_history(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    with TestClient(create_app("application", db_path=path)) as client:
        owner = create(client)
        seed(client, owner)
        result = route(client, owner).json()
    with TestClient(create_app("application", db_path=path)) as restarted:
        data = restarted.get(url(owner), headers=headers(owner)).json()
        assert data["datasets"]["roads"] == pair()["roads"]
        assert data["revision"] == 1
        assert (
            restarted.get(
                url(owner, f"/analyses/{result['analysis_id']}"), headers=headers(owner)
            ).json()
            == result
        )
        assert restarted.get("/ready").status_code == 200


def test_other_owner_and_unauthenticated_user_cannot_read_or_write(application):
    client, _ = application
    a, b = create(client), create(client)
    seed(client, a)
    result = route(client, a).json()
    for method, suffix, body in [
        ("GET", "", None),
        ("GET", "/analyses", None),
        ("GET", f"/analyses/{result['analysis_id']}", None),
        ("PUT", "/datasets", pair(1)),
        ("DELETE", "", None),
        ("POST", "/rotate-key", {}),
    ]:
        assert client.request(method, url(a, suffix), json=body).status_code == 401
        assert (
            client.request(method, url(a, suffix), json=body, headers=headers(b)).status_code == 401
        )
    assert (
        client.get(url(b, f"/analyses/{result['analysis_id']}"), headers=headers(b)).status_code
        == 404
    )


def test_rotation_invalidates_old_key(application):
    client, _ = application
    owner = create(client)
    value = client.post(url(owner, "/rotate-key"), headers=headers(owner)).json()
    assert client.get(url(owner), headers=headers(owner)).status_code == 401
    owner["key"] = value["key"]
    assert client.get(url(owner), headers=headers(owner)).status_code == 200


def test_concurrent_dataset_edits_detect_conflict(application):
    client, _ = application
    owner = create(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: client.put(url(owner, "/datasets"), json=pair(), headers=headers(owner)),
                range(2),
            )
        )
    assert sorted(item.status_code for item in responses) == [200, 409]
    assert client.get(url(owner), headers=headers(owner)).json()["revision"] == 1


@pytest.mark.parametrize(
    "kind,geometry",
    [
        ("roads", {"type": "Point", "coordinates": [21, 52]}),
        ("roads", {"type": "LineString", "coordinates": [[200, 52], [200.01, 52]]}),
        ("roads", {"type": "LineString", "coordinates": [[21, 52], [22, 53]]}),
        ("flood", {"type": "LineString", "coordinates": [[21, 52], [21.1, 52]]}),
        ("flood", {"type": "Polygon", "coordinates": [[[21, 52], [21, 52]]]}),
    ],
)
def test_invalid_upload_is_rejected_without_replacing_data(application, kind, geometry):
    client, _ = application
    owner = create(client)
    seed(client, owner)
    data = pair(1)
    data[kind]["features"][0]["geometry"] = geometry
    assert client.put(url(owner, "/datasets"), json=data, headers=headers(owner)).status_code == 422
    assert client.get(url(owner), headers=headers(owner)).json()["revision"] == 1


def test_missing_flood_is_not_synthesized(application):
    client, _ = application
    owner = create(client)
    data = pair()
    del data["flood"]
    assert client.put(url(owner, "/datasets"), json=data, headers=headers(owner)).status_code == 422
    assert route(client, owner).status_code == 409


def test_explicit_empty_flood_is_valid(application):
    client, _ = application
    owner = create(client)
    data = pair()
    data["flood"]["features"] = []
    assert client.put(url(owner, "/datasets"), json=data, headers=headers(owner)).status_code == 200
    result = route(client, owner).json()
    assert result["metrics"]["blocked_segments"] == 0
    assert result["metrics"]["extra_distance_m"] == 0


def test_history_keeps_input_snapshot_after_dataset_replacement(application):
    client, _ = application
    owner = create(client)
    seed(client, owner)
    old = route(client, owner).json()
    data = pair(1)
    data["flood"]["features"] = []
    assert client.put(url(owner, "/datasets"), json=data, headers=headers(owner)).status_code == 200
    assert route(client, owner, 1).status_code == 409
    assert route(client, owner, 2).json()["metrics"]["blocked_segments"] == 0
    assert (
        client.get(url(owner, f"/analyses/{old['analysis_id']}"), headers=headers(owner)).json()
        == old
    )


def test_sample_reset_does_not_delete_private_data(application):
    client, _ = application
    owner = create(client)
    seed(client, owner)
    result = route(client, owner).json()
    assert client.post("/api/demo/analyze", json={"scenario": "clear"}).status_code == 200
    assert (
        client.get(
            url(owner, f"/analyses/{result['analysis_id']}"), headers=headers(owner)
        ).status_code
        == 200
    )


def test_external_import_requires_both_owner_and_operator(application, monkeypatch):
    client, _ = application
    owner = create(client)
    monkeypatch.setenv("ADMIN_API_KEY", "operator-test-key-of-at-least-32-characters")
    payload = {
        "revision": 0,
        "provider": "overpass",
        "bbox": {"south": 52.2, "west": 20.9, "north": 52.21, "east": 20.91},
    }
    assert (
        client.post(url(owner, "/imports"), json=payload, headers=headers(owner)).status_code == 403
    )
    assert (
        client.post(
            url(owner, "/imports"),
            json=payload,
            headers={"X-Admin-Key": "operator-test-key-of-at-least-32-characters"},
        ).status_code
        == 401
    )


def test_missing_real_sentinel_configuration_fails_explicitly(application, monkeypatch):
    client, _ = application
    owner = create(client)
    monkeypatch.delenv("SENTINELHUB_INSTANCE_ID", raising=False)
    monkeypatch.setenv("ADMIN_API_KEY", "operator-test-key-of-at-least-32-characters")
    response = client.post(
        url(owner, "/imports"),
        json={
            "revision": 0,
            "provider": "sentinel",
            "bbox": {"south": 52.2, "west": 20.9, "north": 52.21, "east": 20.91},
        },
        headers={**headers(owner), "X-Admin-Key": "operator-test-key-of-at-least-32-characters"},
    )
    assert response.status_code == 503
    assert client.get(url(owner), headers=headers(owner)).json()["datasets"] is None


def test_upstream_timeout_does_not_replace_uploaded_inputs(application, monkeypatch):
    client, _ = application
    owner = create(client)
    seed(client, owner)
    monkeypatch.setenv("ADMIN_API_KEY", "operator-test-key-of-at-least-32-characters")

    def fail(*args, **kwargs):
        raise requests.Timeout("private-url")

    monkeypatch.setattr("src.api.workspace_routes.download_osm_roads", fail)
    response = client.post(
        url(owner, "/imports"),
        json={
            "revision": 1,
            "provider": "overpass",
            "bbox": {"south": 52.2, "west": 20.9, "north": 52.21, "east": 20.91},
        },
        headers={**headers(owner), "X-Admin-Key": "operator-test-key-of-at-least-32-characters"},
    )
    assert response.status_code == 502 and "private-url" not in response.text
    assert (
        client.get(url(owner), headers=headers(owner)).json()["datasets"]["roads"]
        == pair()["roads"]
    )


def test_backup_restores_permissions_datasets_and_analysis(application, tmp_path):
    client, path = application
    owner = create(client)
    seed(client, owner)
    result = route(client, owner).json()
    backup = tmp_path / "backup.sqlite3"
    destination = tmp_path / "restore" / "state.sqlite3"
    WorkspaceStore(path).backup(backup)
    restore(backup, destination)
    with TestClient(create_app("application", db_path=destination)) as restored:
        assert restored.get(url(owner), headers=headers(owner)).json()["revision"] == 1
        assert (
            restored.get(
                url(owner, f"/analyses/{result['analysis_id']}"), headers=headers(owner)
            ).json()
            == result
        )
    with pytest.raises(StoreError):
        restore(backup, destination)


def test_newer_schema_is_not_reset_or_silently_downgraded(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(StoreError):
        WorkspaceStore(path).initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_corrupt_backup_is_rejected_without_creating_destination(tmp_path):
    source = tmp_path / "corrupt.sqlite3"
    source.write_bytes(b"not a sqlite database")
    destination = tmp_path / "recovered.sqlite3"
    with pytest.raises(sqlite3.DatabaseError):
        restore(source, destination)
    assert not destination.exists()


def test_owner_delete_does_not_affect_other_workspaces(application):
    client, _ = application
    a, b = create(client), create(client)
    seed(client, a)
    seed(client, b)
    assert client.delete(url(a), headers=headers(a)).status_code == 204
    assert client.get(url(a), headers=headers(a)).status_code == 401
    assert client.get(url(b), headers=headers(b)).json()["datasets"]["roads"] == pair()["roads"]


def test_large_dataset_rejected_before_graph_processing(application):
    client, _ = application
    owner = create(client)
    data = pair()
    data["roads"]["oversize"] = "x" * 1048576
    assert client.put(url(owner, "/datasets"), json=data, headers=headers(owner)).status_code == 422


def test_api_never_returns_owner_digest(application):
    client, _ = application
    owner = create(client)
    response = client.get(url(owner), headers=headers(owner))
    assert "owner_hash" not in response.text
    assert owner["key"] not in response.text
    assert "private workspaces" in json.dumps(client.get("/openapi.json").json())


def test_creation_quota_limits_persistent_public_storage(application):
    client, _ = application
    for _ in range(25):
        create(client)
    assert client.post("/api/workspaces", json={"name": "over quota"}).status_code == 507


def test_history_retention_is_bounded_without_deleting_datasets(application):
    client, _ = application
    owner = create(client)
    seed(client, owner)
    oldest = route(client, owner).json()["analysis_id"]
    for _ in range(10):
        assert route(client, owner).status_code == 201
    assert len(client.get(url(owner, "/analyses"), headers=headers(owner)).json()) == 10
    assert client.get(url(owner, "/analyses/" + oldest), headers=headers(owner)).status_code == 404
    assert (
        client.get(url(owner), headers=headers(owner)).json()["datasets"]["roads"]
        == pair()["roads"]
    )


def test_edit_during_calculation_cannot_save_result_with_wrong_revision(application, monkeypatch):
    from src.api import workspace_routes

    client, path = application
    owner = create(client)
    seed(client, owner)
    original = workspace_routes.analyze_datasets

    def edit_mid_calculation(datasets, start, end):
        current = WorkspaceStore(path).get(owner["id"])
        WorkspaceStore(path).replace_datasets(owner["id"], 1, current["datasets"])
        return original(datasets, start, end)

    monkeypatch.setattr(workspace_routes, "analyze_datasets", edit_mid_calculation)
    assert route(client, owner).status_code == 409
    assert client.get(url(owner, "/analyses"), headers=headers(owner)).json() == []


def test_overpass_whole_way_cannot_create_route_outside_flood_coverage():
    from src.services.dataset_service import roads_inside_coverage

    feature = {
        "type": "Feature",
        "properties": {"highway": "residential", "osm_node_ids": ["1", "2", "3", "4"]},
        "geometry": {
            "type": "LineString",
            "coordinates": [[20.9, 52], [21.001, 52], [21.002, 52], [21.1, 52]],
        },
    }
    clipped = roads_inside_coverage(
        {"type": "FeatureCollection", "features": [feature]}, (51.999, 21, 52.003, 21.003)
    )
    assert len(clipped["features"]) == 1
    assert clipped["features"][0]["geometry"]["coordinates"] == [[21.001, 52], [21.002, 52]]
    assert clipped["features"][0]["properties"]["osm_node_ids"] == ["2", "3"]

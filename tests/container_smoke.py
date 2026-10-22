"""Stdlib checks against the complete Compose ingress, not a mocked TestClient."""

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request


def main() -> None:
    base = os.getenv("DEMO_URL", "http://127.0.0.1:8090")

    def request(path, payload=None, method=None, headers=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    status, body, _ = request("/health")
    assert status == 200 and json.loads(body)["mode"] == "application"
    assert request("/ready")[0] == 200
    for path in ["/", "/app.js", "/styles.css", "/docs", "/openapi.json"]:
        status, _, headers = request(path)
        assert status == 200, (path, status)
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    for scenario in ["detour", "clear", "cutoff"]:
        status, body, _ = request("/api/demo/analyze", {"scenario": scenario})
        result = json.loads(body)
        assert status == 200 and result["data_mode"] == "sample", body
        assert result["status"] == ("unreachable" if scenario == "cutoff" else "found")
    assert request("/api/demo/analyze", {"scenario": "invalid"})[0] == 422
    assert request("/api/admin/update-roads", {})[0] == 404
    assert request("/api/debug/flood-geojson")[0] == 404
    assert request("/.env")[0] == 404
    assert request("/api/demo/analyze", {"scenario": "x" * 5000})[0] == 413
    from pathlib import Path

    status, body, _ = request("/api/workspaces", {"name": "Ingress verification"})
    assert status == 201, body
    owner = json.loads(body)
    prefix = "/api/workspaces/" + owner["id"]
    auth = {"Authorization": "Bearer " + owner["key"]}
    examples = Path(__file__).resolve().parents[1] / "examples"
    datasets = {
        "revision": 0,
        "source": "Synthetic ingress fixture",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "sample": True,
        "roads": json.loads((examples / "roads.geojson").read_text()),
        "flood": json.loads((examples / "flood.geojson").read_text()),
    }
    assert request(prefix + "/datasets", datasets, "PUT", auth)[0] == 200
    status, body, _ = request(
        prefix + "/analyses",
        {"revision": 1, "start": {"lat": 52, "lon": 21}, "end": {"lat": 52, "lon": 21.002}},
        headers=auth,
    )
    assert status == 201, body
    result = json.loads(body)
    assert result["metrics"]["blocked_segments"] == 1
    assert request(prefix + "/analyses/" + result["analysis_id"])[0] == 401
    assert request(prefix + "/analyses/" + result["analysis_id"], headers=auth)[0] == 200
    if os.getenv("VERIFY_CONTAINER_RESTART") == "1":
        command = shlex.split(os.getenv("DOCKER_COMMAND", "docker"))
        subprocess.run([*command, "compose", "restart", "api"], check=True)
        for _ in range(30):
            if request("/ready")[0] == 200:
                break
            time.sleep(1)
        assert request(prefix + "/analyses/" + result["analysis_id"], headers=auth)[0] == 200
        assert request(prefix, headers=auth)[0] == 200
    assert request(prefix, method="DELETE", headers=auth)[0] == 204
    print("Ingress PASS: readiness/assets, sample, private upload/calculation/history/auth/delete.")


if __name__ == "__main__":
    main()

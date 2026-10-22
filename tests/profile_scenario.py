"""Synthetic bounded workload; run locally, never against user data."""

import ctypes
import json
import os
import platform
import statistics
import tempfile
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from src.main import create_app


def peak_rss():
    if os.name != "nt":
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("faults", ctypes.c_ulong),
            *[
                (name, ctypes.c_size_t)
                for name in [
                    "peak",
                    "working",
                    "quota_peak_paged",
                    "quota_paged",
                    "quota_peak_nonpaged",
                    "quota_nonpaged",
                    "pagefile",
                    "peak_pagefile",
                ]
            ],
        ]

    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = ctypes.c_void_p
    measure = ctypes.windll.psapi.GetProcessMemoryInfo
    measure.argtypes = [ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong]
    if not measure(current(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.peak


def main():
    features = []
    for index in range(30):
        for vertical in [False, True]:
            coordinates = [
                [
                    21 + (index if vertical else step) * 0.0001,
                    52 + (step if vertical else index) * 0.0001,
                ]
                for step in range(30)
            ]
            features.append(
                {
                    "type": "Feature",
                    "properties": {"highway": "residential"},
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                }
            )
    data = {
        "roads": {"type": "FeatureCollection", "features": features},
        "flood": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [21.0013, 52.0008],
                                [21.0016, 52.0008],
                                [21.0016, 52.0021],
                                [21.0013, 52.0021],
                                [21.0013, 52.0008],
                            ]
                        ],
                    },
                }
            ],
        },
        "source": "Synthetic 30 x 30 grid with flood; resource check",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "sample": True,
        "revision": 0,
    }
    durations = []
    with (
        tempfile.TemporaryDirectory(prefix="sentinelhub-profile-") as directory,
        TestClient(create_app("application", db_path=Path(directory) / "state.sqlite3")) as client,
    ):
        owner = client.post("/api/workspaces", json={"name": "Bounded profile"}).json()
        headers = {"Authorization": "Bearer " + owner["key"]}
        prefix = "/api/workspaces/" + owner["id"]
        response = client.put(prefix + "/datasets", json=data, headers=headers)
        assert response.status_code == 200, response.text
        for _ in range(5):
            started = perf_counter()
            response = client.post(
                prefix + "/analyses",
                json={
                    "revision": 1,
                    "start": {"lat": 52, "lon": 21},
                    "end": {"lat": 52.0029, "lon": 21.0029},
                },
                headers=headers,
            )
            assert response.status_code == 201, response.text
            durations.append((perf_counter() - started) * 1000)
        result = response.json()
    print(
        json.dumps(
            {
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "python": platform.python_version(),
                "workload": "900 nodes / 1740 segments, flood rectangle, sequential",
                "requests": 5,
                "median_request_ms": round(statistics.median(durations), 2),
                "min_ms": round(min(durations), 2),
                "max_ms": round(max(durations), 2),
                "peak_process_rss_mib": round(peak_rss() / 1024 / 1024, 2),
                "result_nodes": result["metrics"]["nodes"],
                "result_segments": result["metrics"]["total_segments"],
                "scope": "Includes TestClient, validation/imports and SQLite; "
                "excludes Nginx. Architecture is reported above.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

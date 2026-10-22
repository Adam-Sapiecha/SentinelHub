from datetime import date, timedelta
from io import BytesIO

import numpy as np
import pytest
import requests
from PIL import Image

from src.core.sentinel_flood_ogc_client import (
    SentinelHubServiceError,
    SentinelOGCConfig,
    SentinelOGCFloodClient,
)


def test_default_sentinel_time_range_tracks_current_date():
    config = SentinelOGCConfig(instance_id="test")
    expected_start = (date.today() - timedelta(days=30)).isoformat()
    assert config.effective_time == f"{expected_start}/{date.today().isoformat()}"


@pytest.mark.parametrize("time_range", ["invalid", "2026-09-07/2026-01-01"])
def test_sentinel_time_range_is_validated(time_range):
    with pytest.raises(ValueError):
        SentinelOGCConfig(instance_id="test", time=time_range)


def test_image_to_water_mask_uses_configured_blue_threshold(tmp_path):
    client = SentinelOGCFloodClient(
        SentinelOGCConfig(instance_id="test"),
        flood_path=tmp_path / "flood.geojson",
    )
    image = Image.fromarray(
        np.array([[[0, 0, 200], [200, 0, 0]]], dtype=np.uint8),
        mode="RGB",
    )
    assert client._image_to_water_mask(image).tolist() == [[True, False]]


def test_transparent_blue_pixel_is_not_classified_as_water(tmp_path):
    client = SentinelOGCFloodClient(SentinelOGCConfig(instance_id="test"), tmp_path / "flood")
    image = Image.fromarray(np.array([[[0, 0, 255, 0], [0, 0, 255, 255]]], dtype=np.uint8))
    assert client._image_to_water_mask(image).tolist() == [[False, True]]


def test_mask_to_polygons_maps_first_row_to_north(tmp_path):
    client = SentinelOGCFloodClient(
        SentinelOGCConfig(instance_id="test"),
        flood_path=tmp_path / "flood.geojson",
    )
    mask = np.zeros((4, 4), dtype=bool)
    mask[0, :] = True
    mask[1, :] = True
    polygons = client._mask_to_polygons(mask, (0.0, 0.0, 4.0, 4.0))

    assert len(polygons) == 1
    assert polygons[0].bounds == (0.0, 2.0, 4.0, 4.0)


def test_expired_account_error_is_actionable_and_does_not_expose_instance_id(monkeypatch, tmp_path):
    instance_id = "private-instance-id"
    response = requests.Response()
    response.status_code = 403
    response.headers["Content-Type"] = "application/xml"
    response.raw = BytesIO(b"<ServiceException>Account has expired</ServiceException>")

    monkeypatch.setattr(
        "src.core.sentinel_flood_ogc_client.requests.get",
        lambda *args, **kwargs: response,
    )
    client = SentinelOGCFloodClient(
        SentinelOGCConfig(instance_id=instance_id),
        flood_path=tmp_path / "flood.geojson",
    )

    with pytest.raises(SentinelHubServiceError, match="Konto Sentinel Hub wygasło") as error:
        client._fetch_wms_png((52.2, 20.9, 52.3, 21.0))

    assert instance_id not in str(error.value)


def test_wms_rejects_unexpected_raster_dimensions(monkeypatch, tmp_path):
    output = BytesIO()
    Image.new("RGB", (8, 8)).save(output, format="PNG")
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "image/png"
    response.raw = BytesIO(output.getvalue())
    monkeypatch.setattr(
        "src.core.sentinel_flood_ogc_client.requests.get", lambda *args, **kwargs: response
    )
    client = SentinelOGCFloodClient(SentinelOGCConfig(instance_id="test"), tmp_path / "flood")
    with pytest.raises(RuntimeError, match="rozmiar obrazu"):
        client._fetch_wms_png((52.2, 20.9, 52.3, 21.0))


def test_fully_transparent_wms_is_unknown_not_a_dry_area(monkeypatch, tmp_path):
    output = BytesIO()
    Image.new("RGBA", (512, 512), (0, 0, 255, 0)).save(output, format="PNG")
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "image/png"
    response.raw = BytesIO(output.getvalue())
    monkeypatch.setattr(
        "src.core.sentinel_flood_ogc_client.requests.get", lambda *args, **kwargs: response
    )
    client = SentinelOGCFloodClient(SentinelOGCConfig(instance_id="test"), tmp_path / "flood")
    with pytest.raises(RuntimeError, match="nie zawiera widocznych"):
        client._fetch_wms_png((52.2, 20.9, 52.3, 21.0))


def test_upstream_response_limit_stops_reading_and_closes_connection():
    from src.core.http_utils import read_limited

    response = requests.Response()
    response.raw = BytesIO(b"x" * 65536)
    with pytest.raises(ValueError, match="przekracza limit"):
        read_limited(response, limit=100)
    assert response.raw.closed


def test_partial_nodata_raster_cannot_mark_unknown_roads_as_available(monkeypatch, tmp_path):
    output = BytesIO()
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.save(output, format="PNG")
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "image/png"
    response.raw = BytesIO(output.getvalue())
    monkeypatch.setattr(
        "src.core.sentinel_flood_ogc_client.requests.get", lambda *args, **kwargs: response
    )
    client = SentinelOGCFloodClient(SentinelOGCConfig(instance_id="test"), tmp_path / "flood")
    with pytest.raises(RuntimeError, match="obszary bez wiarygodnych"):
        client._fetch_wms_png((52.2, 20.9, 52.3, 21.0))

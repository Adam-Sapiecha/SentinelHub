import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image, UnidentifiedImageError
from shapely.geometry import MultiPolygon, Polygon, box, mapping
from shapely.ops import unary_union

from .config import FLOOD_PATH
from .http_utils import read_limited
from .io_utils import write_json_atomic

logger = logging.getLogger(__name__)


# ======================= KONFIGURACJA / STAŁE =======================

WMS_WIDTH = 512
WMS_HEIGHT = 512

BLUE_THRESHOLD = 180
RED_MAX = 30
GREEN_MAX = 30

BLOCK_SIZE = 4
MIN_FRACTION_IN_BLOCK = 0.1


class SentinelHubServiceError(RuntimeError):
    """A safe, user-facing description of an error returned by Sentinel Hub."""


def _sentinel_error_message(response: requests.Response, payload: bytes | None = None) -> str:
    """Translate known upstream failures without exposing response or request secrets."""
    response_text = (payload.decode(errors="replace") if payload is not None else response.text)[
        :8192
    ].lower()

    if "account has expired" in response_text:
        return (
            "Konto Sentinel Hub wygasło. Odnów dostęp do usługi albo ustaw w .env "
            "identyfikator instancji OGC z aktywnego konta."
        )
    if "layer" in response_text and (
        "does not exist" in response_text or "not found" in response_text
    ):
        return (
            "Warstwa FLOOD nie istnieje w konfiguracji Sentinel Hub. "
            "Dodaj ją w konfiguracji instancji OGC."
        )
    if response.status_code in {401, 403}:
        return (
            f"Sentinel Hub odmówił dostępu (HTTP {response.status_code}). "
            "Sprawdź stan konta i identyfikator instancji OGC."
        )

    return f"Sentinel Hub WMS zwrócił HTTP {response.status_code}."


def _default_time_range() -> str:
    end = date.today()
    start = end - timedelta(days=30)
    return f"{start.isoformat()}/{end.isoformat()}"


@dataclass(frozen=True)
class SentinelOGCConfig:
    """
    Konfiguracja klienta OGC WMS Sentinel Hub.
    Wymaga INSTANCE_ID z dashboardu.

    UWAGA: INSTANCE_ID to ID instancji (Configuration Utility),
    NIE client_id od OAuth!
    """

    instance_id: str
    base_url: str = "https://services.sentinel-hub.com/ogc/wms"
    layer: str = "FLOOD"
    time: str | None = None

    def __post_init__(self) -> None:
        if self.time is None:
            return
        try:
            start_text, end_text = self.time.split("/", maxsplit=1)
            start = date.fromisoformat(start_text)
            end = date.fromisoformat(end_text)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Zakres czasu Sentinel musi mieć format YYYY-MM-DD/YYYY-MM-DD"
            ) from error
        if start > end:
            raise ValueError("Początek zakresu Sentinel nie może być po jego końcu")

    @property
    def effective_time(self) -> str:
        return self.time or _default_time_range()


class SentinelOGCFloodClient:
    """
    Klient do pobierania mapy zalania z Sentinel Hub OGC WMS (PNG)
    i zapisywania jej jako flood.geojson – BEZ użycia rasterio.
    """

    def __init__(self, config: SentinelOGCConfig, flood_path: Path | None = None):
        self.config = config
        self.flood_path = flood_path or FLOOD_PATH
        self.flood_path.parent.mkdir(parents=True, exist_ok=True)

    # --------------- PUBLICZNE API ----------------

    def update_flood_for_bbox(self, bbox: tuple[float, float, float, float]) -> int:
        geojson = self.fetch_flood_geojson(bbox)
        self._save_geojson(geojson)
        return len(geojson["features"])

    def fetch_flood_geojson(self, bbox: tuple[float, float, float, float]) -> dict:
        """
        Główna metoda wołana z /admin/update-flood.

        bbox: (south, west, north, east) w WGS84.
        Zwraca liczbę zapisanych poligonów.
        """
        south, west, north, east = bbox
        logger.info(
            "Pobieram raster zalania z Sentinel Hub dla bbox S=%.6f, W=%.6f, N=%.6f, E=%.6f",
            south,
            west,
            north,
            east,
        )

        img = self._fetch_wms_png(bbox)
        mask = self._image_to_water_mask(img)
        coarse_mask = self._downsample_mask(mask, BLOCK_SIZE, MIN_FRACTION_IN_BLOCK)

        polygons = self._mask_to_polygons(coarse_mask, bbox)
        logger.info(
            "Wygenerowano %d poligonów zalania (po uproszczeniu z kafelków).", len(polygons)
        )

        return self._polygons_to_geojson(polygons)

    # --------------- KROK 1 – WMS PNG ----------------

    def _fetch_wms_png(self, bbox: tuple[float, float, float, float]) -> Image.Image:
        south, west, north, east = bbox

        url = f"{self.config.base_url}/{self.config.instance_id}"

        params = {
            "SERVICE": "WMS",
            "REQUEST": "GetMap",
            "VERSION": "1.3.0",
            "LAYERS": self.config.layer,
            "FORMAT": "image/png",
            "TRANSPARENT": "true",
            "CRS": "EPSG:4326",
            "BBOX": f"{south},{west},{north},{east}",
            "WIDTH": str(WMS_WIDTH),
            "HEIGHT": str(WMS_HEIGHT),
            "TIME": self.config.effective_time,
            "SHOWLOGO": "false",
        }

        logger.debug("Wysyłam zapytanie WMS do Sentinel Hub")
        resp = requests.get(url, params=params, timeout=(10, 60), stream=True)
        payload = read_limited(resp)

        if resp.status_code != 200:
            raise SentinelHubServiceError(_sentinel_error_message(resp, payload))
        if not resp.headers.get("Content-Type", "").lower().startswith("image/"):
            raise SentinelHubServiceError(_sentinel_error_message(resp, payload))

        try:
            with Image.open(BytesIO(payload)) as image:
                if image.size != (WMS_WIDTH, WMS_HEIGHT):
                    raise RuntimeError("Sentinel Hub WMS zwrócił nieoczekiwany rozmiar obrazu")
                image.load()
                result = image.convert("RGBA")
                if not result.getchannel("A").getbbox():
                    raise RuntimeError(
                        "WMS nie zawiera widocznych danych; "
                        "pusty raster nie potwierdza braku zalania"
                    )
                if result.getchannel("A").getextrema()[0] < 255:
                    raise RuntimeError(
                        "WMS zawiera obszary bez wiarygodnych danych; analiza odrzucona"
                    )
                return result
        except (UnidentifiedImageError, OSError) as error:
            raise RuntimeError("Sentinel Hub WMS zwrócił uszkodzony obraz") from error

    # --------------- KROK 2 – Maska wody z obrazka ----------------

    def _image_to_water_mask(self, img: Image.Image) -> np.ndarray:
        arr = np.asarray(img)  # (H, W, 3)
        r = arr[:, :, 0].astype(np.int16)
        g = arr[:, :, 1].astype(np.int16)
        b = arr[:, :, 2].astype(np.int16)

        water_mask = (b >= BLUE_THRESHOLD) & (r <= RED_MAX) & (g <= GREEN_MAX)
        if arr.shape[2] == 4:
            water_mask &= arr[:, :, 3] > 0

        logger.info(
            "Maska wody: %d pikseli zalanych na %d",
            int(water_mask.sum()),
            water_mask.size,
        )
        return water_mask

    # --------------- KROK 3 – Denoising / kafelki ----------------

    def _downsample_mask(
        self, mask: np.ndarray, block_size: int, min_fraction: float
    ) -> np.ndarray:
        h, w = mask.shape
        h2 = (h // block_size) * block_size
        w2 = (w // block_size) * block_size

        if h2 == 0 or w2 == 0:
            return np.zeros((0, 0), dtype=bool)

        if h2 != h or w2 != w:
            mask = mask[:h2, :w2]

        new_h = h2 // block_size
        new_w = w2 // block_size

        reshaped = mask.reshape(new_h, block_size, new_w, block_size)
        counts = reshaped.sum(axis=(1, 3))
        block_pixels = block_size * block_size
        threshold = min_fraction * block_pixels

        coarse_mask = counts >= threshold

        logger.info(
            "Downsample: %dx%d -> %dx%d, kafelki z wodą: %d",
            h,
            w,
            new_h,
            new_w,
            int(coarse_mask.sum()),
        )

        return coarse_mask

    # --------------- KROK 4 – maska -> poligony ----------------

    def _mask_to_polygons(
        self,
        coarse_mask: np.ndarray,
        bbox: tuple[float, float, float, float],
    ) -> list[Polygon]:
        """
        Zamiana maski flood (0/1) na poligony w układzie geograficznym.

        UWAGA: obrazek z WMS ma początek (0,0) w LEWYM GÓRNYM rogu,
        więc wiersz i=0 to NORTH, nie SOUTH → odwracamy oś Y.
        """
        if coarse_mask.size == 0 or not coarse_mask.any():
            logger.info("Brak pikseli wody po uproszczeniu maski.")
            return []

        south, west, north, east = bbox
        h2, w2 = coarse_mask.shape

        lat_step = (north - south) / h2
        lon_step = (east - west) / w2

        boxes = []
        for i in range(h2):
            for j in range(w2):
                if not coarse_mask[i, j]:
                    continue

                # tu była stara wersja – od dołu
                max_lat = north - i * lat_step
                min_lat = north - (i + 1) * lat_step

                min_lon = west + j * lon_step
                max_lon = west + (j + 1) * lon_step

                boxes.append(box(min_lon, min_lat, max_lon, max_lat))

        if not boxes:
            return []

        logger.info("Zbudowano %d kafelków z wodą, wykonuję unary_union…", len(boxes))
        merged = unary_union(boxes)

        polygons: list[Polygon] = []
        if isinstance(merged, Polygon):
            polygons = [merged]
        elif isinstance(merged, MultiPolygon):
            polygons = list(merged.geoms)
        else:
            for geom in getattr(merged, "geoms", []):
                if isinstance(geom, Polygon):
                    polygons.append(geom)
                elif isinstance(geom, MultiPolygon):
                    polygons.extend(list(geom.geoms))

        logger.info("Po union() zostało %d poligonów (przed filtrowaniem).", len(polygons))

        polygons = self._remove_small_polygons(
            polygons,
            lat_step=lat_step,
            lon_step=lon_step,
            min_cells=7,
        )

        return polygons

    # --------------- KROK 5 – zapis GeoJSON ----------------

    def _polygons_to_geojson(self, polygons: list[Polygon]) -> dict:
        features = []
        for idx, poly in enumerate(polygons):
            if poly.is_empty:
                continue
            feat = {
                "type": "Feature",
                "geometry": mapping(poly),
                "properties": {
                    "id": idx,
                    "source": "sentinelhub_ogc",
                },
            }
            features.append(feat)

        return {
            "type": "FeatureCollection",
            "features": features,
        }

    def _save_geojson(self, geojson: dict) -> None:
        write_json_atomic(self.flood_path, geojson)
        logger.info("Zapisano flood.geojson do %s", self.flood_path)

    def _remove_small_polygons(
        self,
        polygons: list[Polygon],
        lat_step: float,
        lon_step: float,
        min_cells: int = 3,
    ) -> list[Polygon]:
        """
        Usuwa bardzo małe poligony (pojedyncze 'kropki').

        min_cells – minimalna liczba kafelków coarse_mask, jaką
        powinien mniej więcej odpowiadać poligonowi, żeby go zostawić.
        """

        cell_area = abs(lat_step * lon_step)
        min_area = cell_area * min_cells

        filtered = [p for p in polygons if p.area >= min_area]

        logger.info(
            "Odfiltrowano małe plamki: %d -> %d poligonów (min_cells=%d)",
            len(polygons),
            len(filtered),
            min_cells,
        )
        return filtered


# ======================= FABRYKA KLIENTA =======================


def create_default_ogc_client() -> SentinelOGCFloodClient:
    """
    Tworzy klienta na podstawie SENTINELHUB_INSTANCE_ID / INSTANCE_ID z .env.
    """
    instance_id = os.getenv("SENTINELHUB_INSTANCE_ID") or os.getenv("INSTANCE_ID")
    if not instance_id:
        raise RuntimeError(
            "Brak SENTINELHUB_INSTANCE_ID (lub INSTANCE_ID) w .env – "
            "ustaw tam ID instancji z Sentinel Hub (NIE client_id OAuth)."
        )

    configured_time = os.getenv("SENTINELHUB_TIME_RANGE")
    try:
        config = SentinelOGCConfig(instance_id=instance_id, time=configured_time or None)
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    return SentinelOGCFloodClient(config=config, flood_path=FLOOD_PATH)

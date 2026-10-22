import logging
from pathlib import Path

import requests

from .http_utils import read_limited
from .osm_to_geojson import osm_to_roads_geojson, save_geojson

logger = logging.getLogger(__name__)


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT = (10, 60)


def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """
    bbox: (south, west, north, east)
    """
    south, west, north, east = bbox

    query = f"""
    [out:xml][timeout:25];
    (
      way["highway"]({south},{west},{north},{east});
    );
    (._;>;);
    out body;
    """
    return query.strip()


def download_osm_roads(bbox: tuple[float, float, float, float]) -> str:
    """
    Pobiera dane OSM (XML) dla dróg w zadanym bboxie.
    bbox: (south, west, north, east) w stopniach WGS84.
    Zwraca string z zawartością XML.
    """
    query = build_overpass_query(bbox)
    logger.info("Wysyłam zapytanie do Overpass API dla bbox=%s", bbox)

    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": "SentinelHub-Evacuation-Router/0.2"},
        timeout=OVERPASS_TIMEOUT,
        stream=True,
    )
    payload = read_limited(response)
    response.raise_for_status()

    logger.info("Odebrano dane z Overpass: %d bajtów", len(payload))
    return payload.decode("utf-8")


def download_and_save_roads_geojson(
    bbox: tuple[float, float, float, float],
    output_path: Path,
) -> None:
    """
    Główna funkcja:
    - pobiera OSM dla bbox,
    - konwertuje tylko drogi,
    - zapisuje jako GeoJSON.
    """
    osm_xml = download_osm_roads(bbox)
    geojson = osm_to_roads_geojson(osm_xml)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_geojson(geojson, str(output_path))

    logger.info(
        "Zapisano roads GeoJSON do pliku %s (liczba dróg: %d)",
        output_path,
        len(geojson["features"]),
    )


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) != 5:
        print("Użycie: python -m src.core.osm_downloader south west north east")
        print("Przykład: python -m src.core.osm_downloader 52.0 21.0 52.1 21.1")
        sys.exit(1)

    south = float(sys.argv[1])
    west = float(sys.argv[2])
    north = float(sys.argv[3])
    east = float(sys.argv[4])

    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    output = PROJECT_ROOT / "data" / "roads.geojson"

    download_and_save_roads_geojson((south, west, north, east), output)
    print("Gotowe. Zapisano do:", output)

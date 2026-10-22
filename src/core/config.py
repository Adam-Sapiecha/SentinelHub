import math
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _path_from_env(name: str, default: Path) -> Path:
    configured = os.getenv(name)
    if not configured:
        return default

    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


DATA_DIR = _path_from_env("DATA_DIR", PROJECT_ROOT / "data")
ROADS_PATH = DATA_DIR / "roads.geojson"
FLOOD_PATH = DATA_DIR / "flood.geojson"


def get_workspace_database() -> Path:
    name = os.getenv("WORKSPACE_DB_NAME", "sentinelhub.sqlite3")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.sqlite3", name):
        raise RuntimeError("WORKSPACE_DB_NAME musi być prostą nazwą pliku .sqlite3")
    return DATA_DIR / name


def _float_from_env(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} musi być liczbą") from error
    if not math.isfinite(value) or value < minimum:
        raise RuntimeError(f"{name} musi być liczbą nie mniejszą niż {minimum}")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} nie może być większe niż {maximum}")
    return value


MAX_BBOX_AREA_KM2 = _float_from_env("MAX_BBOX_AREA_KM2", 2500, minimum=0.001)
MAX_ROUTE_SNAP_DISTANCE_M = _float_from_env("MAX_ROUTE_SNAP_DISTANCE_M", 2000, minimum=0)
MIN_FLOOD_OVERLAP_RATIO = _float_from_env("MIN_FLOOD_OVERLAP_RATIO", 0.01, minimum=0, maximum=1)


def get_app_mode() -> str:
    mode = os.getenv("APP_MODE", "application")
    if mode not in {"application", "demo", "live"}:
        raise RuntimeError("APP_MODE musi mieć wartość application, demo lub live")
    return mode


def get_public_url() -> str | None:
    value = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or (parsed.path and not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", parsed.path))
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "PUBLIC_URL wymaga HTTP(S), opcjonalnej prostej ścieżki i braku danych dostępowych"
        )
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("PUBLIC_URL wymaga HTTPS poza lokalnym loopback")
    return value


def get_admin_api_key() -> str | None:
    """Read at request time so deployments can rotate the key without imports changing."""
    return os.getenv("ADMIN_API_KEY")


def get_allowed_origins() -> list[str]:
    configured = os.getenv("ALLOWED_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return ["http://localhost:8080", "http://127.0.0.1:8080"]

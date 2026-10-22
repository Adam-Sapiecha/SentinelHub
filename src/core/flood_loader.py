from pathlib import Path

from shapely.geometry import Polygon

from .flood_intersector import load_flood_geometries


class FloodLoader:
    """Load and normalize flood polygons from a WGS84 GeoJSON file."""

    def __init__(self, flood_path: Path):
        self.flood_path = flood_path

    def load_polygons(self) -> list[Polygon]:
        return load_flood_geometries(self.flood_path)

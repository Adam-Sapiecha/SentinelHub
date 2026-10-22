import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .io_utils import write_json_atomic


def osm_to_roads_geojson(osm_content: str) -> dict[str, Any]:
    """Convert OSM XML into road features without joining across missing nodes."""
    root = ET.fromstring(osm_content)
    nodes: dict[str, tuple[float, float]] = {}

    for node in root.findall("node"):
        node_id = node.get("id")
        latitude = node.get("lat")
        longitude = node.get("lon")
        if node_id is None or latitude is None or longitude is None:
            continue
        nodes[node_id] = (float(longitude), float(latitude))

    features: list[dict[str, Any]] = []
    for way in root.findall("way"):
        tags = {
            tag.get("k"): tag.get("v") for tag in way.findall("tag") if tag.get("k") is not None
        }
        if "highway" not in tags:
            continue

        contiguous_parts: list[list[str]] = []
        current_part: list[str] = []
        for reference_element in way.findall("nd"):
            reference = reference_element.get("ref")
            if reference is not None and reference in nodes:
                current_part.append(reference)
            else:
                if len(current_part) >= 2:
                    contiguous_parts.append(current_part)
                current_part = []
        if len(current_part) >= 2:
            contiguous_parts.append(current_part)

        for node_ids in contiguous_parts:
            properties = {
                **tags,
                "osm_way_id": way.get("id"),
                "osm_node_ids": node_ids,
            }
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [nodes[node_id] for node_id in node_ids],
                    },
                }
            )

    return {"type": "FeatureCollection", "features": features}


def save_geojson(geojson: dict[str, Any], path: str | Path) -> None:
    write_json_atomic(Path(path), geojson)

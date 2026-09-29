"""Spatial data layers for the rules engine.

RFZ zones load from ``data/rfz/*.geojson`` — the 286-zone eSUA snapshot lands
there via ``scripts/download_data.sh`` (override with the ``UTM_RFZ_GEOJSON``
env var). The real file is a FeatureCollection of Polygon features whose
properties carry the zone ``name`` (e.g. "Victoria Harbour") plus
``effectiveDateTime`` / ``description``; MultiPolygon is also accepted.

The population/buildings layer for the 30 m separation rule is not pipelined
yet (WorldPop ships GeoTIFF, buildings ship as 3D Tiles), so the rule accepts
explicitly supplied geometries and otherwise reports pending-data.
"""

import glob
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"

RFZ_ENV_VAR = "UTM_RFZ_GEOJSON"


@dataclass(frozen=True)
class Zone:
    zone_id: str
    name: str
    geometry: BaseGeometry  # WGS84 lon/lat


def _zone_from_feature(feature: dict) -> Zone | None:
    geometry = feature.get("geometry")
    if not geometry or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    props = feature.get("properties") or {}
    name = str(props.get("name") or props.get("zone_name") or "unnamed zone")
    zone_id = str(
        props.get("id") or props.get("zone_id") or feature.get("id") or name
    )
    return Zone(zone_id=zone_id, name=name, geometry=shape(geometry))


@lru_cache(maxsize=8)
def _load_zones(path: str) -> tuple[Zone, ...]:
    with open(path, encoding="utf-8") as f:
        collection = json.load(f)
    zones = []
    for feature in collection.get("features", []):
        zone = _zone_from_feature(feature)
        if zone is not None:
            zones.append(zone)
    return tuple(zones)


def default_rfz_path() -> str | None:
    env_path = os.environ.get(RFZ_ENV_VAR)
    if env_path:
        return env_path
    matches = sorted(glob.glob(str(DATA_DIR / "rfz" / "*.geojson")))
    return matches[0] if matches else None


def load_rfz_zones(path: str | None = None) -> list[Zone] | None:
    """Load RFZ zones; ``None`` means no RFZ data on disk (pending-data)."""
    resolved = path or default_rfz_path()
    if resolved is None or not os.path.exists(resolved):
        return None
    return list(_load_zones(resolved))


def load_geojson_geometries(path: str) -> list[BaseGeometry]:
    """All Polygon/MultiPolygon geometries from a GeoJSON file."""
    with open(path, encoding="utf-8") as f:
        collection = json.load(f)
    geometries = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry")
        if geometry and geometry.get("type") in ("Polygon", "MultiPolygon"):
            geometries.append(shape(geometry))
    return geometries


def default_obstacle_geometries() -> list[BaseGeometry] | None:
    """Population/buildings footprints for the separation rule.

    Returns ``None`` when no usable layer exists yet — the WorldPop grid is
    GeoTIFF and the building set is 3D Tiles, so until a footprints GeoJSON is
    derived into ``data/population/`` or ``data/buildings/`` the rule reports
    pending-data instead of silently passing.
    """
    for subdir in ("population", "buildings"):
        matches = sorted(glob.glob(str(DATA_DIR / subdir / "*.geojson")))
        if matches:
            return load_geojson_geometries(matches[0])
    return None

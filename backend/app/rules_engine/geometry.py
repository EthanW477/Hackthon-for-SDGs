"""GeoJSON parsing and projection helpers for the rules engine.

Routes arrive as GeoJSON LineStrings in WGS84 (lon/lat). Intersection tests
are topology-only and safe in lon/lat space; distance tests (the 30 m
separation rule) need metres, so we project through a local equirectangular
approximation anchored on Hong Kong — error stays well under 0.1% anywhere
inside the territory.
"""

from dataclasses import dataclass, field
from math import cos, radians
from typing import Any

from shapely.geometry import LineString
from shapely.ops import transform

HK_REFERENCE_LAT = 22.35
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * cos(radians(HK_REFERENCE_LAT))


def lonlat_to_m(lon: float, lat: float) -> tuple[float, float]:
    return lon * M_PER_DEG_LON, lat * M_PER_DEG_LAT


def _project(geom):
    return transform(lambda x, y, z=None: (x * M_PER_DEG_LON, y * M_PER_DEG_LAT), geom)


@dataclass
class Route:
    """Parsed route: raw coordinates plus cached shapely lines."""

    coordinates: list[list[float]]
    properties: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_geojson(cls, route_geojson: dict[str, Any]) -> "Route":
        """Accept a bare LineString geometry or a Feature wrapping one.

        Extra top-level keys on a bare LineString (e.g. ``time_window``) are
        treated as properties, so older clients sending a plain geometry keep
        working.
        """
        if route_geojson.get("type") == "Feature":
            geometry = route_geojson.get("geometry") or {}
            return cls(
                coordinates=geometry.get("coordinates", []),
                properties=route_geojson.get("properties") or {},
            )
        properties = {
            k: v for k, v in route_geojson.items() if k not in ("type", "coordinates")
        }
        return cls(
            coordinates=route_geojson.get("coordinates", []),
            properties=properties,
        )

    def line_lonlat(self) -> LineString | None:
        points = [(c[0], c[1]) for c in self.coordinates if len(c) >= 2]
        return LineString(points) if len(points) >= 2 else None

    def line_m(self) -> LineString | None:
        line = self.line_lonlat()
        return _project(line) if line is not None else None

    def segments_lonlat(self) -> list[LineString]:
        line = self.line_lonlat()
        if line is None:
            return []
        coords = list(line.coords)
        return [LineString([a, b]) for a, b in zip(coords, coords[1:])]


def project_geometry(geom):
    """Project a lon/lat shapely geometry into local metres."""
    return _project(geom)

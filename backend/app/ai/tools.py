"""LLM tools — six grounded data accessors (project-plan §4.4, Phase 2).

Adjudication MUST come only from ``evaluate_flight_plan`` via ``check_flight_plan``.
Regulation text MUST come only from ``app.rag.query`` via ``search_regulations``.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import httpx

from app.rag import RegulationStoreNotReady, query as rag_query
from app.rules_engine import evaluate_flight_plan
from app.rules_engine.layers import DATA_DIR, default_rfz_path, load_rfz_zones
from app.schemas.flight_plan import FlightPlanParams
from app.simulator import generate_tracks

REPO_ROOT = Path(__file__).resolve().parents[3]

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_flight_plan",
            "description": (
                "Run the authoritative CAD rules engine on a proposed route. "
                "Returns verdict approved/rejected, violations with regulation refs, "
                "and clause numbers. Always call this before stating whether a route may fly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "route": {
                        "type": "object",
                        "description": "GeoJSON Feature or LineString route with coordinates [lon, lat, alt_m].",
                    },
                    "params": {
                        "type": "object",
                        "description": "Flight plan params: max_altitude_ft, aircraft_category, time_window, etc.",
                    },
                },
                "required": ["route", "params"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_regulations",
            "description": (
                "Retrieve CAD circular excerpts (AC-001..017) for a natural-language question. "
                "Every excerpt includes regulation_id and section (clause) for citation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Regulation question or topic."},
                    "k": {"type": "integer", "description": "Number of excerpts (1-10).", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_airspace",
            "description": (
                "RFZ / restricted flying zone context for an area name or bounding question, "
                "plus live simulator tracks snapshot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": "Place name or district, e.g. Victoria Harbour, Sha Tin.",
                    },
                    "lon": {"type": "number", "description": "Optional longitude for point lookup."},
                    "lat": {"type": "number", "description": "Optional latitude for point lookup."},
                },
                "required": ["area"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hko_weather",
            "description": "Current Hong Kong Observatory open-data: district weather and active warnings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lang": {
                        "type": "string",
                        "enum": ["en", "tc", "sc"],
                        "default": "en",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_population",
            "description": (
                "Estimated population density near a WGS84 point (WorldPop 100 m grid when available)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lon": {"type": "number"},
                    "lat": {"type": "number"},
                    "radius_m": {"type": "number", "default": 100},
                },
                "required": ["lon", "lat"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_poi",
            "description": (
                "Nearby emergency POIs (hospitals, fire stations, police, helipads) from LandsD iGeoCom subset."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lon": {"type": "number"},
                    "lat": {"type": "number"},
                    "radius_m": {"type": "number", "default": 500},
                    "facility_type": {
                        "type": "string",
                        "description": "Optional filter: hospital, fire_station, police_station, helipad.",
                    },
                },
                "required": ["lon", "lat"],
            },
        },
    },
]


def _normalize_route(route: dict[str, Any]) -> dict[str, Any]:
    if route.get("type") == "LineString":
        return {"type": "Feature", "properties": {}, "geometry": route}
    return route


def _coerce_flight_params(params: dict[str, Any]) -> FlightPlanParams:
    clean = {k: v for k, v in params.items() if v is not None}
    cat = clean.get("aircraft_category")
    if cat not in ("cat_a", "cat_b"):
        clean.pop("aircraft_category", None)
    return FlightPlanParams(**clean)


def tool_check_flight_plan(route: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    parsed = _coerce_flight_params(params)
    evaluation = evaluate_flight_plan(_normalize_route(route), parsed)
    return {
        "verdict": evaluation.verdict,
        "violations": [v.model_dump() for v in evaluation.violations],
        "clauses_hit": evaluation.clauses_hit,
        "pending_rules": evaluation.pending_rules,
    }


def tool_search_regulations(query: str, k: int = 5) -> dict[str, Any]:
    try:
        excerpts = rag_query(query, min(max(k, 1), 10))
    except RegulationStoreNotReady as exc:
        return {"query": query, "excerpts": [], "note": str(exc)}
    return {"query": query, "excerpts": excerpts}


def _rfz_path() -> str | None:
    return os.environ.get("UTM_RFZ_GEOJSON") or default_rfz_path()


def tool_query_airspace(
    area: str,
    lon: float | None = None,
    lat: float | None = None,
) -> dict[str, Any]:
    zones = load_rfz_zones(_rfz_path())
    rfz_count = len(zones) if zones else 0
    needle = area.lower()
    matched = []
    if zones:
        for z in zones:
            if needle in z.name.lower() or z.name.lower() in needle:
                matched.append({"zone_id": z.zone_id, "name": z.name})
        if lon is not None and lat is not None:
            from shapely.geometry import Point

            pt = Point(lon, lat)
            for z in zones:
                if z.geometry.contains(pt) or z.geometry.intersects(pt.buffer(0.001)):
                    entry = {"zone_id": z.zone_id, "name": z.name, "contains_point": True}
                    if entry not in matched:
                        matched.append(entry)
    return {
        "area": area,
        "rfz_path": _rfz_path(),
        "rfz_count": rfz_count,
        "matching_zones": matched[:20],
        "active_tracks": [t.model_dump() for t in generate_tracks(count=5)],
    }


def tool_get_hko_weather(lang: str = "en") -> dict[str, Any]:
    base = "https://data.weather.gov.hk/weatherAPI/opendata"
    out: dict[str, Any] = {"source": "Hong Kong Observatory open data", "lang": lang}
    try:
        with httpx.Client(timeout=15.0) as client:
            rhr = client.get(
                f"{base}/weather.php",
                params={"dataType": "rhrread", "lang": lang},
            )
            rhr.raise_for_status()
            out["current"] = rhr.json()
            warn = client.get(
                f"{base}/weather.php",
                params={"dataType": "warnsum", "lang": lang},
            )
            warn.raise_for_status()
            out["warnings"] = warn.json()
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def _population_tif() -> Path | None:
    matches = sorted(DATA_DIR.glob("population/*.tif"))
    return matches[0] if matches else None


def tool_query_population(lon: float, lat: float, radius_m: float = 100.0) -> dict[str, Any]:
    tif = _population_tif()
    if tif is None:
        return {
            "lon": lon,
            "lat": lat,
            "status": "pending_data",
            "message": "WorldPop GeoTIFF not in data/population/ — run scripts/download_data.sh",
        }
    try:
        import rasterio  # optional — only when grid is downloaded
        from rasterio.warp import transform as rio_transform
    except ImportError:
        return {
            "lon": lon,
            "lat": lat,
            "status": "pending_data",
            "message": "rasterio not installed; population grid present but unreadable",
        }
    with rasterio.open(tif) as ds:
        xs, ys = rio_transform("EPSG:4326", ds.crs, [lon], [lat])
        row, col = ds.index(xs[0], ys[0])
        if not (0 <= row < ds.height and 0 <= col < ds.width):
            return {"lon": lon, "lat": lat, "status": "out_of_bounds"}
        val = float(ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
        return {
            "lon": lon,
            "lat": lat,
            "radius_m": radius_m,
            "persons_per_100m_cell": val,
            "source": tif.name,
            "status": "ok",
        }


def _poi_path() -> Path | None:
    for name in (
        "emergency_facilities_hk.geojson",
        "emergency_facilities_hk_2026-09-29.geojson",
    ):
        p = DATA_DIR / "poi" / name
        if p.exists():
            return p
    store = Path(
        "/cursor/stores/bc-84c3ba31-ae28-4e90-aac4-a36c4f7fcb14/internal/datasets/poi/emergency_facilities_hk_2026-09-29.geojson"
    )
    if store.exists():
        return store
    return None


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def tool_query_poi(
    lon: float,
    lat: float,
    radius_m: float = 500.0,
    facility_type: str | None = None,
) -> dict[str, Any]:
    path = _poi_path()
    if path is None:
        return {
            "lon": lon,
            "lat": lat,
            "status": "pending_data",
            "message": "POI GeoJSON not in data/poi/ — run scripts/download_data.sh",
        }
    collection = json.loads(path.read_text(encoding="utf-8"))
    hits = []
    want = facility_type.lower().replace(" ", "_") if facility_type else None
    for feat in collection.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        plon, plat = float(coords[0]), float(coords[1])
        dist = _haversine_m(lon, lat, plon, plat)
        if dist > radius_m:
            continue
        props = feat.get("properties") or {}
        ftype = str(props.get("facility_type") or props.get("TYPE") or "unknown")
        if want and want not in ftype.lower():
            continue
        hits.append(
            {
                "name_en": props.get("name_en") or props.get("ENGLISHNAME"),
                "facility_type": ftype,
                "distance_m": round(dist, 1),
                "lon": plon,
                "lat": plat,
            }
        )
    hits.sort(key=lambda h: h["distance_m"])
    return {
        "lon": lon,
        "lat": lat,
        "radius_m": radius_m,
        "count": len(hits),
        "facilities": hits[:15],
        "source": str(path),
    }


TOOLS: dict[str, Any] = {
    "check_flight_plan": tool_check_flight_plan,
    "search_regulations": tool_search_regulations,
    "query_airspace": tool_query_airspace,
    "get_hko_weather": tool_get_hko_weather,
    "query_population": tool_query_population,
    "query_poi": tool_query_poi,
}


def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(**arguments)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}

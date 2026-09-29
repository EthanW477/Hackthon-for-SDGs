"""Rule engine v1 — the five core CAD rules as pure functions.

Each rule takes (coordinates, params) and returns a list of RuleViolation
(empty when compliant). `coordinates` is the GeoJSON LineString coordinate
array: [[lon, lat, alt_m?], ...].

Phase-0 status: stubs with real signatures and minimal working logic so the
API contract and tests run end-to-end. Spatial checks (RFZ intersection,
separation) get real GeoJSON/shapely implementations in Phase 1 (step 1.3)
once data/ is populated by scripts/download_data.sh.
"""

from collections.abc import Callable

from app.schemas.flight_plan import FlightPlanParams, RuleViolation

MAX_ALTITUDE_FT = 300.0  # AC-014/AC-015 default scenario ceiling
FT_PER_M = 3.28084
MIN_HORIZONTAL_SEPARATION_M = 30.0  # from people / buildings


def check_altitude_limit(
    coordinates: list[list[float]], params: FlightPlanParams
) -> list[RuleViolation]:
    """Rule 1: flight altitude must stay <= 300 ft AGL (AC-014/AC-015)."""
    if params.max_altitude_ft <= MAX_ALTITUDE_FT:
        return []
    return [
        RuleViolation(
            rule_id="altitude_limit",
            regulation_ref="AC-014",
            message=(
                f"Planned max altitude {params.max_altitude_ft:.0f} ft exceeds "
                f"the {MAX_ALTITUDE_FT:.0f} ft ceiling."
            ),
        )
    ]


def check_horizontal_separation(
    coordinates: list[list[float]], params: FlightPlanParams
) -> list[RuleViolation]:
    """Rule 2: keep >= 30 m horizontal separation from people/buildings.

    TODO(phase-1): buffer the route by 30 m and intersect with building
    footprints / WorldPop population grid from data/.
    """
    return []


def check_rfz_intersection(
    coordinates: list[list[float]], params: FlightPlanParams
) -> list[RuleViolation]:
    """Rule 3: route must not intersect any restricted flying zone (RFZ).

    TODO(phase-1): load data/rfz/*.geojson (286 zones) and run a shapely
    intersection check per segment.
    """
    return []


def check_aircraft_category(
    coordinates: list[list[float]], params: FlightPlanParams
) -> list[RuleViolation]:
    """Rule 4: Cat B aircraft (25-150 kg) carry extra restrictions (AC-014).

    TODO(phase-1): enforce Cat B-only constraints (e.g. no operations over
    populated areas without specific approval).
    """
    return []


def check_time_window(
    coordinates: list[list[float]], params: FlightPlanParams
) -> list[RuleViolation]:
    """Rule 5: operation must fall inside the permitted time window.

    TODO(phase-1): parse the requested window from the flight plan and check
    daylight / approval-window constraints.
    """
    return []


RULES: list[Callable[[list[list[float]], FlightPlanParams], list[RuleViolation]]] = [
    check_altitude_limit,
    check_horizontal_separation,
    check_rfz_intersection,
    check_aircraft_category,
    check_time_window,
]


def check_flight_plan(
    route_geojson: dict, params: FlightPlanParams
) -> list[RuleViolation]:
    """Run every rule against the route and collect all violations."""
    coordinates = route_geojson.get("coordinates", [])
    violations: list[RuleViolation] = []
    for rule in RULES:
        violations.extend(rule(coordinates, params))
    return violations

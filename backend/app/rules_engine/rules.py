"""The five core CAD-derived rules as pure functions (project plan §4.3).

Each rule takes the parsed route, the flight-plan params and a RuleContext of
spatial layers, and returns exactly one RuleResult:

    {rule_id, passed, clause_ref, detail, segment_index?, pending_data}

``passed=True`` with ``pending_data=True`` means the check is fully structured
but its data layer is not loaded yet — pending rules never reject a plan.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from shapely.geometry.base import BaseGeometry

from app.rules_engine.geometry import Route, project_geometry
from app.rules_engine.layers import Zone
from app.schemas.flight_plan import FlightPlanParams

MAX_ALTITUDE_FT = 300.0  # AC-014/AC-015 default scenario ceiling
MAX_ALTITUDE_M = 91.44  # 300 ft, AMSL
FT_PER_M = 3.28084
MIN_HORIZONTAL_SEPARATION_M = 30.0  # from crowds / buildings
MAX_TIME_WINDOW = timedelta(hours=12)  # engine assumption: single-slot operations
HK_TZ = timezone(timedelta(hours=8))


class RuleResult(BaseModel):
    rule_id: str
    passed: bool
    clause_ref: str
    detail: str
    segment_index: int | None = None
    pending_data: bool = False


@dataclass
class RuleContext:
    """Spatial layers a rule may consult. ``None`` = data not loaded."""

    rfz_zones: list[Zone] | None = None
    obstacles: list[BaseGeometry] | None = None  # crowds/buildings, lon/lat


def check_altitude_limit(route: Route, params: FlightPlanParams, ctx: RuleContext) -> RuleResult:
    """Rule 1: altitude must stay <= 300 ft (91.44 m) AMSL — AC-014/AC-015."""
    breaches: list[str] = []
    first_index: int | None = None
    if params.max_altitude_ft > MAX_ALTITUDE_FT:
        breaches.append(
            f"planned max altitude {params.max_altitude_ft:.0f} ft exceeds the "
            f"{MAX_ALTITUDE_FT:.0f} ft ceiling"
        )
    for i, coord in enumerate(route.coordinates):
        if len(coord) >= 3 and coord[2] is not None and coord[2] > MAX_ALTITUDE_M:
            breaches.append(
                f"route point {i} at {coord[2]:.1f} m AMSL exceeds "
                f"{MAX_ALTITUDE_M:.2f} m (300 ft)"
            )
            if first_index is None:
                first_index = max(i - 1, 0)
    if breaches:
        return RuleResult(
            rule_id="altitude_limit",
            passed=False,
            clause_ref="AC-014",
            detail="; ".join(breaches),
            segment_index=first_index,
        )
    return RuleResult(
        rule_id="altitude_limit",
        passed=True,
        clause_ref="AC-014",
        detail=(
            f"planned max altitude {params.max_altitude_ft:.0f} ft and all route "
            f"points within the {MAX_ALTITUDE_FT:.0f} ft (91.44 m) AMSL ceiling"
        ),
    )


def check_horizontal_separation(route: Route, params: FlightPlanParams, ctx: RuleContext) -> RuleResult:
    """Rule 2: keep >= 30 m lateral separation from crowds/buildings — AC-014.

    The population/buildings layer is injected via the rule context; when no
    layer is loaded (WorldPop GeoTIFF / 3D Tiles not yet derived to GeoJSON)
    the check reports pending-data instead of silently passing.
    """
    if ctx.obstacles is None:
        return RuleResult(
            rule_id="horizontal_separation",
            passed=True,
            clause_ref="AC-014",
            pending_data=True,
            detail=(
                "pending-data: no population/buildings layer loaded "
                "(data/population, data/tiles); 30 m lateral separation check "
                "is structured but not enforced"
            ),
        )
    line_m = route.line_m()
    if line_m is None:
        return RuleResult(
            rule_id="horizontal_separation",
            passed=True,
            clause_ref="AC-014",
            detail="route has fewer than 2 points; no segment to check",
        )
    too_close: list[str] = []
    for i, obstacle in enumerate(ctx.obstacles):
        distance_m = line_m.distance(project_geometry(obstacle))
        if distance_m < MIN_HORIZONTAL_SEPARATION_M:
            too_close.append(f"obstacle {i} at {distance_m:.1f} m")
    if too_close:
        return RuleResult(
            rule_id="horizontal_separation",
            passed=False,
            clause_ref="AC-014",
            detail=(
                f"route passes within {MIN_HORIZONTAL_SEPARATION_M:.0f} m of "
                f"crowds/buildings ({'; '.join(too_close)})"
            ),
        )
    return RuleResult(
        rule_id="horizontal_separation",
        passed=True,
        clause_ref="AC-014",
        detail=(
            f"route keeps >= {MIN_HORIZONTAL_SEPARATION_M:.0f} m from all "
            f"{len(ctx.obstacles)} loaded obstacle feature(s)"
        ),
    )


def check_rfz_intersection(route: Route, params: FlightPlanParams, ctx: RuleContext) -> RuleResult:
    """Rule 3: route must not intersect any restricted flying zone — AC-014."""
    if ctx.rfz_zones is None:
        return RuleResult(
            rule_id="rfz_intersection",
            passed=True,
            clause_ref="AC-014",
            pending_data=True,
            detail=(
                "pending-data: no RFZ GeoJSON loaded (expected at data/rfz/); "
                "restricted-zone intersection check is structured but not enforced"
            ),
        )
    line = route.line_lonlat()
    if line is None:
        return RuleResult(
            rule_id="rfz_intersection",
            passed=True,
            clause_ref="AC-014",
            detail="route has fewer than 2 points; no segment to check",
        )
    segments = route.segments_lonlat()
    hits: list[str] = []
    first_index: int | None = None
    for zone in ctx.rfz_zones:
        if not line.intersects(zone.geometry):
            continue
        segment_index = next(
            (i for i, seg in enumerate(segments) if seg.intersects(zone.geometry)),
            None,
        )
        hits.append(f"{zone.name} (segment {segment_index})")
        if first_index is None:
            first_index = segment_index
    if hits:
        return RuleResult(
            rule_id="rfz_intersection",
            passed=False,
            clause_ref="AC-014",
            detail=f"route intersects restricted flying zone(s): {'; '.join(hits)}",
            segment_index=first_index,
        )
    return RuleResult(
        rule_id="rfz_intersection",
        passed=True,
        clause_ref="AC-014",
        detail=f"route clears all {len(ctx.rfz_zones)} loaded restricted flying zones",
    )


def check_aircraft_category(route: Route, params: FlightPlanParams, ctx: RuleContext) -> RuleResult:
    """Rule 4: Category B aircraft (25-150 kg) extra restrictions — AC-014.

    Parameter-based: Cat B operations must stay within visual line of sight
    (AC-013/AC-014) and must name a registered operator.
    """
    if params.aircraft_category != "cat_b":
        return RuleResult(
            rule_id="aircraft_category",
            passed=True,
            clause_ref="AC-014",
            detail="Cat A aircraft (<25 kg): no additional category restrictions apply",
        )
    breaches: list[str] = []
    if not params.within_visual_line_of_sight:
        breaches.append(
            "Cat B (25-150 kg) operations must remain within visual line of "
            "sight unless specifically approved (AC-013)"
        )
    if not params.operator:
        breaches.append(
            "Cat B (25-150 kg) operations require a registered operator; "
            "the operator field is empty"
        )
    if breaches:
        return RuleResult(
            rule_id="aircraft_category",
            passed=False,
            clause_ref="AC-014",
            detail="; ".join(breaches),
        )
    return RuleResult(
        rule_id="aircraft_category",
        passed=True,
        clause_ref="AC-014",
        detail="Cat B (25-150 kg) operation satisfies VLOS and operator requirements",
    )


_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def _parse_instant(raw: str) -> datetime:
    instant = datetime.fromisoformat(raw)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=HK_TZ)  # naive times read as Hong Kong time
    return instant


def _parse_window(raw: str) -> tuple[datetime, datetime]:
    start_raw, _, end_raw = raw.partition("/")
    if not end_raw:
        raise ValueError("expected 'start/end' or 'start/duration'")
    start = _parse_instant(start_raw)
    duration_match = _DURATION_RE.match(end_raw)
    if duration_match:
        parts = {k: float(v) for k, v in duration_match.groupdict().items() if v}
        end = start + timedelta(
            days=parts.get("days", 0.0),
            hours=parts.get("hours", 0.0),
            minutes=parts.get("minutes", 0.0),
            seconds=parts.get("seconds", 0.0),
        )
    else:
        end = _parse_instant(end_raw)
    return start, end


def check_time_window(route: Route, params: FlightPlanParams, ctx: RuleContext) -> RuleResult:
    """Rule 5: the operation must declare a valid time window — AC-014.

    The window travels in the route's GeoJSON properties as an ISO 8601
    interval (``start/end`` or ``start/duration``, e.g.
    ``2026-10-20T09:00:00+08:00/PT30M``); naive times read as Hong Kong time.
    """
    raw = route.properties.get("time_window")
    if not raw:
        return RuleResult(
            rule_id="time_window",
            passed=True,
            clause_ref="AC-014",
            pending_data=True,
            detail=(
                "pending-data: no time_window supplied in the route properties; "
                "provide an ISO 8601 interval (start/end or start/duration)"
            ),
        )
    try:
        start, end = _parse_window(str(raw))
    except ValueError:
        return RuleResult(
            rule_id="time_window",
            passed=False,
            clause_ref="AC-014",
            detail=f"time_window {raw!r} is not a valid ISO 8601 interval",
        )
    if end <= start:
        return RuleResult(
            rule_id="time_window",
            passed=False,
            clause_ref="AC-014",
            detail=f"time_window ends at or before it starts ({raw})",
        )
    if end - start > MAX_TIME_WINDOW:
        return RuleResult(
            rule_id="time_window",
            passed=False,
            clause_ref="AC-014",
            detail=(
                f"time_window spans {end - start}, exceeding the "
                f"{MAX_TIME_WINDOW.total_seconds() / 3600:.0f} h single-operation limit"
            ),
        )
    return RuleResult(
        rule_id="time_window",
        passed=True,
        clause_ref="AC-014",
        detail=(
            f"operation window {start.isoformat()} -> {end.isoformat()} "
            f"({end - start}) is valid"
        ),
    )


Rule = Callable[[Route, FlightPlanParams, RuleContext], RuleResult]

RULES: list[Rule] = [
    check_altitude_limit,
    check_horizontal_separation,
    check_rfz_intersection,
    check_aircraft_category,
    check_time_window,
]

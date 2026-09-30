"""evaluate_flight_plan: run the five CAD rules and aggregate a verdict."""

from typing import Any, Literal

from pydantic import BaseModel
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.rules_engine.geometry import Route
from app.rules_engine.layers import default_obstacle_geometries, load_rfz_zones
from app.rules_engine.rules import RULES, RuleContext, RuleResult
from app.schemas.flight_plan import FlightPlanParams, RuleViolation


class EvaluationResult(BaseModel):
    verdict: Literal["approved", "rejected"]
    violations: list[RuleViolation]
    clauses_hit: list[str]
    results: list[RuleResult]

    @property
    def pending_rules(self) -> list[str]:
        return [r.rule_id for r in self.results if r.pending_data]


def _normalize_obstacles(obstacles: list[Any]) -> list[BaseGeometry]:
    """Accept shapely geometries or GeoJSON geometry dicts."""
    return [shape(o) if isinstance(o, dict) else o for o in obstacles]


def evaluate_flight_plan(
    route_geojson: dict[str, Any],
    params: FlightPlanParams,
    *,
    rfz_path: str | None = None,
    obstacles: list[Any] | None = None,
    context: RuleContext | None = None,
) -> EvaluationResult:
    """Evaluate a flight plan against every registered rule.

    ``rfz_path`` / ``obstacles`` override the default data layers (used by
    tests); with no overrides the layers load from ``data/`` and any missing
    layer surfaces as a pending-data rule result rather than a silent pass.
    """
    route = Route.from_geojson(route_geojson)
    if context is None:
        context = RuleContext(
            rfz_zones=load_rfz_zones(rfz_path),
            obstacles=(
                _normalize_obstacles(obstacles)
                if obstacles is not None
                else default_obstacle_geometries()
            ),
        )
    results = [rule(route, params, context) for rule in RULES]
    violations = [
        RuleViolation(
            rule_id=result.rule_id,
            regulation_ref=result.clause_ref,
            message=result.detail,
            segment_index=result.segment_index,
        )
        for result in results
        if not result.passed
    ]
    clauses_hit = sorted({result.clause_ref for result in results if not result.passed})
    return EvaluationResult(
        verdict="rejected" if violations else "approved",
        violations=violations,
        clauses_hit=clauses_hit,
        results=results,
    )


def check_flight_plan(
    route_geojson: dict[str, Any], params: FlightPlanParams
) -> list[RuleViolation]:
    """Backwards-compatible wrapper returning only the violations list."""
    return evaluate_flight_plan(route_geojson, params).violations

"""Flight plan check models — see API contract: POST /api/v1/flight-plans/check."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class FlightPlanParams(BaseModel):
    """Aircraft / operation parameters accompanying the route."""

    aircraft_category: Literal["cat_a", "cat_b"] = Field(
        default="cat_a",
        description="cat_a: <25kg; cat_b: 25-150kg (extra limits per AC-014).",
    )
    max_altitude_ft: float = Field(default=250.0, description="Planned max altitude in feet AGL.")
    within_visual_line_of_sight: bool = True
    operator: str | None = None


class FlightPlanCheckRequest(BaseModel):
    route_geojson: dict[str, Any] = Field(
        ...,
        description="GeoJSON LineString: [[lon, lat, alt_m?], ...] coordinates.",
    )
    params: FlightPlanParams = FlightPlanParams()


class RuleViolation(BaseModel):
    rule_id: str = Field(..., examples=["rfz_intersection"])
    regulation_ref: str = Field(..., examples=["AC-014"])
    message: str
    segment_index: int | None = Field(
        default=None, description="Index of the offending route segment, when applicable."
    )


class Suggestion(BaseModel):
    kind: Literal["reroute", "lower_altitude", "reschedule", "change_aircraft"]
    description: str
    patched_route_geojson: dict[str, Any] | None = None


class FlightPlanCheckResponse(BaseModel):
    verdict: Literal["approved", "rejected"]
    violations: list[RuleViolation] = []
    suggestions: list[Suggestion] = []

"""Scenario models — see API contract: POST /api/v1/scenarios, POST /api/v1/scenarios/{id}/run.

Scenario JSON schema follows project-plan §4.4:
{area, time_window, weather, traffic_density, injected_events[], expected_system_behavior[]}
"""

from typing import Literal

from pydantic import BaseModel, Field


class InjectedEvent(BaseModel):
    kind: Literal["gps_loss", "rfz_intrusion", "off_course", "weather_shift", "comms_loss"]
    at_second: int = Field(..., ge=0, description="Sim-time offset when the event fires.")
    target_track_id: str | None = None
    detail: str | None = None


class ExpectedBehavior(BaseModel):
    check: str = Field(..., examples=["System raises lost-link alert within 30s"])
    pass_criteria: str | None = None


class Scenario(BaseModel):
    area: str = Field(default="Sha Tin — Science Park", examples=["Sha Tin — Science Park"])
    time_window: str = Field(..., examples=["2026-10-20T09:00:00+08:00/PT30M"])
    weather: str = Field(default="fine", examples=["typhoon_approaching"])
    traffic_density: Literal["low", "medium", "high"] = "medium"
    aircraft_count: int = Field(default=5, ge=1, le=100)
    injected_events: list[InjectedEvent] = []
    expected_system_behavior: list[ExpectedBehavior] = []


class ScenarioCreateRequest(BaseModel):
    description: str = Field(
        ...,
        examples=["Typhoon eve: 10 drones over Sha Tin, one loses GPS at minute 5"],
    )


class ScenarioCreateResponse(BaseModel):
    id: str
    scenario_json: Scenario
    checklist: list[str] = []


class ScenarioRunResponse(BaseModel):
    scenario_id: str
    status: Literal["completed", "failed"] = "completed"
    report_url: str
    log_excerpt: list[str] = []

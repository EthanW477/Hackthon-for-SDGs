"""Scenario models — see API contract: POST /api/v1/scenarios, POST /api/v1/scenarios/{id}/run.

Scenario JSON schema follows project-plan §4.4:
{area, time_window, weather, traffic_density, injected_events[], expected_system_behavior[]}

Phase 3 adds the structured test-report models returned by the scenario
executor and the trilingual brief models.
"""

from typing import Literal

from pydantic import BaseModel, Field


class InjectedEvent(BaseModel):
    kind: Literal["gps_loss", "rfz_intrusion", "off_course", "weather_shift", "comms_loss"]
    at_second: int = Field(..., ge=0, description="Sim-time offset when the event fires.")
    duration_s: float = Field(
        default=60.0, ge=1.0, le=1800.0,
        description="How long the fault stays active, sim seconds.",
    )
    target_track_id: str | None = Field(
        default=None, description="Simulator track id, e.g. SIM-005."
    )
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
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal generation notes (e.g. heuristic fallback used).",
    )


class CheckResult(BaseModel):
    check: str
    status: Literal["pass", "fail", "pending"]
    evidence: str | None = None
    regulation_ref: str | None = None


class TimelineEvent(BaseModel):
    t: float = Field(..., description="Sim-time offset in seconds.")
    kind: Literal[
        "scenario_start", "fault_injected", "fault_detected", "fault_recovered",
        "advisory", "violation", "weather", "note",
    ]
    message: str
    track_id: str | None = None


class ObservedViolation(BaseModel):
    rule_id: str
    regulation_ref: str
    message: str
    track_id: str | None = None
    at_second: float | None = None


class ReportCitation(BaseModel):
    regulation_id: str
    section: str | None = None
    excerpt: str | None = None


class ReportSummary(BaseModel):
    total_checks: int
    passed: int
    failed: int
    pending: int
    pass_rate: float = Field(
        ..., description="passed / (passed + failed); 1.0 when nothing auto-verifiable ran."
    )
    violations_count: int
    advisories_count: int
    events_count: int
    duration_s: int
    aircraft_count: int


class TestReport(BaseModel):
    report_id: str
    scenario_id: str
    generated_at: str = Field(..., description="ISO 8601 timestamp, Hong Kong time.")
    description: str = ""
    scenario: Scenario
    summary: ReportSummary
    checks: list[CheckResult] = []
    violations: list[ObservedViolation] = []
    timeline: list[TimelineEvent] = []
    citations: list[ReportCitation] = []
    log_excerpt: list[str] = []
    notes: list[str] = []


class ScenarioRunResponse(BaseModel):
    scenario_id: str
    status: Literal["completed", "failed"] = "completed"
    report_url: str
    log_excerpt: list[str] = []
    report: TestReport | None = None
    markdown: str | None = None


class BriefRequest(BaseModel):
    audience: Literal["cad_technical", "legco_policy", "community"] = Field(
        ...,
        description="cad_technical: CAD technical summary; legco_policy: LegCo policy "
        "brief; community: plain-language community notice.",
    )


class BriefResponse(BaseModel):
    scenario_id: str
    audience: str
    briefs: dict[str, str] = Field(
        ..., description="Markdown brief per language: zh (書面中文), en, yue (粵語)."
    )
    generated_with: Literal["llm", "mixed", "fallback"] = "llm"

"""UTM Copilot backend — API entrypoint.

Phase-0/1: contract endpoints are working stubs so frontend and AI
integration can proceed in parallel against the contract — except the
tracks/airspace endpoints, which are backed by the live trajectory
simulator (app/simulator/, project-plan §4.3 / step 1.4).
See docs/dev-readme.md §5 for the API contract.
"""

import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.rules_engine import check_flight_plan
from app.schemas import (
    AirspaceResponse,
    ChatRequest,
    ChatResponse,
    FlightPlanCheckRequest,
    FlightPlanCheckResponse,
    ReportRequest,
    ReportResponse,
    Scenario,
    ScenarioCreateRequest,
    ScenarioCreateResponse,
    ScenarioRunResponse,
    Suggestion,
)
from app.simulator import generate_tracks, parse_fault_specs, stream_tracks

app = FastAPI(title="UTM Copilot API", version="0.1.0")

# The Next.js dev server / container calls from the browser; allow all origins
# in Phase 0, tighten before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory scenario store — fine for Phase 0 stubs; Phase 3 decides on real
# persistence once the scenario executor lands.
SCENARIOS: dict[str, Scenario] = {}


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Natural-language entry point.

    TODO(phase-2, step 2.2): route through the LLM tool-calling loop
    (app/ai/). For now returns a canned, contract-shaped reply.
    """
    return ChatResponse(
        reply=(
            "UTM Copilot stub: I received your message "
            f"({req.message[:80]}). The AI layer lands in Phase 2 — "
            "meanwhile use /api/v1/flight-plans/check for route checks."
        ),
        map_annotations=[],
        citations=[],
    )


@app.post("/api/v1/flight-plans/check", response_model=FlightPlanCheckResponse)
def flight_plans_check(req: FlightPlanCheckRequest) -> FlightPlanCheckResponse:
    """Run the rule engine over a proposed route."""
    violations = check_flight_plan(req.route_geojson, req.params)
    suggestions: list[Suggestion] = []
    if violations:
        # TODO(phase-2, step 2.4): real counterfactual search (perturb ->
        # re-check -> minimal-edit suggestion). Stub advice for now.
        suggestions.append(
            Suggestion(
                kind="lower_altitude",
                description="Lower the planned maximum altitude to 300 ft or below.",
            )
        )
    return FlightPlanCheckResponse(
        verdict="rejected" if violations else "approved",
        violations=violations,
        suggestions=suggestions,
    )


@app.get("/api/v1/airspace", response_model=AirspaceResponse)
def airspace() -> AirspaceResponse:
    """Current airspace picture: live simulator snapshot + stubbed context.

    TODO(phase-1/2): active_restrictions and rfz_count stay stubbed until the
    RFZ GeoJSON layer is wired into the rules engine.
    TODO(phase-3): weather stays stubbed ("fine") until the HKO open-data
    feed lands for weather scenarios.
    """
    return AirspaceResponse(
        active_restrictions=["AC-014", "AC-015"],
        active_tracks=generate_tracks(count=8),
    )


@app.get("/api/v1/tracks/stream")
async def tracks_stream(count: int = 8, faults: str | None = None) -> StreamingResponse:
    """Server-sent events stream of simulated tracks (1 Hz).

    Query params:
    - count: number of aircraft (clamped to 1–10, default 8).
    - faults: fault-injection specs, e.g.
      "gps_loss:SIM-002@30+15|deviation:SIM-004@60+20" — starts are seconds
      from stream start; see app.simulator.parse_fault_specs for the format.
    """
    try:
        fault_specs = parse_fault_specs(faults) if faults else []
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def events() -> AsyncGenerator[str, None]:
        async for tracks in stream_tracks(count=count, interval_s=1.0, faults=fault_specs):
            payload = [t.model_dump() for t in tracks]
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/v1/scenarios", response_model=ScenarioCreateResponse, status_code=201)
def scenarios_create(req: ScenarioCreateRequest) -> ScenarioCreateResponse:
    """Turn a plain-language description into a scenario JSON + checklist.

    TODO(phase-3, step 3.1): LLM generation with schema validation + retry.
    """
    scenario = Scenario(
        time_window="2026-10-20T09:00:00+08:00/PT30M",
        weather="typhoon_approaching" if "typhoon" in req.description.lower() else "fine",
        traffic_density="high",
        aircraft_count=10,
    )
    scenario_id = uuid.uuid4().hex[:8]
    SCENARIOS[scenario_id] = scenario
    return ScenarioCreateResponse(
        id=scenario_id,
        scenario_json=scenario,
        checklist=[
            "System raises lost-link alert within 30 s of GPS loss",
            "Remaining aircraft receive avoidance advisories",
        ],
    )


@app.post("/api/v1/scenarios/{scenario_id}/run", response_model=ScenarioRunResponse)
def scenarios_run(scenario_id: str) -> ScenarioRunResponse:
    """Execute a stored scenario through the simulator and return a report.

    TODO(phase-3, step 3.2): real executor + LLM-drafted test report.
    """
    scenario = SCENARIOS.get(scenario_id)
    log = (
        [f"loaded scenario {scenario_id}: {scenario.aircraft_count} aircraft"]
        if scenario
        else [f"scenario {scenario_id} not found; ran default mock scenario"]
    )
    return ScenarioRunResponse(
        scenario_id=scenario_id,
        report_url=f"/api/v1/reports/{scenario_id}",
        log_excerpt=log + ["simulation tick 0..1800 complete", "0 conflicts, 0 alerts"],
    )


@app.post("/api/v1/reports", response_model=ReportResponse)
def reports_create(req: ReportRequest) -> ReportResponse:
    """Generate a plain-language brief for the chosen audience.

    TODO(phase-3, step 3.3): three fixed templates filled by the LLM.
    """
    titles = {
        "cad_technical": "Technical Summary",
        "legco_policy": "Policy Brief",
        "community": "Community Note",
    }
    markdown = (
        f"# {titles[req.audience]} ({req.range})\n\n"
        "Stub report — generation pipeline lands in Phase 3.\n\n"
        "- 1,240 movements, zero incidents (mock data)\n"
        "- 3 conflict alerts, all handled per procedure (mock data)\n"
    )
    return ReportResponse(audience=req.audience, range=req.range, markdown=markdown)

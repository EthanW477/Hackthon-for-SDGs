"""UTM Copilot backend — API entrypoint.

Phase-0/1: contract endpoints are working stubs so frontend and AI
integration can proceed in parallel against the contract — except the
tracks/airspace endpoints, which are backed by the live trajectory
simulator (app/simulator/, project-plan §4.3 / step 1.4).
See docs/dev-readme.md §5 for the API contract.
"""

import json
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path


def _load_backend_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_backend_dotenv()


from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.rag import RegulationStoreNotReady
from app.rag import query as rag_query
from app.rules_engine import evaluate_flight_plan
from app.schemas import (
    AirspaceResponse,
    BriefRequest,
    BriefResponse,
    ChatRequest,
    ChatResponse,
    FlightPlanCheckRequest,
    FlightPlanCheckResponse,
    RegulationExcerpt,
    RegulationSearchResponse,
    ReportRequest,
    ReportResponse,
    ScenarioCreateRequest,
    ScenarioCreateResponse,
    ScenarioRunResponse,
    Suggestion,
)
from app.ai.agent import run_chat
from app.scenarios import (
    generate_briefs,
    generate_scenario,
    get_report,
    get_scenario,
    redact_text,
    render_markdown,
    run_scenario,
    save_report,
    save_scenario,
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

# Scenario/report persistence lives in app.scenarios.store (in-memory, Phase-3).


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Natural-language entry point — Kimi/DeepSeek tool-calling loop (app/ai/)."""
    try:
        return run_chat(req.message, route=req.route)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/flight-plans/check", response_model=FlightPlanCheckResponse)
def flight_plans_check(req: FlightPlanCheckRequest) -> FlightPlanCheckResponse:
    """Run the real rule engine (5 CAD-derived rules) over a proposed route."""
    evaluation = evaluate_flight_plan(req.route_geojson, req.params)
    violations = evaluation.violations
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


@app.get("/api/v1/regulations/search", response_model=RegulationSearchResponse)
def regulations_search(
    q: str = Query(..., min_length=1, description="natural-language regulation question"),
    k: int = Query(5, ge=1, le=20),
) -> RegulationSearchResponse:
    """Search the CAD regulation vector library (20 circulars, step 2.1).

    Returns top-k chunks with full citations (circular no., title, clause,
    page span, verbatim excerpt) — the citation source for LLM answers.
    503 until the library is ingested (scripts/ingest_regulations.py).
    """
    try:
        hits = rag_query(q, k)
    except RegulationStoreNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RegulationSearchResponse(
        query=q, k=k, results=[RegulationExcerpt(**h) for h in hits]
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

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # no-cache + X-Accel-Buffering keep proxies (e.g. the demo tunnel) from
        # buffering the event stream instead of flushing each event.
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/scenarios", response_model=ScenarioCreateResponse, status_code=201)
def scenarios_create(req: ScenarioCreateRequest) -> ScenarioCreateResponse:
    """Turn a plain-language description into a scenario JSON + checklist.

    Phase 3 (step 3.1): LLM drafts the JSON, pydantic validates it, invalid
    output is retried automatically; a disclosed deterministic fallback keeps
    the flow alive if no LLM is reachable.
    """
    description = redact_text(req.description)
    result = generate_scenario(description)
    scenario_id = uuid.uuid4().hex[:8]
    save_scenario(scenario_id, result.scenario, description, result.checklist)
    return ScenarioCreateResponse(
        id=scenario_id,
        scenario_json=result.scenario,
        checklist=result.checklist,
        warnings=result.warnings,
    )


@app.get("/api/v1/scenarios/{scenario_id}", response_model=ScenarioCreateResponse)
def scenarios_get(scenario_id: str) -> ScenarioCreateResponse:
    """Fetch a previously generated scenario (for the report panel)."""
    stored = get_scenario(scenario_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario {scenario_id}")
    return ScenarioCreateResponse(
        id=stored.id, scenario_json=stored.scenario, checklist=stored.checklist
    )


@app.post("/api/v1/scenarios/{scenario_id}/run", response_model=ScenarioRunResponse)
def scenarios_run(scenario_id: str) -> ScenarioRunResponse:
    """Execute a stored scenario through the simulator and return a structured
    test report (pass rate, violations with clause refs, timeline events).

    Phase 3 (step 3.2): deterministic executor + monitor; verdicts never
    depend on the LLM.
    """
    stored = get_scenario(scenario_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario {scenario_id}")
    report = run_scenario(
        scenario_id,
        stored.scenario,
        description=stored.description,
        checklist=stored.checklist,
    )
    save_report(scenario_id, report)
    return ScenarioRunResponse(
        scenario_id=scenario_id,
        report_url=f"/api/v1/scenarios/{scenario_id}/report",
        log_excerpt=report.log_excerpt,
        report=report,
        markdown=render_markdown(report),
    )


@app.get("/api/v1/scenarios/{scenario_id}/report")
def scenarios_report(scenario_id: str, format: str = Query("json", pattern="^(json|markdown)$")):
    """Export the latest test report for a scenario as JSON or Markdown."""
    report = get_report(scenario_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"no report for scenario {scenario_id} — run it first",
        )
    if format == "markdown":
        return Response(
            content=render_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="utm-report-{scenario_id}.md"'
            },
        )
    return report


@app.post("/api/v1/scenarios/{scenario_id}/brief", response_model=BriefResponse)
def scenarios_brief(scenario_id: str, req: BriefRequest) -> BriefResponse:
    """Generate trilingual (zh/en/yue) markdown briefs from the latest report.

    Phase 3 (step 3.3): three fixed audience templates (CAD technical
    summary / LegCo policy brief / community notice) narrated by the LLM from
    the structured report only; deterministic offline template as fallback.
    """
    report = get_report(scenario_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"no report for scenario {scenario_id} — run it first",
        )
    briefs, generated_with = generate_briefs(req.audience, report)
    return BriefResponse(
        scenario_id=scenario_id,
        audience=req.audience,
        briefs=briefs,
        generated_with=generated_with,
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

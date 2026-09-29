"""LLM tool definitions — the six tools from project-plan §4.4.

Phase-0 status: signatures + dispatch table returning stub payloads so the
chat endpoint can exercise the full contract. Each tool gets its real
implementation in the phase noted in its docstring.
"""

from typing import Any

from app.rules_engine import check_flight_plan
from app.schemas.flight_plan import FlightPlanParams
from app.simulator import generate_tracks


def tool_check_flight_plan(route: dict, params: dict) -> dict[str, Any]:
    """check_flight_plan(route, params) -> rules-engine verdict.

    Real implementation exists from Phase 0: delegates to the rule engine.
    """
    parsed = FlightPlanParams(**params)
    violations = check_flight_plan(route, parsed)
    return {
        "verdict": "rejected" if violations else "approved",
        "violations": [v.model_dump() for v in violations],
    }


def tool_query_airspace(area: str, time: str | None = None) -> dict[str, Any]:
    """query_airspace(area, time) -> airspace status and live tracks.

    TODO(phase-1): read real RFZ GeoJSON + simulator state.
    """
    return {
        "area": area,
        "time": time,
        "rfz_count": 286,
        "active_tracks": [t.model_dump() for t in generate_tracks(count=3)],
    }


def tool_get_regulation(topic: str) -> dict[str, Any]:
    """get_regulation(topic) -> regulation excerpts with clause numbers (RAG).

    TODO(phase-2, step 2.1): Chroma retrieval over the 20 CAD PDFs; every
    excerpt must carry its clause number for mandatory citation.
    """
    return {"topic": topic, "excerpts": [], "note": "RAG store not seeded yet"}


def tool_generate_scenario(description: str) -> dict[str, Any]:
    """generate_scenario(description) -> scenario JSON (schema-validated).

    TODO(phase-3, step 3.1): LLM generation + schema validation with retry.
    """
    return {"description": description, "scenario_json": None}


def tool_generate_brief(audience: str, data: dict) -> dict[str, Any]:
    """generate_brief(audience, data) -> brief in one of three templates.

    TODO(phase-3, step 3.3): CAD technical summary / LegCo policy brief /
    trilingual community note.
    """
    return {"audience": audience, "markdown": ""}


def tool_analyze_feed(frame: str) -> dict[str, Any]:
    """analyze_feed(frame) -> VLM event recognition on aerial footage (F4, optional).

    TODO(phase-3, step 3.4): frame sampling from pre-recorded footage + VLM
    event summary.
    """
    return {"frame": frame, "events": []}


TOOLS: dict[str, Any] = {
    "check_flight_plan": tool_check_flight_plan,
    "query_airspace": tool_query_airspace,
    "get_regulation": tool_get_regulation,
    "generate_scenario": tool_generate_scenario,
    "generate_brief": tool_generate_brief,
    "analyze_feed": tool_analyze_feed,
}

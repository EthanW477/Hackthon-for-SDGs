"""Phase 3: NL scenario generation + automated test reports + trilingual briefs."""

from app.scenarios.briefs import generate_briefs
from app.scenarios.executor import render_markdown, run_scenario
from app.scenarios.generator import GenerationResult, generate_scenario
from app.scenarios.redact import redact_text
from app.scenarios.store import get_report, get_scenario, save_report, save_scenario

__all__ = [
    "GenerationResult",
    "generate_briefs",
    "generate_scenario",
    "get_report",
    "get_scenario",
    "redact_text",
    "render_markdown",
    "run_scenario",
    "save_report",
    "save_scenario",
]

"""In-memory scenario/report store — Phase-3 scope (per-demo-process).

Persistence (sqlite/Postgres) is a Phase-4 deployment concern; the demo runs
one backend process, so module-level dicts keep the flow simple.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.schemas.scenario import Scenario, TestReport


@dataclass
class StoredScenario:
    id: str
    scenario: Scenario
    description: str
    checklist: list[str]
    created_at: float = field(default_factory=time.time)


SCENARIOS: dict[str, StoredScenario] = {}
REPORTS: dict[str, TestReport] = {}  # keyed by scenario_id (latest run wins)


def save_scenario(scenario_id: str, scenario: Scenario, description: str, checklist: list[str]) -> None:
    SCENARIOS[scenario_id] = StoredScenario(
        id=scenario_id, scenario=scenario, description=description, checklist=checklist
    )


def get_scenario(scenario_id: str) -> StoredScenario | None:
    return SCENARIOS.get(scenario_id)


def save_report(scenario_id: str, report: TestReport) -> None:
    REPORTS[scenario_id] = report


def get_report(scenario_id: str) -> TestReport | None:
    return REPORTS.get(scenario_id)


def clear() -> None:
    """Test hook: drop all state between cases."""
    SCENARIOS.clear()
    REPORTS.clear()

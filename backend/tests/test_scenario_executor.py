"""Scenario executor tests — deterministic simulator runs, no LLM involved.

The RAG citation enrichment is stubbed out here (it loads the embedding
model); the retrieval layer has its own tests in test_rag_*.
"""

import pytest

import app.scenarios.executor as executor
from app.schemas.scenario import InjectedEvent, Scenario
from app.scenarios.executor import render_markdown, run_scenario, window_seconds


@pytest.fixture(autouse=True)
def stub_rag_citations(monkeypatch):
    monkeypatch.setattr(executor, "_enrich_citations", lambda violations, scenario: [])


GPS_SCENARIO = Scenario(
    time_window="2026-10-20T09:00:00+08:00/PT10M",
    weather="typhoon_approaching",
    traffic_density="high",
    aircraft_count=10,
    injected_events=[
        InjectedEvent(kind="gps_loss", at_second=60, duration_s=120, target_track_id="SIM-005")
    ],
)

GPS_CHECKLIST = [
    "System raises lost-link alert within 30 s of GPS loss",
    "Remaining aircraft receive avoidance advisories",
]


def test_window_seconds_parses_iso_intervals():
    assert window_seconds("2026-10-20T09:00:00+08:00/PT30M") == 1800
    assert window_seconds("2026-10-20T09:00:00+08:00/PT5M") == 300
    assert window_seconds("2026-10-20T09:00:00+08:00/2026-10-20T09:10:00+08:00") == 600
    assert window_seconds("garbage") == 1800  # default
    assert window_seconds("2026-10-20T09:00:00+08:00/PT3H") == 1800  # clamped


def test_gps_loss_scenario_passes_latency_check():
    report = run_scenario("test-gps-1", GPS_SCENARIO, "typhoon gps loss", GPS_CHECKLIST)
    latency = next(c for c in report.checks if "alert" in c.check)
    assert latency.status == "pass"
    assert "SIM-005" in latency.evidence
    advisory = next(c for c in report.checks if "avoidance" in c.check)
    assert advisory.status == "pass"

    kinds = [e.kind for e in report.timeline]
    assert "fault_detected" in kinds
    assert "fault_recovered" in kinds
    assert any(
        e.kind == "advisory" and "lost-link advisory broadcast" in e.message
        for e in report.timeline
    )
    assert report.summary.pass_rate == 1.0
    assert report.summary.aircraft_count == 10
    assert report.summary.duration_s == 600


def test_intrusion_scenario_records_violation_and_citation_ref():
    scenario = Scenario(
        time_window="2026-10-20T09:00:00+08:00/PT10M",
        aircraft_count=4,
        injected_events=[
            InjectedEvent(
                kind="rfz_intrusion", at_second=40, duration_s=260, target_track_id="SIM-001"
            )
        ],
    )
    report = run_scenario(
        "test-rfz-1", scenario, "intrusion", ["System flags the restricted-zone intrusion"]
    )
    assert any(v.rule_id == "rfz_intersection" for v in report.violations)
    assert all(v.regulation_ref == "AC-014" for v in report.violations)
    check = report.checks[0]
    assert check.status == "pass"
    assert check.regulation_ref == "AC-014"


def test_off_course_scenario_flags_deviation():
    scenario = Scenario(
        time_window="2026-10-20T09:00:00+08:00/PT5M",
        aircraft_count=3,
        injected_events=[
            InjectedEvent(kind="off_course", at_second=30, duration_s=90, target_track_id="SIM-002")
        ],
    )
    report = run_scenario(
        "test-dev-1", scenario, "off course", ["System flags the off-course deviation"]
    )
    assert report.checks[0].status == "pass"
    assert any(e.kind == "fault_detected" and "DEVIATION" in e.message for e in report.timeline)


def test_unverifiable_check_is_honestly_pending():
    report = run_scenario(
        "test-pending-1",
        GPS_SCENARIO,
        "typhoon",
        ["Faulted aircraft performs automatic emergency landing"],
    )
    assert report.checks[0].status == "pending"
    assert report.summary.pending == 1


def test_report_is_deterministic_per_scenario_id():
    a = run_scenario("same-id", GPS_SCENARIO, "d", GPS_CHECKLIST)
    b = run_scenario("same-id", GPS_SCENARIO, "d", GPS_CHECKLIST)
    assert [e.model_dump() for e in a.timeline] == [e.model_dump() for e in b.timeline]
    assert a.summary == b.summary


def test_markdown_has_all_sections():
    report = run_scenario("test-md-1", GPS_SCENARIO, "typhoon gps loss", GPS_CHECKLIST)
    md = render_markdown(report)
    for section in (
        "# UTM Scenario Test Report",
        "## Summary",
        "## Checklist results",
        "## Observed violations",
        "## Timeline",
    ):
        assert section in md
    assert "[PASS]" in md


def test_description_secrets_redacted_everywhere():
    leak = "use key sk-1234567890abcdefghijklmnop for the demo"
    report = run_scenario("test-redact-1", GPS_SCENARIO, leak, GPS_CHECKLIST)
    assert report.description != leak
    assert "sk-1234567890abcdefghijklmnop" not in report.model_dump_json()
    assert "sk-1234567890abcdefghijklmnop" not in render_markdown(report)
    assert "sk-1234567890abcdefghijklmnop" not in " ".join(report.log_excerpt)


def test_aircraft_count_clamped_with_note():
    scenario = Scenario(
        time_window="2026-10-20T09:00:00+08:00/PT1M",
        aircraft_count=50,
    )
    report = run_scenario("test-clamp-1", scenario, "big fleet", [])
    assert report.summary.aircraft_count == 10
    assert any("clamped" in n for n in report.notes)

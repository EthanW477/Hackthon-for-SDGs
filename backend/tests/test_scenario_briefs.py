"""Trilingual brief tests — mock LLM; fallback path exercised without it."""

import pytest

import app.scenarios.executor as executor
from app.ai import llm
from app.scenarios.briefs import generate_briefs
from app.schemas.scenario import InjectedEvent, Scenario
from app.scenarios.executor import run_scenario

SCENARIO = Scenario(
    time_window="2026-10-20T09:00:00+08:00/PT5M",
    weather="typhoon_approaching",
    traffic_density="high",
    aircraft_count=10,
    injected_events=[
        InjectedEvent(kind="gps_loss", at_second=30, duration_s=90, target_track_id="SIM-005")
    ],
)
CHECKLIST = [
    "System raises lost-link alert within 30 s of GPS loss",
    "Remaining aircraft receive avoidance advisories",
]


@pytest.fixture(autouse=True)
def stub_rag_citations(monkeypatch):
    monkeypatch.setattr(executor, "_enrich_citations", lambda violations, scenario: [])


@pytest.fixture(autouse=True)
def clear_llm_mock():
    llm.set_mock_handler(None)
    yield
    llm.set_mock_handler(None)


@pytest.fixture()
def report():
    return run_scenario("brief-test-1", SCENARIO, "typhoon gps loss", CHECKLIST)


def _mock_writer(messages, tools):  # noqa: ARG001
    """Answer in whichever language the prompt demands."""
    system = messages[0]["content"]
    if "Cantonese" in system:
        text = "# 社區通告\n\n演練入面有架無人機唔見咗 GPS，系統 1 秒就拉咗警報。"
    elif "Traditional characters" in system:
        text = "# 社區通告\n\n演練中一架無人機失去 GPS，系統即時發出告警。"
    else:
        text = "# Community Notice\n\nOne drone lost GPS; the system alerted within 1 s."
    return {"role": "assistant", "content": text}


def test_llm_briefs_cover_three_languages(report):
    llm.set_mock_handler(_mock_writer)
    briefs, generated_with = generate_briefs("community", report)
    assert generated_with == "llm"
    assert set(briefs) == {"zh", "en", "yue"}
    assert "Community Notice" in briefs["en"]
    assert briefs["zh"].startswith("#")
    assert "唔見咗" in briefs["yue"]  # genuinely Cantonese


def test_prompt_scopes_facts_to_report(report):
    seen = {}

    def capture(messages, tools):  # noqa: ARG001
        seen["system"] = messages[0]["content"]
        seen["user"] = messages[1]["content"]
        return {"role": "assistant", "content": "# x\n\nstub"}

    llm.set_mock_handler(capture)
    generate_briefs("cad_technical", report)
    assert "never invent" in seen["system"]
    assert "CAD Technical Summary" in seen["system"]
    payload = seen["user"]
    assert "brief-test-1" in payload
    assert "pass_rate" in payload  # numbers come from the structured report


def test_audience_templates_have_distinct_sections(report):
    llm.set_mock_handler(_mock_writer)
    seen = {}

    def capture(messages, tools):  # noqa: ARG001
        seen.setdefault("systems", []).append(messages[0]["content"])
        return {"role": "assistant", "content": "# x\n\nstub"}

    llm.set_mock_handler(capture)
    generate_briefs("cad_technical", report)
    generate_briefs("legco_policy", report)
    generate_briefs("community", report)
    systems = seen["systems"]
    assert any("Checklist verification results" in s for s in systems)
    assert any("Policy relevance" in s for s in systems)
    assert any("Was anyone at risk" in s for s in systems)


def test_fallback_briefs_when_llm_down(report):
    def boom(messages, tools):  # noqa: ARG001
        raise RuntimeError("All LLM providers failed")

    llm.set_mock_handler(boom)
    briefs, generated_with = generate_briefs("legco_policy", report)
    assert generated_with == "fallback"
    assert set(briefs) == {"zh", "en", "yue"}
    # numbers straight from the report, no invention
    assert "100%" in briefs["en"] or "pass" in briefs["en"].lower()
    assert "立法會政策簡報" in briefs["zh"]
    # Cantonese fallback honestly marks itself as written-Chinese template
    assert "離線範本" in briefs["yue"]


def test_briefs_never_leak_keys(report):
    def leaker(messages, tools):  # noqa: ARG001
        return {
            "role": "assistant",
            "content": "# brief\n\nkey: sk-abcdef1234567890abcdef",
        }

    llm.set_mock_handler(leaker)
    briefs, _ = generate_briefs("community", report)
    assert "sk-abcdef1234567890abcdef" not in "".join(briefs.values())

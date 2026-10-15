"""Scenario generator tests — mock LLM, no live API keys required.

Covers: valid-JSON happy path, schema-validation retry, the disclosed
heuristic fallback, and the Cantonese/Chinese extraction the demo leans on.
"""

import json

import pytest

from app.ai import llm
from app.scenarios.generator import _fallback_generate, generate_scenario

VALID_PAYLOAD = {
    "scenario": {
        "area": "Sha Tin — Science Park",
        "time_window": "2026-10-20T09:00:00+08:00/PT30M",
        "weather": "typhoon_approaching",
        "traffic_density": "high",
        "aircraft_count": 10,
        "injected_events": [
            {
                "kind": "gps_loss",
                "at_second": 300,
                "duration_s": 120,
                "target_track_id": "SIM-005",
                "detail": "GPS signal lost",
            }
        ],
        "expected_system_behavior": [
            {"check": "System raises lost-link alert within 30 s of GPS loss"},
            {"check": "Remaining aircraft receive avoidance advisories"},
        ],
    },
    "checklist": [
        "System raises lost-link alert within 30 s of GPS loss",
        "Remaining aircraft receive avoidance advisories",
    ],
}


@pytest.fixture(autouse=True)
def clear_llm_mock():
    llm.set_mock_handler(None)
    yield
    llm.set_mock_handler(None)


def _assistant(payload) -> dict:
    return {"role": "assistant", "content": json.dumps(payload)}


def test_valid_llm_json_parsed_directly():
    llm.set_mock_handler(lambda messages, tools: _assistant(VALID_PAYLOAD))
    result = generate_scenario("typhoon, 10 drones, one loses GPS at minute 5")
    assert result.source == "llm"
    assert result.attempts == 1
    assert result.scenario.aircraft_count == 10
    assert result.scenario.injected_events[0].kind == "gps_loss"
    assert result.scenario.injected_events[0].at_second == 300
    assert len(result.checklist) == 2


def test_markdown_fenced_json_accepted():
    fenced = {"role": "assistant", "content": f"```json\n{json.dumps(VALID_PAYLOAD)}\n```"}
    llm.set_mock_handler(lambda messages, tools: fenced)
    result = generate_scenario("anything")
    assert result.source == "llm"
    assert result.scenario.weather == "typhoon_approaching"


def test_invalid_json_triggers_retry_then_succeeds():
    calls = {"n": 0}

    def flaky(messages, tools):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            return {"role": "assistant", "content": "not json at all"}
        return _assistant(VALID_PAYLOAD)

    llm.set_mock_handler(flaky)
    result = generate_scenario("typhoon scenario")
    assert result.source == "llm"
    assert result.attempts == 2
    assert calls["n"] == 2


def test_schema_violation_triggers_retry():
    bad = json.loads(json.dumps(VALID_PAYLOAD))
    bad["scenario"]["traffic_density"] = "extreme"  # not in the Literal
    calls = {"n": 0}

    def first_bad(messages, tools):  # noqa: ARG001
        calls["n"] += 1
        return _assistant(bad if calls["n"] == 1 else VALID_PAYLOAD)

    llm.set_mock_handler(first_bad)
    result = generate_scenario("typhoon scenario")
    assert result.attempts == 2
    assert result.scenario.traffic_density == "high"


def test_persistent_failure_falls_back_with_warning():
    llm.set_mock_handler(
        lambda messages, tools: {"role": "assistant", "content": "garbage"}  # noqa: ARG005
    )
    result = generate_scenario("台风逼近，沙田 10 架无人机同时作业，第 5 分钟一架丢 GPS")
    assert result.source == "fallback"
    assert result.warnings, "fallback must always be disclosed"
    # heuristic extraction still got the essentials
    assert result.scenario.aircraft_count == 10
    assert result.scenario.weather == "typhoon_approaching"
    assert result.scenario.injected_events[0].kind == "gps_loss"
    assert result.scenario.injected_events[0].at_second == 300


def test_llm_outage_falls_back():
    def boom(messages, tools):  # noqa: ARG001
        raise RuntimeError("All LLM providers failed: connection refused")

    llm.set_mock_handler(boom)
    result = generate_scenario("Typhoon eve: 10 drones over Sha Tin, one loses GPS at minute 5")
    assert result.source == "fallback"
    assert result.scenario.aircraft_count == 10
    assert result.checklist


def test_fallback_parser_english():
    result = _fallback_generate("gale warning: 3 drones, one drifts off course at minute 2")
    assert result.scenario.aircraft_count == 3
    assert result.scenario.weather == "gale"
    assert result.scenario.traffic_density == "low"
    assert result.scenario.injected_events[0].kind == "off_course"
    assert result.scenario.injected_events[0].at_second == 120


def test_fallback_parser_target_track_from_ordinal():
    result = _fallback_generate("台风: 10 架无人机, 第 5 分钟第 7 架丢 GPS")
    assert result.scenario.injected_events[0].target_track_id == "SIM-007"

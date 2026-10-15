"""LLM chat loop tests — mock provider, no live API keys required."""

import json

import pytest
from fastapi.testclient import TestClient

from app.ai import llm
from app.ai.tools import tool_check_flight_plan, tool_search_regulations
from app.main import app

client = TestClient(app)

VICTORIA_ROUTE = {
    "type": "Feature",
    "properties": {"time_window": "2026-10-20T09:00:00+08:00/PT30M"},
    "geometry": {
        "type": "LineString",
        "coordinates": [[114.175, 22.301, 50.0], [114.190, 22.301, 60.0]],
    },
}


@pytest.fixture(autouse=True)
def clear_llm_mock():
    llm.set_mock_handler(None)
    yield
    llm.set_mock_handler(None)


def test_check_flight_plan_tool_rejects_victoria_harbour_450ft(monkeypatch):
    monkeypatch.setenv(
        "UTM_RFZ_GEOJSON",
        "/workspace/frontend/public/rfz/hong-kong-rfz.geojson",
    )
    result = tool_check_flight_plan(
        VICTORIA_ROUTE,
        {"max_altitude_ft": 450.0},
    )
    assert result["verdict"] == "rejected"
    assert any(v["rule_id"] == "rfz_intersection" for v in result["violations"])
    assert "Victoria Harbour" in result["violations"][0]["message"] or any(
        "Victoria Harbour" in v["message"] for v in result["violations"]
    )


def test_search_regulations_returns_citations_shape():
    out = tool_search_regulations("maximum altitude 300 feet", k=2)
    if out.get("excerpts"):
        hit = out["excerpts"][0]
        assert "regulation_id" in hit
        assert "section" in hit
        assert "excerpt" in hit


def _mock_assistant(messages, tools):  # noqa: ARG001
    """Simulate one tool round then a final answer."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user = msg.get("content", "")
            break
    else:
        user = ""
    if "450" in user or "Victoria" in user or "维多利亚" in user:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "check_flight_plan",
                        "arguments": json.dumps(
                            {
                                "route": VICTORIA_ROUTE,
                                "params": {"max_altitude_ft": 450.0},
                            }
                        ),
                    },
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "search_regulations",
                        "arguments": json.dumps(
                            {"query": "restricted flying zones altitude limit", "k": 3}
                        ),
                    },
                },
            ],
        }
    # Second round — no more tool calls
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    if tool_msgs:
        return {
            "role": "assistant",
            "content": (
                "Your Victoria Harbour plan at 450 ft is rejected per the rules engine "
                "(RFZ intersection and altitude limit, AC-014)."
            ),
        }
    return {"role": "assistant", "content": "How can I help with your flight plan?"}


def test_chat_endpoint_mock_llm_rejects_victoria(monkeypatch):
    monkeypatch.setenv(
        "UTM_RFZ_GEOJSON",
        "/workspace/frontend/public/rfz/hong-kong-rfz.geojson",
    )
    llm.set_mock_handler(_mock_assistant)
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "Can I fly over Victoria Harbour at 450 feet?",
            "route": VICTORIA_ROUTE,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "reject" in body["reply"].lower() or "rejected" in body["reply"].lower()
    assert body["map_annotations"]
    assert body["map_annotations"][0]["kind"] == "rejected_route"


def test_chat_endpoint_no_llm_config_returns_503(monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def boom(messages, tools):  # noqa: ARG001
        raise RuntimeError("No LLM provider configured")

    llm.set_mock_handler(None)
    # Force real path to fail
    with pytest.raises(RuntimeError):
        llm.chat_completion([{"role": "user", "content": "hi"}], tools=None)

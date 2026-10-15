"""Phase-3 API flow tests — mock LLM end to end, no live keys.

create scenario → run → export report (json + markdown) → trilingual brief,
plus the 404 paths and the no-keys-in-output security red line.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

import app.scenarios.executor as executor
from app.ai import llm
from app.main import app
from app.scenarios import store

client = TestClient(app)

SCENARIO_PAYLOAD = {
    "scenario": {
        "area": "Sha Tin — Science Park",
        "time_window": "2026-10-20T09:00:00+08:00/PT5M",
        "weather": "typhoon_approaching",
        "traffic_density": "high",
        "aircraft_count": 10,
        "injected_events": [
            {
                "kind": "gps_loss",
                "at_second": 30,
                "duration_s": 90,
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

DESCRIPTION = "台风逼近，沙田 10 架无人机同时作业，第 5 分钟一架丢 GPS"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    store.clear()
    monkeypatch.setattr(executor, "_enrich_citations", lambda violations, scenario: [])
    llm.set_mock_handler(None)
    yield
    llm.set_mock_handler(None)
    store.clear()


def _mock_llm(messages, tools):  # noqa: ARG001
    system = messages[0].get("content", "")
    if "scenario generator" in system:
        return {"role": "assistant", "content": json.dumps(SCENARIO_PAYLOAD)}
    if "brief writer" in system:
        if "Cantonese" in system:
            return {"role": "assistant", "content": "# 社區通告\n\n有架機唔見咗 GPS。"}
        if "Traditional characters" in system:
            return {"role": "assistant", "content": "# 社區通告\n\n一架無人機失去 GPS。"}
        return {"role": "assistant", "content": "# Brief\n\nGPS lost; alerted in 1 s."}
    return {"role": "assistant", "content": "ok"}


def _create_scenario() -> str:
    response = client.post("/api/v1/scenarios", json={"description": DESCRIPTION})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["scenario_json"]["aircraft_count"] == 10
    assert body["scenario_json"]["injected_events"][0]["kind"] == "gps_loss"
    assert len(body["checklist"]) == 2
    return body["id"]


def test_full_scenario_flow():
    llm.set_mock_handler(_mock_llm)
    scenario_id = _create_scenario()

    # fetch-back
    got = client.get(f"/api/v1/scenarios/{scenario_id}")
    assert got.status_code == 200
    assert got.json()["scenario_json"]["weather"] == "typhoon_approaching"

    # run
    ran = client.post(f"/api/v1/scenarios/{scenario_id}/run")
    assert ran.status_code == 200, ran.text
    body = ran.json()
    assert body["status"] == "completed"
    assert body["report_url"] == f"/api/v1/scenarios/{scenario_id}/report"
    report = body["report"]
    assert report["summary"]["total_checks"] == 2
    assert report["summary"]["passed"] == 2
    assert report["summary"]["pass_rate"] == 1.0
    assert any(e["kind"] == "fault_detected" for e in report["timeline"])
    assert report["checks"][0]["regulation_ref"] == "AC-014"
    assert "## Timeline" in body["markdown"]

    # export json
    rjson = client.get(f"/api/v1/scenarios/{scenario_id}/report")
    assert rjson.status_code == 200
    assert rjson.json()["scenario_id"] == scenario_id

    # export markdown
    rmd = client.get(f"/api/v1/scenarios/{scenario_id}/report?format=markdown")
    assert rmd.status_code == 200
    assert rmd.headers["content-type"].startswith("text/markdown")
    assert "attachment" in rmd.headers["content-disposition"]
    assert "# UTM Scenario Test Report" in rmd.text

    # briefs for every audience
    for audience in ("cad_technical", "legco_policy", "community"):
        brief = client.post(
            f"/api/v1/scenarios/{scenario_id}/brief", json={"audience": audience}
        )
        assert brief.status_code == 200, brief.text
        data = brief.json()
        assert set(data["briefs"]) == {"zh", "en", "yue"}
        assert data["generated_with"] == "llm"
        assert all(v.strip().startswith("#") for v in data["briefs"].values())


def test_unknown_scenario_404s():
    assert client.get("/api/v1/scenarios/nope").status_code == 404
    assert client.post("/api/v1/scenarios/nope/run").status_code == 404
    assert client.get("/api/v1/scenarios/nope/report").status_code == 404
    assert (
        client.post("/api/v1/scenarios/nope/brief", json={"audience": "community"}).status_code
        == 404
    )


def test_report_before_run_404s():
    llm.set_mock_handler(_mock_llm)
    scenario_id = _create_scenario()
    assert client.get(f"/api/v1/scenarios/{scenario_id}/report").status_code == 404


def test_api_keys_never_appear_in_outputs():
    """Security red line: a key pasted into the description must not round-trip."""
    real_key = os.getenv("KIMI_API_KEY", "")
    poison = f"test sk-fakekey1234567890abcdef {real_key}".strip()
    llm.set_mock_handler(_mock_llm)
    created = client.post("/api/v1/scenarios", json={"description": poison})
    scenario_id = created.json()["id"]
    ran = client.post(f"/api/v1/scenarios/{scenario_id}/run")
    blob = json.dumps(ran.json(), ensure_ascii=False)
    assert "sk-fakekey1234567890abcdef" not in blob
    if real_key:
        assert real_key not in blob
        brief = client.post(
            f"/api/v1/scenarios/{scenario_id}/brief", json={"audience": "community"}
        )
        assert real_key not in json.dumps(brief.json(), ensure_ascii=False)

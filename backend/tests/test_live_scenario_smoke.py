"""Live-API smoke test — real Kimi/DeepSeek, full Phase-3 flow.

Skipped by default; run explicitly with:

    cd backend && RUN_LIVE_LLM=1 pytest tests/test_live_scenario_smoke.py -v

Requires KIMI_API_KEY or DEEPSEEK_API_KEY in backend/.env (or the
environment). This is the pre-demo verification that the typhoon + GPS-loss
scenario works end to end against the real provider chain.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scenarios import store

client = TestClient(app)

RUN_LIVE = os.getenv("RUN_LIVE_LLM") == "1"
HAVE_KEYS = bool(os.getenv("KIMI_API_KEY") or os.getenv("DEEPSEEK_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (RUN_LIVE and HAVE_KEYS),
    reason="live LLM smoke — set RUN_LIVE_LLM=1 with provider keys configured",
)


def test_live_typhoon_gps_scenario_end_to_end():
    store.clear()
    description = "台风逼近，沙田 10 架无人机同时作业，第 5 分钟一架丢 GPS"

    created = client.post("/api/v1/scenarios", json={"description": description})
    assert created.status_code == 201, created.text
    body = created.json()
    scenario = body["scenario_json"]
    assert scenario["aircraft_count"] == 10
    assert scenario["weather"] in ("typhoon_approaching", "gale", "rain", "overcast")
    assert scenario["injected_events"], "LLM should inject at least the GPS-loss event"
    kinds = {e["kind"] for e in scenario["injected_events"]}
    assert kinds & {"gps_loss", "comms_loss"}
    assert body["checklist"]
    scenario_id = body["id"]

    ran = client.post(f"/api/v1/scenarios/{scenario_id}/run")
    assert ran.status_code == 200, ran.text
    report = ran.json()["report"]
    assert report["summary"]["total_checks"] > 0
    assert 0.0 <= report["summary"]["pass_rate"] <= 1.0
    assert report["timeline"]

    brief = client.post(
        f"/api/v1/scenarios/{scenario_id}/brief", json={"audience": "community"}
    )
    assert brief.status_code == 200, brief.text
    data = brief.json()
    assert set(data["briefs"]) == {"zh", "en", "yue"}
    assert data["generated_with"] in ("llm", "mixed")
    for lang, md in data["briefs"].items():
        assert len(md) > 200, f"{lang} brief suspiciously short"
        assert md.lstrip().startswith("#")

    store.clear()

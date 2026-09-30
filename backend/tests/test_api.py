"""Contract tests for POST /api/v1/flight-plans/check with the real engine.

Data-independent on purpose: these cases must behave the same whether or not
data/rfz/ is populated, so they use the Sha Tin route verified clear of the
real 286-zone snapshot and an altitude breach that needs no spatial layer.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CLEAN_ROUTE = {
    "type": "Feature",
    "properties": {"time_window": "2026-10-20T09:00:00+08:00/PT30M"},
    "geometry": {
        "type": "LineString",
        "coordinates": [[114.180, 22.390, 50.0], [114.196, 22.392, 60.0]],
    },
}


def test_check_endpoint_approves_clean_plan():
    response = client.post(
        "/api/v1/flight-plans/check",
        json={"route_geojson": CLEAN_ROUTE, "params": {"max_altitude_ft": 250.0}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "approved"
    assert body["violations"] == []
    assert body["suggestions"] == []


def test_check_endpoint_rejects_over_altitude_plan():
    response = client.post(
        "/api/v1/flight-plans/check",
        json={"route_geojson": CLEAN_ROUTE, "params": {"max_altitude_ft": 450.0}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "rejected"
    assert any(v["rule_id"] == "altitude_limit" for v in body["violations"])
    assert all(v["regulation_ref"] == "AC-014" for v in body["violations"])
    assert body["suggestions"][0]["kind"] == "lower_altitude"

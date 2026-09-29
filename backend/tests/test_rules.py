"""Rule engine unit tests — Phase 0: altitude rule is live, the other four
rules are stubs that must at least run and return lists.

Phase 1 (step 1.3) adds the deliberately-non-compliant route cases (e.g. a
route through an RFZ must be rejected with the hit clauses listed).
"""

from app.rules_engine import RULES, check_flight_plan
from app.schemas.flight_plan import FlightPlanParams

ROUTE = {
    "type": "LineString",
    "coordinates": [[114.17, 22.30, 50.0], [114.20, 22.39, 60.0]],
}


def test_five_core_rules_registered():
    assert len(RULES) == 5


def test_compliant_plan_approved():
    params = FlightPlanParams(max_altitude_ft=250.0)
    assert check_flight_plan(ROUTE, params) == []


def test_over_altitude_rejected_with_citation():
    params = FlightPlanParams(max_altitude_ft=450.0)
    violations = check_flight_plan(ROUTE, params)
    assert len(violations) == 1
    assert violations[0].rule_id == "altitude_limit"
    assert violations[0].regulation_ref == "AC-014"

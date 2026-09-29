"""Rule engine v1 unit tests — the five CAD-derived rules as pure functions.

Covers: a clean route approved end-to-end, a deliberately offending route
rejected with the hit clauses, the 300 ft edge case, RFZ intersection against
the synthetic Sha Tin fixture, 30 m separation with an injected buildings
layer, pending-data behaviour when layers are absent, and the time-window
validity check.
"""

from pathlib import Path

from shapely.geometry import box

from app.rules_engine import RULES, RuleContext, check_flight_plan, evaluate_flight_plan
from app.rules_engine.layers import load_rfz_zones
from app.schemas.flight_plan import FlightPlanParams, RuleViolation

FIXTURE_RFZ = Path(__file__).parent / "fixtures" / "rfz_sample.geojson"

VALID_WINDOW = "2026-10-20T09:00:00+08:00/PT30M"

# Threads between the three fixture zones; also verified clear of the real
# 286-zone eSUA snapshot, so API tests behave the same with or without data.
CLEAN_ROUTE = {
    "type": "Feature",
    "properties": {"time_window": VALID_WINDOW},
    "geometry": {
        "type": "LineString",
        "coordinates": [[114.180, 22.390, 50.0], [114.196, 22.392, 60.0]],
    },
}

# Straight through the "Sha Tin Central (test)" fixture zone at 120-130 m.
OFFENDING_ROUTE = {
    "type": "Feature",
    "properties": {"time_window": "2026-10-20T10:00:00+08:00/2026-10-20T09:00:00+08:00"},
    "geometry": {
        "type": "LineString",
        "coordinates": [[114.180, 22.380, 120.0], [114.200, 22.380, 130.0]],
    },
}


def _ctx(**overrides) -> RuleContext:
    base = {"rfz_zones": load_rfz_zones(str(FIXTURE_RFZ)), "obstacles": None}
    base.update(overrides)
    return RuleContext(**base)


def _result(result, rule_id):
    return next(r for r in result.results if r.rule_id == rule_id)


def test_five_core_rules_registered():
    assert len(RULES) == 5


def test_clean_route_approved():
    result = evaluate_flight_plan(
        CLEAN_ROUTE, FlightPlanParams(max_altitude_ft=250.0), rfz_path=str(FIXTURE_RFZ)
    )
    assert result.verdict == "approved"
    assert result.violations == []
    assert result.clauses_hit == []
    # separation layer is not pipelined yet — structured but pending-data
    assert _result(result, "horizontal_separation").pending_data is True


def test_offending_route_rejected_with_clauses():
    params = FlightPlanParams(
        aircraft_category="cat_b",
        max_altitude_ft=450.0,
        within_visual_line_of_sight=False,
        operator=None,
    )
    result = evaluate_flight_plan(OFFENDING_ROUTE, params, rfz_path=str(FIXTURE_RFZ))
    assert result.verdict == "rejected"
    rule_ids = {v.rule_id for v in result.violations}
    assert {
        "altitude_limit",
        "rfz_intersection",
        "aircraft_category",
        "time_window",
    } <= rule_ids
    assert "AC-014" in result.clauses_hit
    rfz = _result(result, "rfz_intersection")
    assert "Sha Tin Central (test)" in rfz.detail
    assert rfz.segment_index == 0


def test_altitude_exactly_300ft_passes():
    route = {
        "type": "Feature",
        "properties": {"time_window": VALID_WINDOW},
        "geometry": {
            "type": "LineString",
            "coordinates": [[114.180, 22.390, 91.44], [114.196, 22.392, 91.44]],
        },
    }
    result = evaluate_flight_plan(
        route, FlightPlanParams(max_altitude_ft=300.0), rfz_path=str(FIXTURE_RFZ)
    )
    assert _result(result, "altitude_limit").passed is True
    assert result.verdict == "approved"


def test_altitude_just_over_300ft_fails():
    result = evaluate_flight_plan(
        CLEAN_ROUTE, FlightPlanParams(max_altitude_ft=300.1), rfz_path=str(FIXTURE_RFZ)
    )
    altitude = _result(result, "altitude_limit")
    assert altitude.passed is False
    assert altitude.clause_ref == "AC-014"


def test_route_point_altitude_over_91_44m_fails():
    result = evaluate_flight_plan(
        CLEAN_ROUTE,
        FlightPlanParams(max_altitude_ft=250.0),
        rfz_path=str(FIXTURE_RFZ),
    )
    assert _result(result, "altitude_limit").passed is True
    high_route = {
        "type": "LineString",
        "coordinates": [[114.180, 22.390, 50.0], [114.196, 22.392, 92.0]],
        "time_window": VALID_WINDOW,
    }
    result = evaluate_flight_plan(
        high_route, FlightPlanParams(max_altitude_ft=250.0), rfz_path=str(FIXTURE_RFZ)
    )
    altitude = _result(result, "altitude_limit")
    assert altitude.passed is False
    assert "92.0 m" in altitude.detail


def test_rfz_pending_data_when_file_absent():
    result = evaluate_flight_plan(
        CLEAN_ROUTE,
        FlightPlanParams(),
        rfz_path="/nonexistent/rfz.geojson",
    )
    rfz = _result(result, "rfz_intersection")
    assert rfz.passed is True
    assert rfz.pending_data is True
    assert "pending-data" in rfz.detail


def test_rfz_route_clearing_all_zones_passes():
    result = evaluate_flight_plan(
        CLEAN_ROUTE, FlightPlanParams(), rfz_path=str(FIXTURE_RFZ)
    )
    rfz = _result(result, "rfz_intersection")
    assert rfz.passed is True
    assert "3 loaded restricted flying zones" in rfz.detail


def test_horizontal_separation_violation():
    # ~22 m from the clean route's midpoint (0.0002 deg lat)
    near_building = box(114.18795, 22.39115, 114.18805, 22.39125)
    result = evaluate_flight_plan(
        CLEAN_ROUTE,
        FlightPlanParams(),
        context=_ctx(obstacles=[near_building]),
    )
    separation = _result(result, "horizontal_separation")
    assert separation.passed is False
    assert "30 m" in separation.detail


def test_horizontal_separation_clear():
    # ~445 m away from the route
    far_building = box(114.1879, 22.3949, 114.1881, 22.3951)
    result = evaluate_flight_plan(
        CLEAN_ROUTE,
        FlightPlanParams(),
        context=_ctx(obstacles=[far_building]),
    )
    assert _result(result, "horizontal_separation").passed is True


def test_horizontal_separation_pending_data():
    result = evaluate_flight_plan(
        CLEAN_ROUTE, FlightPlanParams(), context=_ctx(obstacles=None)
    )
    separation = _result(result, "horizontal_separation")
    assert separation.passed is True
    assert separation.pending_data is True


def test_cat_b_bvlos_and_missing_operator_rejected():
    params = FlightPlanParams(
        aircraft_category="cat_b", within_visual_line_of_sight=False, operator=None
    )
    result = evaluate_flight_plan(CLEAN_ROUTE, params, rfz_path=str(FIXTURE_RFZ))
    category = _result(result, "aircraft_category")
    assert category.passed is False
    assert "visual line of sight" in category.detail
    assert "operator" in category.detail


def test_cat_b_compliant_and_cat_a_unrestricted():
    compliant = FlightPlanParams(
        aircraft_category="cat_b", within_visual_line_of_sight=True, operator="demo-op"
    )
    result = evaluate_flight_plan(CLEAN_ROUTE, compliant, rfz_path=str(FIXTURE_RFZ))
    assert _result(result, "aircraft_category").passed is True
    result = evaluate_flight_plan(
        CLEAN_ROUTE, FlightPlanParams(aircraft_category="cat_a"), rfz_path=str(FIXTURE_RFZ)
    )
    assert _result(result, "aircraft_category").passed is True


def test_time_window_missing_is_pending():
    route = {
        "type": "LineString",
        "coordinates": [[114.180, 22.390, 50.0], [114.196, 22.392, 60.0]],
    }
    result = evaluate_flight_plan(route, FlightPlanParams(), rfz_path=str(FIXTURE_RFZ))
    window = _result(result, "time_window")
    assert window.passed is True
    assert window.pending_data is True


def test_time_window_unparseable_rejected():
    route = {
        "type": "LineString",
        "coordinates": [[114.180, 22.390, 50.0], [114.196, 22.392, 60.0]],
        "time_window": "next tuesday morning",
    }
    result = evaluate_flight_plan(route, FlightPlanParams(), rfz_path=str(FIXTURE_RFZ))
    assert _result(result, "time_window").passed is False


def test_time_window_over_12h_rejected():
    route = {
        "type": "LineString",
        "coordinates": [[114.180, 22.390, 50.0], [114.196, 22.392, 60.0]],
        "time_window": "2026-10-20T06:00:00+08:00/2026-10-20T20:00:00+08:00",
    }
    result = evaluate_flight_plan(route, FlightPlanParams(), rfz_path=str(FIXTURE_RFZ))
    window = _result(result, "time_window")
    assert window.passed is False
    assert "12 h" in window.detail


def test_check_flight_plan_backcompat_wrapper():
    violations = check_flight_plan(CLEAN_ROUTE, FlightPlanParams(max_altitude_ft=450.0))
    assert len(violations) == 1
    assert isinstance(violations[0], RuleViolation)
    assert violations[0].rule_id == "altitude_limit"
    assert violations[0].regulation_ref == "AC-014"

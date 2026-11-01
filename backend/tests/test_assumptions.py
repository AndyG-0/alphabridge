import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import assumptions as a
from services import quant_engine as qe


@pytest.fixture(autouse=True)
def _restore():
    yield
    a.apply({})


def test_every_assumption_has_default_and_source():
    assert all(r["source"] and r["min"] <= r["default"] <= r["max"] for r in a.CATALOG)


def test_apply_defaults_is_a_no_op():
    before = (dict(qe.ASSET_ASSUMPTIONS), qe.INFLATION, qe.CORR_EQUITY)
    a.apply({})
    assert (dict(qe.ASSET_ASSUMPTIONS), qe.INFLATION, qe.CORR_EQUITY) == before


def test_override_changes_engine_and_reset_restores():
    a.apply({"ret.US_EQUITY": 0.05, "inflation": 0.03})
    assert qe.ASSET_ASSUMPTIONS["US_EQUITY"][0] == 0.05 and qe.INFLATION == 0.03
    assert qe.expected_return_vol({"US_EQUITY": 1})[0] == pytest.approx(0.05)
    a.apply({})
    assert qe.ASSET_ASSUMPTIONS["US_EQUITY"][0] == 0.075 and qe.INFLATION == 0.025


def test_correlation_override_moves_portfolio_vol():
    base = qe.expected_return_vol({"US_EQUITY": 0.5, "INTL_EQUITY": 0.5})[1]
    a.apply({"corr.equity": 0.2})
    assert qe.expected_return_vol({"US_EQUITY": 0.5, "INTL_EQUITY": 0.5})[1] < base


def test_validate_rejects_unknown_and_out_of_range():
    with pytest.raises(ValueError):
        a.validate({"nope": 1})
    with pytest.raises(ValueError):
        a.validate({"inflation": 0.5})
    assert a.validate({"inflation": None}) == {}


def test_fee_drag_known_answer():
    r = a.fee_drag(100_000, 0, 10, 0.07, 0.01)
    assert r["without_fee"] == pytest.approx(100_000 * 1.07**10) and r["with_fee"] == pytest.approx(100_000 * 1.06**10)
    assert a.fee_drag(1, 1, 5, 0.05, 0)["cost"] == pytest.approx(0)


@settings(max_examples=30, deadline=None)
@given(fee=st.floats(0, 0.03), more=st.floats(0, 0.02))
def test_fee_drag_monotone_in_fee(fee, more):
    assert a.fee_drag(50_000, 5_000, 20, 0.07, fee)["cost"] <= a.fee_drag(50_000, 5_000, 20, 0.07, fee + more)["cost"] + 1e-6


def test_health_known_answer_and_bounds():
    h = a.health(
        {"success_rate": 0.85, "target_success_rate": 0.85, "bridge_readiness_pct": 100, "planned_spend_monthly": 5000, "sustainable_spend_monthly": 5000}
    )
    assert h["score"] == 100 and h["grade"] == "STRONG" and sum(p["points"] for p in h["parts"]) == pytest.approx(100)
    weak = a.health(
        {"success_rate": 0.2, "target_success_rate": 0.85, "bridge_readiness_pct": 10, "planned_spend_monthly": 5000, "sustainable_spend_monthly": 1000}
    )
    assert 0 <= weak["score"] < 65 and weak["grade"] == "WEAK"


def test_diff_reports_changes_only():
    prev = {"metrics": {"success_rate": 0.8, "earliest_retirement_age": 55}, "assumptions": {"inflation": 0.025}}
    cur = {"metrics": {"success_rate": 0.7, "earliest_retirement_age": 55}, "assumptions": {"inflation": 0.03}}
    d = a.diff(prev, cur)
    assert [m["metric"] for m in d["metrics"]] == ["success_rate"] and d["assumptions"][0]["key"] == "inflation"
    assert a.diff(None, cur)["has_previous"] is False


def test_routes_roundtrip_and_snapshot_diff(client):
    assert client.put("/api/planner/assumptions", json={"overrides": {"inflation": 0.9}}).status_code == 400
    assert client.put("/api/planner/assumptions", json={}).status_code == 400
    r = client.put("/api/planner/assumptions", json={"overrides": {"inflation": 0.03}})
    assert r.status_code == 200 and r.get_json()["overridden"] == 1
    first = client.post("/api/planner/health/snapshot").get_json()
    assert 0 <= first["health"]["score"] <= 100 and first["diff"]["has_previous"] is False
    client.put("/api/planner/assumptions", json={"overrides": {"inflation": None, "ret.US_EQUITY": 0.05}})
    second = client.get("/api/planner/health").get_json()
    assert second["diff"]["has_previous"] is True and {x["key"] for x in second["diff"]["assumptions"]} >= {"inflation", "ret.US_EQUITY"}
    assert client.get("/api/planner/fee-drag?balance=1000&years=5").status_code == 200

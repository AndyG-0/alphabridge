import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import survivor as sv


def test_exemption_data_is_sourced():
    d = sv.defaults()
    assert d["source_url"].startswith("https://") and d["retrieved_on"] and d["basic_exclusion"] == 15_000_000


def test_estate_ok_watch_over():
    assert sv.estate_exposure(5_000_000, True)["flag"] == "OK"
    assert sv.estate_exposure(25_000_000, True)["flag"] == "WATCH"
    r = sv.estate_exposure(20_000_000, False)
    assert r["flag"] == "OVER" and r["estimated_tax"] == pytest.approx(5_000_000 * 0.4)


def test_portability_doubles_the_shelter():
    assert sv.estate_exposure(20_000_000, True)["estimated_tax"] == 0
    assert sv.estate_exposure(20_000_000, True, portability=False)["estimated_tax"] > 0


def test_survivor_keeps_larger_benefit():
    r = sv.survivor_social_security(3000, 1500, 67, 67)
    assert r["household_after"] == pytest.approx(3000) and r["monthly_lost"] == pytest.approx(1500)
    low = sv.survivor_social_security(1500, 3000, 67, 67)
    assert low["household_after"] == pytest.approx(3000) and low["monthly_lost"] == pytest.approx(1500)


def test_widows_penalty_same_income_more_tax():
    r = sv.death_of_spouse(year=2026, spend=90_000, ss_before_monthly=4500, ss_after_monthly=3000, other_ordinary=0, pretax_draw=60_000)
    assert r["tax_after"] > 0 and r["income_after"] < r["income_before"]
    same = sv.death_of_spouse(year=2026, spend=90_000, ss_before_monthly=3000, ss_after_monthly=3000, other_ordinary=0, pretax_draw=80_000)
    assert same["widows_penalty"] and same["tax_increase"] > 0


def test_insurance_gap_known_answer():
    r = sv.insurance_gap(income=100_000, debts=200_000, liquid_assets=100_000, existing_life=300_000, group_disability_monthly=2000)
    assert r["life_need"] == pytest.approx(100_000 * 0.7 * 10 + 200_000 + 15_000)
    assert r["life_gap"] == pytest.approx(r["life_need"] - 400_000)
    assert r["disability_gap_monthly"] == pytest.approx(5000 - 2000)
    assert sv.insurance_gap(income=0, debts=0, liquid_assets=1e9, existing_life=0, group_disability_monthly=0)["life_gap"] == 0


def test_beneficiary_audit_is_a_checklist_not_findings():
    r = sv.beneficiary_audit([{"name": "IRA", "bucket": "PRE_TAX_401K", "owner": "SELF", "balance": 1.0}])
    assert r["stored"] is False and r["accounts"][0]["account"] == "IRA" and r["retitling"]


@settings(max_examples=30, deadline=None)
@given(nw=st.floats(0, 1e9), more=st.floats(0, 1e8))
def test_estate_tax_monotone_and_nonnegative(nw, more):
    a, b = sv.estate_exposure(nw, True)["estimated_tax"], sv.estate_exposure(nw + more, True)["estimated_tax"]
    assert 0 <= a <= b + 1e-6


def test_route(client):
    r = client.get("/api/planner/survivor")
    assert r.status_code == 200 and "estate" in r.get_json() and "insurance" in r.get_json()


def test_plan_for_married_household(app):
    from services import planner
    from tests.test_household import _profile

    with app.app_context():
        out = planner.survivor_plan(_profile(), {"annual_spend": 90_000})
    assert out["married"] and out["deceased"] == "SPOUSE"
    assert out["social_security"]["household_after"] <= out["social_security"]["household_before"]
    assert out["death_of_spouse"]["spend_after"] == pytest.approx(90_000 * 0.75)
    assert out["estate"]["portability_assumed"]

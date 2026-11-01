from datetime import date
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from schemas import ProfileIn
from services import household
from services import spending as sp


def test_default_model_is_flat():
    m = sp.load({})
    assert sp.is_default(m) and sp.multiplier(m, 80, 30) == pytest.approx(1.0)
    assert sum(sp.shares(m).values()) == pytest.approx(1.0)


def test_smile_phases_apply_by_age():
    m = sp.load({"smile": True})
    assert sp.phase_multiplier(m, 66) == 1.0
    assert sp.phase_multiplier(m, 75) == 0.92
    assert sp.phase_multiplier(m, 90) == 0.85
    assert sp.phase_multiplier(sp.load({}), 90) == 1.0  # off by default
    custom = sp.load({"smile": True, "phases": [{"from_age": 70, "multiplier": 0.5}]})
    assert sp.phase_multiplier(custom, 69) == 1.0 and sp.phase_multiplier(custom, 71) == 0.5


def test_category_inflation_weights_the_basket():
    m = sp.load({"shares": {"housing": 0.5, "other": 0.5}, "real_inflation": {"housing": 0.02}})
    assert sp.category_multiplier(m, 10) == pytest.approx(0.5 * 1.02**10 + 0.5)
    assert sp.category_multiplier(m, 0) == pytest.approx(1.0)


def test_validation():
    with pytest.raises(ValidationError):
        sp.load({"shares": {"a": 0.5}})
    with pytest.raises(ValidationError):
        sp.load({"real_inflation": {"housing": 0.5}})
    assert ProfileIn.model_validate({"spending_model": {"smile": True}}).spending_model == {"smile": True}
    with pytest.raises(ValidationError):
        ProfileIn.model_validate({"spending_model": {"shares": {"a": 2}}})


def test_projection_real_vs_nominal():
    m = sp.load({"smile": True})
    real = sp.projection(m, 60_000, 60, 65, 90)
    nom = sp.projection(m, 60_000, 60, 65, 90, 0.03, nominal=True)
    assert real["rows"][0]["age"] == 65 and real["rows"][0]["total"] == pytest.approx(60_000)
    assert nom["rows"][5]["total"] == pytest.approx(real["rows"][5]["total"] * 1.03 ** real["rows"][5]["year_index"])
    assert real["rows"][-1]["phase"] == "no-go" and real["rows"][0]["phase"] == "go-go"
    assert sp.to_nominal([100, 100], 0.1) == pytest.approx([100, 110]) and sp.to_real([100, 110], 0.1) == pytest.approx([100, 100])


def test_event_templates():
    assert set(sp.template_names()) == {"college", "wedding", "home_purchase", "car", "downsizing"}
    college = sp.event_from_template("college", 2040)[0]
    assert college["repeat_until_year"] == 2043 and college["repeat_every_years"] == 1
    home = sp.event_from_template("home_purchase", 2030, amount=500_000)[0]
    assert home["financed"] and home["amount"] == 500_000 and home["down_payment"] < home["amount"]
    assert sp.event_from_template("downsizing", 2045)[0]["is_home_sale"]


def test_data_file_flags_illustrative_figures():
    assert sp._data()["verified"] is False and "ILLUSTRATIVE" in sp._data()["notes"]


def _profile(model):
    return SimpleNamespace(
        name="A",
        current_age=55.0,
        spouse_age=0.0,
        target_retirement_age=60.0,
        social_security_monthly=0.0,
        annual_income=0.0,
        monthly_contribution=0.0,
        monthly_expenses_retirement=5_000.0,
        effective_tax_rate=0.1,
        health_inflation=0.05,
        dental_vision_monthly=0,
        health_oop_annual=0,
        medicare_monthly_per_person=0,
        home_value=0,
        home_upkeep_pct=0,
        ltc_years=0,
        ltc_annual=0,
        ltc_start_age=85,
        state="AZ",
        spending_model=model,
        aca_benchmark_premium_monthly=1,
    )


def _flows(model):
    return household.build_flows(_profile(model), [], [], retire_age=60, years=40, inflation=0.025, today=date(2026, 1, 1))


def test_flows_unchanged_by_default_model_and_adjusted_by_smile():
    base, same = _flows({}), _flows({"smile": False})
    assert (base.extra_spend == same.extra_spend).all()
    smile = _flows({"smile": True})
    y85 = 85 - 55
    assert smile.extra_spend[y85] - base.extra_spend[y85] == pytest.approx(60_000 * (0.85 - 1))
    assert smile.extra_spend[5] == base.extra_spend[5]  # go-go years untouched
    assert (smile.breakdown["spending_adjustment"][:5] == 0).all()  # nothing before retirement


@settings(max_examples=40, deadline=None)
@given(infl=st.floats(-0.1, 0.1), years=st.floats(0, 40))
def test_basket_multiplier_monotone_in_inflation(infl, years):
    lo = sp.category_multiplier(sp.load({"real_inflation": {"housing": infl}}), years)
    hi = sp.category_multiplier(sp.load({"real_inflation": {"housing": infl + 0.01}}), years)
    assert hi >= lo - 1e-12


def test_routes(client):
    assert client.put("/api/profile", json={"spending_model": {"smile": True}}).status_code == 200
    d = client.get("/api/planner/spending").get_json()
    assert d["model"]["smile"] is True and client.get("/api/planner/spending?nominal=1").get_json()["nominal"]
    assert client.put("/api/profile", json={"spending_model": {"shares": {"x": 3}}}).status_code in (400, 422)
    t = client.get("/api/planner/event-templates").get_json()
    assert "college" in t
    r = client.post("/api/planner/events/from-template", json={"template": "wedding", "start_year": 2031})
    assert r.status_code == 201 and r.get_json()[0]["start_year"] == 2031
    assert client.post("/api/planner/events/from-template", json={"template": "nope"}).status_code == 400

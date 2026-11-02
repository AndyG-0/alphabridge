from types import SimpleNamespace

import pytest

from services import coverage as C
from tests.test_household import _flows, _profile


def _opt(**kw):
    d = dict(
        id=1,
        name="Plan",
        category="PRE_MEDICARE",
        premium_by_year={"2026": 1000.0},
        premium_period="MONTHLY",
        premium_basis="PER_PERSON",
        eligibility_min_age=55.0,
        eligibility_max_age=None,
        requires_part_b_premium=False,
        includes_drugs=False,
        drug_option_id=None,
        owner="BOTH",
        active=True,
        verified=False,
    )
    d.update(kw)
    return SimpleNamespace(**d)


def test_premium_year_selection_and_period():
    o = _opt(premium_by_year={"2026": 100.0, "2028": 130.0})
    assert C.monthly_premium(o, 2026) == 100 and C.monthly_premium(o, 2027) == 100 and C.monthly_premium(o, 2040) == 130
    assert C.monthly_premium(o, 2020) == 100  # before the first price: earliest known
    assert C.monthly_premium(_opt(premium_by_year={"2026": 1200.0}, premium_period="ANNUAL"), 2026) == 100
    assert C.monthly_premium(_opt(premium_by_year={}), 2026) == 0


def test_eligibility_age_owner_and_active():
    o = _opt(eligibility_min_age=55, eligibility_max_age=65, owner="SELF")
    assert C.eligible(o, 55) and not C.eligible(o, 54.9) and not C.eligible(o, 65)
    assert not C.eligible(o, 60, "SPOUSE") and not C.eligible(_opt(active=False), 60)


def test_annual_cost_household_split_and_drug_addon():
    assert C.annual_cost(_opt(premium_basis="PER_HOUSEHOLD"), 2026, enrollees=2) == 6000
    rx = _opt(id=2, category="DRUG", premium_by_year={"2026": 162.0}, eligibility_min_age=65)
    ma = _opt(id=3, category="MEDICARE_ADVANTAGE", premium_by_year={"2026": 5.0}, drug_option_id=2)
    assert C.annual_cost(ma, 2026, 1, rx) == pytest.approx(12 * 167)
    assert C.annual_cost(_opt(includes_drugs=True, premium_by_year={"2026": 5.0}), 2026, 1, rx) == 60  # plan already covers drugs


def test_compare_splits_pre_and_post_medicare():
    pre, ma = _opt(id=1), _opt(id=2, category="MEDICARE_ADVANTAGE", eligibility_min_age=65)
    rows = C.compare([pre, ma], {}, {"SELF": 60.0, "SPOUSE": 66.0}, 2026, {"SELF": 9999.0})
    assert [o["id"] for o in rows[0]["options"]] == [1] and rows[0]["aca_net"] == 9999.0
    assert [o["id"] for o in rows[1]["options"]] == [2]


def test_default_choice_is_unchanged_and_eligible_choice_replaces_aca():
    base = _flows()
    assert _flows(coverage_options=[_opt()]).health[10] == base.health[10]  # an option nobody chose changes nothing
    p = _profile(coverage_choice={"SELF": 1, "SPOUSE": 1})
    f = _flows(p, coverage_options=[_opt(eligibility_min_age=0)])
    h = f.health[10]
    assert h["plan_cost"] > 0 and h["aca_net"] == 0 and h["coverage_plans"] == ["Plan", "Plan"] and h["coverage_note"] == ""


def test_ineligible_choice_falls_back_to_aca_with_note():
    p = _profile(coverage_choice={"SELF": 1, "SPOUSE": 1})
    h = _flows(p, coverage_options=[_opt(eligibility_min_age=54)]).health[10]  # primary 55 qualifies, spouse (53) does not
    assert h["coverage_plans"] == ["Plan"] and "not available" in h["coverage_note"] and h["aca_benchmark"] > 0 and h["plan_cost"] > 0


def test_medicare_advantage_keeps_part_b_and_adds_rx():
    rx = _opt(id=2, category="DRUG", premium_by_year={"2026": 162.0}, eligibility_min_age=65)
    ma = _opt(id=3, category="MEDICARE_ADVANTAGE", premium_by_year={"2026": 5.0}, eligibility_min_age=65, requires_part_b_premium=True, drug_option_id=2)
    p = _profile(coverage_choice={"SELF": 3, "SPOUSE": 3})
    f = _flows(p, coverage_options=[ma, rx])
    plain = _flows()
    i = 22  # both on Medicare
    assert f.health[i]["coverage"] == "MEDICARE"
    adj = f.health[i]["total"] / (f.health[i]["medicare"] + f.health[i]["dental_vision"] + f.health[i]["out_of_pocket"])
    part_b_floor = 2 * 12 * 100  # Part B is well above $100/mo, so Part B is clearly still being charged
    assert f.health[i]["medicare"] / adj > part_b_floor + 2 * 12 * 167
    assert f.health[i]["medicare"] != plain.health[i]["medicare"]
    no_b = _flows(p, coverage_options=[_opt(**{**ma.__dict__, "requires_part_b_premium": False}), rx])
    assert no_b.health[i]["medicare"] < f.health[i]["medicare"]


def _payload(**kw):
    return {"name": "HSC1", "carrier": "UHC", "premium_by_year": {"2026": 1616}, "eligibility_min_age": 55} | kw


def test_crud_and_validation(client):
    r = client.post("/api/coverage-options", json=_payload())
    assert r.status_code == 201
    oid = r.get_json()["id"]
    assert client.post("/api/coverage-options", json=_payload(eligibility_max_age=50)).status_code == 422
    assert client.post("/api/coverage-options", json=_payload(premium_by_year={"abc": 1})).status_code == 422
    assert client.post("/api/coverage-options", json=_payload(premium_by_year={"2026": -5})).status_code == 422
    assert client.post("/api/coverage-options", json=_payload(category="BOGUS")).status_code == 422
    assert client.post("/api/coverage-options", json=_payload(drug_option_id=oid)).status_code == 422  # not a DRUG row
    u = client.put(f"/api/coverage-options/{oid}", json=_payload(name="HSC1b", verified=True))
    assert u.get_json()["name"] == "HSC1b" and u.get_json()["verified"] is True
    assert client.put("/api/coverage-options/9999", json=_payload()).status_code == 404
    assert client.get("/api/coverage-options").get_json()["options"][0]["id"] == oid
    assert client.delete(f"/api/coverage-options/{oid}").status_code == 204
    assert client.delete(f"/api/coverage-options/{oid}").status_code == 404


def test_choice_validation_and_cleanup_on_delete(client):
    oid = client.post("/api/coverage-options", json=_payload()).get_json()["id"]
    rx = client.post("/api/coverage-options", json=_payload(name="Rx", category="DRUG")).get_json()["id"]
    assert client.put("/api/coverage-choice", json={"SELF": rx}).status_code == 422  # drug-only
    assert client.put("/api/coverage-choice", json={"SELF": 9999}).status_code == 422
    assert client.put("/api/coverage-choice", json={"SELF": oid}).get_json()["choice"] == {"SELF": oid}
    assert client.get("/api/coverage-options").get_json()["choice"] == {"SELF": oid}
    client.delete(f"/api/coverage-options/{oid}")
    assert client.get("/api/coverage-options").get_json()["choice"] == {}
    assert client.put("/api/coverage-choice", json={"SELF": None}).get_json()["choice"] == {}


def test_healthcare_plan_lists_comparison(client):
    client.post("/api/coverage-options", json=_payload(eligibility_min_age=0))
    d = client.get("/api/planner/healthcare?magi=60000").get_json()
    assert d["coverage_options"] and d["coverage_options"][0]["options"][0]["annual"] == pytest.approx(12 * 1616)

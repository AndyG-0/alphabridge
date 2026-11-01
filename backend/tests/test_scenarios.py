from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from schemas import ScenarioIn
from services import quant_engine as qe
from services import scenarios as sc


def _p(**kw):
    d = dict(
        target_retirement_age=60.0, current_age=45.0, monthly_expenses_retirement=6000.0, social_security_monthly=3000.0, spouse_social_security_monthly=1500.0
    )
    return SimpleNamespace(**(d | kw))


def test_presets_build_overrides():
    p = _p()
    assert sc.preset("spend_up_10", p)["overrides"]["monthly_expenses_retirement"] == pytest.approx(6600)
    assert sc.preset("spend_down_10", p)["overrides"]["monthly_expenses_retirement"] == pytest.approx(5400)
    assert sc.preset("retire_at", p, 55)["overrides"]["target_retirement_age"] == 55
    assert sc.preset("crash_30", p)["shock"] == pytest.approx(-0.30)
    cut = sc.preset("ss_cut", p)["overrides"]
    assert cut["social_security_monthly"] == pytest.approx(3000 * 0.77)
    sd = sc.preset("spouse_death", p)["overrides"]
    assert sd["spouse_age"] == 0 and sd["social_security_monthly"] == 3000
    assert sc.preset("job_loss", p)["overrides"]["target_retirement_age"] == 45
    with pytest.raises(ValueError):
        sc.preset("nope", p)


def test_tornado_ranks_by_swing():
    rows = sc.tornado(0.8, [{"input": "a", "low": 0.7, "high": 0.82}, {"input": "b", "low": 0.5, "high": 0.9}])
    assert [r["input"] for r in rows] == ["b", "a"] and rows[0]["low_delta"] == pytest.approx(-0.3)


def test_bisect_finds_boundary_both_directions():
    assert sc.bisect(lambda x: 1 - x / 100, 0, 100, 0.7, increasing=False) == pytest.approx(30, abs=0.1)
    assert sc.bisect(lambda x: x / 100, 0, 100, 0.7, increasing=True) == pytest.approx(70, abs=0.1)
    assert sc.bisect(lambda x: 0.1, 0, 100, 0.7, increasing=False) is None  # easiest end still misses
    assert sc.bisect(lambda x: 1.0, 0, 100, 0.7, increasing=False) == 100  # hardest end already passes


@settings(max_examples=30, deadline=None)
@given(t=st.floats(0.05, 0.95))
def test_bisect_result_meets_target(t):
    v = sc.bisect(lambda x: 1 - x, 0.0, 1.0, t, increasing=False)
    assert v is not None and 1 - v >= t - 1e-9


def test_scenario_schema_rejects_unknown_fields():
    assert ScenarioIn(name="x", overrides={"target_retirement_age": 55}).shock == 0
    with pytest.raises(ValidationError):
        ScenarioIn(name="x", overrides={"password": 1})
    with pytest.raises(ValidationError):
        ScenarioIn(name="x", shock=-2)


def _inp(**kw):
    base = dict(
        current_age=60,
        retire_age=60,
        taxable=800_000,
        pretax=0,
        annual_contribution_bridge=0,
        annual_contribution_pretax=0,
        retirement_spend=30_000,
        tax_rate=0.1,
        mu_taxable=0.06,
        sigma_taxable=0.12,
        mu_pretax=0.06,
        sigma_pretax=0.12,
        end_age=90,
    )
    return qe.FireInputs(**(base | kw))


def test_first_year_shock_hurts_and_default_is_unchanged():
    a = qe.simulate_fire(_inp(), n_sims=1500)["success_rate"]
    b = qe.simulate_fire(_inp(first_year_shock=-0.30), n_sims=1500)["success_rate"]
    assert b < a
    assert qe.simulate_fire(_inp(first_year_shock=0.0), n_sims=1500)["success_rate"] == a


def test_routes(client):
    r = client.post("/api/planner/scenarios", json={"name": "Retire 55", "overrides": {"target_retirement_age": 55}})
    assert r.status_code == 201
    sid = r.get_json()["id"]
    assert client.post("/api/planner/scenarios", json={"name": "bad", "overrides": {"x": 1}}).status_code == 400
    lst = client.get("/api/planner/scenarios").get_json()
    assert any(s["id"] == sid for s in lst["saved"]) and lst["presets"]
    cmp = client.get(f"/api/planner/scenarios/compare?ids={sid}&presets=crash_30,spend_up_10&sims=300").get_json()
    assert [x["kind"] for x in cmp["scenarios"]] == ["saved", "preset", "preset"] and "success_rate" in cmp["base"]
    assert client.get("/api/planner/scenarios/compare?presets=nope").status_code == 400
    assert client.get("/api/planner/solve?kind=bogus").status_code == 400
    assert client.get("/api/planner/solve?kind=max_spend&sims=300").status_code == 200
    assert client.get("/api/planner/tornado?sims=300").get_json()["bars"]
    assert client.delete(f"/api/planner/scenarios/{sid}").status_code == 204
    assert client.delete(f"/api/planner/scenarios/{sid}").status_code == 404

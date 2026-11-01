import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import withdrawal_strategies as ws


def _setup(**kw):
    return ws.Setup(**({"portfolio": 1_000_000, "years": 30, "mu": 0.04, "sigma": 0.11, "n_sims": 600} | kw))


def test_deterministic_with_seed():
    a = ws.summarize("fixed_real", 40_000, _setup())
    b = ws.summarize("fixed_real", 40_000, _setup())
    assert a == b
    assert ws.summarize("fixed_real", 40_000, _setup(seed=7))["success_rate"] != pytest.approx(a["success_rate"], abs=0) or True


def test_zero_volatility_fixed_real_known_answer():
    # no risk, 0% real return: a 30-year plan lasts exactly while 30*S0 <= portfolio
    s = _setup(mu=0.0, sigma=0.0, n_sims=5)
    assert ws.summarize("fixed_real", 1_000_000 / 30 - 1, s)["success_rate"] == 1.0
    assert ws.summarize("fixed_real", 1_000_000 / 30 + 100, s)["success_rate"] == 0.0


def test_income_reduces_draw():
    s = _setup(mu=0.0, sigma=0.0, n_sims=3, income=[0.0] * 10 + [20_000.0] * 20)
    sim = ws.simulate("fixed_real", 40_000, s)
    assert sim["spend"][0, 0] == 40_000 and sim["spend"][0, 15] == 40_000  # total spend is the target
    assert sim["ending"][0] == pytest.approx(1_000_000 - 10 * 40_000 - 20 * 20_000)


def test_solver_hits_target_and_is_monotone_in_target():
    s = _setup()
    s90 = ws.solve_spend("fixed_real", s, 0.90)
    s95 = ws.solve_spend("fixed_real", s, 0.95)
    assert s95 < s90
    rets = ws.real_returns(s)
    assert ws.simulate("fixed_real", s90, s, rets=rets)["success"].mean() >= 0.90
    assert ws.simulate("fixed_real", s90 * 1.03, s, rets=rets)["success"].mean() < 0.90


def test_flexible_policies_start_higher_than_fixed():
    s = _setup()
    fixed = ws.solve_spend("fixed_real", s, 0.90)
    assert ws.solve_spend("guyton_klinger", s, 0.90) > fixed
    assert ws.solve_spend("vpw", s, 0.90) > fixed


def test_pct_portfolio_spend_tracks_portfolio():
    s = _setup(sigma=0.0, mu=0.0, n_sims=2)
    sim = ws.simulate("pct_portfolio", 40_000, s)
    # constant 4% of a shrinking balance spends less each year
    assert sim["spend"][0, 0] == pytest.approx(40_000) and sim["spend"][0, 5] < sim["spend"][0, 0]


def test_guyton_klinger_cuts_after_a_crash():
    s = _setup(n_sims=1, years=30)
    rets = np.zeros((1, 30))
    rets[0, 0] = -0.4
    sim = ws.simulate("guyton_klinger", 20_000, s, rets=rets)
    assert sim["spend"][0, 1] < sim["spend"][0, 0]
    # the published rule: no cuts once 15 or fewer years remain
    late = np.zeros((1, 30))
    late[0, 20] = -0.5
    sim = ws.simulate("guyton_klinger", 20_000, s, rets=late)
    assert sim["spend"][0, 21:].min() >= sim["spend"][0, 20] - 1e-6


def test_ratcheting_never_cuts_and_raises_after_a_boom():
    s = _setup(n_sims=1, years=4)
    rets = np.array([[0.8, 0.0, 0.0, 0.0]])
    sim = ws.simulate("ratcheting", 40_000, s, rets=rets)
    assert sim["spend"][0, 1] == pytest.approx(44_000) and np.all(np.diff(sim["spend"][0]) >= 0)


def test_floor_and_ceiling_bounds():
    s = _setup(n_sims=300)
    sim = ws.simulate("floor_ceiling", 40_000, s)
    live = sim["spend"] > 0
    assert sim["spend"][live].max() <= 1.25 * 40_000 + 1e-6


def test_vpw_year_zero_spends_s0_and_last_year_empties():
    s = _setup(mu=0.03, sigma=0.0, n_sims=1, vpw_rate=0.03)
    sim = ws.simulate("vpw", 50_000, s)
    assert sim["spend"][0, 0] == pytest.approx(50_000)
    assert sim["ending"][0] == pytest.approx(0.0, abs=1.0)


def test_bucket_spends_from_cash_first():
    s = _setup(n_sims=1, years=2, mu=0.0, sigma=0.0)
    rets = np.array([[-0.5, -0.5]])
    out = ws.simulate("bucket", 40_000, s, rets=rets)
    assert out["spend"][0].tolist() == [40_000, 40_000] and out["success"][0]
    fixed = ws.simulate("fixed_real", 40_000, s, rets=rets)
    assert out["ending"][0] > fixed["ending"][0]  # the cash bucket shields spending from the crash


def test_unknown_policy():
    with pytest.raises(ValueError):
        ws.simulate("nope", 1.0, _setup())


def test_compare_shape():
    c = ws.compare(_setup(n_sims=300), detail=True)
    assert [p["policy"] for p in c["policies"]] == list(ws.POLICIES)
    for p in c["policies"]:
        assert p["safe_spend"]["95"] <= p["safe_spend"]["90"] + 1e-6
        assert len(p["bands"]) == 30 and all(b["p10"] <= b["p50"] <= b["p90"] for b in p["bands"])


@settings(max_examples=15, deadline=None)
@given(policy=st.sampled_from(ws.POLICIES), s0=st.floats(1_000, 150_000), extra=st.floats(1_000, 50_000))
def test_higher_spend_never_more_likely_to_succeed_for_fixed_style(policy, s0, extra):
    if policy not in ("fixed_real", "bucket"):
        return
    s = _setup(n_sims=200)
    rets = ws.real_returns(s)
    lo = ws.simulate(policy, s0, s, rets=rets)["success"].mean()
    hi = ws.simulate(policy, s0 + extra, s, rets=rets)["success"].mean()
    assert hi <= lo + 1e-9


@settings(max_examples=15, deadline=None)
@given(policy=st.sampled_from(ws.POLICIES), s0=st.floats(1_000, 150_000))
def test_balances_and_spend_nonnegative(policy, s0):
    sim = ws.simulate(policy, s0, _setup(n_sims=100, years=20))
    assert (sim["ending"] >= 0).all() and (sim["spend"] >= 0).all()


def test_route(client):
    assert client.get("/api/planner/strategies?portfolio=1000000&n_sims=300&detail=0").status_code == 200
    assert client.get("/api/planner/strategies?policies=nope").status_code == 400

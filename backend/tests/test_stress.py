from datetime import date

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import stress as sx
from services import withdrawal_strategies as ws


def _setup(**kw):
    return ws.Setup(**({"portfolio": 1_000_000, "years": 30, "mu": 0.04, "sigma": 0.11, "n_sims": 500} | kw))


def test_data_file_is_sourced_and_fresh():
    d = sx._data()
    assert d["source_url"].startswith("https://") and d["last_year"] == 2025 and d["first_year"] == 1928
    assert len(d["years"]) == 98
    assert (date.today() - sx.retrieved_on()).days < 3 * 366


def test_known_historical_returns():
    y = sx._data()["years"]
    assert y["2008"]["stocks"] == pytest.approx(-0.3655, abs=1e-3)
    assert y["1931"]["stocks"] == pytest.approx(-0.4384, abs=1e-3)
    assert y["1928"]["stocks"] == pytest.approx(0.4381, abs=1e-3)


def test_real_series_mixes_and_deflates():
    yrs, r = sx.real_series(1.0)
    d = sx._data()["years"]["1931"]
    assert r[yrs.index(1931)] == pytest.approx((1 + d["stocks"]) / (1 + d["inflation"]) - 1)
    _, r0 = sx.real_series(0.0)
    assert r0[yrs.index(1931)] == pytest.approx((1 + d["bonds"]) / (1 + d["inflation"]) - 1)


def test_historical_flags_incomplete_windows():
    rows = {h["start_year"]: h for h in sx.historical(_setup(), 40_000)}
    assert rows[1966]["complete"] and not rows[2008]["complete"] and rows[2008]["years_covered"] == 18
    assert not rows[2008]["success"]  # never reported as a pass without the full horizon
    assert rows[1966]["lowest_balance_real"] <= rows[1966]["ending_real"] + 1e12


def test_historical_zero_spend_always_succeeds():
    assert all(h["success"] for h in sx.historical(_setup(years=15), 0.0) if h["complete"])


def test_rolling_counts_windows():
    r = sx.rolling(_setup(), 40_000)
    assert r["windows"] == 98 - 30 + 1 and 0 <= r["success_rate"] <= 1
    assert sx.rolling(_setup(years=200), 40_000)["windows"] == 0


def test_bootstrap_deterministic_and_from_sample():
    a = sx.bootstrap_paths(_setup())
    assert np.array_equal(a, sx.bootstrap_paths(_setup()))
    _, r = sx.real_series(0.6)
    assert a.shape == (500, 30) and a.min() >= r.min() - 1e-12 and a.max() <= r.max() + 1e-12


def test_fat_tail_matches_mean_and_vol_but_has_fatter_tails():
    s = _setup(n_sims=20_000, years=10, sigma=0.12, mu=0.05)
    f = sx.fat_tail_paths(s)
    z = np.random.default_rng(1).standard_normal(f.size) * 0.12 + 0.05
    assert f.mean() == pytest.approx(0.05, abs=0.005) and f.std() == pytest.approx(0.12, rel=0.1)
    assert np.sum(f < 0.05 - 4 * 0.12) > np.sum(z < 0.05 - 4 * 0.12)


def test_regime_has_crisis_years():
    p = sx.regime_paths(_setup(n_sims=2000, years=30))
    assert (p < -0.2).mean() > 0.005 and p.min() >= -0.95


def test_success_by_first5_worse_early_returns_fail_more():
    s = _setup(n_sims=3000)
    paths = sx.bootstrap_paths(s)
    sim = ws.simulate("fixed_real", 45_000, s, rets=paths)
    rows = sx.success_by_first5(paths, sim["success"])
    assert sum(r["n"] for r in rows) == 3000
    assert rows[0]["success_rate"] < rows[-1]["success_rate"]


def test_stress_bundle_is_labelled():
    o = sx.stress(_setup(n_sims=300), 40_000)
    assert {m["method"] for m in o["simulated"]} == {"bootstrap", "fat_tail", "regime"}
    assert all(m["description"] for m in o["simulated"]) and set(o["methods"]) >= {"historical", "rolling"}
    assert o["data"]["source_url"] and -1 <= o["bucket"]["improvement"] <= 1


@settings(max_examples=10, deadline=None)
@given(s0=st.floats(0, 100_000), extra=st.floats(1_000, 40_000))
def test_more_spending_never_helps_in_stress(s0, extra):
    s = _setup(n_sims=200, years=25)
    paths = sx.bootstrap_paths(s)
    lo = ws.simulate("fixed_real", s0, s, rets=paths)["success"].mean()
    hi = ws.simulate("fixed_real", s0 + extra, s, rets=paths)["success"].mean()
    assert hi <= lo + 1e-9


def test_route(client):
    r = client.get("/api/planner/stress?portfolio=1000000&spend=40000&n_sims=200")
    assert r.status_code == 200 and r.get_json()["historical"]
    assert client.get("/api/planner/stress?policy=nope").status_code == 400

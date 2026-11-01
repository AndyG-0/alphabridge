import numpy as np
import pytest

from services import cash_optimizer as co
from services import quant_engine as qe


def base(**kw):
    d = dict(
        current_age=40,
        retire_age=50,
        taxable=800_000,
        pretax=500_000,
        annual_contribution_bridge=0,
        annual_contribution_pretax=0,
        retirement_spend=60_000,
        tax_rate=0.15,
        mu_taxable=0.07,
        sigma_taxable=0.15,
        mu_pretax=0.07,
        sigma_pretax=0.15,
    )
    d.update(kw)
    return qe.FireInputs(**d)


def test_monte_carlo_deterministic_with_seed():
    a, b = qe.simulate_fire(base(), 500, seed=1), qe.simulate_fire(base(), 500, seed=1)
    assert a["success_rate"] == b["success_rate"]


def test_monte_carlo_monotonic_in_wealth():
    poor = qe.simulate_fire(base(taxable=100_000, pretax=100_000), 1000, seed=3)["success_rate"]
    rich = qe.simulate_fire(base(taxable=3_000_000, pretax=1_000_000), 1000, seed=3)["success_rate"]
    assert rich > poor and rich > 0.95 and poor < 0.2


def test_bridge_failure_when_taxable_too_small():
    r = qe.simulate_fire(base(taxable=100_000, pretax=2_000_000), 1000, seed=3)
    assert r["bridge_success_rate"] < 0.1


def test_rule_of_55_helps_bridge():
    b = base(retire_age=55, current_age=45, taxable=50_000, pretax=2_000_000)
    assert qe.simulate_fire(FireR55(b), 800, seed=2)["success_rate"] > qe.simulate_fire(b, 800, seed=2)["success_rate"]


def FireR55(b):
    return qe.FireInputs(**{**b.__dict__, "rule_of_55": True})


def test_bridge_capital_needed():
    assert qe.bridge_capital_needed(59.5, 50_000, 0.15) == 0
    assert qe.bridge_capital_needed(50, 50_000, 0.0, real_return=0.0) == pytest.approx(50_000 * 10)


def test_sharpe_zero_vol():
    assert qe.sharpe_ratio(np.ones(50)) == 0.0


def test_sharpe_positive():
    r = np.random.default_rng(0).normal(0.001, 0.01, 500)
    assert qe.sharpe_ratio(r) > 0


def test_beta_of_scaled_market():
    m = np.random.default_rng(1).normal(0, 0.01, 300)
    assert qe.beta(2 * m, m) == pytest.approx(2.0)


def test_correlation_perfect():
    x = np.random.default_rng(2).normal(size=100)
    c = qe.correlation_matrix({"a": x, "b": -x})
    assert c["a"]["b"] == pytest.approx(-1.0)


def test_erp():
    assert qe.equity_risk_premium(20, 0.04) == pytest.approx(0.01)


def test_rsi_extremes():
    assert qe.rsi(np.arange(1, 40)) == 100.0
    assert qe.rsi(np.arange(40, 1, -1)) < 1


def test_sma_distance_and_drawdown():
    p = np.concatenate([np.full(199, 100.0), [110.0]])
    assert qe.sma_distance(p, 200) == pytest.approx(110 / 100.05 - 1)
    assert qe.sma_distance(p[:50], 200) is None
    assert qe.max_drawdown(np.array([100, 120, 60, 90])) == pytest.approx(-0.5)


def test_dcf_sane():
    v = qe.simple_dcf(100, 0.10, discount=0.10, terminal_growth=0.025)
    assert v > 100 * 10
    with pytest.raises(ValueError):
        qe.simple_dcf(100, 0.1, discount=0.02, terminal_growth=0.03)


def test_expected_return_blend():
    mu, sg = qe.expected_return_vol({"US_EQUITY": 50, "BOND": 50})
    assert 0.04 < mu < 0.075 and 0.05 < sg < 0.17


# --- cash optimizer
CHEAP = co.MarketInputs(tbill_3m=0.02, ten_year=0.03, cpi_yoy=0.03, sp500_pe=14, vix=32, sp500_vs_200dma=-0.12)
RICH = co.MarketInputs(tbill_3m=0.055, ten_year=0.045, cpi_yoy=0.02, sp500_pe=30, vix=12, sp500_vs_200dma=0.08)


def test_score_ordering():
    assert co.deployment_score(CHEAP)["score"] > 70
    assert co.deployment_score(RICH)["score"] < 45
    assert co.signal_label(co.deployment_score(CHEAP)["score"]) == "AGGRESSIVE_BUY"
    assert co.signal_label(co.deployment_score(RICH)["score"]) == "HOLD_MMF"


def test_recommend_respects_buffer():
    r = co.recommend(30_000, 5_000, 6, 0.045, CHEAP)
    assert r["investable_surplus"] == 0 and r["deploy_now"] == 0 and r["keep_in_mmf"] == 30_000


def test_recommend_hold_keeps_everything():
    r = co.recommend(100_000, 5_000, 6, 0.045, RICH)
    assert r["deploy_now"] == 0 and r["keep_in_mmf"] == 100_000


def test_recommend_deploys_and_conserves():
    r = co.recommend(100_000, 5_000, 6, 0.045, CHEAP)
    assert 0 < r["deploy_now"] <= 70_000
    assert r["deploy_now"] + r["keep_in_mmf"] == pytest.approx(100_000)
    assert r["tranches"] > 0


def _fi(**kw):
    import services.quant_engine as qe

    d = dict(
        current_age=45,
        retire_age=55,
        taxable=600_000,
        pretax=500_000,
        annual_contribution_bridge=20_000,
        annual_contribution_pretax=30_000,
        retirement_spend=70_000,
        tax_rate=0.15,
        mu_taxable=0.06,
        sigma_taxable=0.14,
        mu_pretax=0.06,
        sigma_pretax=0.14,
    )
    d.update(kw)
    return qe.FireInputs(**d)


def test_zero_household_vectors_match_legacy_results():
    import services.quant_engine as qe

    a = qe.simulate_fire(_fi(), n_sims=600)
    b = qe.simulate_fire(_fi(extra_spend_by_year=[0.0] * 50, income_by_year=[0.0] * 50), n_sims=600)
    assert a["success_rate"] == b["success_rate"] and a["median_final_real"] == b["median_final_real"]


def test_extra_spend_hurts_income_helps():
    import services.quant_engine as qe

    base = qe.simulate_fire(_fi(), n_sims=800)
    car = qe.simulate_fire(_fi(extra_spend_by_year=[0.0] * 12 + [60_000.0] + [0.0] * 40), n_sims=800)
    pension = qe.simulate_fire(_fi(income_by_year=[0.0] * 10 + [20_000.0] * 40), n_sims=800)
    assert car["median_final_real"] < base["median_final_real"] < pension["median_final_real"]


def test_sustainable_spend_hits_target():
    import services.quant_engine as qe

    inp = _fi()
    s = qe.sustainable_spend(inp, target_success=0.85)
    at = qe.simulate_fire(qe.FireInputs(**{**inp.__dict__, "retirement_spend": s}), n_sims=1000)["success_rate"]
    above = qe.simulate_fire(qe.FireInputs(**{**inp.__dict__, "retirement_spend": s * 1.05}), n_sims=1000)["success_rate"]
    assert at >= 0.85 > above


def test_guardrails_raise_sustainable_spend():
    import services.quant_engine as qe

    plain = qe.sustainable_spend(_fi(), 0.85)
    gr = qe.sustainable_spend(_fi(guardrails=True), 0.85)
    assert gr > plain
    assert qe.simulate_fire(_fi(guardrails=True), n_sims=500)["guardrail_cut_rate"] is not None

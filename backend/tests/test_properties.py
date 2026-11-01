"""Property-based + seeded golden tests for the deterministic math (core law #1)."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import cash_optimizer as co
from services import household as hh
from services import liabilities as lb
from services import planner
from services import quant_engine as qe

money = st.floats(min_value=1_000, max_value=5_000_000, allow_nan=False)
apr = st.floats(min_value=0.0, max_value=0.30, allow_nan=False)


@given(balance=money, rate=apr, pay=st.floats(min_value=10, max_value=50_000, allow_nan=False))
def test_amortize_is_consistent(balance, rate, pay):
    out = lb.amortize(balance, rate, pay)
    if out["months"] is None:
        assert pay <= balance * rate / 12 + 1e-6 or pay <= 0
        return
    assert out["total_interest"] >= 0
    assert pay * out["months"] >= balance - 1e-6  # total paid covers principal
    if out["months"] > 1:  # one fewer payment must not clear the debt
        r = rate / 12
        bal = balance
        for _ in range(out["months"] - 1):
            bal = bal * (1 + r) - pay
        assert bal > -1e-6


@given(balance=money, rate=apr, pay=st.floats(min_value=10, max_value=50_000, allow_nan=False))
def test_higher_payment_never_costs_more_interest(balance, rate, pay):
    a, b = lb.amortize(balance, rate, pay), lb.amortize(balance, rate, pay * 1.5)
    if a["months"] is not None:
        assert b["months"] <= a["months"] and b["total_interest"] <= a["total_interest"] + 0.01


@given(a=st.floats(62, 70), b=st.floats(62, 70))
def test_ss_factor_monotone_and_bounded(a, b):
    lo, hi = sorted((a, b))
    assert hh.ss_factor(lo) <= hh.ss_factor(hi) + 1e-12
    assert 0.70 - 1e-9 <= hh.ss_factor(a) <= 1.24 + 1e-9


def test_ss_factor_anchor_points():
    assert hh.ss_factor(67) == pytest.approx(1.0)
    assert hh.ss_factor(62) == pytest.approx(0.70)
    assert hh.ss_factor(70) == pytest.approx(1.24)
    assert hh.ss_factor(50) == hh.ss_factor(62) and hh.ss_factor(80) == hh.ss_factor(70)


@given(surplus=st.floats(0, 1e7, allow_nan=False), risk=st.floats(-1, 2, allow_nan=False))
def test_allocate_surplus_sums_to_input(surplus, risk):
    out = planner.allocate_surplus(surplus, risk)
    assert sum(out.values()) == pytest.approx(surplus, abs=0.02)
    assert all(v >= -0.01 for v in out.values())


@given(
    tbill=st.floats(0, 0.10),
    ten=st.floats(0, 0.10),
    cpi=st.floats(-0.02, 0.15),
    pe=st.floats(8, 60),
    vix=st.floats(8, 80),
    dma=st.floats(-0.4, 0.3),
)
def test_deployment_score_bounded_and_signal_consistent(tbill, ten, cpi, pe, vix, dma):
    d = co.deployment_score(co.MarketInputs(tbill, ten, cpi, pe, vix, dma))
    assert 0 <= d["score"] <= 100
    assert co.signal_label(d["score"]) in {"AGGRESSIVE_BUY", "DCA", "HOLD_MMF"}


@given(pe=st.floats(8, 40), vix=st.floats(12, 35), better=st.floats(0.5, 10))
def test_deployment_score_rises_as_stocks_get_cheaper_and_fear_rises(pe, vix, better):
    m = co.MarketInputs(0.04, 0.04, 0.03, pe, vix, 0.0)
    cheaper = co.MarketInputs(0.04, 0.04, 0.03, pe - min(better, pe - 1), vix, 0.0)
    assert co.deployment_score(cheaper)["score"] >= co.deployment_score(m)["score"] - 1e-9


@given(st.lists(st.floats(1, 1000), min_size=2, max_size=60))
def test_max_drawdown_range(prices):
    assert -1 < qe.max_drawdown(np.array(prices)) <= 0


@given(st.dictionaries(st.sampled_from(list("ABCDEF")), st.floats(1, 1e6), min_size=1))
def test_concentration_weights_sum_to_one(exp):
    assert sum(qe.concentration(exp, sum(exp.values())).values()) == pytest.approx(1.0)


@given(fcf=st.floats(1, 1e4), g=st.floats(-0.1, 0.4), d=st.floats(0.06, 0.2))
def test_dcf_monotone_in_discount_rate(fcf, g, d):
    assert qe.simple_dcf(fcf, g, d) >= qe.simple_dcf(fcf, g, d + 0.01) - 1e-9


def _fire(**kw):
    d = dict(
        current_age=40, retire_age=50, taxable=800_000, pretax=500_000, annual_contribution_bridge=0, annual_contribution_pretax=0,
        retirement_spend=60_000, tax_rate=0.15, mu_taxable=0.07, sigma_taxable=0.15, mu_pretax=0.07, sigma_pretax=0.15,
    )  # fmt: skip
    d.update(kw)
    return qe.FireInputs(**d)


@settings(max_examples=15, deadline=None)
@given(spend=st.floats(30_000, 120_000), extra=st.floats(5_000, 60_000))
def test_mc_success_monotone_in_spend(spend, extra):
    lo = qe.simulate_fire(_fire(retirement_spend=spend), 400, seed=7)["success_rate"]
    hi = qe.simulate_fire(_fire(retirement_spend=spend + extra), 400, seed=7)["success_rate"]
    assert hi <= lo + 1e-9  # same seed -> same shocks -> strictly comparable


@settings(max_examples=15, deadline=None)
@given(bal=st.floats(200_000, 2_000_000), extra=st.floats(50_000, 500_000))
def test_mc_success_monotone_in_balance(bal, extra):
    lo = qe.simulate_fire(_fire(taxable=bal), 400, seed=7)["success_rate"]
    hi = qe.simulate_fire(_fire(taxable=bal + extra), 400, seed=7)["success_rate"]
    assert hi >= lo - 1e-9


def test_mc_golden_seeded():
    r = qe.simulate_fire(_fire(), 2000, seed=42)
    # Frozen from the current implementation; a change here means the model changed - review, then update on purpose.
    assert r["success_rate"] == pytest.approx(GOLDEN["success_rate"], abs=1e-9)
    assert r["median_final_real"] == pytest.approx(GOLDEN["median_final_real"], rel=1e-9)
    assert r["p90_final_real"] == pytest.approx(GOLDEN["p90_final_real"], rel=1e-9)


def test_deployment_score_golden():
    d = co.deployment_score(co.MarketInputs(0.045, 0.043, 0.03, 22.0, 18.0, 0.02))
    assert d["score"] == pytest.approx(GOLDEN["deploy_score"], abs=1e-9)


GOLDEN = {"success_rate": 0.592, "median_final_real": 1270054.4888912549, "p90_final_real": 14298287.013727976, "deploy_score": 29.9}


def test_amortize_interest_excludes_overpayment_on_last_month():
    # $1,000 at 12% APR, $600/mo: interest 10.00 in month 1, 4.10 in month 2 (final payment 414.10).
    assert lb.amortize(1000, 0.12, 600) == {"months": 2, "total_interest": 14.1}
    assert lb.amortize(1000, 1e-300, 10) == {"months": 100, "total_interest": 0.0}


def test_chat_tools_return_python_computed_json_only(app, monkeypatch):
    """Core law #1: every tool result handed to the LLM is JSON produced by Python, truncated if huge, never raises."""
    import json

    from services import chat_tools

    assert json.loads(chat_tools.dispatch("nope", {})) == {"error": "unknown tool nope"}
    monkeypatch.setitem(chat_tools.HANDLERS, "boom", lambda a: 1 / 0)
    assert "ZeroDivisionError" in json.loads(chat_tools.dispatch("boom", {}))["error"]
    monkeypatch.setitem(chat_tools.HANDLERS, "big", lambda a: ["x" * 100] * 1000)
    assert chat_tools.dispatch("big", {}).endswith("[truncated]")
    with app.app_context():
        for name in ("get_profile", "get_accounts_and_holdings", "get_planned_events", "get_allocation"):
            out = chat_tools.dispatch(name, {})
            json.loads(out)  # parses -> structured data, not free text
    schema_names = {t[0] for t in chat_tools.TOOLS}
    assert schema_names <= set(chat_tools.HANDLERS)

from datetime import date
from types import SimpleNamespace

import pytest

from services import household as H

TODAY = date(2026, 1, 15)


def _profile(**kw):
    d = dict(
        name="A",
        current_age=45.0,
        spouse_age=43.0,
        spouse_name="B",
        target_retirement_age=55.0,
        spouse_target_retirement_age=0.0,
        social_security_monthly=3000,
        spouse_social_security_monthly=2000,
        ss_claim_age=67,
        spouse_ss_claim_age=67,
        annual_income=120_000,
        spouse_annual_income=80_000,
        monthly_contribution=4000,
        effective_tax_rate=0.15,
        monthly_expenses_retirement=6000,
        aca_benchmark_premium_monthly=0,
        dental_vision_monthly=50,
        health_oop_annual=2500,
        medicare_monthly_per_person=450,
        health_inflation=0.05,
        home_value=400_000,
        home_upkeep_pct=0.01,
        ltc_annual=100_000,
        ltc_years=0,
        ltc_start_age=85,
        spouse_take_home_monthly=0,
        guardrails_enabled=False,
    )
    d.update(kw)
    return SimpleNamespace(**d)


def _ev(**kw):
    d = dict(
        name="Car",
        kind="PURCHASE",
        amount=40_000,
        start_year=2028,
        repeat_every_years=0,
        repeat_until_year=None,
        owner="JOINT",
        financed=False,
        down_payment=0,
        loan_apr=0,
        loan_term_months=60,
        is_home_sale=False,
    )
    d.update(kw)
    return SimpleNamespace(**d)


def _flows(p=None, debts=(), events=(), retire=55.0, **kw):
    return H.build_flows(p or _profile(), list(debts), list(events), retire_age=retire, years=50, inflation=0.025, today=TODAY, **kw)


@pytest.mark.parametrize(("age", "factor"), [(62, 0.70), (64, 0.80), (65, 0.8667), (67, 1.0), (68, 1.08), (70, 1.24)])
def test_ss_claiming_factors(age, factor):
    assert H.ss_factor(age) == pytest.approx(factor, abs=1e-3)


def test_spouse_retires_with_primary_by_default():
    ppl = H.people(_profile())
    assert ppl[1].retire_age == pytest.approx(53.0)
    tl = H.timeline(_profile(), [], [], retire_age=55, today=TODAY)
    r = next(m for m in tl if m["kind"] == "RETIRE")
    assert r["label"] == "You both retire" and r["ages"] == {"SELF": 55.0, "SPOUSE": 53.0} and r["year"] == 2036


def test_separate_spouse_retirement_shows_two_rows_and_keeps_paycheck():
    p = _profile(spouse_target_retirement_age=58)
    assert len([m for m in H.timeline(p, [], [], retire_age=55, today=TODAY) if m["kind"] == "RETIRE"]) == 2
    f = _flows(p)
    assert f.retire_y == 10 and f.breakdown["spouse_wages"][10] > 0 and f.breakdown["spouse_wages"][15] == 0
    assert f.contrib_pretax_spouse[12] > 0 and f.contrib_pretax[12] == 0
    assert f.health[11]["coverage"] == "EMPLOYER"  # working spouse's plan covers both


def test_purchases_repeat_and_financing():
    f = _flows(events=[_ev(repeat_every_years=10, repeat_until_year=2050)])
    assert [y for y, v in enumerate(f.breakdown["purchases"]) if v] == [2, 12, 22]
    fin = _flows(events=[_ev(financed=True, down_payment=10_000, loan_apr=0.06, loan_term_months=60)])
    assert fin.breakdown["purchases"][2] == 10_000
    assert fin.debt_nominal[2] > 0 and fin.debt_nominal[6] > 0 and fin.debt_nominal[7] == 0


def test_inflows_pension_and_home_sale():
    f = _flows(
        events=[
            _ev(name="Inheritance", kind="INFLOW", amount=100_000, start_year=2040),
            _ev(name="Pension", kind="PENSION", amount=1000, start_year=2037),
            _ev(name="Sell house", kind="INFLOW", amount=300_000, start_year=2045, is_home_sale=True),
        ]
    )
    assert f.income[14] == 100_000 + 12_000 and f.income[11] == 12_000 and f.income[10] == 0
    assert f.breakdown["home_upkeep"][18] == 4000 and f.breakdown["home_upkeep"][19] == 0


def test_health_aca_then_medicare_per_person():
    f = _flows()
    y_ret = f.health[10]
    assert y_ret["coverage"] == "ACA" and y_ret["aca_benchmark"] > 0
    spouse_still_under = f.health[20]  # primary 65, spouse 63
    assert spouse_still_under["coverage"] == "ACA+MEDICARE" and spouse_still_under["medicare"] > 0
    assert f.health[22]["coverage"] == "MEDICARE" and f.health[22]["aca_net"] == 0
    assert all(h["total"] == 0 for h in f.health[:10])  # employer plan while working


def test_high_income_hits_cliff_low_income_gets_subsidy():
    rich = _flows(_profile(monthly_expenses_retirement=12_000), gain_ratio=1.0, taxable_now=2_000_000)
    lean = _flows(_profile(monthly_expenses_retirement=3000, meets_community_engagement=True), gain_ratio=0.1, taxable_now=2_000_000)
    assert rich.health[10]["over_cliff"] and not lean.health[10]["over_cliff"]
    assert lean.health[10]["aca_credit"] > 0


def _lean(**kw):
    return _flows(_profile(monthly_expenses_retirement=3000, **kw), gain_ratio=0.1, taxable_now=2_000_000).health[10]


def test_arizona_medicaid_needs_the_2027_work_rule_to_be_free():
    free = _lean(state="AZ", meets_community_engagement=True)
    assert free["medicaid"] and free["medicaid_agency"] == "AHCCCS" and free["engagement_required"] and free["aca_net"] == 0
    blocked = _lean(state="AZ", meets_community_engagement=False)
    assert blocked["engagement_blocked"] and not blocked["medicaid"] and blocked["aca_credit"] == 0 and blocked["aca_net"] > 0


def test_non_expansion_state_has_coverage_gap_not_medicaid():
    row = _lean(state="TX")
    assert row["coverage_gap"] and not row["medicaid"] and row["aca_net"] == row["aca_benchmark"] > 0


def test_ltc_window():
    f = _flows(_profile(ltc_years=2, ltc_start_age=85))
    assert f.breakdown["ltc"][39] == 0 and f.breakdown["ltc"][40] > 0 and f.breakdown["ltc"][41] > 0
    assert f.breakdown["ltc"][42] > 0  # spouse (2 years younger) starts at y=42
    assert f.breakdown["ltc"][44] == 0


def test_no_spouse():
    p = _profile(spouse_age=0.0)
    assert len(H.people(p)) == 1
    f = _flows(p)
    assert f.ss_spouse[0] == 0 and not f.contrib_pretax_spouse.any()


def _debt(**kw):
    d = dict(
        id=1, name="Car loan", kind="AUTO", balance=12_000, apr=0.0, monthly_payment=1000, payoff_date=None, owner="SELF", extra_payment_until="RETIREMENT"
    )
    d.update(kw)
    return SimpleNamespace(**d)


def test_payoff_schedule_fixed_loan_and_ongoing_card():
    car = _debt()
    card = _debt(id=2, name="Card", kind="CARD", balance=10_000, apr=0.24, monthly_payment=100)
    paid = _debt(id=3, balance=0)
    out = H.payoff_schedule(_profile(), [card, car, paid], retire_age=55, today=TODAY)
    assert [d["name"] for d in out] == ["Car loan", "Card"]  # soonest first, zero balance skipped
    c = out[0]
    assert c["months"] == 12 and (c["payoff_year"], c["payoff_month"]) == (2027, 1)
    assert c["ages"] == {"SELF": 46.0, "SPOUSE": 44.0} and c["paid_before_retirement"] and not c["ongoing"]
    assert out[1]["ongoing"] and out[1]["payoff_year"] is None and not out[1]["paid_before_retirement"]


def test_payoff_schedule_after_retirement_and_payoff_date_override():
    long = _debt(balance=240_000, monthly_payment=1000)  # 20 years, retire in 10
    assert not H.payoff_schedule(_profile(), [long], retire_age=55, today=TODAY)[0]["paid_before_retirement"]
    dated = _debt(payoff_date=date(2030, 6, 1))
    d = H.payoff_schedule(_profile(), [dated], retire_age=55, today=TODAY)[0]
    assert (d["payoff_year"], d["payoff_month"]) == (2030, 6)

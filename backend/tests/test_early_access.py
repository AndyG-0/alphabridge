import json
from datetime import date

import pytest

from models import Account, Holding
from services import early_access as ea
from services import planner


def _plan(name, current, value=100_000, owner="SELF"):
    a = Account(name=name, tax_bucket="PRE_TAX_401K", owner=owner, is_current_employer_plan=current)
    a.holdings = [Holding(symbol="X", market_value=value, asset_class="US_EQUITY")]
    return a


def test_rule_of_55_turns_on_in_the_year_of_the_55th_birthday():
    b = date(1971, 12, 31)
    assert not ea.rule_of_55_eligible(b, 2025, True)
    assert ea.rule_of_55_eligible(b, 2026, True)
    assert ea.rule_of_55_eligible(b, 2030, True)


def test_old_employer_plan_never_qualifies():
    assert not ea.rule_of_55_eligible(date(1970, 1, 1), 2040, False)


def test_penalty_is_income_tax_plus_ten_percent():
    c = ea.penalty_cost(10_000, 0.22)
    assert c["income_tax"] == pytest.approx(2200)
    assert c["penalty"] == pytest.approx(1000)
    assert c["net"] == pytest.approx(6800)


def test_sepp_rmd_method_divides_by_life_expectancy():
    r = ea.sepp_payment(500_000, 55, 0.05, "rmd")
    assert r["annual_payment"] == pytest.approx(500_000 / 31.6)
    assert r["years_required"] == 5 and r["ends_at_age"] == 60


def test_sepp_amortization_matches_annuity_formula():
    r = ea.sepp_payment(500_000, 50, 0.05)
    n, i = 36.2, 0.05
    assert r["annual_payment"] == pytest.approx(500_000 * i / (1 - (1 + i) ** -n))
    assert r["ends_at_age"] == pytest.approx(59.5)  # longer of 5 years and the run to 59.5


def test_sepp_rejects_bad_input():
    with pytest.raises(ValueError):
        ea.sepp_payment(1, 30, 0.05)
    with pytest.raises(ValueError):
        ea.sepp_payment(1, 55, 0.05, "bogus")
    with pytest.raises(ValueError):
        ea.sepp_payment(1, 55, 0.05, table="joint")


def test_access_and_rollover_flip_with_separation_age():
    a = _plan("Current", True)
    today = date(2026, 10, 31)
    late = ea.account_access(a, date(1980, 5, 1), 56, True, today)
    assert late["accessible_at"] == 55
    assert ea.rollover_advice(late, True)["action"] == "keep"
    early = ea.account_access(a, date(1980, 5, 1), 50, True, today)
    assert early["accessible_at"] == 59.5
    old = ea.account_access(_plan("Old", False), date(1980, 5, 1), 56, False, today)
    assert old["accessible_at"] == 59.5
    assert ea.rollover_advice(old, False)["action"] == "consider_roll"


def test_rule55_locks_other_plans_only_after_flagging():
    cur, old = _plan("Cur", True, 100), _plan("Old", False, 40)
    assert planner._rule55_locked([cur, old]) == 40
    assert planner._rule55_locked([_plan("A", False, 100), old]) == 0  # nothing flagged: legacy behaviour
    assert planner._rule55_locked([cur, _plan("Sp", False, 70, owner="SPOUSE")]) == 0


def test_early_access_api(client):
    r = client.get("/api/early-access")
    assert r.status_code == 200 and "exceptions" in r.json
    assert client.get("/api/early-access/sepp?balance=500000&age=55&method=rmd").json["life_expectancy"] == 31.6
    assert client.get("/api/early-access/sepp?balance=1&age=20").status_code == 400


def test_mortality_rates_reproduce_the_verified_single_life_table():
    """Table 4 (qx) was read from a summarised page; deriving life expectancies from it must match Pub 590-B Table I."""
    q = ea._data()["mortality_qx"]
    sl = {int(k): v for k, v in json.loads((ea.DATA_FILE.parent / "rmd_tables.json").read_text())["single_life"].items()}
    assert len(q) == 121
    for age in range(0, 101):  # the 113+ tail is sensitive to how the open-ended last row is closed
        alive, e = 1.0, 0.0
        for a in range(age, 121):
            e += alive * (1 - q[a] / 2)
            alive *= 1 - q[a]
        e += alive * 0.6 / 0.4
        assert abs(e - sl[age]) < 0.1, age


def test_annuity_factor_known_properties():
    f0 = ea.annuity_factor(55, 0.0)
    assert 30 < f0 < 36  # undiscounted ~ life expectancy + 0.5 at 55 (31.6 + ~0.5-1)
    assert ea.annuity_factor(55, 0.05) < f0
    assert ea.annuity_factor(60, 0.05) < ea.annuity_factor(50, 0.05)
    assert ea.annuity_factor(55, 0.05) > 1


def test_annuitization_payment_is_balance_over_factor():
    r = ea.sepp_payment(500_000, 55, 0.05, "annuitization")
    assert r["annual_payment"] == pytest.approx(500_000 / ea.annuity_factor(55, 0.05))
    amort = ea.sepp_payment(500_000, 55, 0.05, "amortization")
    assert amort["annual_payment"] == pytest.approx(500_000 * 0.05 / (1 - 1.05**-31.6))
    # annuitization (annuity due, last-survivor-free) pays about the same as amortization, within a few percent
    assert abs(r["annual_payment"] / amort["annual_payment"] - 1) < 0.08


def test_uniform_table_option_and_rate_cap():
    u = ea.sepp_payment(500_000, 55, 0.05, "rmd", table="uniform")
    assert u["life_expectancy"] == 43.6 and u["annual_payment"] == pytest.approx(500_000 / 43.6)
    assert ea.max_sepp_rate(0.03) == 0.05 and ea.max_sepp_rate(0.05) == pytest.approx(0.06)
    assert not ea.sepp_payment(1, 55, 0.07, mid_term_rate=0.04)["rate_within_cap"]
    assert ea.sepp_payment(1, 55, 0.07, mid_term_rate=0.06)["rate_within_cap"]


def test_uniform_table_matches_notice_and_rmd_table():
    u = ea._data()["uniform_lifetime"]
    rm = json.loads((ea.DATA_FILE.parent / "rmd_tables.json").read_text())["uniform_lifetime"]
    assert u["10"] == 88.2 and u["50"] == 48.5 and u["70"] == 29.2
    assert all(u[str(a)] == rm[str(a)] for a in range(72, 121))


def test_roth_ordering_layers():
    out = ea.roth_ordering(20_000, [{"year": 2028, "amount": 10_000}, {"year": 2020, "amount": 10_000}], 5_000, 43_000, 50, 2030, 2015)
    assert out["from_contributions"] == 20_000
    assert [c["year"] for c in out["from_conversions"]] == [2020, 2028]  # oldest first
    assert out["from_conversions"][0]["penalty"] == 0  # 10 years old
    assert out["from_conversions"][1]["penalty"] == 1_000  # 2 years old and under 59.5
    assert out["from_earnings"] == 3_000 and out["taxable"] == 3_000 and out["penalty"] == 1_300
    assert out["unfunded"] == 0


def test_roth_ordering_qualified_and_five_year_rules():
    old = ea.roth_ordering(0, [{"year": 2018, "amount": 10_000}], 8_000, 18_000, 61, 2030, 2015)
    assert old["penalty"] == 0 and old["taxable"] == 0 and old["earnings_qualified"]
    young = ea.roth_ordering(0, [{"year": 2029, "amount": 10_000}], 8_000, 18_000, 40, 2030, 2015)
    assert young["penalty"] == pytest.approx(1_800) and young["taxable"] == 8_000
    short = ea.roth_ordering(1_000, [], 0, 5_000, 40, 2030, 2015)
    assert short["unfunded"] == 4_000


def test_roth_order_route(client):
    r = client.post("/api/early-access/roth-order", json={"withdraw": 1000, "age": 40, "year": 2030, "roth_open_year": 2020, "contributions": 5000})
    assert r.status_code == 200 and r.get_json()["penalty"] == 0
    assert client.post("/api/early-access/roth-order", json={}).status_code == 400

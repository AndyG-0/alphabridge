from datetime import date
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import household, tax
from services import income_streams as inc


def test_annuity_exclusion_ratio_until_basis_recovered():
    c = inc.components("ANNUITY", 2_000, basis=100_000, years_paid=0)
    assert c["cash"] == 24_000 and c["ordinary"] == pytest.approx(24_000 - 100_000 / 20)
    assert inc.components("ANNUITY", 2_000, basis=100_000, years_paid=20)["ordinary"] == 24_000


def test_rental_depreciation_shelters_and_floors_at_zero():
    assert inc.components("RENTAL", 20_000, basis=8_000)["ordinary"] == 12_000
    assert inc.components("RENTAL", 5_000, basis=8_000)["ordinary"] == 0


def test_inheritance_is_untaxed_and_sale_is_capital_gain():
    r = inc.after_tax([inc.components("INHERIT", 100_000)], 50_000, "SINGLE", 2026)
    assert r["tax"] == 0 and r["net"] == 100_000
    s = inc.components("BIZSALE", 500_000, basis=200_000)
    assert s["qualified"] == 300_000 and s["ordinary"] == 0


def test_incremental_tax_matches_engine_difference():
    got = inc.incremental_tax(40_000, 0, 30_000, "SINGLE", 2026)
    want = tax.total_tax(ordinary=70_000, status="SINGLE", year=2026)["total"] - tax.total_tax(ordinary=30_000, status="SINGLE", year=2026)["total"]
    assert got == pytest.approx(want) and got > 0


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        inc.components("BOGUS", 1)


@settings(max_examples=25, deadline=None)
@given(a=st.floats(0, 500_000), b=st.floats(0, 500_000))
def test_more_income_never_means_less_tax_or_negative_net_tax(a, b):
    lo, hi = sorted((a, b))
    t_lo = inc.incremental_tax(lo, 0, 40_000, "MFJ", 2026)
    t_hi = inc.incremental_tax(hi, 0, 40_000, "MFJ", 2026)
    assert 0 <= t_lo <= t_hi + 1e-6


def test_event_years_run_annually_for_recurring_kinds():
    ev = SimpleNamespace(kind="PARTTIME", start_year=2030, repeat_until_year=2034, repeat_every_years=0)
    assert household.event_years(ev, 2026, 40) == [4, 5, 6, 7, 8]


def test_events_feed_flows_net_of_tax():
    base = _flows([])
    ev = SimpleNamespace(
        kind="PARTTIME",
        amount=30_000,
        start_year=date.today().year + 20,
        repeat_until_year=date.today().year + 24,
        repeat_every_years=0,
        owner="SELF",
        financed=False,
        down_payment=0,
        loan_apr=0,
        loan_term_months=60,
        is_home_sale=False,
        name="Consulting",
        basis=0,
    )
    f = _flows([ev])
    y = 20
    assert f.income[y] > base.income[y]
    assert f.income[y] < 30_000  # taxed


def _flows(events):
    from tests.test_household import _profile

    p = _profile(spouse_age=0.0, current_age=50.0, target_retirement_age=55.0, tax_filing_status="SINGLE", ltc_years=0)
    return household.build_flows(p, [], events, retire_age=55, years=45, inflation=0.025)


def test_route(client):
    r = client.post(
        "/api/planner/events",
        json={"name": "SPIA", "kind": "ANNUITY", "amount": 1500, "start_year": 2040, "basis": 200000},
    )
    assert r.status_code == 201
    d = client.get("/api/planner/income-streams").get_json()
    assert d["years"] and d["years"][0]["tax"] >= 0

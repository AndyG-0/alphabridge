from datetime import date

import pytest

from services import cash_optimizer as co
from services import ladder as ld


def test_curve_interpolation_endpoints_and_midpoint():
    assert ld.curve_yield(3, 0.04, 0.05) == pytest.approx(0.04)
    assert ld.curve_yield(120, 0.04, 0.05) == pytest.approx(0.05)
    assert ld.curve_yield(61.5, 0.04, 0.05) == pytest.approx(0.045)
    assert ld.curve_yield(1, 0.04, 0.05) == pytest.approx(0.04)  # clamped


def test_ladder_by_hand():
    y = {3: 0.04, 6: 0.042, 12: 0.045}
    lad = ld.build_ladder(30000, [3, 6, 12], y, date(2026, 1, 31))
    assert [r["amount"] for r in lad["rungs"]] == [10000, 10000, 10000]
    assert lad["rungs"][0]["matures_on"] == "2026-04-30"  # month-end clamp
    assert lad["rungs"][2]["matures_on"] == "2027-01-31"
    assert lad["rungs"][1]["interest_at_maturity"] == pytest.approx(10000 * 0.042 * 0.5)
    assert lad["blended_yield"] == pytest.approx((0.04 + 0.042 + 0.045) / 3)
    assert lad["annual_interest"] == pytest.approx(30000 * (0.04 + 0.042 + 0.045) / 3, abs=0.01)
    assert lad["next_maturity"] == "2026-04-30"


def test_ladder_cents_sum_exactly_and_empty():
    lad = ld.build_ladder(100.01, [3, 6, 9], {3: 0.04, 6: 0.04, 9: 0.04}, date(2026, 1, 1))
    assert sum(r["amount"] for r in lad["rungs"]) == pytest.approx(100.01)
    assert ld.build_ladder(0, [3], {3: 0.04}, date(2026, 1, 1))["rungs"] == []


def test_state_tax_advantage_by_hand():
    # $100k, MMF 4.0%, bill 4.0%, 24% federal, flat 5% state, no Treasury share:
    # MMF after-tax = 4000*(1-.24-.05)=2840 ; T-bill = 4000*(1-.24)=3040 ; advantage 200.
    a = ld.state_tax_advantage(100_000, 0.04, 0.04, "ZZ", 0.24, 0.0)
    assert a["state_rate_known"] is False
    rate = a["state_rate"]
    assert a["advantage"] == pytest.approx(4000 * rate, abs=0.01)
    assert a["winner"] == "TBILL"
    # No-income-tax state: nothing to gain at equal yields.
    tx = ld.state_tax_advantage(100_000, 0.04, 0.04, "TX", 0.24, 0.0)
    assert tx["advantage"] == 0
    # A fund that is entirely Treasuries removes the advantage.
    full = ld.state_tax_advantage(100_000, 0.04, 0.04, "ZZ", 0.24, 1.0)
    assert full["advantage"] == pytest.approx(0)
    # Higher MMF yield can outweigh the state exemption.
    assert ld.state_tax_advantage(100_000, 0.06, 0.04, "ZZ", 0.24, 0.0)["winner"] == "MMF"


def test_i_bond_cap_scales_with_household():
    assert ld.i_bond_plan(1, None, 0.04)["annual_purchase_cap"] == 10000
    assert ld.i_bond_plan(2, 0.05, 0.04)["annual_purchase_cap"] == 20000
    assert "beats" in ld.i_bond_plan(1, 0.05, 0.04)["verdict"]


def test_bridge_reserve_sums_first_years():
    rows = [
        {"year": 2040, "draw_taxable": 50000, "draw_pretax": 0, "draw_roth": 0},
        {"year": 2041, "draw_taxable": 30000, "draw_pretax": 10000, "draw_roth": 5000},
        {"year": 2042, "draw_taxable": 99999, "draw_pretax": 0, "draw_roth": 0},
    ]
    r = ld.bridge_reserve(rows, 2)
    assert r["total"] == 95000 and r["first_year"] == 2040 and r["per_year"] == [50000, 45000]
    assert ld.bridge_reserve([], 2)["total"] == 0


def test_dca_schedule_sums_and_dates():
    s = ld.dca_schedule(1000, 3, date(2026, 1, 1), 30)
    assert [x["amount"] for x in s] == [333.33, 333.33, 333.34]
    assert [x["on"] for x in s] == ["2026-01-01", "2026-01-31", "2026-03-02"]
    assert ld.dca_schedule(0, 3, date(2026, 1, 1)) == []


def test_due_tranches_skip_notified():
    plan = {"schedule": [{"on": "2026-01-01", "amount": 1}, {"on": "2026-02-01", "amount": 1}], "notified": ["2026-01-01"]}
    assert [t["on"] for t in ld.due_tranches(plan, date(2026, 2, 5))] == ["2026-02-01"]
    assert ld.due_tranches(plan, date(2025, 12, 1)) == []
    assert ld.due_tranches(None, date(2026, 1, 1)) == []


def test_deploy_fraction_matches_recommendation_rule():
    assert co.deploy_fraction(30) == 0
    assert co.deploy_fraction(45) == pytest.approx(0.25)
    assert co.deploy_fraction(70) == pytest.approx(0.60)
    assert co.deploy_fraction(100) == pytest.approx(0.90)

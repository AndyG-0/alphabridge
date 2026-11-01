import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import real_estate as re


def test_exclusion_amounts():
    assert re.exclusion("SINGLE") == 250_000 and re.exclusion("MFJ") == 500_000


def test_mortgage_balance_path_amortizes_to_zero():
    path = re.mortgage_balance_path(200_000, 0.06, 1199.10, 30)
    assert path[0] < 200_000 and path[-1] == pytest.approx(0, abs=50)
    assert all(b >= 0 for b in path)


def test_equity_projection_value_compounds():
    rows = re.equity_projection(500_000, 0.03, [{"balance": 100_000, "apr": 0.04, "monthly_payment": 1500}], 5, 2026)
    assert rows[0]["value"] == pytest.approx(515_000) and rows[-1]["equity"] > rows[0]["equity"]


def test_downsize_inside_exclusion_has_no_tax():
    r = re.downsize(sale_price=700_000, mortgage=100_000, cost_basis=400_000, new_home_price=350_000, status="MFJ", year=2026, selling_cost_pct=0.06)
    assert r["gain"] == pytest.approx(700_000 * 0.94 - 400_000) and r["taxable_gain"] == 0 and r["tax"] == 0
    assert r["cash_freed"] == pytest.approx(700_000 * 0.94 - 100_000 - 350_000)


def test_downsize_over_exclusion_taxes_the_excess():
    r = re.downsize(sale_price=1_500_000, mortgage=0, cost_basis=300_000, new_home_price=500_000, status="SINGLE", year=2026, selling_cost_pct=0.0)
    assert r["taxable_gain"] == pytest.approx(950_000) and r["tax"] > 100_000
    assert r["net_proceeds"] == pytest.approx(1_500_000 - r["tax"])


def test_cost_of_living_ratio_and_state_tax():
    r = re.cost_of_living(80_000, 100, 80, income=100_000, from_state="CA", to_state="TX")
    assert r["new_spend"] == pytest.approx(64_000) and r["annual_saving"] >= 16_000
    with pytest.raises(ValueError):
        re.cost_of_living(1, 0, 1)


@settings(max_examples=25, deadline=None)
@given(price=st.floats(0, 5e6), basis=st.floats(0, 5e6))
def test_tax_never_negative_and_net_never_exceeds_price(price, basis):
    r = re.downsize(sale_price=price, mortgage=0, cost_basis=basis, new_home_price=0, status="MFJ", year=2026)
    assert r["tax"] >= 0 and r["net_proceeds"] <= price + 1e-6


def test_route(client):
    d = client.get("/api/planner/real-estate?home_value=600000&new_home_price=350000&target_col_index=85").get_json()
    assert d["home_value"] == 600_000 and d["projection"] and d["downsize"]["cash_freed"] != 0 and d["relocation"]["ratio"] == 0.85

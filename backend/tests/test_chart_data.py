import pytest

from services import chart_data, tax


def test_bracket_fill_matches_tax_engine():
    r = chart_data.bracket_fill(80_000, "SINGLE", 2026)
    taxable = 80_000 - tax.standard_deduction("SINGLE", r["year"])
    assert r["taxable_income"] == taxable
    assert sum(b["filled"] for b in r["bands"]) == pytest.approx(taxable)
    assert r["tax"] == pytest.approx(tax.ordinary_tax(taxable, "SINGLE", r["year"])[0])
    assert r["marginal_rate"] == 0.22
    assert r["source_url"].startswith("https://")
    assert r["bands"][-1]["to"] is None


def test_bracket_fill_below_deduction_is_empty():
    r = chart_data.bracket_fill(5_000, "MFJ", 2026)
    assert r["taxable_income"] == 0 and all(b["filled"] == 0 for b in r["bands"])


def test_cash_flow_links_sum_to_income(client):
    client.put("/api/profile", json={"annual_income": 150000, "monthly_expenses_current": 4000, "monthly_contribution": 2000})
    r = client.get("/api/charts/cashflow").get_json()
    assert r["gross_income"] == 150000
    assert sum(link["value"] for link in r["links"]) == pytest.approx(150000 - r["shortfall"])
    assert r["nodes"][0] == "Income" and "Taxes" in r["nodes"]


def test_cash_flow_reports_shortfall(client):
    client.put("/api/profile", json={"annual_income": 40000, "monthly_expenses_current": 5000})
    r = client.get("/api/charts/cashflow").get_json()
    assert r["shortfall"] > 0 and "Left over" not in r["nodes"]


def test_fire_path_has_ordered_percentile_bands(client):
    client.put("/api/profile", json={"annual_income": 150000, "monthly_expenses_retirement": 4000, "birth_date": "1985-01-01"})
    r = client.get("/api/planner/fire?sims=300").get_json()
    assert r["path"]
    for pt in r["path"]:
        assert pt["p10"] <= pt["p25"] <= pt["value"] <= pt["p75"] <= pt["p90"] + 1e-6


def test_brackets_route_defaults_to_income(client):
    client.put("/api/profile", json={"annual_income": 100000})
    assert client.get("/api/charts/brackets").get_json()["magi"] == 100000

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import aca
from services import withdrawals as w


def _inp(**kw):
    n = 40
    base = dict(
        start_year=2030,
        start_age=55,
        end_age=95,
        status="MFJ",
        household_size=2,
        taxable=600_000,
        pretax=1_200_000,
        roth=200_000,
        gain_ratio=0.35,
        spend=[90_000] * n,
        ss=[0] * 12 + [50_000] * 28,
        aca_benchmark=[20_000] * 10 + [0] * 30,
        medicaid_limit=1.38,
    )
    return w.Inputs(**(base | kw))


def test_all_strategies_fund_spending_with_enough_assets():
    out = w.compare(_inp())
    assert {s["strategy"] for s in out["strategies"]} == set(w.STRATEGIES)
    for s in out["strategies"]:
        assert s["shortfall_years"] == 0
        assert len(s["years"]) == 40
        first = s["years"][0]
        assert first["draw_pretax"] == 0  # locked before 59.5
        assert all(r["tax"] >= 0 for r in s["years"])


def test_target_magi_keeps_income_under_cliff_and_beats_taxable_first_on_aca():
    out = {s["strategy"]: s for s in w.compare(_inp())["strategies"]}
    cliff = aca.cliff_magi(2)
    pre65 = [r for r in out["TARGET_MAGI"]["years"] if r["aca_premium"] > 0 or r["age"] < 65][:10]
    assert all(r["magi"] <= cliff for r in pre65)
    assert out["TARGET_MAGI"]["years_over_aca_cliff"] == 0
    assert out["TARGET_MAGI"]["lifetime_aca_premiums"] <= out["TAXABLE_FIRST"]["lifetime_aca_premiums"]


def test_known_year_taxable_only_draw():
    """One year, taxable-only: tax is LTCG on the gain portion, stacked on zero ordinary income (0% band covers it)."""
    inp = _inp(taxable=500_000, pretax=0, roth=0, spend=[40_000], ss=[0], aca_benchmark=[0], start_age=70, end_age=71, household_size=2)
    row = w.simulate(inp, "TAXABLE_FIRST")["years"][0]
    assert row["draw_taxable"] == pytest.approx(40_000, abs=1)
    assert row["tax"] == pytest.approx(0, abs=1)  # 14k of gains under the MFJ standard deduction


def test_shortfall_reported_when_assets_run_out():
    out = w.simulate(_inp(taxable=10_000, pretax=0, roth=0, ss=[0] * 40, aca_benchmark=[0] * 40), "TAXABLE_FIRST")
    assert out["shortfall_years"] > 30 and out["total_shortfall"] > 0


def test_unknown_strategy():
    with pytest.raises(ValueError):
        w.simulate(_inp(), "NOPE")


def test_aca_schedule_has_cliff_and_data_file_metadata():
    sch = aca.subsidy_schedule(2, 20_000, medicaid_limit=1.38)
    assert sch["cliff_magi"] == pytest.approx(4 * aca.fpl(2))
    assert sch["points"][-1]["credit"] == 0 and sch["points"][-1]["net_premium"] == 20_000
    nets = [p["net_premium"] for p in sch["points"] if not p["medicaid"]]
    assert nets == sorted(nets)
    assert aca.retrieved_on() and aca.target_magi(2) < sch["cliff_magi"]


@settings(max_examples=25, deadline=None)
@given(spend=st.floats(10_000, 150_000), taxable=st.floats(0, 1_000_000), pretax=st.floats(0, 2_000_000))
def test_properties_balances_and_tax_never_negative(spend, taxable, pretax):
    inp = _inp(spend=[spend] * 40, taxable=taxable, pretax=pretax, end_age=75)
    for strat in w.STRATEGIES:
        for r in w.simulate(inp, strat)["years"]:
            assert r["tax"] >= -1e-6 and r["shortfall"] >= -1e-6
            assert all(v >= -1e-6 for v in r["balances"].values())


def test_more_spending_never_lowers_lifetime_tax():
    low = w.simulate(_inp(spend=[60_000] * 40), "TAXABLE_FIRST")["lifetime_tax"]
    high = w.simulate(_inp(spend=[120_000] * 40), "TAXABLE_FIRST")["lifetime_tax"]
    assert high >= low


def test_route_and_planner_wiring(client):
    r = client.get("/api/planner/withdrawals?detail=0")
    assert r.status_code == 200
    body = r.get_json()
    assert body["best"] in w.STRATEGIES and body["aca_rules_year"] == aca.RULES_YEAR and "aca_schedule" in body
    assert client.get("/api/planner/withdrawals?strategies=BAD").status_code == 400
    one = client.get("/api/planner/withdrawals?strategies=TARGET_MAGI").get_json()
    assert len(one["strategies"]) == 1 and one["strategies"][0]["years"]


def test_aca_table_is_sourced_and_fresh():
    from datetime import date, timedelta

    for y, t in aca._tables().items():
        assert t["source_url"].startswith("https://") and t["year"] == y
    assert date.today() - date.fromisoformat(aca.retrieved_on()) < timedelta(days=366)

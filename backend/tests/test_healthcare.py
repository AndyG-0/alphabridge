import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from schemas import PlannedEventIn
from services import healthcare as hc
from services import tax


def test_no_irmaa_below_first_tier():
    r = hc.medicare_cost(50_000, "SINGLE", 2026)
    assert r["irmaa_tier"] == 0 and r["irmaa_monthly"] == 0
    assert r["part_b_monthly"] == pytest.approx(tax.table(2026)["irmaa"]["base_part_b_monthly"])


def test_irmaa_adds_surcharge_known_answer():
    top = tax.irmaa(1_000_000, "MFJ", 2026)
    r = hc.medicare_cost(1_000_000, "MFJ", 2026, people=2)
    assert r["irmaa_tier"] == top["tier"] > 0
    base = hc.medicare_cost(0, "MFJ", 2026, people=2)
    assert r["annual"] - base["annual"] == pytest.approx(2 * 12 * (top["part_b_surcharge_monthly"] + top["part_d_surcharge_monthly"]))


def test_medigap_toggle():
    assert hc.medicare_cost(0, "SINGLE", 2026, medigap=False)["annual"] < hc.medicare_cost(0, "SINGLE", 2026)["annual"]


@settings(max_examples=25, deadline=None)
@given(a=st.floats(0, 3e6), b=st.floats(0, 3e6))
def test_medicare_cost_monotone_in_magi(a, b):
    lo, hi = sorted((a, b))
    assert hc.medicare_cost(lo, "MFJ", 2026)["annual"] <= hc.medicare_cost(hi, "MFJ", 2026)["annual"] + 1e-9


def test_pre65_premium_rises_with_age_and_credit_never_negative():
    rows = hc.pre65_table([30, 50, 64], 60_000, 1)
    assert rows[0]["benchmark"] < rows[1]["benchmark"] < rows[2]["benchmark"]
    assert all(r["credit"] >= 0 and r["net"] >= 0 for r in rows)


def test_ltc_expected_vs_stress():
    e, s = hc.ltc_event("EXPECTED", 100_000, 2, 0.7), hc.ltc_event("STRESS", 100_000, 2)
    assert e["total"] == pytest.approx(140_000) and s["total"] == pytest.approx(200_000)
    with pytest.raises(ValueError):
        hc.ltc_event("BOGUS", 1, 1)


def test_hsa_accumulates_then_pays_medical():
    rows = hc.hsa_projection(10_000, False, 40, 60, 80, 2026, growth=0.0, medical_spend=5_000)
    assert rows[0]["contribution"] > 0 and rows[-1]["contribution"] == 0
    assert all(r["balance"] >= 0 for r in rows)
    assert all(r["medical_spend"] == 0 for r in rows if r["age"] < 60)
    assert max(r["medical_spend"] for r in rows) <= 5_000


def test_ltc_is_a_valid_event_kind():
    assert PlannedEventIn(name="LTC", kind="LTC", amount=70_000, start_year=2060).kind == "LTC"
    with pytest.raises(ValidationError):
        PlannedEventIn(name="x", kind="BOGUS", amount=1, start_year=2060)


def test_route(client):
    r = client.get("/api/planner/healthcare?magi=300000&status=MFJ&people=2")
    assert r.status_code == 200
    d = r.get_json()
    assert d["medicare"]["irmaa_tier"] > 0 and {x["mode"] for x in d["ltc"]} == {"EXPECTED", "STRESS"}

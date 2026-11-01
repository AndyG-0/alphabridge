from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import tax

YEAR = 2026
income = st.floats(0, 3_000_000, allow_nan=False)
status = st.sampled_from(["SINGLE", "MFJ"])


# --- known answers (hand-computed from the 2026 tables) -------------------------------------------------------


def test_ordinary_tax_single_100k():
    # taxable 83,900: 12,400*10% + 38,000*12% + 33,500*22%
    t, marginal = tax.ordinary_tax(100_000 - tax.standard_deduction("SINGLE", YEAR), "SINGLE", YEAR)
    assert t == pytest.approx(13_170)
    assert marginal == 0.22


def test_ordinary_tax_mfj_100k():
    t, marginal = tax.ordinary_tax(100_000 - tax.standard_deduction("MFJ", YEAR), "MFJ", YEAR)
    assert t == pytest.approx(7_640)
    assert marginal == 0.12


def test_social_security_pub915_single():
    # provisional income 30,000 + 10,000 = 40,000; 50% of (34,000-25,000) + 85% of (40,000-34,000)
    assert tax.taxable_social_security(20_000, 30_000, "SINGLE", YEAR) == pytest.approx(9_600)


def test_social_security_mfj_first_tier_only():
    assert tax.taxable_social_security(30_000, 20_000, "MFJ", YEAR) == pytest.approx(1_500)


def test_social_security_zero_below_base_and_capped_at_85pct():
    assert tax.taxable_social_security(20_000, 0, "SINGLE", YEAR) == 0
    assert tax.taxable_social_security(20_000, 1_000_000, "SINGLE", YEAR) == pytest.approx(17_000)


def test_niit_applies_to_lesser_of_nii_and_excess():
    assert tax.niit(50_000, 220_000, "SINGLE", YEAR) == pytest.approx(760)
    assert tax.niit(10_000, 220_000, "SINGLE", YEAR) == pytest.approx(380)
    assert tax.niit(50_000, 150_000, "SINGLE", YEAR) == 0


def test_ltcg_stacks_on_ordinary_income():
    # 9,450 of the gain fits under the 0% ceiling (49,450); the rest is 15%
    assert tax.ltcg_tax(20_000, 40_000, "SINGLE", YEAR) == pytest.approx(10_550 * 0.15)
    assert tax.ltcg_tax(20_000, 0, "SINGLE", YEAR) == 0
    assert tax.ltcg_tax(100_000, 600_000, "SINGLE", YEAR) == pytest.approx(20_000)


def test_irmaa_tiers():
    assert tax.irmaa(100_000, "SINGLE", YEAR)["tier"] == 0
    r = tax.irmaa(150_000, "SINGLE", YEAR)
    assert r["tier"] == 2 and r["part_b_total_monthly"] == pytest.approx(405.80)
    assert tax.irmaa(218_000, "MFJ", YEAR)["tier"] == 0
    assert tax.irmaa(218_001, "MFJ", YEAR)["tier"] == 1


def test_state_tax_none_flat_and_unknown():
    assert tax.state_tax(100_000, "TX") == 0
    assert tax.state_tax(100_000, "AZ") == pytest.approx(2_500)
    assert tax.state_rule("ZZ")["known"] is False
    assert tax.state_tax(100_000, "ZZ", flat_rate=0.05) == pytest.approx(5_000)


def test_total_tax_breakdown_adds_up_and_reports_year():
    r = tax.total_tax(ordinary=80_000, qualified=20_000, social_security=0, status="SINGLE", year=2030, state="TX")
    assert r["rules_year"] == 2026  # clamps to the newest table
    assert r["total"] == pytest.approx(r["federal"] + r["state"])
    assert r["federal"] == pytest.approx(r["federal_ordinary"] + r["federal_capital_gains"] + r["niit"])
    assert r["state"] == 0


def test_spare_standard_deduction_shelters_qualified_income():
    r = tax.total_tax(ordinary=0, qualified=10_000, status="SINGLE", year=YEAR, state="TX")
    assert r["total"] == 0


def test_unknown_status_defaults_to_single():
    assert tax.standard_deduction("HOH", YEAR) == tax.standard_deduction("SINGLE", YEAR)


# --- properties -----------------------------------------------------------------------------------------------


@settings(max_examples=60)
@given(a=income, b=income, s=status)
def test_total_tax_monotone_in_income(a, b, s):
    lo, hi = sorted([a, b])
    t_lo = tax.total_tax(ordinary=lo, status=s, year=YEAR, state="AZ")["total"]
    t_hi = tax.total_tax(ordinary=hi, status=s, year=YEAR, state="AZ")["total"]
    assert t_hi >= t_lo - 1e-6


@settings(max_examples=60)
@given(o=income, q=income, ss=st.floats(0, 100_000, allow_nan=False), s=status)
def test_tax_never_negative_and_rates_bounded(o, q, ss, s):
    r = tax.total_tax(ordinary=o, qualified=q, social_security=ss, status=s, year=YEAR, state="TX")
    assert r["total"] >= 0
    assert 0 <= r["marginal_federal_rate"] <= max(rate for _, rate in tax._brackets(s, YEAR))
    assert r["effective_rate"] <= 1


@settings(max_examples=60)
@given(b=st.floats(0, 100_000, allow_nan=False), o1=income, o2=income, s=status)
def test_taxable_social_security_bounded_and_monotone(b, o1, o2, s):
    lo, hi = sorted([o1, o2])
    t_lo = tax.taxable_social_security(b, lo, s, YEAR)
    t_hi = tax.taxable_social_security(b, hi, s, YEAR)
    assert 0 <= t_lo <= t_hi + 1e-6
    assert t_hi <= 0.85 * b + 1e-6


@settings(max_examples=60)
@given(o=income, g1=income, g2=income, s=status)
def test_ltcg_tax_monotone_in_gains(o, g1, g2, s):
    lo, hi = sorted([g1, g2])
    assert tax.ltcg_tax(lo, o, s, YEAR) <= tax.ltcg_tax(hi, o, s, YEAR) + 1e-6


# --- data -----------------------------------------------------------------------------------------------------


def test_tables_have_source_and_newest_is_fresh():
    for y in tax.table_years():
        t = tax.table(y)
        assert t["source_url"].startswith("https://www.irs.gov/")
        assert t["year"] == y
        date.fromisoformat(t["retrieved_on"])
    assert date.today() - tax.retrieved_on() < timedelta(days=366)


@pytest.mark.parametrize("s", ["SINGLE", "MFJ"])
def test_brackets_ascending_and_start_at_zero(s):
    br = tax._brackets(s, YEAR)
    assert br[0][0] == 0
    assert [lo for lo, _ in br] == sorted(lo for lo, _ in br)
    assert [r for _, r in br] == sorted(r for _, r in br)
    irmaa = tax.table(YEAR)["irmaa"]["tiers"][s]
    assert [t[0] for t in irmaa] == sorted(t[0] for t in irmaa)


def test_state_file_has_sources():
    d = tax._states()
    assert d["source_url"].startswith("https://") and date.fromisoformat(d["retrieved_on"])
    assert all(v["source_url"].startswith("https://") and 0 <= v["flat_rate"] < 0.2 for v in d["states"].values())


# --- API ------------------------------------------------------------------------------------------------------


def test_estimate_route(client):
    r = client.get("/api/tax/estimate?ordinary=100000&year=2026&status=SINGLE&state=TX")
    assert r.status_code == 200
    body = r.get_json()
    assert body["federal_ordinary"] == pytest.approx(13_170)
    assert body["rules_year"] == 2026 and body["retrieved_on"]


def test_estimate_route_defaults_from_profile_and_rejects_bad_input(client):
    assert client.get("/api/tax/estimate").status_code == 200
    assert client.get("/api/tax/estimate?ordinary=abc").status_code == 400


def test_profile_rejects_unknown_filing_status(client):
    assert client.put("/api/profile", json={"tax_filing_status": "HOH"}).status_code == 400
    assert client.put("/api/profile", json={"tax_filing_status": "MFJ"}).status_code == 200

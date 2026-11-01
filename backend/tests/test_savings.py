import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import savings as s


def test_limits_2026_by_age():
    young = s.limits(2026, 35)
    assert young["k401_max"] == 24_500 and young["ira_base"] == 7_500 and young["k401_catch_up_kind"] == "none"
    mid = s.limits(2026, 52)
    assert mid["k401_max"] == 24_500 + 8_000 and mid["ira_base"] == 8_600
    sup = s.limits(2026, 61)
    assert sup["k401_max"] == 24_500 + 11_250 and sup["k401_catch_up_kind"] == "super"  # replaces, not adds to, the 50+ catch-up
    assert s.limits(2026, 64)["k401_catch_up"] == 8_000
    assert s.limits(2026, 59)["k401_catch_up"] == 8_000


def test_future_year_uses_latest_table():
    assert s.limits(2031, 40)["rules_year"] == 2026 and s.limits(2031, 40)["k401_deferral"] == 24_500


def test_roth_ira_phase_out_known_answers():
    assert s.limits(2026, 40, "SINGLE", 150_000)["roth_ira_allowed"] == 7_500
    assert s.limits(2026, 40, "SINGLE", 168_000)["roth_ira_allowed"] == 0
    # halfway through 153k-168k: 7500 * 7500/15000 = 3750
    assert s.limits(2026, 40, "SINGLE", 160_500)["roth_ira_allowed"] == 3_750
    # reduction rounds up to the next $10 (age 61, base 8600): 8600*8000/15000 = 4586.67 -> 4590
    assert s.limits(2026, 61, "SINGLE", 160_000)["roth_ira_allowed"] == 4_590
    assert s.limits(2026, 40, "MFJ", 250_000)["roth_ira_allowed"] == 1_500
    # near the top of the range the floor is $200
    assert s.limits(2026, 40, "SINGLE", 167_990)["roth_ira_allowed"] == 200


def test_ira_deduction():
    assert s.limits(2026, 40, "SINGLE", 200_000, covered_by_plan=False)["ira_deductible"] == 7_500
    assert s.limits(2026, 40, "SINGLE", 100_000, covered_by_plan=True)["ira_deductible"] == 0
    assert s.limits(2026, 40, "MFJ", 100_000, covered_by_plan=True)["ira_deductible"] == 7_500
    assert s.limits(2026, 40, "MFJ", 247_000, covered_by_plan=False, spouse_covered=True)["ira_deductible"] == 3_750


def test_roth_catch_up_flag():
    assert s.limits(2026, 55, wages_prior_year=200_000)["roth_catch_up_required"]
    assert not s.limits(2026, 55, wages_prior_year=100_000)["roth_catch_up_required"]
    assert not s.limits(2026, 40, wages_prior_year=200_000)["roth_catch_up_required"]


def test_hsa_limits_come_from_hsa_table():
    assert s.limits(2026, 56)["hsa_self_only"] == 4_400 + 1_000


def test_match_capture():
    m = s.match_capture(100_000, 3_000, 0.5, 0.06)  # 50% of the first 6%
    assert m["max_match"] == 3_000 and m["captured"] == 1_500 and m["left_on_table"] == 1_500
    assert m["deferral_to_capture_all"] == 6_000 and not m["fully_captured"]
    assert s.match_capture(100_000, 10_000, 0.5, 0.06)["fully_captured"]


def test_waterfall_order_and_totals():
    w = s.waterfall(40_000, 120_000, 40, 2026, "SINGLE", 120_000, 0.5, 0.06, hsa_eligible=True)
    names = [x["step"] for x in w["steps"]]
    assert names[0].startswith("401(k) up to the employer match") and names[1] == "HSA" and names[2] == "Roth IRA"
    assert sum(x["amount"] for x in w["steps"]) == pytest.approx(40_000) and w["unallocated"] == 0
    assert w["steps"][0]["amount"] == pytest.approx(7_200)
    # the 401(k) step after the match tops up to 24,500 total deferral
    assert w["steps"][3]["amount"] == pytest.approx(24_500 - 7_200)
    assert w["steps"][-1]["step"] == "Taxable brokerage"


def test_waterfall_high_income_goes_backdoor():
    w = s.waterfall(30_000, 400_000, 40, 2026, "SINGLE", 400_000)
    assert any("backdoor" in x["step"] for x in w["steps"])


def test_waterfall_small_surplus_stops_in_match():
    w = s.waterfall(2_000, 100_000, 30, 2026, match_rate=1.0, match_cap_pct=0.04)
    assert w["steps"][0]["amount"] == 2_000 and all(x["amount"] == 0 for x in w["steps"][1:])


def test_backdoor_checklist_pro_rata():
    assert not s.backdoor_checklist(50_000, True, True)["backdoor_viable"]
    c = s.backdoor_checklist(0, True, False)
    assert c["backdoor_viable"] and not c["mega_backdoor_viable"]


def test_fi_numbers():
    assert s.fi_number(40_000, 0.04) == 1_000_000
    v = s.fi_variants(50_000, 200_000, 30_000, 35, 50, 0.05, 0.04, part_time_income=20_000)
    assert v["numbers"]["fi"] == 1_250_000 and v["numbers"]["barista"] == 750_000
    assert v["numbers"]["lean"] < v["numbers"]["fi"] < v["numbers"]["fat"]
    assert v["coast"]["needed_now"] == pytest.approx(1_250_000 / 1.05**15)


def test_years_to_target_matches_simulation():
    n = s.years_to_target(100_000, 20_000, 1_000_000, 0.05)
    bal, yrs = 100_000.0, 0
    while bal < 1_000_000:
        bal = bal * 1.05 + 20_000
        yrs += 1
    assert yrs - 1 < n <= yrs
    assert s.years_to_target(2_000_000, 0, 1_000_000, 0.05) == 0.0
    assert s.years_to_target(0, 0, 1_000_000, 0.05) is None
    assert s.years_to_target(0, 10_000, 100_000, 0.0) == 10.0


@settings(max_examples=60, deadline=None)
@given(
    bal=st.floats(0, 5e6),
    save=st.floats(1_000, 200_000),
    target=st.floats(1e5, 5e6),
    r=st.floats(0.0, 0.1),
    extra=st.floats(1, 50_000),
)
def test_more_saving_never_slower(bal, save, target, r, extra):
    a = s.years_to_target(bal, save, target, r)
    b = s.years_to_target(bal, save + extra, target, r)
    if a is not None:
        assert b is not None and b <= a + 1e-9


@settings(max_examples=60, deadline=None)
@given(magi=st.floats(0, 600_000), status=st.sampled_from(["SINGLE", "MFJ"]), age=st.floats(20, 80))
def test_phase_out_monotone_and_bounded(magi, status, age):
    lo = s.limits(2026, age, status, magi)["roth_ira_allowed"]
    hi = s.limits(2026, age, status, magi + 5_000)["roth_ira_allowed"]
    assert 0 <= hi <= lo <= s.limits(2026, age)["ira_base"]


def test_route(client):
    r = client.get("/api/planner/savings?match_rate=0.5&match_cap_pct=0.06&hsa_eligible=1")
    assert r.status_code == 200
    d = r.get_json()
    assert d["waterfall"]["limits"]["k401_deferral"] == 24_500 and "fi" in d["fi"]["numbers"]

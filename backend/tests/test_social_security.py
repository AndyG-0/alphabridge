import json
from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from services import household
from services import social_security as ss


def test_pia_known_answers():
    # SSA worked example shape: 90% of first 1286 + 32% to 7749 + 15% above
    assert ss.pia_from_aime(1000) == 900.0
    assert ss.pia_from_aime(1286) == 1157.4
    assert ss.pia_from_aime(5000) == pytest.approx(1157.4 + 0.32 * (5000 - 1286), abs=0.1)
    assert ss.pia_from_aime(10000) == pytest.approx(1157.4 + 0.32 * (7749 - 1286) + 0.15 * (10000 - 7749), abs=0.1)
    assert ss.pia_from_aime(0) == 0


def test_fra_table():
    assert [ss.fra_age(y) for y in (1940, 1943, 1954, 1955, 1957, 1959, 1960, 1975)] == [65 + 6 / 12, 66, 66, 66 + 2 / 12, 66 + 6 / 12, 66 + 10 / 12, 67, 67]


def test_adjustment_known_answers_and_matches_legacy_factor():
    assert ss.adjustment(62, 67) == pytest.approx(0.70)  # 36*5/9 + 24*5/12 = 30%
    assert ss.adjustment(70, 67) == pytest.approx(1.24)
    assert ss.adjustment(66, 66) == 1.0 and ss.adjustment(62, 66) == pytest.approx(0.75)
    for age in (62, 63.5, 65, 67, 68.25, 70):
        assert household.ss_factor(age) == pytest.approx(ss.adjustment(age, 67))


def test_spousal_and_survivor():
    assert ss.spousal_top_up(3000, 500, 67) == pytest.approx(1000)
    assert ss.spousal_top_up(3000, 2000, 67) == 0
    assert ss.spousal_top_up(3000, 0, 62) == pytest.approx(1500 * 0.65)  # 32.5% of PIA at 62 with FRA 67
    assert ss.survivor_benefit(2000, 70, 67, 67, 67) == pytest.approx(2000 * 1.24)
    assert ss.survivor_benefit(2000, 62, 67, 67, 67) == pytest.approx(2000 * 0.825)  # floor beats 70% own
    assert ss.survivor_benefit(2000, 67, 67, 60, 67) == pytest.approx(2000 * 0.715)


def test_earnings_test():
    assert ss.earnings_test_withheld(20_000, 24_480, 62, 67) == 0
    assert ss.earnings_test_withheld(20_000, 34_480, 62, 67) == 5_000
    assert ss.earnings_test_withheld(20_000, 1e6, 62, 67) == 20_000
    assert ss.earnings_test_withheld(20_000, 74_160, 66.5, 67) == pytest.approx(3_000)  # year FRA is reached: $1 per $3
    assert ss.earnings_test_withheld(20_000, 1e6, 67, 67) == 0


def test_breakeven():
    be = ss.breakeven_age(2000, 62, 70, 67)
    assert 80 < be < 82  # the familiar ~80-81 break-even for 62 vs 70
    assert ss.breakeven_age(2000, 70, 62, 67) is None


def test_data_file_sourced_and_fresh():
    d = json.loads(ss.DATA.read_text())
    assert all(u.startswith("https://www.ssa.gov") for u in d["sources"].values())
    assert date.today() - date.fromisoformat(d["retrieved_on"]) < timedelta(days=400)


def _p(name="A", year=1970, age=56, pia=2800, claim=67):
    return {"name": name, "birth_year": year, "age_now": age, "pia": pia, "claim_age": claim}


def test_single_grid_prefers_later_with_long_life_and_earlier_with_short():
    longlived = ss.grid(_p(), None, modal=95, dispersion=8, real_rate=0.0)
    short = ss.grid(_p(), None, modal=72, dispersion=8, real_rate=0.0)
    assert longlived["best"]["claim_a"] == 70 and short["best"]["claim_a"] <= 64


def test_couple_lower_earner_gains_from_higher_earner_delaying():
    a, b = _p("hi", pia=3500), _p("lo", pia=800, year=1972, age=54)
    g = ss.grid(a, b, real_rate=0.01)
    assert g["best"]["claim_a"] >= 68  # delaying the higher earner raises the survivor benefit
    assert g["best"]["npv"] >= g["current"]["npv"]
    assert len(g["pairs"]) == 81


def test_haircut_lowers_npv():
    a = _p()
    assert ss.household_npv(a, None, 67, None, haircut=0.2, haircut_year=2035) < ss.household_npv(a, None, 67, None)


@given(pia=st.floats(0, 5000), c1=st.floats(62, 70), c2=st.floats(62, 70))
def test_benefit_monotone_in_claim_age(pia, c1, c2):
    lo, hi = sorted((c1, c2))
    assert ss.own_benefit(pia, lo) <= ss.own_benefit(pia, hi) + 1e-9


@given(aime=st.floats(0, 20000), more=st.floats(0, 5000))
def test_pia_monotone_and_concave(aime, more):
    assert ss.pia_from_aime(aime) <= ss.pia_from_aime(aime + more)
    assert ss.pia_from_aime(aime + more) - ss.pia_from_aime(aime) <= 0.9 * more + 0.1


def test_route(client):
    body = client.get("/api/planner/social-security?haircut=0.2&haircut_year=2034").get_json()
    assert len(body["people"][0]["rows"]) == 9 and body["best"]["npv"] >= 0

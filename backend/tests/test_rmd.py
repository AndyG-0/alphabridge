import json
from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from services import rmd


def test_start_age_by_birth_year():
    assert [rmd.start_age(y) for y in (1949, 1950, 1951, 1959, 1960, 1975)] == [72, 72, 73, 73, 75, 75]


def test_irs_worked_examples():
    # Pub 590-B: age 73 divisor 26.5, age 75 divisor 24.6; $265,000 at 73 -> $10,000
    assert rmd.uniform_divisor(73) == 26.5 and rmd.uniform_divisor(75) == 24.6
    assert rmd.rmd(265_000, 73) == pytest.approx(10_000)
    assert rmd.uniform_divisor(120) == rmd.uniform_divisor(130) == 2.0 and rmd.uniform_divisor(70) is None
    assert rmd.single_life_divisor(50) == 36.2 and rmd.single_life_divisor(120) == 1.0


def test_tables_complete_and_monotone():
    d = json.loads(rmd.DATA.read_text())
    assert sorted(map(int, d["uniform_lifetime"])) == list(range(72, 121))
    vals = [d["uniform_lifetime"][str(a)] for a in range(72, 121)]
    assert vals == sorted(vals, reverse=True)
    assert len(d["single_life"]) == 121
    assert d["source_url"].startswith("https://") and date.today() - date.fromisoformat(d["retrieved_on"]) < timedelta(days=366)


def test_qcd_offsets_rmd_and_is_capped():
    assert rmd.qcd_limit(2026) == 111_000 and rmd.qcd_limit(2040) == 111_000
    p = rmd.projection(1_000_000, 1953, 2026, qcd_annual=200_000, age_now=73)
    first = p["rows"][0]
    assert first["age"] == 73 and first["qcd"] == 111_000
    assert first["taxable_rmd"] == pytest.approx(max(first["rmd"] - 111_000, 0))
    nq = rmd.projection(1_000_000, 1953, 2026, age_now=73)["rows"][0]
    assert nq["taxable_rmd"] == nq["rmd"] > first["taxable_rmd"]


def test_no_rmd_before_start_age_and_balance_grows():
    rows = rmd.projection(500_000, 1970, 2026, real_return=0.03, age_now=56)["rows"]
    assert all(r["rmd"] == 0 for r in rows if r["age"] < 75)
    assert rows[0]["end_balance"] == pytest.approx(515_000)
    assert next(r for r in rows if r["age"] == 75)["rmd"] > 0


def test_joint_life_flag():
    assert rmd.joint_life_applies(75, 60, True) and not rmd.joint_life_applies(75, 70, True) and not rmd.joint_life_applies(75, 60, False)
    assert rmd.projection(1e6, 1951, 2026, spouse_age_now=60, spouse_sole_beneficiary=True, age_now=75)["joint_life_table_would_apply"]


def test_inherited_ten_year_rule():
    no_rbd = rmd.inherited_schedule(100_000, 50, 2026, False, real_return=0.0)
    assert [r["required"] for r in no_rbd["rows"]][:9] == [0.0] * 9 and no_rbd["rows"][-1]["required"] == pytest.approx(100_000)
    assert no_rbd["rows"][-1]["year"] == 2036
    rbd = rmd.inherited_schedule(100_000, 50, 2026, True, real_return=0.0)
    assert rbd["rows"][0]["required"] == pytest.approx(100_000 / single_life_first(50))
    assert sum(r["required"] for r in rbd["rows"]) == pytest.approx(100_000)
    stretch = rmd.inherited_schedule(100_000, 50, 2026, False, eligible_designated=True, real_return=0.0)
    assert len(stretch["rows"]) > 10 and sum(r["required"] for r in stretch["rows"]) == pytest.approx(100_000, rel=1e-6)


def single_life_first(age):
    return rmd.single_life_divisor(age + 1)


def test_forced_bracket_warning():
    big = rmd.forced_bracket(250_000, 0, 60_000, "MFJ", 2026)
    small = rmd.forced_bracket(5_000, 0, 0, "MFJ", 2026)
    assert big["bracket_jump"] and big["extra_tax"] > 0 and big["marginal_with"] > big["marginal_without"]
    assert not small["bracket_jump"] and not small["irmaa_jump"]
    assert rmd.forced_bracket(250_000, 0, 60_000, "MFJ", 2026, qcd=111_000)["extra_tax"] < big["extra_tax"]


@given(bal=st.floats(0, 5_000_000), age=st.integers(72, 125))
def test_rmd_bounded_by_balance(bal, age):
    assert 0 <= rmd.rmd(bal, age) <= bal


def test_routes(client):
    assert client.get("/api/rmd").status_code == 200
    body = client.get("/api/rmd?qcd=5000").get_json()
    assert body["qcd_limit"] == 111_000 and body["people"][0]["start_age"] in (72, 73, 75)
    r = client.get("/api/rmd/inherited?balance=100000&beneficiary_age=50&death_year=2026").get_json()
    assert r["rows"][-1]["required"] > 0
    assert client.get("/api/rmd/inherited").status_code == 400

import pytest

from services import aca


def test_fpl_and_cliff():
    assert aca.fpl(1) == 15_650 and aca.fpl(2) == 21_150
    assert aca.cliff_magi(2) == pytest.approx(84_600)


def test_subsidy_shrinks_with_income_and_stops_at_cliff():
    bench = 24_000
    low = aca.premium(1.6 * aca.fpl(2), 2, bench)
    mid = aca.premium(3.0 * aca.fpl(2), 2, bench)
    high = aca.premium(4.01 * aca.fpl(2), 2, bench)
    assert low["net"] < mid["net"] < high["net"] == bench
    assert mid["net"] == pytest.approx(0.0996 * 3.0 * aca.fpl(2))
    assert high["over_cliff"] and high["credit"] == 0


def test_medicaid_range_and_no_enrollees():
    assert aca.premium(1.2 * aca.fpl(2), 2, 20_000)["medicaid"]
    assert aca.premium(50_000, 2, 0)["net"] == 0


def test_age_curve_raises_premium():
    assert aca.benchmark_annual([60]) > aca.benchmark_annual([40]) * 2
    assert aca.benchmark_annual([40]) == pytest.approx(aca.BENCHMARK_40_MONTHLY * 12)


def test_enhanced_switch(monkeypatch):
    monkeypatch.setattr(aca, "ENHANCED", True)
    r = aca.premium(5 * aca.fpl(2), 2, 30_000)
    assert not r["over_cliff"] and r["net"] == pytest.approx(min(30_000, 0.085 * 5 * aca.fpl(2)))
    assert aca.cliff_magi(2) is None


def test_non_expansion_has_no_medicaid_and_a_coverage_gap_below_poverty():
    gap = aca.premium(0.8 * aca.fpl(2), 2, 20_000, medicaid_limit=None)
    assert gap["coverage_gap"] and not gap["medicaid"] and gap["net"] == 20_000
    above = aca.premium(1.2 * aca.fpl(2), 2, 20_000, medicaid_limit=None)
    assert not above["medicaid"] and not above["coverage_gap"] and above["credit"] > 0


def test_arizona_medicaid_edge():
    assert aca.premium(1.37 * aca.fpl(2), 2, 20_000, medicaid_limit=1.38)["medicaid"]
    assert not aca.premium(1.5 * aca.fpl(2), 2, 20_000, medicaid_limit=1.38)["medicaid"]


def test_engagement_blocked_pays_full_price_with_no_credit():
    r = aca.premium(1.2 * aca.fpl(2), 2, 20_000, medicaid_blocked=True)
    assert r["engagement_blocked"] and not r["medicaid"] and r["credit"] == 0 and r["net"] == 20_000
    assert aca.premium(1.6 * aca.fpl(2), 2, 20_000, medicaid_blocked=True)["credit"] > 0  # above Medicaid: unaffected

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from services import aca, rmd
from services import roth as r
from services import tax as tax_svc
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
        roth=100_000,
        gain_ratio=0.35,
        spend=[80_000] * n,
        ss=[0] * 12 + [50_000] * 28,
        aca_benchmark=[20_000] * 10 + [0] * 30,
        medicaid_limit=1.38,
    )
    return w.Inputs(**(base | kw))


@pytest.fixture(scope="module")
def cmp():
    return r.compare(_inp(), rmd_start_age=75, until_age=74)


def _plan(cmp, name):
    return next(p for p in cmp["plans"] if p["strategy"] == name)


def test_baseline_has_no_conversions(cmp):
    base = _plan(cmp, "NONE")
    assert base["total_converted"] == 0 and base["ladder"] == []
    # the baseline must equal the plain withdrawal simulator
    plain = w.simulate(_inp(), "TAXABLE_FIRST")
    assert base["lifetime_tax"] == pytest.approx(plain["lifetime_tax"])
    assert base["ending_after_tax"] == pytest.approx(plain["ending_after_tax"])


def test_fill_bracket_tops_out_at_bracket_limit(cmp):
    p = _plan(cmp, "FILL_BRACKET")
    top = w._bracket_top(_inp(bracket_rate=0.12), 2030)
    assert p["total_converted"] > 0
    for row in p["years"]:
        if row["conversion"] > 1 and row["age"] <= 74:
            assert row["ordinary_income"] + row["taxable_social_security"] <= top * 1.005 + 200


def test_aca_mode_keeps_marketplace_years_under_cliff(cmp):
    p = _plan(cmp, "ACA_MAGI")
    target = aca.target_magi(2)
    assert p["total_converted"] > 0
    converting = [row for row in p["years"][:10] if row["conversion"] > 1]
    assert converting and all(row["magi"] <= target + 250 and not row["aca_over_cliff"] for row in converting)


def test_irmaa_mode_keeps_agi_under_first_tier(cmp):
    p = _plan(cmp, "IRMAA")
    limit = r.irmaa_limit("MFJ", 2030)
    assert all(row["agi"] <= limit + 250 for row in p["years"] if row["conversion"] > 1)


def test_conversions_shrink_pretax_and_rmd(cmp):
    base = _plan(cmp, "NONE")
    fill = _plan(cmp, "FILL_BRACKET")
    assert fill["pretax_at_rmd_age"] < base["pretax_at_rmd_age"]
    assert fill["vs_none"]["first_rmd"] < 0
    assert fill["first_rmd"] == pytest.approx(rmd.rmd(fill["pretax_at_rmd_age"], 75))


def test_seasoning_ledger_and_bridge(cmp):
    p = _plan(cmp, "FILL_BRACKET")
    assert all(c["seasoned_year"] == c["year"] + 5 for c in p["ladder"])
    assert sum(c["amount"] for c in p["ladder"]) == pytest.approx(p["total_converted"])
    assert p["bridge_ok"] and p["min_taxable_balance"] >= 0
    # conversion tax is real money: it is paid, not free
    assert p["conversion_tax"] > 0


def test_locked_conversions_are_not_spendable_under_595():
    ledger = [{"year": 2030, "amount": 50_000}, {"year": 2020, "amount": 99_000}]
    assert r._locked(ledger, 2032, 57) == 50_000
    assert r._locked(ledger, 2035, 57) == 0
    assert r._locked(ledger, 2032, 60) == 0


def test_no_pretax_means_no_conversion():
    out = r.simulate(_inp(pretax=0), "FILL_BRACKET")
    assert out["total_converted"] == 0


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        r.simulate(_inp(), "BOGUS")


def test_best_requires_beating_doing_nothing():
    # tiny pre-tax balance already below the bracket floor: nothing worth doing
    cmp = r.compare(_inp(pretax=2_000, taxable=900_000), rmd_start_age=75)
    assert cmp["best"] is None or _plan(cmp, cmp["best"])["lifetime_cost"] < _plan(cmp, "NONE")["lifetime_cost"]


@settings(max_examples=12, deadline=None)
@given(pretax=st.floats(0, 3_000_000), rate=st.sampled_from([0.10, 0.12, 0.22]))
def test_conversion_never_exceeds_balance_and_total_is_nonnegative(pretax, rate):
    inp = _inp(pretax=pretax, end_age=75, spend=[80_000] * 20, ss=[0] * 12 + [50_000] * 8, aca_benchmark=[20_000] * 10 + [0] * 10)
    out = r.simulate(inp, "FILL_BRACKET", bracket_rate=rate, until_age=70)
    assert out["total_converted"] >= 0  # may exceed the starting balance: later years convert growth
    assert all(row["conversion_tax"] >= -1 for row in out["years"])
    assert all(v >= -1e-6 for row in out["years"] for v in row["balances"].values())


def test_tax_table_has_irmaa_tiers():
    assert tax_svc.table(2030)["irmaa"]["tiers"]["MFJ"][0][0] > 200_000


def test_route(client):
    assert client.get("/api/planner/roth?detail=0").status_code == 200
    assert client.get("/api/planner/roth?modes=NOPE").status_code == 400

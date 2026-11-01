import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import db
from models import Account, AllowedPlanMenu, Holding, UserProfile
from services import rebalance as rb

PROXIES = {"US_EQUITY": "VTI", "BOND": "BND", "MONEY_MARKET": None, "INTL_EQUITY": "VXUS"}


def acct(id_, bucket, holds, restricted=False, name=None):
    a = Account(id=id_, name=name or f"A{id_}", institution="X", tax_bucket=bucket, risk_tier="GROWTH", is_restricted_plan=restricted)
    a.holdings = [
        Holding(id=id_ * 100 + i, account_id=id_, symbol=sym, shares=1, market_value=mv, cost_basis_total=basis, asset_class=cls)
        for i, (sym, cls, mv, basis) in enumerate(holds)
    ]
    return a


def test_drift_by_hand():
    d = rb.drift({"US_EQUITY": 70.0, "BOND": 30.0}, {"US_EQUITY": 0.6, "BOND": 0.4})
    rows = {r["asset_class"]: r for r in d["rows"]}
    assert rows["US_EQUITY"]["drift"] == pytest.approx(0.10)
    assert rows["US_EQUITY"]["dollars"] == pytest.approx(-10.0)
    assert rows["BOND"]["dollars"] == pytest.approx(10.0)
    assert d["total_drift"] == pytest.approx(0.10)
    assert d["breached"] is True
    assert rb.drift({"US_EQUITY": 62.0, "BOND": 38.0}, {"US_EQUITY": 0.6, "BOND": 0.4})["breached"] is False


def test_401k_buys_only_menu_funds_and_taxable_sells_lowest_gain_first():
    k = acct(1, "PRE_TAX_401K", [("BIGFUND", "US_EQUITY", 1000.0, 1000.0)], restricted=True)
    menu = [
        AllowedPlanMenu(account_id=1, ticker_or_cusip="BONDX", fund_name="Bond X", asset_class="BOND", expense_ratio=0.004),
        AllowedPlanMenu(account_id=1, ticker_or_cusip="BONDY", fund_name="Bond Y", asset_class="BOND", expense_ratio=0.001),
    ]
    t = acct(2, "TAXABLE_BROKERAGE", [("HIGHGAIN", "US_EQUITY", 1000.0, 200.0), ("LOWGAIN", "US_EQUITY", 1000.0, 950.0)])
    res = rb.plan_trades([t, k], {1: menu}, {"US_EQUITY": -500.0, "BOND": 500.0}, PROXIES)
    tr = res["trades"]
    k_buys = [x for x in tr if x["account_id"] == 1 and x["action"] == "BUY"]
    assert [x["symbol"] for x in k_buys] == ["BONDY"]  # cheapest menu fund
    assert not any(x["account_id"] == 2 for x in tr)  # 401k absorbed it all, tax free
    assert res["unresolved"] == {"sell": {}, "buy": {}}


def test_taxable_picks_low_gain_lot_and_prices_gain():
    t = acct(2, "TAXABLE_BROKERAGE", [("HIGHGAIN", "US_EQUITY", 1000.0, 200.0), ("LOWGAIN", "US_EQUITY", 1000.0, 950.0), ("BND", "BOND", 100.0, 100.0)])
    res = rb.plan_trades([t], {}, {"US_EQUITY": -400.0, "BOND": 400.0}, PROXIES)
    sells = [x for x in res["trades"] if x["action"] == "SELL"]
    assert [s_["symbol"] for s_ in sells] == ["LOWGAIN"]
    assert sells[0]["realized_gain"] == pytest.approx(400 * 50 / 1000)
    buys = [x for x in res["trades"] if x["action"] == "BUY"]
    assert buys[0]["symbol"] == "BND"  # already held, so reuse it


def test_unresolved_when_account_cannot_buy_needed_class():
    k = acct(1, "PRE_TAX_401K", [("BIGFUND", "US_EQUITY", 1000.0, 1000.0)], restricted=True)  # no menu entries
    res = rb.plan_trades([k], {}, {"US_EQUITY": -300.0, "BOND": 300.0}, PROXIES)
    assert res["trades"] == []
    assert res["unresolved"]["sell"]["US_EQUITY"] == pytest.approx(300.0)


@settings(max_examples=60, deadline=None)
@given(
    eq=st.floats(1000, 100000),
    bd=st.floats(1000, 100000),
    mm=st.floats(0, 50000),
    w_eq=st.floats(0.05, 0.9),
    w_mm=st.floats(0, 0.2),
    split=st.floats(0.1, 0.9),
)
def test_trades_net_to_zero_per_account_and_never_increase_drift(eq, bd, mm, w_eq, w_mm, split):
    target = {"US_EQUITY": w_eq, "MONEY_MARKET": w_mm, "BOND": 1 - w_eq - w_mm}
    k = acct(1, "ROTH", [("E1", "US_EQUITY", eq * split, eq * split * 0.5), ("B1", "BOND", bd * split, bd * split)])
    t = acct(
        2,
        "TAXABLE_BROKERAGE",
        [("E2", "US_EQUITY", eq * (1 - split), eq * (1 - split) * 0.7), ("B2", "BOND", bd * (1 - split), bd * (1 - split)), ("SPAXX", "MONEY_MARKET", mm, mm)],
    )
    holds = k.holdings + t.holdings
    values = rb.class_values(holds)
    d = rb.drift(values, target)
    deltas = {r["asset_class"]: r["dollars"] for r in d["rows"]}
    res = rb.plan_trades([k, t], {}, deltas, PROXIES)
    for aid in (1, 2):
        net = sum((x["amount"] if x["action"] == "BUY" else -x["amount"]) for x in res["trades"] if x["account_id"] == aid)
        assert net == pytest.approx(0, abs=1e-6)
    after = rb.drift(rb.post_trade_values(values, res["trades"]), target)
    assert after["total_drift"] <= d["total_drift"] + 1e-9
    assert all(x["realized_gain"] == 0 for x in res["trades"] if x["tax_bucket"] != "TAXABLE_BROKERAGE")


def test_asset_location_flags_bonds_in_taxable():
    t = acct(2, "TAXABLE_BROKERAGE", [("BND", "BOND", 10000.0, 10000.0)])
    k = acct(1, "PRE_TAX_401K", [("VTI", "US_EQUITY", 10000.0, 10000.0)])
    p = UserProfile(annual_income=100000, tax_filing_status="SINGLE")
    out = rb.asset_location([t, k], p)
    bonds = next(x for x in out["suggestions"] if x["symbol"] == "BND")
    assert bonds["to_bucket"] == "PRE_TAX_401K"
    assert bonds["est_annual_tax_drag"] == pytest.approx(10000 * 0.04 * out["marginal_rate"])
    assert 0.2 < out["marginal_rate"] < 0.3  # 22–24% bracket at 100k single
    eq = [x for x in out["suggestions"] if x["symbol"] == "VTI"]
    assert eq and eq[0]["to_bucket"] == "TAXABLE_BROKERAGE"


def test_endpoint_without_and_with_target(client, app):
    j = client.get("/api/rebalance").get_json()
    assert j["has_target"] is False and j["notes"]
    assert client.get("/api/rebalance?threshold=5").status_code == 400
    with app.app_context():
        s = db.session()
        a = Account(name="Brokerage", institution="Fidelity", tax_bucket="TAXABLE_BROKERAGE", risk_tier="GROWTH")
        s.add(a)
        s.flush()
        s.add_all(
            [
                Holding(account_id=a.id, symbol="VTI", shares=1, market_value=8000.0, cost_basis_total=4000.0, asset_class="US_EQUITY"),
                Holding(account_id=a.id, symbol="BND", shares=1, market_value=2000.0, cost_basis_total=2000.0, asset_class="BOND"),
            ]
        )
        s.commit()
    assert client.put("/api/profile", json={"target_allocation": {"US_EQUITY": 0.6, "BOND": 0.4}, "annual_income": 200000}).status_code == 200
    j = client.get("/api/rebalance").get_json()
    assert j["drift"]["breached"] is True
    sells = [t for t in j["trades"] if t["action"] == "SELL"]
    assert sells[0]["amount"] == pytest.approx(2000.0) and sells[0]["realized_gain"] == pytest.approx(1000.0)
    assert j["est_tax"] > 0
    assert j["after"]["total_drift"] == pytest.approx(0, abs=1e-9)


def test_scheduler_alert_fires_only_when_breached(app, monkeypatch):
    from services import notifier, scheduler

    sent = []
    monkeypatch.setattr(notifier, "notify", lambda *a, **k: sent.append(a))
    with app.app_context():
        s = db.session()
        a = Account(name="B", institution="X", tax_bucket="TAXABLE_BROKERAGE", risk_tier="GROWTH")
        s.add(a)
        s.flush()
        s.add_all(
            [
                Holding(account_id=a.id, symbol="VTI", shares=1, market_value=80.0, asset_class="US_EQUITY"),
                Holding(account_id=a.id, symbol="BND", shares=1, market_value=20.0, asset_class="BOND"),
            ]
        )
        s.commit()
        p = UserProfile(target_allocation={})
        scheduler._rebalance_alert(s, p)
        assert sent == []  # no target
        p.target_allocation = {"US_EQUITY": 0.8, "BOND": 0.2}
        scheduler._rebalance_alert(s, p)
        assert sent == []  # on target
        p.target_allocation = {"US_EQUITY": 0.5, "BOND": 0.5}
        scheduler._rebalance_alert(s, p)
        assert len(sent) == 1 and sent[0][0] == "Rebalance needed"

import json
from pathlib import Path

import numpy as np
import pytest

import db
from models import Account, Holding
from services import risk

GOLDEN = json.loads((Path(__file__).parent / "golden" / "risk_two_asset.json").read_text())


def test_golden_two_asset_portfolio():
    """Expected values were computed independently with the stdlib (sample covariance, linear-interpolated 5th percentile)."""
    a, b = np.array(GOLDEN["A"]), np.array(GOLDEN["B"])
    w = dict(zip(["A", "B"], GOLDEN["weights"], strict=True))
    port = risk.portfolio_returns({"A": a, "B": b}, w)
    e = GOLDEN["expected"]
    s = risk.stats(port, 100000.0, 0.95)
    assert s["volatility"] == pytest.approx(e["volatility"], rel=1e-9)
    assert s["max_drawdown"] == pytest.approx(e["max_drawdown"], rel=1e-9)
    assert s["var_1d"] == pytest.approx(e["var_1d"], rel=1e-9)
    assert s["cvar_1d"] == pytest.approx(e["cvar_1d"], rel=1e-9)
    assert s["var_1d_dollars"] == pytest.approx(e["var_1d"] * 100000)
    cov = np.cov(np.vstack([a, b]), ddof=1)
    rc = risk.risk_contribution(np.array(GOLDEN["weights"]), cov)
    assert rc.tolist() == pytest.approx(e["risk_share"], rel=1e-9)
    assert rc.sum() == pytest.approx(1.0)
    from services import quant_engine as qe

    assert qe.correlation_matrix({"A": a, "B": b})["A"]["B"] == pytest.approx(e["correlation"], rel=1e-9)


def test_cvar_is_at_least_var_and_hedge_has_negative_contribution():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0004, 0.01, 500)
    s = risk.stats(r, 1.0, 0.95)
    assert s["cvar_1d"] >= s["var_1d"] > 0
    # a position negatively correlated with the rest reduces risk, so it carries a negative share
    cov = np.array([[0.04, -0.01], [-0.01, 0.01]])
    rc = risk.risk_contribution(np.array([0.5, 0.1]), cov)
    assert rc[1] < 0 < rc[0]
    assert rc.sum() == pytest.approx(1.0)
    assert risk.stats(np.array([0.01] * 5), 1.0) == {}  # too short to say anything


def test_stress_uses_historical_years_by_hand():
    out = {s["id"]: s for s in risk.stress({"US_EQUITY": 60000.0, "BOND": 30000.0, "MONEY_MARKET": 10000.0, "INDIVIDUAL_STOCK": 10000.0})}
    gfc = out["gfc"]  # 2008: stocks -36.5523%, bonds +20.1013%, bills +1.4%
    assert gfc["by_class"]["US_EQUITY"]["change"] == pytest.approx(60000 * -0.365523)
    assert gfc["by_class"]["BOND"]["change"] == pytest.approx(30000 * 0.201013)
    assert gfc["by_class"]["MONEY_MARKET"]["change"] == pytest.approx(10000 * 0.014)
    assert gfc["by_class"]["INDIVIDUAL_STOCK"]["return"] == pytest.approx(-0.365523 * 1.3)
    assert gfc["portfolio_return"] == pytest.approx(gfc["portfolio_change"] / 110000)
    # 2022: stocks and bonds both fell, so bonds were no hedge
    r22 = out["rates_2022"]
    assert r22["by_class"]["BOND"]["return"] < 0 and r22["by_class"]["US_EQUITY"]["return"] < 0
    # dot-com compounds three years
    d = out["dotcom"]["benchmark"]["stocks"]
    assert d == pytest.approx((1 - 0.090318) * (1 - 0.118498) * (1 - 0.21966) - 1, rel=1e-4)


def test_stress_caps_loss_at_total_for_leveraged_sensitivity():
    out = risk.stress({"INDIVIDUAL_STOCK": 100.0}, betas={"INDIVIDUAL_STOCK": 5.0})
    assert min(s["by_class"]["INDIVIDUAL_STOCK"]["return"] for s in out) >= -1.0


def _closes(seed, n=300, drift=0.0004, vol=0.01):
    r = np.random.default_rng(seed).normal(drift, vol, n)
    return list(100 * np.cumprod(1 + r))


def test_report_endpoint_with_cash_proxy_and_unpriced(client, app, monkeypatch):
    from services import market_data

    data = {"VTI": _closes(1), "SPY": _closes(1), "BND": _closes(2, vol=0.003), "VGT": _closes(3, vol=0.014)}

    def fake(sym, *a, **k):
        if sym not in data:
            raise RuntimeError("no data")
        return data[sym]

    monkeypatch.setattr(market_data, "get_closes", fake)
    with app.app_context():
        s = db.session()
        a = Account(name="B", institution="X", tax_bucket="TAXABLE_BROKERAGE", risk_tier="GROWTH")
        s.add(a)
        s.flush()
        s.add_all(
            [
                Holding(account_id=a.id, symbol="VTI", shares=1, market_value=50000.0, asset_class="US_EQUITY"),
                Holding(account_id=a.id, symbol="VGT", shares=1, market_value=20000.0, asset_class="SECTOR_ETF"),
                Holding(account_id=a.id, symbol="PLANFUND", shares=1, market_value=20000.0, asset_class="BOND", proxy_ticker="BND"),
                Holding(account_id=a.id, symbol="WEIRD", shares=1, market_value=5000.0, asset_class="INTL_EQUITY", proxy_ticker="NOPE"),
                Holding(account_id=a.id, symbol="SPAXX", shares=1, market_value=5000.0, asset_class="MONEY_MARKET"),
            ]
        )
        s.commit()
    j = client.get("/api/portfolio/risk").get_json()
    assert j["total"] == pytest.approx(100000)
    assert j["coverage"]["proxied"] == ["PLANFUND via BND"] and j["coverage"]["cash_pct"] == pytest.approx(0.05)
    assert j["coverage"]["unpriced"] == ["WEIRD"] and j["coverage"]["priced_pct"] == pytest.approx(0.95)
    assert 0 < j["risk"]["volatility"] < 0.3 and j["risk"]["var_1d_dollars"] > 0
    assert j["risk"]["beta"] is not None
    assert sum(c["risk_share"] for c in j["contribution"]) == pytest.approx(1.0)
    assert j["contribution"][0]["symbol"] == "VTI"
    assert set(j["correlation"]) == {"VTI", "VGT", "PLANFUND"}
    assert len(j["stress"]) == 4


def test_report_empty_and_no_prices(client, app, monkeypatch):
    assert client.get("/api/portfolio/risk").get_json()["notes"] == ["No holdings yet."]
    from services import market_data

    monkeypatch.setattr(market_data, "get_closes", lambda *a, **k: [])
    with app.app_context():
        s = db.session()
        a = Account(name="B", institution="X", tax_bucket="TAXABLE_BROKERAGE", risk_tier="GROWTH")
        s.add(a)
        s.flush()
        s.add(Holding(account_id=a.id, symbol="VTI", shares=1, market_value=1000.0, asset_class="US_EQUITY"))
        s.commit()
    j = client.get("/api/portfolio/risk").get_json()
    assert "risk" not in j and len(j["stress"]) == 4 and "stress tests" in j["notes"][0]

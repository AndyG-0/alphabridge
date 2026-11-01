import pytest
from hypothesis import given
from hypothesis import strategies as st

import db
from models import Account, Holding, MarketCache
from services import market_data as md
from services import xray

STOCK = {"sector": "Technology", "country": "United States", "market_cap": 3e12}


def H(sym, ac, value, ticker=None):
    return {"symbol": sym, "ticker": ticker or sym, "asset_class": ac, "value": value}


def test_known_answer_stock_fund_cash():
    holdings = [H("NVDA", "INDIVIDUAL_STOCK", 200), H("VOO", "US_EQUITY", 600), H("SPAXX", "MONEY_MARKET", 200)]
    lt = {"VOO": {"top_holdings": {"NVDA": 0.10, "AAPL": 0.20}, "sectors": {"technology": 0.5, "healthcare": 0.5}, "asset_mix": {}}}
    r = xray.build_xray(holdings, lt, {"NVDA": STOCK}, employer_symbol="nvda")
    assert r["total"] == 1000
    assert r["asset_class"] == {"Stocks": pytest.approx(0.8), "Cash": pytest.approx(0.2)}
    # sector: NVDA 200 tech + VOO 600 split 300/300 + cash 200
    assert r["sector"]["Technology"] == pytest.approx(0.5)
    assert r["sector"]["Healthcare"] == pytest.approx(0.3)
    assert r["sector"]["Cash"] == pytest.approx(0.2)
    # NVDA direct 200 + 10% of 600 = 260 => 26%; employer weight matches
    names = {n["symbol"]: n["weight"] for n in r["concentration"]["top_names"]}
    assert names["NVDA"] == pytest.approx(0.26)
    assert r["concentration"]["employer_weight"] == pytest.approx(0.26)
    assert any("Employer stock NVDA" in w for w in r["concentration"]["warnings"])
    assert r["region"]["US"] == pytest.approx(1.0)  # VOO fallback is 100% US, cash is US, NVDA is US
    assert r["market_cap"]["Large"] == pytest.approx(0.985)  # (200 NVDA + 600 x 0.98 VOO) / 800 equity dollars
    assert r["market_cap"]["Mid"] == pytest.approx(0.015)


def test_missing_lookthrough_is_unclassified_and_reported():
    r = xray.build_xray([H("ZZZZ", "US_EQUITY", 100)], {"ZZZZ": {"top_holdings": {}, "sectors": {}, "asset_mix": {}}}, {})
    assert r["sector"] == {"Unclassified": pytest.approx(1.0)}
    assert r["region"] == {"Unclassified": pytest.approx(1.0)}
    assert r["coverage"][0]["symbol"] == "ZZZZ" and "region" in r["coverage"][0]["missing"]


def test_bond_fund_has_no_market_cap_and_no_sector_gap():
    r = xray.build_xray([H("BND", "BOND", 100)], {}, {})
    assert r["asset_class"] == {"Bonds": pytest.approx(1.0)}
    assert r["sector"] == {"Bonds": pytest.approx(1.0)}
    assert r["market_cap"] == {}


def test_overlap_is_min_of_shared_weights():
    m = xray.overlap_matrix({"A": {"X": 0.10, "Y": 0.05}, "B": {"X": 0.04, "Z": 0.2}, "C": {"Q": 0.1}})
    ab = next(o for o in m if (o["a"], o["b"]) == ("A", "B"))
    assert ab["overlap"] == pytest.approx(0.04) and ab["shared"] == 1
    assert len(m) == 3


def test_region_and_cap_tiers():
    assert xray.region_of("United States") == "US"
    assert xray.region_of("India") == "Emerging"
    assert xray.region_of("Germany") == "Developed ex-US"
    assert xray.region_of(None) == "Unclassified"
    assert [xray.cap_tier(x) for x in (5e11, 5e9, 1e9, None)] == ["Large", "Mid", "Small", "Unclassified"]


@given(st.lists(st.tuples(st.sampled_from(["VTI", "BND", "NVDA", "SPAXX", "XXXX"]), st.floats(1, 1e6)), min_size=1, max_size=6))
def test_dimensions_sum_to_one(rows):
    ac = {"VTI": "US_EQUITY", "BND": "BOND", "NVDA": "INDIVIDUAL_STOCK", "SPAXX": "MONEY_MARKET", "XXXX": "US_EQUITY"}
    r = xray.build_xray([H(s, ac[s], v) for s, v in rows], {}, {"NVDA": STOCK})
    for dim in ("asset_class", "sector", "region"):
        assert sum(r[dim].values()) == pytest.approx(1.0)


class FakeFunds:
    def __init__(self):
        import pandas as pd

        self.sector_weightings = {"technology": 0.6, "healthcare": 0.4}
        self.asset_classes = {"cashPosition": 0.01, "stockPosition": 0.99, "bondPosition": 0, "otherPosition": 0}
        self.top_holdings = pd.DataFrame({"Holding Percent": [0.07]}, index=["AAPL"])


@pytest.fixture
def fake_yf(monkeypatch):
    import types

    import yfinance

    calls = {"n": 0, "fail": False}

    class T:
        def __init__(self, sym):
            calls["n"] += 1
            if calls["fail"]:
                raise RuntimeError("down")
            self.funds_data = FakeFunds()

    monkeypatch.setattr(yfinance, "Ticker", T)
    monkeypatch.setattr(md, "_throttle", lambda *a, **k: None)
    return types.SimpleNamespace(calls=calls)


def test_fund_lookthrough_parses_and_caches(app, fake_yf):
    with app.app_context():
        a = md.get_fund_lookthrough("FOO")
        assert a["top_holdings"] == {"AAPL": 0.07} and a["sectors"]["technology"] == 0.6
        assert a["asset_mix"]["Stocks"] == 0.99
        md.get_fund_lookthrough("FOO")
        assert fake_yf.calls["n"] == 1


def test_fund_lookthrough_failure_retried_after_miss_ttl(app, fake_yf):
    from datetime import UTC, datetime, timedelta

    with app.app_context():
        fake_yf.calls["fail"] = True
        assert not any(md.get_fund_lookthrough("BAR").values())
        md.get_fund_lookthrough("BAR")
        assert fake_yf.calls["n"] == 1  # within the hour: no retry
        row = db.session().get(MarketCache, "xray:fund:BAR")
        row.fetched_at = datetime.now(UTC) - timedelta(hours=2)
        db.session().commit()
        fake_yf.calls["fail"] = False
        assert md.get_fund_lookthrough("BAR")["top_holdings"] == {"AAPL": 0.07}


def test_xray_route_and_employer_field(client, app, fake_yf):
    with app.app_context():
        s = db.session()
        acct = Account(name="Brokerage", institution="Fidelity", tax_bucket="TAXABLE")
        s.add(acct)
        s.flush()
        s.add(Holding(account_id=acct.id, symbol="VTI", shares=10, market_value=1000, current_price=100, asset_class="US_EQUITY"))
        s.commit()
    assert client.put("/api/profile", json={"employer_symbol": "AAPL"}).status_code == 200
    r = client.get("/api/portfolio/xray")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 1000
    assert body["concentration"]["employer_weight"] == pytest.approx(0.07)
    assert body["region"]["US"] == pytest.approx(1.0)  # from the static fallback
    assert client.put("/api/profile", json={"employer_symbol": "bad sym!"}).status_code == 400

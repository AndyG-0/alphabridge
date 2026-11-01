import json

import pytest

import db
from models import Account, Holding
from services import research_pipeline as rp

GOOD = {
    "revenue_growth": 0.25,
    "debt_to_equity": 0.4,
    "free_cash_flow": 1e9,
    "margin_now": 0.30,
    "margin_prev": 0.25,
    "operating_margin": 0.3,
    "trailing_pe": 30,
    "sector": "Technology",
    "name": "X",
}


def closes(n=250, start=100.0, step=0.2):
    return [start + i * step for i in range(n)]


def test_screen_pass_and_fail():
    ok = rp.screen_one(GOOD, closes())
    assert ok["passed"] and ok["score"] > 60
    bad = rp.screen_one({**GOOD, "debt_to_equity": 2.5}, closes())
    assert not bad["passed"] and not bad["checks"]["leverage"]
    assert not rp.screen_one({**GOOD, "revenue_growth": 0.05}, closes())["passed"]
    assert not rp.screen_one({**GOOD, "margin_now": 0.2}, closes())["passed"]
    assert not rp.screen_one({**GOOD, "free_cash_flow": -1}, closes())["passed"]


def test_screen_handles_missing_data():
    m = rp.screen_one({}, [])
    assert not m["passed"] and m["score"] >= 0


def test_macro_overlay_reorders():
    cands = [{"symbol": "A", "score": 80, "sector": "Energy"}, {"symbol": "B", "score": 80, "sector": "Technology"}]
    sectors = [{"etf": "XLK", "score": 0.1}, {"etf": "XLE", "score": -0.1}]
    out = rp.apply_macro_overlay(cands, sectors)
    assert out[0]["symbol"] == "B"


def test_concentration_warnings():
    before = {"sectors": {"Technology": 0.25}, "names": {}}
    after = {"sectors": {"Technology": 0.35}, "names": {"NVDA": 0.12}}
    w = rp.concentration_warnings(before, after, 0.30)
    assert len(w) == 2
    assert rp.concentration_warnings(after, after, 0.30) == []


@pytest.fixture
def portfolio(app, monkeypatch):
    with app.app_context():
        s = db.session()
        a = Account(name="Brokerage")
        s.add(a)
        s.flush()
        s.add(Holding(account_id=a.id, symbol="MSFT", shares=1, market_value=30000, asset_class="INDIVIDUAL_STOCK"))
        s.add(Holding(account_id=a.id, symbol="SPAXX", shares=1, market_value=70000, asset_class="MONEY_MARKET"))
        s.commit()
        monkeypatch.setattr(rp, "_safe_fund", lambda sym: {"sector": "Technology"})
        yield


def test_exposure_and_deep_dive_guardrail(app, portfolio):
    with app.app_context():
        ex = rp.portfolio_exposure()
        assert ex["sectors"]["Technology"] == pytest.approx(0.3)

        def fake_llm(sys, usr):
            assert "risk_factors_excerpt" in json.loads(usr)
            return rp.Thesis(
                valuation_grade="B", growth_grade="A", moat_grade="B", bull_case_md="bull", bear_case_md="bear", recommended_action="BUY_SATELLITE"
            )

        def fake_edgar(sym, ident):
            return {
                "citation": {"form": "10-K", "filing_date": "2025-01-01", "accession": "x", "url": "u"},
                "risk_factors": "rf",
                "mdna": "md",
                "financials": "",
            }

        rep = rp.deep_dive("NVDA", "ON_DEMAND", "", "id", metrics={"score": 80}, llm=fake_llm, edgar=fake_edgar)
        # Technology already at 30% == limit and NVDA adds more -> guardrail downgrades BUY
        assert rep.recommended_action == "WATCHLIST"
        assert "exposure" in rep.portfolio_fit_notes


def test_screen_breakdown_sums_to_score():
    m = rp.screen_one(GOOD, closes())
    assert sum(v["points"] for v in m["score_breakdown"].values()) == pytest.approx(m["score"], abs=0.1)


def test_symbol_detail(app, portfolio, monkeypatch):
    monkeypatch.setattr(rp.md, "get_fundamentals", lambda s: {**GOOD, "shares_outstanding": 1e9})
    monkeypatch.setattr(rp.md, "get_closes", lambda s, p="2y": closes())
    with app.app_context():
        d = rp.symbol_detail("nvda")
        assert d["symbol"] == "NVDA" and d["dcf_value"] > 0
        assert d["technicals"]["high_52w"] >= d["technicals"]["low_52w"]
        assert 40 < len(d["price_series"]) <= 60 and d["report"] is None
        monkeypatch.setattr(rp.md, "get_closes", lambda s, p="2y": [])
        with pytest.raises(LookupError):
            rp.symbol_detail("ZZZZ")


def test_symbol_route(client, monkeypatch):
    monkeypatch.setattr(rp, "symbol_detail", lambda s: (_ for _ in ()).throw(LookupError("none")))
    assert client.get("/api/research/symbol/ZZZZ").status_code == 404
    assert client.get("/api/research/symbol/bad$sym").status_code == 400

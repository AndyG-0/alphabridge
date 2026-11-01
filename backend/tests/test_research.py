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


# ---- I7: DCF grid, signals, narrative check, cache and budget, watchlist/thesis ------------------------------------
from datetime import date  # noqa: E402

from services import quant_engine as qe  # noqa: E402
from services import research_extras as rx  # noqa: E402


def test_dcf_grid_matches_point_estimates_and_is_monotone():
    g = qe.dcf_grid(100.0, 0.10, 0.10, [-0.02, 0.0, 0.02], [-0.01, 0.0, 0.01], shares=10)
    base = qe.simple_dcf(100.0, 0.10, 0.10, shares=10)
    assert g["base"] == pytest.approx(base)
    assert g["rows"][1]["values"][1] == pytest.approx(base)
    # more growth -> more value (down a column); higher discount -> less value (across a row)
    assert g["rows"][2]["values"][1] > g["rows"][1]["values"][1] > g["rows"][0]["values"][1]
    assert g["rows"][1]["values"][0] > g["rows"][1]["values"][1] > g["rows"][1]["values"][2]
    assert g["low"] == g["rows"][0]["values"][2] and g["high"] == g["rows"][2]["values"][0]


def test_dcf_grid_blank_when_discount_not_above_terminal():
    g = qe.dcf_grid(100.0, 0.05, 0.03, [0.0], [-0.01, 0.0], terminal_growth=0.025)
    assert g["rows"][0]["values"][0] is None and g["rows"][0]["values"][1] is not None


def test_dcf_sensitivity_none_without_fcf():
    assert rx.dcf_sensitivity(-5, 10, 0.1, 50) is None
    assert rx.dcf_sensitivity(100, None, 0.1, 50) is None
    out = rx.dcf_sensitivity(100, 10, 0.5, 50)  # growth capped at 30%
    assert out["rows"][2]["growth"] == pytest.approx(0.30)


def test_insider_signal_counts_only_open_market_in_window():
    today = date(2026, 6, 30)
    trades = [
        {"date": "2026-06-01", "insider": "A", "code": "P", "shares": 10000, "price": 20},  # buy 200k
        {"date": "2026-06-10", "insider": "B", "code": "S", "shares": 1000, "price": 20},  # sell 20k
        {"date": "2026-06-11", "insider": "B", "code": "A", "shares": 99999, "price": 20},  # award: ignored
        {"date": "2026-01-01", "insider": "C", "code": "S", "shares": 99999, "price": 20},  # outside window
    ]
    s = rx.insider_signal(trades, today)
    assert s["buy_value"] == 200000 and s["sell_value"] == 20000 and s["net_value"] == 180000
    assert s["signal"] == "BUYING" and s["buyers"] == 1 and s["sellers"] == 1
    assert rx.insider_signal([], today)["signal"] == "NEUTRAL"
    assert rx.insider_signal([{"date": "2026-06-20", "insider": "D", "code": "S", "shares": 10000, "price": 50}], today)["signal"] == "SELLING"


def test_institutional_signal_actions():
    out = rx.institutional_signal({"A": 150, "B": 100, "C": 0, "D": 50, "E": 80}, {"A": 100, "B": 100, "C": 40, "E": 100})
    acts = {r["manager"]: r["action"] for r in out["managers"]}
    assert acts == {"A": "ADDED", "B": "HELD", "C": "EXITED", "D": "NEW", "E": "TRIMMED"}


PAYLOAD = {
    "quant_metrics": {"revenue_growth": 0.26, "trailing_pe": 31.5, "free_cash_flow": 1.2e9, "score": 82},
    "filing": {"form": "10-K"},
    "note": "Revenue $4.5 billion in FY2025",
}


def test_verify_narrative_accepts_supported_numbers():
    text = "Revenue grew 26% with a 31.5x P/E; free cash flow of $1.2B and revenue of $4.5B in 2025."
    assert rx.verify_narrative_numbers(text, PAYLOAD) == []


def test_verify_narrative_flags_invented_numbers():
    bad = rx.verify_narrative_numbers("Margins hit 47% and the stock could reach $250 within 3 years; growth was 26%.", PAYLOAD)
    assert "47%" in bad and "$250" in bad
    assert "26%" not in bad and "3" not in bad  # small integers are ignored


def test_verify_narrative_rounding_and_years():
    assert rx.verify_narrative_numbers("About 26.0% growth and 31x earnings in 2024.", {"g": 0.2604, "pe": 31.2}) == []
    assert rx.verify_narrative_numbers("It grew 30%", {"g": 0.26}) == ["30%"]


def test_token_budget_and_trim():
    b = rx.TokenBudget(100)
    b.spend(60)
    assert b.remaining() == 40
    with pytest.raises(rx.BudgetExceeded):
        b.spend(50)
    assert rx.TokenBudget(0).remaining() is None
    payload = {"quant_metrics": {"x": 1}, "risk_factors_excerpt": "r" * 4000, "mdna_excerpt": "m" * 400, "financial_statements": ""}
    out, cut = rx.fit_to_budget(payload, 500)
    assert cut and rx.est_tokens(json.dumps(out)) <= 520 and out["quant_metrics"] == {"x": 1}
    same, cut2 = rx.fit_to_budget(payload, 100000)
    assert not cut2 and same == payload


def test_check_criteria_and_watch_alerts():
    res = rx.check_criteria(
        [
            {"metric": "revenue_growth", "op": "<", "value": 0.05, "text": "growth stalls"},
            {"metric": "trailing_pe", "op": ">", "value": 40},
            {"metric": "missing", "op": "<", "value": 1},
        ],
        {"revenue_growth": 0.02, "trailing_pe": 31},
    )
    assert [c["triggered"] for c in res] == [True, False, None]
    item = {"symbol": "X", "buy_below": 100, "upside_alert": None}
    assert len(rx.watch_alerts(item, 95, 150, 0.15)) == 2
    assert rx.watch_alerts(item, 120, 130, 0.15) == []
    assert rx.watch_alerts(item, None, 130, 0.15) == []


def _llm_and_edgar(calls):
    def fake_llm(sys, usr):
        calls.append(usr)
        return rp.Thesis(
            valuation_grade="B",
            growth_grade="A",
            moat_grade="B",
            bull_case_md="Growth is 26% and margin 47%",
            bear_case_md="bear",
            recommended_action="WATCHLIST",
        )

    def fake_edgar(sym, ident):
        return {
            "citation": {"form": "10-K", "filing_date": "2025-01-01", "accession": "x", "url": "u"},
            "risk_factors": "rf" * 3000,
            "mdna": "md",
            "financials": "",
        }

    return fake_llm, fake_edgar


def test_deep_dive_caches_flags_unverified_and_respects_budget(app, portfolio, monkeypatch):
    monkeypatch.setattr(rp.md, "get_fundamentals", lambda s: {})
    monkeypatch.setattr(rp.md, "get_closes", lambda s, p="2y": [])
    with app.app_context():
        calls: list[str] = []
        llm, edgar = _llm_and_edgar(calls)
        ins = lambda s, i: [{"date": date.today().isoformat(), "insider": "A", "code": "P", "shares": 10000, "price": 20}]
        r1 = rp.deep_dive("NVDA", "ON_DEMAND", "", "id", metrics={"score": 80, "revenue_growth": 0.26}, llm=llm, edgar=edgar, insiders=ins)
        assert r1.metrics_json["unverified_numbers"] == ["47%"]
        assert r1.metrics_json["insider_activity"]["signal"] == "BUYING"
        assert json.loads(calls[0])["insider_activity"]["buyers"] == 1
        r2 = rp.deep_dive("NVDA", "ON_DEMAND", "", "id", metrics={"score": 80, "revenue_growth": 0.26}, llm=llm, edgar=edgar, insiders=ins)
        assert r2.id == r1.id and len(calls) == 1  # identical inputs: no second LLM call
        r3 = rp.deep_dive("NVDA", "ON_DEMAND", "", "id", metrics={"score": 80, "revenue_growth": 0.26}, llm=llm, edgar=edgar, insiders=ins, force=True)
        assert r3.id != r1.id and len(calls) == 2
        with pytest.raises(rx.BudgetExceeded):
            rp.deep_dive("AMD", "ON_DEMAND", "", "id", metrics={"score": 70}, llm=llm, edgar=edgar, insiders=ins, budget=rx.TokenBudget(1000))
        assert len(calls) == 2
        # a budget just above the output allowance trims the long excerpt but still runs
        r4 = rp.deep_dive(
            "MSFT", "ON_DEMAND", "", "id", metrics={"score": 70}, llm=llm, edgar=edgar, insiders=ins, budget=rx.TokenBudget(rp.THESIS_OUTPUT_TOKENS + 400)
        )
        assert r4.metrics_json["input_truncated"] is True and len(json.loads(calls[-1])["risk_factors_excerpt"]) < 6000


def test_watchlist_theses_routes_and_alert_job(client, app, monkeypatch):
    from services import notifier, research_watch, scheduler

    monkeypatch.setattr(
        research_watch.market_data,
        "get_fundamentals",
        lambda s: {"free_cash_flow": 1e9, "shares_outstanding": 1e9, "revenue_growth": 0.1, "revenue_growth_x": 0},
    )
    monkeypatch.setattr(research_watch.market_data, "get_closes", lambda s, p="1y": [10.0, 11.0, 12.0])
    assert client.post("/api/research/watchlist", json={"symbol": "bad$", "buy_below": 5}).status_code in (400, 422)
    r = client.post("/api/research/watchlist", json={"symbol": "xyz", "buy_below": 12.5})
    assert r.status_code == 201
    w = client.get("/api/research/watchlist").get_json()
    assert w[0]["symbol"] == "XYZ" and w[0]["price"] == 12.0 and any("buy-below" in a for a in w[0]["alerts"])
    bad = client.post("/api/research/theses", json={"symbol": "XYZ", "criteria": [{"metric": "price", "op": "!!", "value": 1}]})
    assert bad.status_code == 400
    ok = client.post(
        "/api/research/theses",
        json={"symbol": "XYZ", "thesis": "cheap compounder", "criteria": [{"metric": "price", "op": ">", "value": 11, "text": "price above 11"}]},
    )
    assert ok.status_code == 201
    t = client.get("/api/research/theses").get_json()
    assert t[0]["broken"][0]["current"] == 12.0

    sent = []
    monkeypatch.setattr(notifier, "notify", lambda *a, **k: sent.append(a) or "x")
    with app.app_context():
        import db

        scheduler._research_alerts(db.session())
        scheduler._research_alerts(db.session())
    assert len(sent) == 1  # alert once a day; thesis flagged once
    assert client.get("/api/research/theses").get_json()[0]["status"] == "INVALIDATED"
    assert client.delete(f"/api/research/watchlist/{w[0]['id']}").status_code == 204
    assert client.delete(f"/api/research/theses/{t[0]['id']}").status_code == 204


def test_dcf_route(client, monkeypatch):
    from services import research_watch

    monkeypatch.setattr(research_watch.market_data, "get_fundamentals", lambda s: {"free_cash_flow": 1e9, "shares_outstanding": 1e9, "revenue_growth": 0.1})
    monkeypatch.setattr(research_watch.market_data, "get_closes", lambda s, p="1y": [10.0])
    d = client.get("/api/research/dcf/abc").get_json()
    assert d["symbol"] == "ABC" and len(d["rows"]) == 5 and d["low"] < d["base"] < d["high"]
    monkeypatch.setattr(research_watch.market_data, "get_fundamentals", lambda s: {})
    assert client.get("/api/research/dcf/abc").status_code == 404
    assert client.get("/api/research/dcf/bad$").status_code == 400

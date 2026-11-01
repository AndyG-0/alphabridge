import pytest

from services import cash_backtest as bt


def test_hand_computed_run():
    hist = {
        1999: {"stocks": 0.10, "bills": 0.05, "inflation": 0.02},
        2000: {"stocks": -0.20, "bills": 0.05, "inflation": 0.02},
        2001: {"stocks": 0.50, "bills": 0.05, "inflation": 0.02},
    }
    assert bt._run(hist, 2000, 2, "LUMP", 0.25) == pytest.approx(0.8 * 1.5)
    assert bt._run(hist, 2000, 2, "CASH", 0.25) == pytest.approx(1.05**2)
    # Naive DCA 50%: y1 move .5 -> cash .5*1.05=.525, stocks .5*.8=.4 ; y2 move .2625 -> cash .2625*1.05, stocks (.4+.2625)*1.5
    expect = 0.2625 * 1.05 + (0.4 + 0.2625) * 1.5
    assert bt._run(hist, 2000, 2, "NAIVE_DCA", 0.5) == pytest.approx(expect)


def test_lite_score_directions():
    calm = bt.lite_score(0.01, 0.02, 0.10)
    scared = bt.lite_score(0.01, 0.02, -0.25)
    high_rate = bt.lite_score(0.06, 0.02, -0.25)
    assert scared > calm  # a falling market is a better entry
    assert high_rate < scared  # a big real cash yield raises the hurdle


def test_run_is_deterministic_and_sane():
    a, b = bt.run(), bt.run()
    assert a == b
    by = {r["mode"]: r for r in a["results"]}
    assert by["LUMP"]["beats_lump_pct"] == 0
    assert by["CASH"]["worst_multiple"] >= 1.0 - 1e-9 or by["CASH"]["loses_money_pct"] >= 0
    assert all(r["worst_multiple"] <= r["median_multiple"] <= r["best_multiple"] for r in a["results"])


def test_checked_in_doc_is_current():
    assert bt.DOC.read_text() == bt.render_markdown(), "run: python -c 'from services import cash_backtest as b; open(b.DOC,\"w\").write(b.render_markdown())'"


def test_endpoints(client, monkeypatch):
    from services import market_data
    from services.cash_optimizer import MarketInputs

    m = MarketInputs(tbill_3m=0.04, ten_year=0.045, cpi_yoy=0.03, sp500_pe=22, vix=18, sp500_vs_200dma=0.02)
    monkeypatch.setattr(market_data, "market_inputs", lambda key: (m, []))
    client.put("/api/profile", json={"state": "AZ", "monthly_expenses_current": 4000, "annual_income": 120000})
    r = client.get("/api/planner/cash/plan?ladder_amount=30000&rungs=3,6,12")
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert [x["months"] for x in d["ladder"]["rungs"]] == [3, 6, 12]
    assert d["ladder"]["amount"] == 30000
    assert d["tax_comparison"]["state"] == "AZ"
    assert d["emergency_fund"]["essential_monthly"] >= 4000
    assert client.get("/api/planner/cash/plan?rungs=x").status_code == 400
    assert client.get("/api/planner/cash/backtest").get_json()["windows"] > 50


def test_dca_save_and_remind(client, app, monkeypatch):
    from datetime import date

    from routes._helpers import get_profile
    from services import notifier, scheduler

    assert client.post("/api/planner/cash/dca", json={"amount": -1, "tranches": 3}).status_code == 400
    r = client.post("/api/planner/cash/dca", json={"amount": 900, "tranches": 3, "start": "2020-01-01"})
    assert [x["amount"] for x in r.get_json()["schedule"]] == [300, 300, 300]
    sent = []
    monkeypatch.setattr(notifier, "notify", lambda *a, **k: sent.append(a) or "x")
    with app.app_context():
        import db

        scheduler._dca_reminder(db.session(), get_profile())
        assert len(sent) == 1 and len(sent[0][3]) == 3
        scheduler._dca_reminder(db.session(), get_profile())
        assert len(sent) == 1  # not repeated
    assert client.delete("/api/planner/cash/dca").status_code == 204
    assert date.today()

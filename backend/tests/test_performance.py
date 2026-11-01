from datetime import date

import pytest

from models import Account, Holding, NetWorthSnapshot
from services import performance as perf


def test_twr_chains_subperiods_and_ignores_flows():
    pts = [(date(2025, 1, 1), 100.0), (date(2025, 2, 1), 110.0), (date(2025, 3, 1), 176.0)]
    # a 50 deposit on Feb 20: period 2 return = (176-50)/110-1
    t = perf.twr(pts, [(date(2025, 2, 20), 50.0)])
    assert t["periods"][0]["return"] == pytest.approx(0.10)
    assert t["periods"][1]["return"] == pytest.approx(126 / 110 - 1)
    assert t["total"] == pytest.approx(1.10 * 126 / 110 - 1)  # = 26%
    assert t["annualized"] is None  # < 1 year


def test_twr_annualizes_over_a_year():
    t = perf.twr([(date(2024, 1, 1), 100.0), (date(2026, 1, 1), 121.0)], [])
    assert t["total"] == pytest.approx(0.21)
    assert t["annualized"] == pytest.approx(0.21**0 * (1.21 ** (365 / 731)) - 1)


def test_xirr_known_value():
    r = perf.xirr([(date(2024, 1, 1), -100.0), (date(2025, 1, 1), 110.0)])
    assert r == pytest.approx(0.10, abs=1e-3)  # 366 days in 2024 -> slightly under 10%
    assert perf.xirr([(date(2024, 1, 1), -100.0)]) is None
    assert perf.xirr([(date(2024, 1, 1), 100.0), (date(2025, 1, 1), 110.0)]) is None


def test_mwr_with_deposit_differs_from_twr():
    pts = [(date(2024, 1, 1), 100.0), (date(2025, 1, 1), 230.0)]
    flows = [(date(2024, 7, 1), 100.0)]
    m = perf.mwr(pts, flows)
    assert m is not None and 0.1 < m < 0.4
    assert perf.twr(pts, flows)["total"] == pytest.approx(0.30)


def test_window_return_and_blend():
    closes = [100.0 + i for i in range(253)]  # ends at 352 today
    r = perf.window_return(closes, date(2025, 1, 1), date(2026, 1, 1), date(2026, 1, 1), 252)
    assert r == pytest.approx(352 / 100 - 1, rel=0.05)
    assert perf.window_return(closes, date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1)) is None
    assert perf.blend({"A": 0.6, "B": 0.4}, {"A": 0.10, "B": 0.05}) == pytest.approx(0.08)
    assert perf.blend({"A": 1.0}, {"A": None}) is None


def test_income_calendar_and_yield_normalization():
    hs = [
        Holding(account_id=1, symbol="SPAXX", shares=1, market_value=12000.0, asset_class="MONEY_MARKET"),
        Holding(account_id=1, symbol="VTI", shares=1, market_value=10000.0, asset_class="US_EQUITY"),
    ]
    c = perf.income_calendar(hs, {"VTI": 0.02}, 0.05)
    assert c["annual_income"] == pytest.approx(600 + 200)
    assert c["months"][0]["amount"] == pytest.approx(50)  # Jan: MMF only
    assert c["months"][2]["amount"] == pytest.approx(50 + 50)  # Mar: MMF + quarterly
    assert perf.normalize_yield(1.5) == pytest.approx(0.015)
    assert perf.normalize_yield(0.015) == 0.015


def test_holding_fees_prefers_menu():
    hs = [
        Holding(account_id=1, symbol="VTI", shares=1, market_value=10000.0, asset_class="US_EQUITY"),
        Holding(account_id=2, symbol="VTI", shares=1, market_value=10000.0, asset_class="US_EQUITY"),
        Holding(account_id=1, symbol="AAPL", shares=1, market_value=5000.0, asset_class="INDIVIDUAL_STOCK"),
        Holding(account_id=1, symbol="ZZZZ", shares=1, market_value=5000.0, asset_class="US_EQUITY"),
    ]
    r = perf.holding_fees(hs, {(2, "VTI"): 0.01}, {"VTI": 0.0003})
    assert r["annual_fee"] == pytest.approx(10000 * 0.0003 + 10000 * 0.01)
    assert r["unknown"] == ["ZZZZ"]
    assert r["covered_pct"] == pytest.approx(25000 / 30000)


def test_month_end_flows():
    f = perf.month_end_flows(date(2025, 1, 15), date(2025, 4, 30), 100.0)
    assert [d for d, _ in f] == [date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)]


def test_cashflow_routes_and_performance_endpoint(client, app, monkeypatch):
    import db

    r = client.post("/api/cashflows", json={"on": "2025-02-01", "amount": 500, "note": "bonus"})
    assert r.status_code == 201
    assert client.post("/api/cashflows", json={"on": "2025-02-01", "amount": 0}).status_code == 400
    assert len(client.get("/api/cashflows").get_json()) == 1

    with app.app_context():
        s = db.session()
        s.add(Account(name="B", institution="Fidelity", tax_bucket="TAXABLE", risk_tier="GROWTH"))
        s.flush()
        for d, v in ((date(2025, 1, 1), 1000.0), (date(2025, 3, 1), 1650.0)):
            from datetime import datetime

            s.add(NetWorthSnapshot(taken_at=datetime(d.year, d.month, d.day, 22), total=v, safe_core=0, satellite=v, dry_powder=0, liabilities=0))
        s.commit()
    from services import market_data

    monkeypatch.setattr(market_data, "get_closes", lambda sym, *a, **k: [100.0 + i * 0.1 for i in range(900)])
    monkeypatch.setattr(market_data, "get_fundamentals", lambda sym, *a, **k: {"dividend_yield": 0.01})
    j = client.get("/api/performance").get_json()
    assert j["flow_mode"] == "recorded"
    assert j["returns"]["twr"]["total"] == pytest.approx((1650 - 500) / 1000 - 1)
    assert j["benchmarks"]["market"]["return"] is not None

    assert client.delete(f"/api/cashflows/{r.get_json()['id']}").status_code == 204
    assert client.get("/api/performance").get_json()["flow_mode"] == "none"


def test_report_without_history(client):
    j = client.get("/api/performance").get_json()
    assert j["returns"] is None and j["notes"]

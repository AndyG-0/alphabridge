from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar

import pandas as pd
import pytest
import responses

import db
from models import MarketCache
from services import market_data as md


@pytest.fixture(autouse=True)
def _ctx(app, monkeypatch):
    monkeypatch.setattr(md, "_throttle", lambda *a, **k: None)
    with app.app_context():
        yield


def test_cache_roundtrip_and_ttl():
    assert md.cache_get("k", 60) is None
    md.cache_set("k", [1, 2])
    assert md.cache_get("k", 60) == [1, 2]
    md.cache_set("k", [3])  # update in place
    assert md.cache_get("k", 60) == [3]
    row = db.session().get(MarketCache, "k")
    row.fetched_at = datetime.now(UTC) - timedelta(seconds=120)
    db.session().commit()
    assert md.cache_get("k", 60) is None and md.cache_get("k", 600) == [3]


class FakeTicker:
    calls = 0

    def __init__(self, sym):
        self.sym = sym
        type(self).calls += 1

    def history(self, period, auto_adjust):
        return pd.DataFrame({"Close": [1.0, float("nan"), 2.5]})

    info: ClassVar[dict] = {"shortName": "Acme", "debtToEquity": 150.0, "trailingPE": 20.0, "sector": "Tech"}
    income_stmt = pd.DataFrame({"a": [100.0, 20.0], "b": [80.0, 8.0]}, index=["Total Revenue", "Operating Income"])


@pytest.fixture
def fake_yf(monkeypatch):
    import yfinance

    FakeTicker.calls = 0
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    return FakeTicker


def test_get_closes_drops_nan_and_caches(fake_yf):
    assert md.get_closes("AAA") == [1.0, 2.5]
    assert md.get_closes("AAA") == [1.0, 2.5]
    assert fake_yf.calls == 1
    assert md.get_quote("AAA")["symbol"] == "AAA"


def test_get_fundamentals_normalises(fake_yf):
    f = md.get_fundamentals("AAA")
    assert f["name"] == "Acme" and f["debt_to_equity"] == 1.5 and f["sector"] == "Tech"
    assert f["margin_now"] == pytest.approx(0.2) and f["margin_prev"] == pytest.approx(0.1)
    md.get_fundamentals("AAA")
    assert fake_yf.calls == 1


def test_etf_holdings_failure_is_empty_and_cached(monkeypatch):
    import yfinance

    def boom(sym):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(yfinance, "Ticker", boom)
    assert md.get_etf_holdings("VTI") == {}
    assert md.cache_get("etfh:VTI", 60) == {}


@responses.activate
def test_fred_latest_skips_missing_values():
    responses.get(
        "https://api.stlouisfed.org/fred/series/observations",
        json={"observations": [{"value": "."}, {"value": "5.25"}, {"value": "5.0"}, {"value": ""}, {"value": "4.9"}]},
    )
    assert md._fred_latest("DTB3", "key") == [5.25]
    assert md._fred_latest("DTB3", "key", 3) == [5.25, 5.0, 4.9]
    assert "api_key=key" in responses.calls[0].request.url


@responses.activate
def test_fred_latest_http_error_raises():
    responses.get("https://api.stlouisfed.org/fred/series/observations", status=500)
    with pytest.raises(Exception, match="500"):
        md._fred_latest("DTB3", "key")


def _stub_closes(monkeypatch, spy):
    table = {"^IRX": [4.0], "^TNX": [4.5], "^VIX": [20.0], "SPY": spy}
    monkeypatch.setattr(md, "get_closes", lambda s, p="2y", ttl=0: table.get(s, []))
    monkeypatch.setattr(md, "get_fundamentals", lambda s, **k: {"trailing_pe": 25.0})


def test_macro_snapshot_yahoo_fallback_flags_estimates(monkeypatch):
    _stub_closes(monkeypatch, [100.0] * 199 + [110.0])
    m = md.macro_snapshot()
    assert m["tbill_3m"] == pytest.approx(0.04) and m["ten_year"] == pytest.approx(0.045) and m["vix"] == 20.0
    assert m["cpi_yoy"] == 0.03 and any("CPI defaulted" in n for n in m["notes"])
    assert m["sp500_vs_200dma"] == pytest.approx(110 / (sum([100.0] * 199 + [110.0]) / 200) - 1)
    assert md.macro_snapshot() == m  # cached


def test_macro_snapshot_uses_fred_when_keyed(monkeypatch):
    _stub_closes(monkeypatch, [100.0] * 10)
    vals = {"DTB3": [5.0], "DGS10": [4.0], "VIXCLS": [15.0], "CPIAUCSL": [103.0] + [0] * 11 + [100.0]}
    monkeypatch.setattr(md, "_fred_latest", lambda s, k, n=1: vals[s])
    m = md.macro_snapshot("key")
    assert m["tbill_3m"] == pytest.approx(0.05) and m["cpi_yoy"] == pytest.approx(0.03) and m["vix"] == 15.0
    assert m["sp500_vs_200dma"] == 0.0 and m["notes"] == []


def test_macro_snapshot_fred_error_falls_back(monkeypatch):
    _stub_closes(monkeypatch, [])
    monkeypatch.setattr(md, "_fred_latest", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    m = md.macro_snapshot("key")
    assert any("FRED error" in n for n in m["notes"]) and m["tbill_3m"] == pytest.approx(0.04)


def test_market_inputs(monkeypatch):
    _stub_closes(monkeypatch, [100.0] * 10)
    mi, notes = md.market_inputs()
    assert mi.vix == 20.0 and mi.sp500_pe == 25.0 and isinstance(notes, list)


def test_sector_strength_ranks_and_skips_short_history(monkeypatch):
    flat = [100.0] * 200
    up = [100.0] * 100 + [100.0 + i for i in range(100)]
    series = {"SPY": flat, "XLK": up, "XLE": flat, "XLV": [1.0] * 5}
    monkeypatch.setattr(md, "get_closes", lambda s, p="1y", ttl=0: series.get(s, []))
    out = md.sector_strength()
    assert out[0]["etf"] == "XLK" and {o["etf"] for o in out} == {"XLK", "XLE"}
    assert out[0]["score"] > out[1]["score"]


def test_throttle_sleeps_between_calls(monkeypatch):
    monkeypatch.undo()
    slept = []
    monkeypatch.setattr(md.time, "sleep", slept.append)
    md._last_call = md.time.monotonic()
    md._throttle(5)
    assert slept and slept[0] > 0


def test_edgar_context_degrades_when_parsing_fails(monkeypatch):
    import edgar

    filing = SimpleNamespace(
        form="10-K", filing_date="2025-01-01", accession_no="0001", filing_url="http://x", obj=lambda: (_ for _ in ()).throw(ValueError("x"))
    )
    co = SimpleNamespace(
        get_filings=lambda form: SimpleNamespace(latest=lambda: filing),
        get_financials=lambda: (_ for _ in ()).throw(ValueError("no fin")),
    )
    monkeypatch.setattr(edgar, "Company", lambda t: co)
    monkeypatch.setattr(edgar, "set_identity", lambda i: None)
    out = md.edgar_filing_context("AAA", "me@x.com")
    assert out["citation"]["accession"] == "0001" and out["risk_factors"] == "" and out["financials"] == ""

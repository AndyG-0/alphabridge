import io
from pathlib import Path

import pytest

from services.importers import ofx

DATA = Path(__file__).parent / "fixtures_data"


def _read(name):
    return (DATA / name).read_text()


def test_ofx_v1_positions_and_cash():
    res = ofx.parse_ofx(_read("brokerage_v1.ofx"))
    by = {r.symbol: r for r in res.rows}
    assert set(by) == {"TSTA", "TSTB", "CASH-2345"}
    assert by["TSTA"].market_value == 500.0 and by["TSTA"].shares == 10
    assert by["TSTB"].name == "TEST INDEX FUND"
    assert by["CASH-2345"].asset_class == "MONEY_MARKET" and by["CASH-2345"].market_value == 1000.0
    assert not [c for c in res.checks if c["level"] == "fail"]


def test_ofx_price_mismatch_fails_check():
    bad = _read("brokerage_v1.ofx").replace("<MKTVAL>500.00", "<MKTVAL>900.00")
    res = ofx.parse_ofx(bad)
    assert any(c["level"] == "fail" for c in res.checks)
    assert res.confidence == "low"


def test_ofx_bad_number_is_row_error():
    bad = _read("brokerage_v1.ofx").replace("<UNITS>10", "<UNITS>ten")
    res = ofx.parse_ofx(bad)
    assert [r.symbol for r in res.rows if r.symbol == "TSTA"] == []
    assert res.row_errors and res.row_errors[0]["level"] == "error"


def test_ofx_empty_warns():
    res = ofx.parse_ofx("<OFX></OFX>")
    assert not res.rows and res.warnings


def test_qif_nets_transactions():
    res = ofx.parse_qif(_read("bank.qif"), "Test Checking")
    assert res.rows[0].market_value == pytest.approx(749.5)
    assert res.rows[0].account_name == "Test Checking"
    assert res.confidence == "low"


def test_detectors():
    assert ofx.is_ofx(_read("brokerage_v1.ofx")) and not ofx.is_ofx("a,b\n1,2")
    assert ofx.is_qif(_read("bank.qif"))


def test_ofx_route_dry_run(client):
    r = client.post(
        "/api/ingest",
        data={"file": (io.BytesIO(_read("brokerage_v1.ofx").encode()), "stmt.ofx"), "dry_run": "1"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["parser"] == "ofx" and len(body["rows"]) == 3


def test_qif_route_imports(client):
    r = client.post(
        "/api/ingest",
        data={"file": (io.BytesIO(_read("bank.qif").encode()), "a.qif"), "account_name": "Test Checking"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 201

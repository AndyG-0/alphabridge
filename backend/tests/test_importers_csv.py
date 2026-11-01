from pathlib import Path

import pytest

from services import ingestion

DATA = Path(__file__).parent / "fixtures_data"


def _parse(name):
    return ingestion.parse_csv((DATA / name).read_text())


def test_schwab_positions():
    res = _parse("schwab_positions.csv")
    assert res.parser == "schwab_positions"
    by = {r.symbol: r for r in res.rows}
    assert set(by) == {"TSTA", "TSTB", "CASH"}
    assert by["CASH"].asset_class == "MONEY_MARKET" and by["CASH"].market_value == 250.0
    assert all(r.account_name == "Individual ...1234" for r in res.rows)
    assert sum(r.market_value for r in res.rows) == pytest.approx(1750.0)  # Account Total row skipped
    assert not [c for c in res.checks if c["level"] == "fail"]


def test_etrade_positions():
    res = _parse("etrade_positions.csv")
    assert res.parser == "etrade_positions"
    assert {r.symbol: r.market_value for r in res.rows} == {"TSTA": 500.0, "TSTB": 1000.0}


def test_vanguard_positions_stop_at_blank_line():
    res = _parse("vanguard_positions.csv")
    assert res.parser == "vanguard_positions"
    assert [r.symbol for r in res.rows] == ["TSTV", "TSTW"]
    assert res.rows[0].shares == 10.5


def test_corrupted_value_fails_check():
    text = (DATA / "etrade_positions.csv").read_text().replace(",500.00\n", ",900.00\n")
    res = ingestion.parse_csv(text)
    assert any(c["level"] == "fail" for c in res.checks)
    assert res.confidence == "low"


def test_ibkr_open_positions():
    from services.importers import ibkr

    text = (DATA / "ibkr_activity.csv").read_text()
    res = ibkr.parse_ibkr(text)
    assert [(r.symbol, r.market_value) for r in res.rows] == [("TSTA", 500.0), ("TSTB", 1000.0)]
    assert res.rows[0].account_name == "Interactive Brokers 4567"
    assert not [c for c in res.checks if c["level"] == "fail"]


def test_ibkr_foreign_currency_without_rate_is_row_error():
    from services.importers import ibkr

    text = (DATA / "ibkr_activity.csv").read_text().replace("USD,TSTA", "XXX,TSTA")
    res = ibkr.parse_ibkr(text, fx=lambda c: None)
    assert [r.symbol for r in res.rows] == ["TSTB"] and res.row_errors


@pytest.mark.parametrize(
    ("name", "inst"),
    [("Schwab Individual ...1234", "SCHWAB"), ("Vanguard Brokerage", "VANGUARD"), ("E*TRADE -1234", "ETRADE"), ("Interactive Brokers 4567", "IBKR")],
)
def test_new_institution_name_rules(name, inst):
    from services import institutions

    assert institutions.attrs_for_name(name)["institution"] == inst

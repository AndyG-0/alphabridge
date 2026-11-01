import io
from datetime import date, timedelta

import pytest

import db
from models import Account, Holding, TaxLot, UserProfile
from services import ingestion
from services import tax_lots as tl

TODAY = date(2026, 6, 15)

LOT_CSV = (
    "Account Number,Account Name,Symbol,Description,Date Acquired,Quantity,Cost Basis Per Share,Cost Basis Total,Current Value,Term\n"
    'TEST0001,Individual,VOO,VANGUARD S&P 500,01/10/2024,10,$400.00,"$4,000.00","$5,000.00",Long\n'
    'TEST0001,Individual,VOO,VANGUARD S&P 500,06/01/2026,5,$600.00,"$3,000.00","$2,500.00",Short\n'
    "TEST0001,Individual,NVDA,NVIDIA,13/45/2025,5,$1.00,$5.00,$6.00,Short\n"
    "TEST0001,Individual,AAPL,APPLE,02/02/2025,abc,$1.00,$5.00,$6.00,Short\n"
    "\n"
    '"Date downloaded 06/15/2026"\n'
)


def acct(id_, bucket="TAXABLE_BROKERAGE", owner="SELF", name=None):
    return Account(id=id_, name=name or f"A{id_}", institution="X", tax_bucket=bucket, risk_tier="GROWTH", owner=owner)


def lot(id_, acct_id, sym, acquired, shares, basis, value):
    return TaxLot(id=id_, account_id=acct_id, symbol=sym, acquired=acquired, shares=shares, cost_basis_total=basis, current_value=value)


def profile(income=100000.0, status="SINGLE"):
    return UserProfile(annual_income=income, tax_filing_status=status, spouse_annual_income=0)


def test_parse_lots_reports_bad_rows_and_detects_export():
    assert ingestion.is_lot_export(LOT_CSV)
    assert not ingestion.is_lot_export("Symbol,Quantity,Current Value\nVOO,1,100\n")
    p = ingestion.parse_lots(LOT_CSV)
    assert [(r.symbol, r.acquired, r.shares, r.cost_basis_total, r.current_value) for r in p.rows] == [
        ("VOO", date(2024, 1, 10), 10.0, 4000.0, 5000.0),
        ("VOO", date(2026, 6, 1), 5.0, 3000.0, 2500.0),
    ]
    errs = {e["symbol"]: e["error"] for e in p.row_errors}
    assert "unreadable date" in errs["NVDA"] and "unreadable shares" in errs["AAPL"]


def test_term_boundary_is_more_than_one_year():
    assert tl.term(date(2025, 6, 15), date(2026, 6, 15)) == "SHORT"  # exactly 365 days is still short
    assert tl.term(date(2025, 6, 14), date(2026, 6, 15)) == "LONG"


def test_identical_groups():
    g = tl.identical_group("ivv")
    assert "VOO" in g["tickers"] and "VTI" in g["alternatives"]
    assert tl.identical_group("ZZZZ")["tickers"] == ["ZZZZ"]


@pytest.mark.parametrize(
    ("days", "conflict"),
    [(-31, False), (-30, True), (0, True), (30, True), (31, False)],
)
def test_wash_sale_window_edge_days(days, conflict):
    ira = acct(2, "PRE_TAX_401K", name="IRA")
    lots = [lot(1, 1, "VOO", date(2020, 1, 1), 10, 1000, 800), lot(2, 2, "IVV", TODAY + timedelta(days=days), 1, 500, 500)]
    out = tl.wash_conflicts("VOO", TODAY, lots, {1: acct(1), 2: ira}, exclude_lot=1)
    assert bool(out) is conflict
    if conflict:
        assert out[0]["account"] == "IRA"  # a purchase in the IRA still triggers it


def test_spouse_account_purchase_conflicts():
    out = tl.wash_conflicts("VTI", TODAY, [lot(5, 3, "ITOT", TODAY - timedelta(days=10), 1, 1, 1)], {3: acct(3, owner="SPOUSE")})
    assert out and out[0]["owner"] == "SPOUSE"


def test_harvest_savings_by_hand_and_term_rates():
    accounts = {1: acct(1), 2: acct(2, "ROTH")}
    lots = [
        lot(1, 1, "QQQ", date(2024, 1, 1), 10, 5000, 4000),  # long-term, loss 1000
        lot(2, 1, "ARKK", date(2026, 3, 1), 10, 2000, 1500),  # short-term, loss 500
        lot(3, 1, "TINY", date(2024, 1, 1), 1, 100, 50),  # loss 50 < min
        lot(4, 2, "VTI", date(2024, 1, 1), 10, 5000, 1000),  # Roth: not harvestable
        lot(5, 1, "VGT", date(2024, 1, 1), 10, 5000, 4000),  # loss but wash-blocked by FTEC bought 5 days ago
        lot(6, 2, "FTEC", TODAY - timedelta(days=5), 1, 100, 100),
    ]
    views = [tl.lot_view(x, {}, TODAY) for x in lots]
    out = tl.harvest_candidates(views, lots, accounts, profile(100000), TODAY)
    c = {x["symbol"]: x for x in out["candidates"]}
    assert set(c) == {"QQQ", "ARKK"}
    assert {x["symbol"] for x in out["blocked_by_wash_sale"]} == {"VGT"}
    # 100k single, 2025+ table: ordinary taxable = 100000 - std ded; short rate is the marginal bracket, long-term rate 15%
    assert c["QQQ"]["rate"] == pytest.approx(0.15)
    assert c["QQQ"]["est_tax_savings"] == pytest.approx(1000 * 0.15)
    assert c["ARKK"]["rate"] == pytest.approx(out["rates"]["short"]) and 0.22 <= c["ARKK"]["rate"] <= 0.24
    assert out["total_loss"] == pytest.approx(1500)
    assert c["QQQ"]["alternatives"]


def test_gain_harvest_fills_zero_bracket_exactly():
    accounts = {1: acct(1)}
    lots = [lot(1, 1, "VTI", date(2020, 1, 1), 100, 10000, 40000), lot(2, 1, "VOO", date(2026, 5, 1), 10, 1000, 5000)]
    views = [tl.lot_view(x, {}, TODAY) for x in lots]
    p = profile(income=0)  # nothing taxed yet: headroom is the whole 0% band
    out = tl.gain_harvest(views, accounts, p, TODAY)
    assert out["headroom"] == pytest.approx(out["zero_bracket_top"])
    assert len(out["picks"]) == 1 and out["picks"][0]["symbol"] == "VTI"  # the short-term lot is excluded
    assert out["total_gain"] == pytest.approx(min(30000, out["zero_bracket_top"]))
    rich = tl.gain_harvest(views, accounts, profile(income=500000), TODAY)
    assert rich["headroom"] == 0 and rich["picks"] == []


def test_suggest_sale_takes_losses_then_cheapest_tax():
    accounts = {1: acct(1)}
    lots = [
        lot(1, 1, "VTI", date(2020, 1, 1), 10, 1000, 5000),  # LT, huge gain
        lot(2, 1, "VTI", date(2025, 12, 1), 10, 5200, 5000),  # ST, loss 200
        lot(3, 1, "VTI", date(2021, 1, 1), 10, 4500, 5000),  # LT, small gain 500
    ]
    views = [tl.lot_view(x, {}, TODAY) for x in lots]
    out = tl.suggest_sale(views, "vti", 7500, profile(100000), TODAY, lots, accounts)
    assert [p["lot_id"] for p in out["picks"]] == [2, 3]
    assert out["picks"][0]["proceeds"] == 5000 and out["picks"][1]["proceeds"] == pytest.approx(2500)
    assert out["total_gain"] == pytest.approx(-200 + 250)
    assert out["shortfall"] == 0
    assert tl.suggest_sale(views, "VTI", 99999, profile(), TODAY, lots, accounts)["shortfall"] == pytest.approx(99999 - 15000)


def test_prices_from_holding_override_export_value():
    l1 = lot(1, 1, "VOO", date(2024, 1, 1), 10, 4000, 5000)
    assert tl.lot_view(l1, {(1, "VOO"): 520.0}, TODAY)["value"] == pytest.approx(5200)
    assert tl.lot_view(l1, {}, TODAY)["value"] == 5000


def test_import_endpoint_is_idempotent_and_ingest_rejects_lot_files(client, app):
    with app.app_context():
        s = db.session()
        a = Account(name="Brokerage", institution="Fidelity", tax_bucket="TAXABLE_BROKERAGE", risk_tier="GROWTH")
        s.add(a)
        s.flush()
        s.add(Holding(account_id=a.id, symbol="VOO", shares=15, market_value=7500, cost_basis_total=7000, current_price=500, asset_class="US_EQUITY"))
        s.commit()
        aid = a.id
    data = {"file": (io.BytesIO(LOT_CSV.encode()), "lots.csv"), "account_id": str(aid)}
    r = client.post("/api/tax-lots/import", data=data, content_type="multipart/form-data")
    assert r.status_code == 201 and r.get_json()["lots"] == 2 and len(r.get_json()["row_errors"]) == 2
    data = {"file": (io.BytesIO(LOT_CSV.encode()), "lots.csv"), "account_id": str(aid)}
    assert client.post("/api/tax-lots/import", data=data, content_type="multipart/form-data").status_code == 201
    assert len(client.get("/api/tax-lots/list").get_json()) == 2  # replaced, not doubled
    rep = client.get("/api/tax-lots").get_json()
    assert rep["lots"] == 2 and rep["missing_lots"] == []
    sell = client.get("/api/tax-lots/sell?symbol=VOO&amount=1000").get_json()
    assert sell["raised"] == pytest.approx(1000)
    assert client.get("/api/tax-lots/sell?symbol=VOO").status_code == 400
    bad = client.post("/api/ingest", data={"file": (io.BytesIO(LOT_CSV.encode()), "lots.csv")}, content_type="multipart/form-data")
    assert bad.status_code == 422 and "lot-level" in bad.get_json()["error"]
    assert client.post("/api/tax-lots/import", data={"account_id": "1"}, content_type="multipart/form-data").status_code == 400


def test_report_without_lots(client):
    j = client.get("/api/tax-lots").get_json()
    assert j["lots"] == 0 and j["notes"]

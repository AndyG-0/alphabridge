import io

import pytest

import db
from models import Account, Holding, IngestionLog
from services import corporate_actions, ingestion
from tests.fixtures import FIDELITY_POSITIONS_CSV


def _post(client, text, name="p.csv", **form):
    return client.post("/api/ingest", data={"file": (io.BytesIO(text.encode()), name), **form}, content_type="multipart/form-data")


def test_reimport_is_idempotent(client):
    r1 = _post(client, FIDELITY_POSITIONS_CSV)
    assert r1.status_code == 201 and r1.get_json()["unchanged"] == []
    r2 = _post(client, FIDELITY_POSITIONS_CSV)
    assert r2.status_code == 201
    assert r2.get_json()["unchanged"] == r1.get_json()["accounts"]
    with client.application.app_context():
        s = db.session()
        assert s.query(IngestionLog).filter(IngestionLog.status == "OK").count() == 1
        assert s.query(Holding).count() == 3


def test_undo_restores_previous_holdings(client):
    _post(client, FIDELITY_POSITIONS_CSV)
    changed = FIDELITY_POSITIONS_CSV.replace("150,$135.40", "100,$135.40").replace('"$20,310.00"', '"$13,540.00"')
    r = _post(client, changed)
    assert r.status_code == 201 and not r.get_json()["unchanged"]
    log = client.get("/api/ingest/log").get_json()
    assert log[0]["can_undo"] and not log[1]["can_undo"]  # only the newest import of an account is undoable
    assert client.post(f"/api/ingest/{log[1]['id']}/undo").status_code == 409
    assert client.post(f"/api/ingest/{log[0]['id']}/undo").status_code == 200
    with client.application.app_context():
        nvda = db.session().query(Holding).filter_by(symbol="NVDA").one()
        assert nvda.shares == 150 and nvda.market_value == 20310
    after = client.get("/api/ingest/log").get_json()
    assert after[0]["status"] == "UNDONE" and not after[0]["can_undo"] and after[1]["can_undo"]
    assert client.post(f"/api/ingest/{log[0]['id']}/undo").status_code == 409


def test_undo_first_import_removes_created_account(client):
    _post(client, FIDELITY_POSITIONS_CSV)
    log_id = client.get("/api/ingest/log").get_json()[0]["id"]
    assert client.post(f"/api/ingest/{log_id}/undo").status_code == 200
    with client.application.app_context():
        s = db.session()
        assert s.query(Account).count() == 0 and s.query(Holding).count() == 0
    assert client.post("/api/ingest/9999/undo").status_code == 404


CSV_BAD = (
    "Account Name,Symbol,Description,Quantity,Last Price,Current Value,Cost Basis Total\n"
    'Brokerage,VTI,VANGUARD TOTAL,10,$200.00,"$2,000.00",$1,500.00\n'
    "Brokerage,BAD,BROKEN ROW,5,$10.00,abc,\n"
    "Brokerage,NEG,NEGATIVE,-5,$10.00,-$50.00,\n"
    "Brokerage,ODD,MISMATCH,10,$10.00,$500.00,\n"
)


def test_row_errors_in_dry_run_preview_and_nothing_written(client):
    r = _post(client, CSV_BAD, dry_run="1")
    body = r.get_json()
    assert r.status_code == 200 and body["preview"]
    assert [x["symbol"] for x in body["rows"]] == ["VTI", "ODD"]
    errs = {e["symbol"]: e for e in body["row_errors"]}
    assert errs["BAD"]["level"] == "error" and "value" in errs["BAD"]["error"] and errs["BAD"]["line"] == 3
    assert errs["NEG"]["level"] == "error" and errs["ODD"]["level"] == "warn"
    with client.application.app_context():
        assert db.session().query(Holding).count() == 0


def test_real_import_reports_row_errors(client):
    r = _post(client, CSV_BAD)
    assert r.status_code == 201 and len(r.get_json()["row_errors"]) == 3


CSV_EUR = (
    "Account Name,Symbol,Description,Quantity,Last Price,Current Value,Cost Basis Total,Currency\n"
    "Euro Brokerage,SAP,SAP SE,10,100.00,1000.00,800.00,EUR\n"
    "Euro Brokerage,VTI,VANGUARD TOTAL,10,200.00,2000.00,1500.00,USD\n"
    "Euro Brokerage,XYZ,UNKNOWN FX,1,10.00,10.00,,ZZZ\n"
)


def test_multicurrency_converted_to_usd():
    res = ingestion.parse_csv(CSV_EUR, fx=lambda c: {"EUR": 1.1}.get(c))
    sap, vti = res.rows
    assert (sap.market_value, sap.price, sap.cost_basis_total, sap.currency, sap.fx_rate) == pytest.approx((1100.0, 110.0, 880.0, "EUR", 1.1))
    assert vti.market_value == 2000 and vti.currency == "USD"
    assert [e["symbol"] for e in res.row_errors] == ["XYZ"] and "ZZZ" in res.row_errors[0]["error"]


def test_split_math():
    h = Holding(symbol="NVDA", shares=10, current_price=1000, market_value=10_000, cost_basis_total=4000)
    corporate_actions.split(h, 10)
    assert (h.shares, h.current_price, h.market_value, h.cost_basis_total) == (100, 100, 10_000, 4000)
    corporate_actions.split(h, 0.1)  # 1-for-10 reverse
    assert (h.shares, h.current_price) == (pytest.approx(10), pytest.approx(1000))
    with pytest.raises(ValueError):
        corporate_actions.split(h, 0)


def test_spinoff_basis_allocation():
    assert corporate_actions.allocate_spinoff_basis(1000, 0.25) == (750, 250)
    with pytest.raises(ValueError):
        corporate_actions.allocate_spinoff_basis(1000, 1)


def test_split_and_spinoff_routes(client):
    _post(client, FIDELITY_POSITIONS_CSV)
    with client.application.app_context():
        hid = db.session().query(Holding).filter_by(symbol="NVDA").one().id
    r = client.post(f"/api/holdings/{hid}/split", json={"ratio": 2})
    assert r.status_code == 200 and r.get_json()["shares"] == 300 and r.get_json()["market_value"] == 20310
    assert client.post(f"/api/holdings/{hid}/split", json={"ratio": -1}).status_code == 400
    r = client.post(f"/api/holdings/{hid}/spinoff", json={"symbol": "NEWC", "shares": 30, "basis_fraction": 0.1, "price": 20})
    assert r.status_code == 201
    out = r.get_json()
    assert out["parent_basis"] == pytest.approx(10_800) and out["child_basis"] == pytest.approx(1200) and out["child_value"] == 600
    assert client.post("/api/holdings/9999/split", json={"ratio": 2}).status_code == 404

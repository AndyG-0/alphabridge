import io
import json

import pytest

from services.importers import mapper

CSV = "Junk line\nTicker,Holding,Qty,Px,Mkt\nTSTA,Test Corp,10,$50.00,$500.00\nTSTB,Test Bond Fund,20,$10.00,$200.00\n\nfooter\n"
MAP = {"columns": {"symbol": "Ticker", "name": "Holding", "shares": "Qty", "price": "Px", "value": "Mkt"}, "skip_rows": 1, "account_name": "Test Acct"}


def test_mapping_parses_and_checks():
    res = mapper.parse_with_mapping(CSV, mapper.Mapping.model_validate(MAP))
    assert [(r.symbol, r.market_value, r.account_name) for r in res.rows] == [("TSTA", 500.0, "Test Acct"), ("TSTB", 200.0, "Test Acct")]
    assert not [c for c in res.checks if c["level"] == "fail"]


def test_missing_column_warns():
    bad = {**MAP, "columns": {**MAP["columns"], "value": "Nope"}}
    res = mapper.parse_with_mapping(CSV, mapper.Mapping.model_validate(bad))
    assert not res.rows and "not found" in res.warnings[0]


@pytest.mark.parametrize("cols", [{"value": "Mkt"}, {"symbol": "Ticker"}, {"symbol": "Ticker", "bogus": "x", "value": "Mkt"}])
def test_invalid_mappings_rejected(cols):
    with pytest.raises(ValueError):
        mapper.Mapping.model_validate({"columns": cols})


def test_template_crud_and_apply(client):
    r = client.post("/api/ingest/templates", json={"name": "My broker", "mapping": MAP})
    assert r.status_code == 201
    tid = r.get_json()["id"]
    assert client.get("/api/ingest/templates").get_json()[0]["name"] == "My broker"
    # saving the same name updates it
    assert client.post("/api/ingest/templates", json={"name": "My broker", "mapping": MAP}).get_json()["id"] == tid
    up = client.post(
        "/api/ingest",
        data={"file": (io.BytesIO(CSV.encode()), "x.csv"), "template_id": str(tid), "dry_run": "1"},
        content_type="multipart/form-data",
    )
    assert up.status_code == 200 and up.get_json()["parser"] == "mapped_csv" and len(up.get_json()["rows"]) == 2
    inline = client.post("/api/ingest", data={"file": (io.BytesIO(CSV.encode()), "x.csv"), "mapping": json.dumps(MAP)}, content_type="multipart/form-data")
    assert inline.status_code == 201
    assert client.delete(f"/api/ingest/templates/{tid}").status_code == 204
    assert client.delete(f"/api/ingest/templates/{tid}").status_code == 404


def test_template_validation_error(client):
    assert client.post("/api/ingest/templates", json={"name": "x", "mapping": {"columns": {"value": "a"}}}).status_code == 400
    assert client.post("/api/ingest/templates", json={"mapping": MAP}).status_code == 400

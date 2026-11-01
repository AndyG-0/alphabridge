import io

import pytest

from services import ingestion, planner
from tests.fixtures import FIDELITY_POSITIONS_CSV, NATIONWIDE_BALANCES_CSV


def test_money_parsing():
    assert ingestion.money("$1,234.50") == 1234.5
    assert ingestion.money("($5.00)") == -5.0
    assert ingestion.money("--") == 0.0


def test_fidelity_csv():
    r = ingestion.parse_csv(FIDELITY_POSITIONS_CSV)
    assert r.parser == "fidelity_positions"
    assert [x.symbol for x in r.rows] == ["VGT", "NVDA", "SPAXX"]
    assert r.rows[0].market_value == 45768.75 and r.rows[0].cost_basis_total == 36000
    assert r.rows[2].asset_class == "MONEY_MARKET" and not r.rows[2].needs_mapping


def test_nationwide_cit_needs_mapping():
    r = ingestion.parse_csv(NATIONWIDE_BALANCES_CSV)
    assert len(r.rows) == 3
    cit = r.rows[0]
    assert cit.needs_mapping and cit.market_value == 49460.60
    assert cit.symbol.startswith("VANGUARD-TARGET")


def test_upload_flow_and_proxy_mapping(client):
    resp = client.post(
        "/api/ingest",
        data={
            "file": (io.BytesIO(NATIONWIDE_BALANCES_CSV.encode()), "nw.csv"),
            "account_id": client.post("/api/accounts", json={"name": "Nationwide 401k", "tax_bucket": "PRE_TAX_401K", "risk_tier": "SAFE_CORE"}).get_json()[
                "id"
            ],
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201 and resp.get_json()["rows"] == 3
    un = client.get("/api/holdings/unmapped").get_json()
    assert len(un) == 3  # no public tickers in a plan balance export
    cit = next(u for u in un if u["symbol"].startswith("VANGUARD-TARGET"))
    m = client.post("/api/holdings/map-proxy", json={"holding_id": cit["id"], "proxy_ticker": "vtivx"})
    assert m.get_json()["proxy_ticker"] == "VTIVX"
    assert len(client.get("/api/holdings/unmapped").get_json()) == 2
    pf = client.get("/api/portfolio").get_json()
    assert pf["buckets"]["safe_core"] == pytest.approx(68552.62)
    assert len(client.get("/api/networth/history").get_json()) == 1


def test_reupload_replaces_holdings(client):
    aid = client.post("/api/accounts", json={"name": "B"}).get_json()["id"]
    for _ in range(2):
        client.post(
            "/api/ingest",
            data={"file": (io.BytesIO(FIDELITY_POSITIONS_CSV.encode()), "f.csv"), "account_id": aid},
            content_type="multipart/form-data",
        )
    assert len(client.get("/api/portfolio").get_json()["accounts"][0]["holdings"]) == 3


def test_auth_token(app):
    app.config["ACCESS_TOKEN"] = "secret"
    c = app.test_client()
    assert c.get("/api/portfolio").status_code == 401
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/portfolio", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_secrets_never_returned(client):
    client.put("/api/settings/llm", json={"provider": "openai", "api_key": "sk-test"})
    body = client.get("/api/settings/llm").get_json()
    assert body["api_key_set"] is True and "sk-test" not in str(body)
    client.put("/api/settings/llm", json={"fast_model": "x"})  # omission must not wipe key
    assert client.get("/api/settings/llm").get_json()["api_key_set"] is True


def test_validation_error(client):
    assert client.put("/api/profile", json={"birth_date": "2999-01-01"}).status_code == 400


def test_menu_grade():
    menu = [
        {"ticker_or_cusip": "A", "fund_name": "", "asset_class": "US_EQUITY", "expense_ratio": 0.009},
        {"ticker_or_cusip": "B", "fund_name": "", "asset_class": "US_EQUITY", "expense_ratio": 0.0002},
    ]
    g = planner.grade_menu(menu, [{"symbol": "A", "market_value": 10000, "asset_class": "US_EQUITY"}])
    assert g["suggestions"][0]["to"] == "B" and g["annual_savings_potential"] == pytest.approx(88.0)
    assert g["grade"] == "D"


def test_allocate_surplus():
    a = planner.allocate_surplus(10000, 0.3)
    assert a["Asymmetric Growth / Momentum"] == 3000 and sum(a.values()) == 10000


def _upload(client, name, data, **form):
    return client.post("/api/ingest", data={"file": (io.BytesIO(data), name), **form}, content_type="multipart/form-data")


def test_duplicate_detected_across_accounts(client):
    csv = FIDELITY_POSITIONS_CSV.encode()
    a = client.post("/api/accounts", json={"name": "A"}).get_json()["id"]
    b = client.post("/api/accounts", json={"name": "B"}).get_json()["id"]
    assert _upload(client, "f.csv", csv, account_id=a).status_code == 201
    dup = _upload(client, "f.csv", csv, account_id=b)
    assert dup.status_code == 409 and dup.get_json()["duplicate_of"]["id"] == a
    diff = dup.get_json()["diff"]
    assert diff["summary"]["same"] == len(diff["rows"]) and diff["summary"]["total_delta_pct"] == 0
    assert _upload(client, "f.csv", csv, account_id=a).status_code == 201  # refresh same account is fine
    assert _upload(client, "f.csv", csv, account_id=b, allow_duplicate="1").status_code == 201


def test_auto_detect_same_file_is_update_not_duplicate(client):
    csv = FIDELITY_POSITIONS_CSV.encode()
    assert _upload(client, "f.csv", csv).status_code == 201
    assert _upload(client, "f.csv", csv).status_code == 201
    assert len(client.get("/api/portfolio").get_json()["accounts"]) == 1


def test_unnamed_import_duplicate_of_existing(client):
    nw = NATIONWIDE_BALANCES_CSV.encode()
    a = client.post("/api/accounts", json={"name": "NW"}).get_json()["id"]
    _upload(client, "nw.csv", nw, account_id=a)
    r = _upload(client, "nw.csv", nw)  # auto-detect -> would create "Imported Account"
    assert r.status_code == 409


def test_delete_account_and_holding(client):
    csv = FIDELITY_POSITIONS_CSV.encode()
    _upload(client, "f.csv", csv)
    pf = client.get("/api/portfolio").get_json()
    hid = pf["accounts"][0]["holdings"][0]["id"]
    assert client.delete(f"/api/holdings/{hid}").status_code == 204
    assert len(client.get("/api/portfolio").get_json()["accounts"][0]["holdings"]) == 2
    assert client.delete(f"/api/accounts/{pf['accounts'][0]['id']}").status_code == 204
    assert client.get("/api/portfolio").get_json()["net_worth"] == 0


def test_ally_invest_statement_text():
    from services.ingestion import parse_ally_invest_text

    txt = """MONEY MARKET FUNDS
THE INSURED DEPOSIT PROGRAM TTZTZ C 1,384.81 $1.00 $1,384.81 $962.58 44% 4.667%
Total Money Market Funds $1,384.81
EQUITIES / OPTIONS
INVESCO QQQ TR QQQ C 14 $739.77 $10,356.78 $10,034.64 3% $43 34.907%
UNIT SER 1
TAIWAN SEMICONDUCTOR MFG CO TSM C 21 456.19 9,579.99 8,721.72 10 68 32.289
LTD-SPONSORED ADR REPSTG 5 COM
Total Equities $28,284.45 $196 95.333%"""
    rows = {r.symbol: r for r in parse_ally_invest_text(txt).rows}
    assert rows["QQQ"].shares == 14 and rows["QQQ"].market_value == 10356.78 and rows["QQQ"].asset_class == "US_EQUITY"
    assert rows["TSM"].market_value == 9579.99
    assert rows["ALLY-SWEEP"].asset_class == "MONEY_MARKET"


def test_ally_bank_statement_text():
    from services.ingestion import parse_ally_bank_text

    r = parse_ally_bank_text("Andy - Savings Account xxxxxx0583 $99,047.90 $98,060.32\nTotal Account Balances: $99,047.90 $98,060.32")
    assert [(x.symbol, x.market_value, x.account_name) for x in r.rows] == [("ALLY-0583", 98060.32, "Ally Bank Savings")]


CHASE_CSV = """Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
DEBIT,03/05/2026,COFFEE,-4.50,DEBIT_CARD,1995.50,
CREDIT,03/04/2026,PAYROLL,2000.00,ACH_CREDIT,2000.00,
"""


def test_chase_activity_csv_uses_latest_balance():
    r = ingestion.parse_csv(CHASE_CSV)
    assert r.parser == "bank_activity" and len(r.rows) == 1
    assert r.rows[0].market_value == 1995.50 and r.rows[0].asset_class == "MONEY_MARKET"


@pytest.mark.parametrize(
    ("name", "inst", "bucket", "tier"),
    [
        ("Chase Checking", "CHASE", "CASH_MMF", "CASH"),
        ("Chase Savings", "CHASE", "CASH_MMF", "CASH"),
        ("Ally Bank Savings", "ALLY", "CASH_MMF", "CASH"),
        ("Ally Invest Brokerage", "ALLY", "TAXABLE_BROKERAGE", "AGGRESSIVE_SATELLITE"),
        ("Nationwide 401k", "NATIONWIDE", "PRE_TAX_401K", "SAFE_CORE"),
        ("Fidelity Roth IRA", "FIDELITY_RETAIL", "ROTH", "MODERATE_GROWTH"),
        ("Brokerage", "FIDELITY_RETAIL", "TAXABLE_BROKERAGE", "AGGRESSIVE_SATELLITE"),
    ],
)
def test_institution_attrs(name, inst, bucket, tier):
    a = ingestion._institution_attrs(name.lower())
    assert (a["institution"], a["tax_bucket"], a["risk_tier"]) == (inst, bucket, tier)


def test_institutions_endpoint_and_chase_account_inference(client):
    ids = {i["id"] for i in client.get("/api/institutions").get_json()}
    assert {"CHASE", "ALLY", "NATIONWIDE"} <= ids
    a = client.post("/api/accounts", json={"name": "Chase Checking"}).get_json()
    assert (a["institution"], a["tax_bucket"], a["risk_tier"], a["bucket"]) == ("CHASE", "CASH_MMF", "CASH", "dry_powder")
    b = client.post("/api/accounts", json={"name": "Chase Checking", "owner": "JOINT"}).get_json()
    assert b["owner"] == "JOINT" and b["institution"] == "CHASE"


def _fid_401k(name="Fidelity NetBenefits 401k", value="10000"):
    return f"Account Name,Symbol,Description,Quantity,Last Price,Current Value\n{name},FXAIX,FIDELITY 500 INDEX,10,$100,${value}\n"


def _post_csv(client, text, **form):
    return client.post("/api/ingest", data={"file": (io.BytesIO(text.encode()), "f.csv"), **form}, content_type="multipart/form-data")


def test_same_named_plans_for_each_spouse_do_not_overwrite(client):
    assert _post_csv(client, _fid_401k(value="10000"), owner="SELF").status_code == 201
    assert _post_csv(client, _fid_401k(value="55000"), owner="SPOUSE").status_code == 201
    accts = client.get("/api/portfolio").get_json()["accounts"]
    assert sorted((a["owner"], a["total"]) for a in accts) == [("SELF", 10000), ("SPOUSE", 55000)]
    # re-importing mine updates mine only
    assert _post_csv(client, _fid_401k(value="12000"), owner="SELF").status_code == 201
    pf = client.get("/api/portfolio").get_json()
    assert sorted((a["owner"], a["total"]) for a in pf["accounts"]) == [("SELF", 12000), ("SPOUSE", 55000)]
    assert pf["by_owner"]["SELF"]["assets"] == 12000 and pf["by_owner"]["SPOUSE"]["assets"] == 55000


def test_auto_detect_asks_whose_account_when_names_collide(client):
    _post_csv(client, _fid_401k(value="10000"), owner="SELF")
    _post_csv(client, _fid_401k(value="55000"), owner="SPOUSE")
    r = _post_csv(client, _fid_401k(value="11000"))
    assert r.status_code == 409 and r.get_json()["needs_owner"] and r.get_json()["owners"] == ["SELF", "SPOUSE"]
    assert _post_csv(client, _fid_401k(), owner="BOSS").status_code == 400


def test_diff_against_account_classifies_rows(client):
    from db import session
    from models import Account
    from services import ingestion

    csv = FIDELITY_POSITIONS_CSV.encode()
    a = client.post("/api/accounts", json={"name": "A"}).get_json()["id"]
    _upload(client, "f.csv", csv, account_id=a)
    acct = session().get(Account, a)
    res = ingestion.parse_csv(csv.decode("utf-8-sig"))
    first, second = res.rows[0], res.rows[1]
    first.shares += 5
    first.market_value += 500
    res.rows.remove(second)
    res.rows.append(ingestion.ParsedRow(symbol="ZZZZ", name="New", shares=1, price=10, market_value=10))
    d = ingestion.diff_against_account(res, acct)
    status = {r["symbol"]: r["status"] for r in d["rows"]}
    assert status[first.symbol] == "changed" and status[second.symbol] == "missing" and status["ZZZZ"] == "new"
    m = d["summary"]
    assert m["same"] + m["changed"] + m["new"] + m["missing"] == len(d["rows"])


def test_account_retype_keeps_plan_flags_consistent(client):
    a = client.post("/api/accounts", json={"name": "Mystery", "tax_bucket": "TAXABLE_BROKERAGE"}).get_json()
    body = {k: a[k] for k in ("name", "institution", "tax_bucket", "risk_tier", "is_restricted_plan", "owner", "is_current_employer_plan")}
    r = client.put(f"/api/accounts/{a['id']}", json=body | {"tax_bucket": "PRE_TAX_401K", "is_current_employer_plan": True}).get_json()
    assert r["is_restricted_plan"] is True and r["is_current_employer_plan"] is True
    r = client.put(f"/api/accounts/{a['id']}", json=body | {"tax_bucket": "ROTH"}).get_json()
    assert (r["tax_bucket"], r["is_restricted_plan"], r["is_current_employer_plan"]) == ("ROTH", False, False)


def test_account_update_rejects_unknown_type(client):
    a = client.post("/api/accounts", json={"name": "X"}).get_json()
    assert client.put(f"/api/accounts/{a['id']}", json={"name": "X", "tax_bucket": "BOGUS"}).status_code == 400
    assert client.put(f"/api/accounts/{a['id']}", json={"name": "", "tax_bucket": "ROTH"}).status_code == 400

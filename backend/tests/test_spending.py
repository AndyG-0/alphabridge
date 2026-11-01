import io
from datetime import date
from pathlib import Path

import pytest

import db
from models import Transaction
from services import transactions

CHASE = (Path(__file__).parent / "fixtures_data" / "spending_chase.csv").read_text()


def _post(client, text, **form):
    return client.post("/api/spending/import", data={"file": (io.BytesIO(text.encode()), "t.csv"), **form}, content_type="multipart/form-data")


def test_parse_signed_mint_and_ynab():
    items, errs = transactions.parse_csv(CHASE)
    assert len(items) == 5 and not errs and items[0]["amount"] == -120
    mint = (
        "Date,Description,Original Description,Amount,Transaction Type,Category,Account Name\n"
        "01/02/2026,Cafe,CAFE,4.50,debit,Restaurants,Chk\n01/03/2026,Pay,PAY,100,credit,Paycheck,Chk\n"
    )
    m, _ = transactions.parse_csv(mint)
    assert [(x["amount"], x["file_category"]) for x in m] == [(-4.5, "Restaurants"), (100.0, "Paycheck")]
    ynab = "Date,Payee,Category,Outflow,Inflow\n2026-01-02,Shop,Shopping,$20.00,$0.00\n2026-01-03,Boss,Income,$0.00,$50.00\n"
    y, _ = transactions.parse_csv(ynab)
    assert [x["amount"] for x in y] == [-20.0, 50.0]


def test_bad_rows_reported():
    items, errs = transactions.parse_csv("Date,Description,Amount\nnot a date,x,5\n01/01/2026,y,abc\n01/01/2026,ok,-5\n")
    assert len(items) == 1 and len(errs) == 2
    assert transactions.parse_csv("a,b\n1,2")[0] == []


def test_import_categorizes_and_dedupes(client):
    r = _post(client, CHASE)
    assert r.status_code == 201 and r.get_json()["added"] == 5 and r.get_json()["uncategorized"] == 1
    assert _post(client, CHASE).get_json() == {"added": 0, "duplicates": 5, "uncategorized": 1, "row_errors": []}
    with client.application.app_context():
        cats = {t.description: t.category for t in db.session().query(Transaction)}
    assert cats["SAFEWAY STORE 1234"] == "food" and cats["TEST LANDLORD RENT"] == "housing"
    assert cats["CREDIT CARD PAYMENT THANK YOU"] == "transfer" and cats["ACME PAYROLL DIRECT DEPOSIT"] == "income"


def test_identical_rows_within_one_file_are_kept(client):
    twice = "Date,Description,Amount\n01/01/2026,COFFEE,-4\n01/01/2026,COFFEE,-4\n"
    assert _post(client, twice).get_json()["added"] == 2


def test_dry_run_writes_nothing(client):
    assert _post(client, CHASE, dry_run="1").get_json()["count"] == 5
    assert client.get("/api/spending/transactions").get_json()["transactions"] == []


def test_user_category_and_rule(client):
    _post(client, CHASE)
    t = client.get("/api/spending/transactions?uncategorized=1").get_json()["transactions"]
    assert len(t) == 1
    assert client.post(f"/api/spending/transactions/{t[0]['id']}/category", json={"category": "bogus"}).status_code == 400
    assert client.post(f"/api/spending/transactions/{t[0]['id']}/category", json={"category": "discretionary", "make_rule": True}).status_code == 200
    assert client.get("/api/spending/rules").get_json()[0]["category"] == "discretionary"
    assert client.post("/api/spending/transactions/9999/category", json={"category": "food"}).status_code == 404


def test_rule_recategorizes_existing(client):
    _post(client, CHASE)
    r = client.post("/api/spending/rules", json={"pattern": "mystery vendor", "category": "other"})
    assert r.get_json()["recategorized"] == 1
    assert client.post("/api/spending/rules", json={"pattern": "", "category": "other"}).status_code == 400


def test_suggest_needs_confirmation(client, monkeypatch):
    _post(client, CHASE)
    tid = client.get("/api/spending/transactions?uncategorized=1").get_json()["transactions"][0]["id"]
    from services import llm_router

    monkeypatch.setattr(
        llm_router,
        "complete_structured",
        lambda task, system, user, schema, **k: schema(suggestions=[{"id": tid, "category": "other"}, {"id": 99999, "category": "food"}]),
    )
    assert client.post("/api/spending/suggest").get_json()["suggested"] == 1
    row = client.get("/api/spending/transactions?uncategorized=1").get_json()["transactions"][0]
    assert row["category"] == "" and row["suggested_category"] == "other"  # not applied yet
    assert client.post("/api/spending/confirm", json={"ids": [tid]}).get_json()["confirmed"] == 1
    assert client.get("/api/spending/transactions?uncategorized=1").get_json()["transactions"] == []


def _seed(monthly: list[float]):
    s = db.session()
    for i, amt in enumerate(monthly):
        s.add(Transaction(tx_date=date(2026, 1 + i, 5), description=f"x{i}", amount=-amt, category="food", tx_hash=f"h{i}"))
    s.add(Transaction(tx_date=date(2026, 1, 6), description="pay", amount=999, category="income", tx_hash="inc"))
    s.add(Transaction(tx_date=date(2026, 1, 7), description="cc", amount=-777, category="transfer", tx_hash="tr"))
    s.commit()


def test_actuals_exclude_transfers_and_partial_month(app):
    from models import UserProfile

    with app.app_context():
        _seed([1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000])
        p = UserProfile(id=1, monthly_expenses_current=800)
        a = transactions.actuals(p, today=date(2026, 9, 15))
        assert a["months_used"][-1] == "2026-08" and a["measured_monthly_avg"] == 1000
        assert a["difference"] == 200 and a["difference_pct"] == 0.25
        assert a["lifestyle_creep"]["flag"] is False


def test_lifestyle_creep_flag(app):
    from models import UserProfile

    with app.app_context():
        _seed([1000, 1000, 1000, 1000, 1000, 1000, 1300, 1300, 1300])
        a = transactions.actuals(UserProfile(id=1, monthly_expenses_current=0), today=date(2026, 12, 1))
        assert a["lifestyle_creep"]["flag"] is True and a["lifestyle_creep"]["change"] == pytest.approx(0.3)


def test_creep_needs_enough_months(app):
    from models import UserProfile

    with app.app_context():
        _seed([1000, 2000])
        a = transactions.actuals(UserProfile(id=1), today=date(2026, 12, 1))
        assert a["lifestyle_creep"]["flag"] is False and "Not enough" in a["lifestyle_creep"]["reason"]


def test_apply_to_plan_requires_confirm(client):
    with client.application.app_context():
        _seed([1000] * 9)
    assert client.post("/api/spending/apply-to-plan", json={}).status_code == 400
    r = client.post("/api/spending/apply-to-plan", json={"confirm": True})
    assert r.status_code == 200 and r.get_json()["after"] == 1000
    assert client.get("/api/profile").get_json()["monthly_expenses_current"] == 1000

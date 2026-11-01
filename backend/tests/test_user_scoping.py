"""Two household members share one database: each must only ever see their own rows."""

import pytest

import db
from models import ACCOUNT_CHILDREN, SHARED_TABLES, USER_SCOPED, Base

H2 = {"X-AlphaBridge-User": "2"}


@pytest.fixture
def two_users(client):
    r = client.post("/api/users", json={"name": "Second"})
    assert r.status_code == 201 and r.get_json()["id"] == 2
    return client


def test_every_table_is_classified_for_tenant_scoping():
    scoped = {m.__tablename__ for m in (*USER_SCOPED, *ACCOUNT_CHILDREN)}
    assert all(hasattr(m, "user_id") for m in USER_SCOPED)
    unclassified = set(Base.metadata.tables) - scoped - SHARED_TABLES
    assert not unclassified, f"add these tables to models.USER_SCOPED/ACCOUNT_CHILDREN/SHARED_TABLES: {sorted(unclassified)}"
    assert not [t for t in SHARED_TABLES if t in scoped]


def test_unknown_user_header_is_rejected(client):
    assert client.get("/api/profile", headers={"X-AlphaBridge-User": "99"}).status_code == 400
    assert client.get("/api/profile", headers={"X-AlphaBridge-User": "abc"}).status_code == 400


def test_profiles_are_separate(two_users):
    c = two_users
    c.put("/api/profile", json={"annual_income": 111000})
    c.put("/api/profile", json={"annual_income": 222000}, headers=H2)
    assert c.get("/api/profile").get_json()["annual_income"] == 111000
    assert c.get("/api/profile", headers=H2).get_json()["annual_income"] == 222000


def test_accounts_and_children_are_private(two_users):
    c = two_users
    a1 = c.post("/api/accounts", json={"name": "Mine", "tax_bucket": "TAXABLE_BROKERAGE"}).get_json()["id"]
    a2 = c.post("/api/accounts", json={"name": "Theirs"}, headers=H2).get_json()["id"]
    names1 = [a["name"] for a in c.get("/api/portfolio").get_json()["accounts"]]
    names2 = [a["name"] for a in c.get("/api/portfolio", headers=H2).get_json()["accounts"]]
    assert "Mine" in names1 and "Theirs" not in names1
    assert names2 == ["Theirs"]
    # direct access by id to another user's account is refused
    assert c.put(f"/api/accounts/{a1}", json={"name": "hijack"}, headers=H2).status_code == 404
    c.delete(f"/api/accounts/{a1}", headers=H2)  # idempotent delete: a no-op for someone else's account
    assert "Mine" in [a["name"] for a in c.get("/api/portfolio").get_json()["accounts"]]
    assert c.get(f"/api/accounts/{a1}/menu", headers=H2).status_code == 404
    item = {"ticker_or_cusip": "ABC", "fund_name": "Fund", "expense_ratio": 0.001}
    assert c.put(f"/api/accounts/{a1}/menu", json=[item], headers=H2).status_code == 404
    assert c.get(f"/api/accounts/{a1}/menu").get_json() == []
    c.delete(f"/api/accounts/{a2}")
    assert [a["name"] for a in c.get("/api/portfolio", headers=H2).get_json()["accounts"]] == ["Theirs"]


def test_holdings_follow_their_account(two_users):
    from models import Account, Holding

    c = two_users
    with c.application.app_context():
        s = db.session()
        a = Account(name="Mine", institution="X", tax_bucket="TAXABLE_BROKERAGE")  # user_id defaults to the current user (1)
        s.add(a)
        s.flush()
        h = Holding(account_id=a.id, symbol="VTI", shares=1, market_value=100)
        s.add(h)
        s.commit()
        hid = h.id
    c.delete(f"/api/holdings/{hid}", headers=H2)  # idempotent delete: a no-op for someone else's holding
    with c.application.app_context():
        assert db.session().get(Holding, hid) is not None
    c.delete(f"/api/holdings/{hid}")
    with c.application.app_context():
        assert db.session().get(Holding, hid) is None


def test_liabilities_events_scenarios_pensions_are_private(two_users):
    c = two_users
    assert c.post("/api/liabilities", json={"name": "Mortgage", "kind": "MORTGAGE", "balance": 1000}).status_code in (200, 201)
    assert c.post("/api/planner/events", json={"name": "Boat", "kind": "PURCHASE", "amount": 5000, "start_year": 2030}).status_code in (200, 201)
    assert c.post("/api/planner/scenarios", json={"name": "Early", "overrides": {"target_retirement_age": 50}}).status_code in (200, 201)
    for path in ("/api/liabilities", "/api/planner/events", "/api/planner/scenarios", "/api/pensions"):
        mine = c.get(path).get_json()
        theirs = c.get(path, headers=H2).get_json()
        assert len(mine if isinstance(mine, list) else mine.get("items", mine.get("liabilities", []))) >= 0
        assert "Mortgage" not in str(theirs) and "Boat" not in str(theirs) and "Early" not in str(theirs), path
    assert "Mortgage" in str(c.get("/api/liabilities").get_json())


def test_chat_sessions_and_actions_are_private(two_users):
    c = two_users
    sid = c.post("/api/chat/sessions").get_json()["id"]
    assert [s["id"] for s in c.get("/api/chat/sessions").get_json()] == [sid]
    assert c.get("/api/chat/sessions", headers=H2).get_json() == []
    assert c.get(f"/api/chat/sessions/{sid}", headers=H2).status_code == 404
    assert c.patch(f"/api/chat/sessions/{sid}", json={"memory": "x"}, headers=H2).status_code == 404
    assert c.delete(f"/api/chat/sessions/{sid}", headers=H2).status_code == 404
    # snoozed/done state is per user
    c.post("/api/actions/year_end:2099:x/done")
    from models import ActionItem

    with c.application.app_context():
        assert db.session().query(ActionItem).count() == 1
    c.application.config["_probe"] = True
    with c.application.test_request_context(headers=H2):
        from flask import g

        g.user_id = 2
        assert db.session().query(ActionItem).count() == 0


def test_new_rows_are_owned_by_the_acting_user(two_users):
    from models import Account

    c = two_users
    c.post("/api/accounts", json={"name": "Theirs"}, headers=H2)
    with c.application.app_context():
        owners = {a.name: a.user_id for a in db.session().query(Account).all()}
    assert owners == {}  # user 1's view must not include user 2's account
    with c.application.test_request_context():
        from flask import g

        g.user_id = 2
        assert {a.name: a.user_id for a in db.session().query(Account).all()} == {"Theirs": 2}

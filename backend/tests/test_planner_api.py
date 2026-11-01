import time


def _setup(client):
    import db
    from models import Holding

    client.put(
        "/api/profile",
        json={
            "birth_date": "1981-03-01",
            "spouse_name": "Sam",
            "spouse_birth_date": "1983-06-01",
            "target_retirement_age": 55,
            "monthly_expenses_retirement": 6000,
            "monthly_contribution": 4000,
            "annual_income": 150000,
            "spouse_annual_income": 90000,
            "social_security_monthly": 3000,
            "spouse_social_security_monthly": 2000,
            "home_value": 450000,
        },
    )
    a = client.post("/api/accounts", json={"name": "Brokerage", "owner": "JOINT", "tax_bucket": "TAXABLE_BROKERAGE"}).get_json()
    b = client.post("/api/accounts", json={"name": "401k", "owner": "SELF", "tax_bucket": "PRE_TAX_401K"}).get_json()
    with client.application.app_context():
        s = db.session()
        s.add(Holding(account_id=a["id"], symbol="VTI", shares=3000, cost_basis_total=600000, market_value=900000))
        s.add(Holding(account_id=b["id"], symbol="FXAIX", shares=3000, cost_basis_total=500000, market_value=700000))
        s.commit()


def test_planned_event_crud_and_validation(client):
    r = client.post("/api/planner/events", json={"name": "Car", "kind": "PURCHASE", "amount": 45000, "start_year": 2028, "repeat_every_years": 10})
    assert r.status_code == 201
    eid = r.get_json()["id"]
    assert client.post("/api/planner/events", json={"name": "x", "kind": "BAD", "amount": 1, "start_year": 2028}).status_code == 400
    assert client.post("/api/planner/events", json={"name": "x", "kind": "PURCHASE", "amount": -5, "start_year": 2028}).status_code == 400
    upd = client.put(f"/api/planner/events/{eid}", json={"name": "Car", "kind": "PURCHASE", "amount": 50000, "start_year": 2029})
    assert upd.get_json()["amount"] == 50000
    assert [e["name"] for e in client.get("/api/planner/events").get_json()] == ["Car"]
    assert client.delete(f"/api/planner/events/{eid}").status_code == 204
    assert client.get("/api/planner/events").get_json() == []


def test_fire_returns_household_view_and_purchase_lowers_income(client):
    _setup(client)
    t = time.time()
    base = client.get("/api/planner/fire").get_json()
    elapsed = time.time() - t
    assert base["sustainable_spend_monthly"] > 0 and base["monthly_income"]
    assert set(base["earliest_ages"]) == {"SELF", "SPOUSE"}
    assert any(m["label"] == "You both retire" for m in base["timeline"])
    assert base["target_success_rate"] == 0.85
    assert base["debts"] == []
    assert elapsed < 15, f"/api/planner/fire took {elapsed:.1f}s"
    client.post("/api/planner/events", json={"name": "Cars", "kind": "PURCHASE", "amount": 60000, "start_year": 2034})
    car = client.get("/api/planner/fire").get_json()
    assert car["sustainable_spend_monthly"] < base["sustainable_spend_monthly"]


def test_what_if_query_overrides_do_not_save(client):
    _setup(client)
    later = client.get("/api/planner/fire?retire_age=60&ss_claim_age=70&sims=500").get_json()
    early = client.get("/api/planner/fire?retire_age=50&sims=500").get_json()
    assert later["success_rate"] >= early["success_rate"]
    assert client.get("/api/profile").get_json()["target_retirement_age"] == 55


def test_fire_includes_debt_payoff_schedule(client):
    _setup(client)
    client.post("/api/liabilities", json={"name": "Car loan", "kind": "AUTO", "balance": 12000, "apr": 0, "monthly_payment": 1000, "owner": "SELF"})
    debts = client.get("/api/planner/fire?sims=200").get_json()["debts"]
    assert len(debts) == 1 and debts[0]["name"] == "Car loan" and debts[0]["months"] == 12 and debts[0]["paid_before_retirement"]

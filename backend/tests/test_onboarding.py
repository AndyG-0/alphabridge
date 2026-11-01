import db
from models import Account, Holding, UserProfile
from routes._helpers import get_profile
from services import onboarding


def test_fresh_install_is_first_run_and_resumes_at_household(client):
    r = client.get("/api/onboarding").get_json()
    assert r["first_run"] and r["show"] and not r["completed"]
    assert r["current"] == "household"
    assert [s["done"] for s in r["steps"]] == [False] * 5
    assert r["completeness"]["score"] == 5  # only "spouse" (no spouse -> nothing missing) counts


def test_steps_derive_from_data_and_resume_moves_forward(client, app):
    with app.app_context():
        s = db.session()
        p = get_profile()
        p.name, p.annual_income = "Pat", 120000
        s.commit()
    r = client.get("/api/onboarding").get_json()
    assert r["steps"][0]["done"] and r["current"] == "accounts" and not r["first_run"]
    with app.app_context():
        s = db.session()
        a = Account(name="Brokerage")
        s.add(a)
        s.flush()
        s.add(Holding(account_id=a.id, symbol="VTI", shares=1, market_value=100))
        p = s.get(UserProfile, 1)
        p.monthly_expenses_retirement = 5000
        s.commit()
    r = client.get("/api/onboarding").get_json()
    assert [x["done"] for x in r["steps"]] == [True, True, True, True, False]
    assert r["current"] == "plan"


def test_skip_complete_dismiss_persist(client):
    r = client.put("/api/onboarding", json={"skip": "upload"}).get_json()
    up = next(s for s in r["steps"] if s["id"] == "upload")
    assert up["done"] and up["skipped"]
    client.put("/api/onboarding", json={"skip": "upload"})  # idempotent
    r = client.put("/api/onboarding", json={"step": "goals"}).get_json()
    assert r["current"] == "goals"
    r = client.put("/api/onboarding", json={"completed": True}).get_json()
    assert r["completed"] and not r["show"]
    assert client.put("/api/onboarding", json={"completed": False, "dismissed": True}).get_json()["show"] is False


def test_rejects_unknown_step(client):
    assert client.put("/api/onboarding", json={"step": "nope"}).status_code == 400


def test_completeness_is_weighted_and_explains_gaps(app):
    with app.app_context():
        s = db.session()
        p = get_profile()
        c0 = onboarding.completeness(s, p)
        p.annual_income, p.monthly_expenses_retirement = 100000, 4000
        s.commit()
        c1 = onboarding.completeness(s, p)
    assert c1["score"] - c0["score"] == 25  # income 10 + retirement spending 15
    weights = sum(i["weight"] for i in c1["inputs"])
    assert weights == 100
    assert c1["next_best"]["improves"]
    assert all(i["improves"] and i["where"] for i in c1["inputs"])


def test_spouse_without_ss_is_a_gap(app):
    from datetime import date

    with app.app_context():
        s = db.session()
        p = get_profile()
        p.spouse_birth_date = date(1990, 1, 1)
        s.commit()
        spouse = next(i for i in onboarding.completeness(s, p)["inputs"] if i["key"] == "spouse")
    assert not spouse["filled"]

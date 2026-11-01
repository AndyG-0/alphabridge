import io
from datetime import date

import pytest

from services import ingestion, planner
from services import pension as pension_svc

STATEMENT = """Nationwide Retirement Plan - Account Balance Account Statement
{holder} Data as of September 30, 2026
Account Balance
Plan Balance As of
Nationwide Retirement Plan -
${ending} 09/30/2026
Account Balance - Account Details as of 09/30/2026
Current Year
1/26 - 9/26
Beginning Balance ${beginning}
${total}
• Interest Credits ${interest}
• Pay Credits ${pay}
• Excess Pay Credits $0.00
Ending Balance ${ending}
View Rates
2026 2025 2024
• Interest Credits-Cash Balance - CB 0.188931%* 0.183057%* 0.156515%*
• Pay Credits-Cash Balance - CB {pct}% {pct}% 6.00%
• Excess Pay Credits-Cash Balance - CB 4.00% 4.00%
"""

ANDREA = dict(holder="ANDREA B SAMPLE", beginning="200,000.00", interest="7,200.00", pay="12,000.00", total="19,200.00", ending="219,200.00", pct="7.00")
CARLA = dict(holder="CARLA A SAMPLE", beginning="60,000.00", interest="2,250.00", pay="7,500.00", total="9,750.00", ending="69,750.00", pct="5.00")


def stmt(**kw) -> str:
    return STATEMENT.format(**kw)


def test_parse_cash_balance_statement():
    r = ingestion.parse_cash_balance_text(stmt(**ANDREA))
    p = r.pension
    assert r.rows == [] and r.confidence == "high"
    assert p.ending == 219200.00 and p.as_of == date(2026, 9, 30) and p.pay_credit_pct == 0.07 and p.months == 9
    assert p.interest_rate == pytest.approx(7200 / 200000 * 12 / 9)
    assert p.covered_pay == pytest.approx(12000 / 0.07 * 12 / 9)
    assert r.checks[0]["level"] == "ok"


def test_roll_forward_mismatch_fails():
    r = ingestion.parse_cash_balance_text(stmt(**{**ANDREA, "ending": "229,200.00"}))
    assert any(c["level"] == "fail" for c in r.checks) and r.confidence == "low"


def test_known_pdf_dispatch_skips_llm():
    assert ingestion._parse_known_pdf(stmt(**CARLA)).pension.holder_name == "Carla A Sample"


def _profile(client):
    client.put(
        "/api/profile",
        json={
            "name": "Andrew Sample",
            "birth_date": "1985-01-01",
            "target_retirement_age": 55,
            "spouse_name": "Carla Sample",
            "spouse_birth_date": "1987-01-01",
        },
    )


def _upload(client, text: str, **form):
    # the route reads PDFs; a text statement goes through the known-parser path by stubbing the reader
    return client.post("/api/ingest", data={"file": (io.BytesIO(b"%PDF-1.4"), "pension.pdf"), **form}, content_type="multipart/form-data")


@pytest.fixture
def stub_pdf(monkeypatch):
    def use(text):
        monkeypatch.setattr(ingestion.doc_reader, "read_pdf", lambda data: ingestion.doc_reader.DocContent(text=text))
        monkeypatch.setattr("security.validate_upload", lambda name, data: None)
        monkeypatch.setattr("routes.portfolio_routes.validate_upload", lambda name, data: None)

    return use


def test_upload_creates_pension_per_owner_without_holdings(client, stub_pdf):
    _profile(client)
    stub_pdf(stmt(**ANDREA))
    r = _upload(client, "")
    assert r.status_code == 201, r.get_json()
    stub_pdf(stmt(**CARLA))
    assert _upload(client, "").status_code == 201
    pens = client.get("/api/pensions").get_json()
    assert [(p["owner"], p["plan_balance"]) for p in pens] == [("SELF", 219200.0), ("SPOUSE", 69750.0)]
    assert client.get("/api/portfolio").get_json()["accounts"] == []
    stub_pdf(stmt(**ANDREA))
    _upload(client, "")  # re-import updates in place
    assert len(client.get("/api/pensions").get_json()) == 2


def test_unknown_holder_asks_for_owner(client, stub_pdf):
    _profile(client)
    stub_pdf(stmt(**{**ANDREA, "holder": "ZED OTHER"}))
    r = _upload(client, "")
    assert r.status_code == 409 and r.get_json()["needs_owner"]
    assert _upload(client, "", owner="SPOUSE").status_code == 201


def test_edit_assumptions_survive_reimport(client, stub_pdf):
    _profile(client)
    stub_pdf(stmt(**ANDREA))
    _upload(client, "")
    pid = client.get("/api/pensions").get_json()[0]["id"]
    assert client.put(f"/api/pensions/{pid}", json={"start_age": 62, "payout": "LUMP_SUM"}).status_code == 200
    _upload(client, "")
    p = client.get("/api/pensions").get_json()[0]
    assert p["start_age"] == 62 and p["payout"] == "LUMP_SUM"


def test_projection_properties():
    args = dict(balance=100_000, nominal_rate=0.05, annual_credit=10_000, years_to_start=20)
    short = pension_svc.project_balance(years_working=5, **args)
    long = pension_svc.project_balance(years_working=15, **args)
    assert long > short > pension_svc.project_balance(years_working=0, **args)
    assert pension_svc.project_balance(100_000, 0.05, 10_000, 0, 0) == 100_000
    m = pension_svc.monthly_annuity(500_000, 65)
    assert m * 12 * 30 > 500_000 and m < 500_000 / 12 / 10  # pays out more than the balance (1% real interest) over 30 years
    assert pension_svc.monthly_annuity(500_000, 60) < m  # longer payout, smaller check


def test_planner_pension_income_moves_with_retirement_age(client, stub_pdf):
    _profile(client)
    client.put("/api/profile", json={"monthly_expenses_retirement": 6000})
    stub_pdf(stmt(**ANDREA))
    _upload(client, "")
    from routes._helpers import get_profile

    with client.application.app_context():
        p = get_profile()
        import db
        from models import Pension

        pens = db.session().query(Pension).all()
        early = pension_svc.virtual_events(pens, p, 50)[0].amount
        late = pension_svc.virtual_events(pens, p, 62)[0].amount
        assert late > early > 0
        assert pension_svc.virtual_events(pens, p, 55)[0].kind == "PENSION"
        with_pension = planner.run_fire(p, n_sims=1000, detail=False)["success_rate"]
        for row in pens:
            db.session().delete(row)
        db.session().commit()
        without = planner.run_fire(p, n_sims=1000, detail=False)["success_rate"]
        assert with_pension >= without

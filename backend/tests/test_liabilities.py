from datetime import date
from types import SimpleNamespace

import services.liabilities as L
import services.quant_engine as qe


def _l(**kw):
    d = dict(id=1, name="x", kind="OTHER", balance=100_000, apr=0.05, monthly_payment=1000, payoff_date=None, escrow_monthly=0)
    d.update(kw)
    return SimpleNamespace(**d, to_dict=lambda: d)


def test_amortize_matches_known_loan():
    r = L.amortize(200_000, 0.06, 1199.10)  # ~30y mortgage
    assert 359 <= r["months"] <= 361


def test_amortize_never_pays_off():
    assert L.amortize(10_000, 0.24, 100)["months"] is None


def test_schedule_ends_at_payoff_and_escrow_persists():
    m = _l(balance=50_000, apr=0.0, monthly_payment=1000, escrow_monthly=500)
    out = L.debt_service_by_year([m], 6, today=date(2026, 1, 1))
    assert out[0] == 12_000 and out[3] == 12_000 and out[4] == 2_000 and out[5] == 0
    assert L.escrow_monthly([m]) == 500


def test_payoff_date_overrides_amortization():
    m = _l(payoff_date=date(2028, 1, 1))
    assert L.months_remaining(m, date(2026, 1, 1)) == 24


def test_paydown_rules():
    mmf, eq = 0.045, 0.075
    assert L.paydown_vs_invest(_l(apr=0.22), mmf, eq)["action"] == "PAY_DOWN"
    assert L.paydown_vs_invest(_l(apr=0.03), mmf, eq)["action"] == "INVEST"
    assert L.paydown_vs_invest(_l(apr=0.05), mmf, eq)["action"] == "SPLIT"
    assert L.paydown_vs_invest(_l(apr=0.07), mmf, eq)["action"] == "PAY_DOWN"


def _inp(**kw):
    d = dict(
        current_age=40,
        retire_age=45,
        taxable=1_500_000,
        pretax=1_000_000,
        annual_contribution_bridge=0,
        annual_contribution_pretax=0,
        retirement_spend=50_000,
        tax_rate=0.15,
        mu_taxable=0.05,
        sigma_taxable=0.12,
        mu_pretax=0.06,
        sigma_pretax=0.12,
    )
    d.update(kw)
    return qe.FireInputs(**d)


def test_no_debt_is_backward_compatible():
    a = qe.simulate_fire(_inp(), n_sims=400)
    b = qe.simulate_fire(_inp(debt_service_by_year=None), n_sims=400)
    assert a["median_final_real"] == b["median_final_real"]
    assert qe.bridge_capital_needed(45, 50_000, 0.15) == qe.bridge_capital_needed(45, 50_000, 0.15, debt_real_by_year=[])


def test_debt_service_raises_need_and_lowers_outcome():
    debt = [24_000.0] * 55
    assert qe.bridge_capital_needed(45, 50_000, 0.15, debt_real_by_year=debt) > qe.bridge_capital_needed(45, 50_000, 0.15)
    assert qe.simulate_fire(_inp(debt_service_by_year=debt), n_sims=400)["median_final_real"] < qe.simulate_fire(_inp(), n_sims=400)["median_final_real"]


def test_liability_api_and_networth(client):
    j = client.post("/api/liabilities", json={"name": "Visa", "kind": "CARD", "balance": 5000, "apr": 0.22, "monthly_payment": 200}).get_json()
    assert client.post("/api/liabilities", json={"name": "x", "kind": "BAD"}).status_code == 400
    assert client.get("/api/portfolio").get_json()["liabilities"] == 5000
    d = client.get("/api/planner/debt").get_json()
    assert d["liabilities"][0]["recommendation"]["action"] == "PAY_DOWN"
    assert client.get("/api/planner/fire?sims=200").status_code == 200
    assert client.delete(f"/api/liabilities/{j['id']}").status_code == 204
    assert client.get("/api/liabilities").get_json() == []


def test_liability_edit(client):
    j = client.post("/api/liabilities", json={"name": "Car", "kind": "AUTO", "balance": 20000, "apr": 0.05, "monthly_payment": 400}).get_json()
    # The UI sends back the full saved record with changed fields.
    r = client.put(f"/api/liabilities/{j['id']}", json={**j, "name": "Car loan", "balance": 18000, "apr": 0.045})
    assert r.status_code == 200
    assert r.get_json()["name"] == "Car loan"
    [saved] = client.get("/api/liabilities").get_json()
    assert (saved["balance"], saved["apr"], saved["monthly_payment"]) == (18000, 0.045, 400)
    assert client.get("/api/portfolio").get_json()["liabilities"] == 18000
    assert client.put(f"/api/liabilities/{j['id']}", json={**j, "apr": 2}).status_code == 400
    assert client.put("/api/liabilities/99999", json={"name": "x"}).status_code == 404


def test_csv_parse_and_upsert(client):
    csv_text = (
        'Account Name,Current Balance,Interest Rate,Monthly Payment\nHome Mortgage,"$310,000.00",3.25%,1850\n'
        "Chase Freedom Visa 1234,2400,22.99,150\nTotal,312400,,\n"
    )
    r = client.post("/api/liabilities/ingest", data={"file": (__import__("io").BytesIO(csv_text.encode()), "debts.csv")})
    assert r.status_code == 201 and len(r.get_json()["created"]) == 2
    d = {x["name"]: x for x in client.get("/api/liabilities").get_json()}
    assert d["Home Mortgage"]["kind"] == "MORTGAGE" and abs(d["Home Mortgage"]["apr"] - 0.0325) < 1e-9
    assert d["Chase Freedom Visa 1234"]["kind"] == "CARD"
    lid = d["Home Mortgage"]["id"]
    client.put(f"/api/liabilities/{lid}", json={**d["Home Mortgage"], "escrow_monthly": 650, "payoff_date": "2049-03-01"})
    csv2 = csv_text.replace("310,000.00", "309,000.00")
    r2 = client.post("/api/liabilities/ingest", data={"file": (__import__("io").BytesIO(csv2.encode()), "again.csv")}).get_json()
    assert r2["created"] == [] and len(r2["updated"]) == 2
    m = next(x for x in client.get("/api/liabilities").get_json() if x["id"] == lid)
    assert m["balance"] == 309_000 and m["escrow_monthly"] == 650 and m["payoff_date"] == "2049-03-01"


def test_pdf_text_extraction_converts_percent_in_code():
    import services.liability_ingest as LI

    fake = LI._PdfDebts(debts=[LI._PdfDebt(name="Wells Fargo Auto 9876", kind="auto", balance=18_000, apr_percent=5.9, principal_and_interest_payment=520)])
    res = LI.debts_from_text("stmt text", lambda sys, usr: fake)
    assert res.debts[0].kind == "AUTO" and abs(res.debts[0].apr - 0.059) < 1e-9


def test_no_debts_found_is_422(client):
    r = client.post("/api/liabilities/ingest", data={"file": (__import__("io").BytesIO(b"a,b\n1,2\n"), "x.csv")})
    assert r.status_code == 422


def test_extra_payment_shortens_payoff_and_saves_interest():
    base = L.amortize(200_000, 0.06, 1199.10)
    eff = L.extra_payment_effect(_l(balance=200_000, apr=0.06, monthly_payment=1199.10, extra_monthly_payment=300))
    assert eff["months_with_extra"] < base["months"] - 100
    assert eff["months_saved"] == base["months"] - eff["months_with_extra"]
    assert 50_000 < eff["interest_saved"] < base["total_interest"]


def test_extra_payment_stops_at_retirement():
    liab = _l(balance=200_000, apr=0.06, monthly_payment=1199.10, extra_monthly_payment=300)
    always = L.monthly_schedule(liab, 400)
    until = L.monthly_schedule(liab, 400, extra_stop_month=60)
    assert until[59] == 1499.10 and until[60] == 1199.10
    assert (until > 0).sum() - (always > 0).sum() > 0  # stopping early pays off later
    assert (until > 0).sum() < 360


def test_debt_service_by_year_honors_extra_until():
    liab = _l(balance=50_000, apr=0.05, monthly_payment=500, extra_monthly_payment=500, extra_payment_until="RETIREMENT")
    to_ret = L.debt_service_by_year([liab], 3, extra_stop_month=12)
    assert to_ret[0] == 12_000 and to_ret[1] == 6_000
    liab.extra_payment_until = "PAYOFF"
    assert L.debt_service_by_year([liab], 3, extra_stop_month=12)[1] == 12_000


def test_no_extra_payment_is_unchanged():
    liab = _l()
    assert L.extra_payment_effect(liab) is None
    assert list(L.debt_service_by_year([liab], 2)) == [12_000, 12_000]

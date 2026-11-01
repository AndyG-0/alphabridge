import services.quant_engine as qe


def _inp(**kw):
    d = dict(
        current_age=40,
        retire_age=50,
        taxable=400_000,
        pretax=300_000,
        annual_contribution_bridge=0,
        annual_contribution_pretax=0,
        retirement_spend=60_000,
        tax_rate=0.15,
        mu_taxable=0.05,
        sigma_taxable=0.12,
        mu_pretax=0.06,
        sigma_pretax=0.12,
    )
    d.update(kw)
    return qe.FireInputs(**d)


def test_younger_spouse_pool_unlocks_later_than_primary():
    base = qe.simulate_fire(_inp(pretax=0, pretax_spouse=500_000, spouse_unlock_age=59.5), n_sims=800)
    older = qe.simulate_fire(_inp(pretax=0, pretax_spouse=500_000, spouse_unlock_age=52.0), n_sims=800)
    assert older["success_rate"] >= base["success_rate"]


def test_no_spouse_pool_is_backward_compatible():
    a = qe.simulate_fire(_inp(), n_sims=500)
    b = qe.simulate_fire(_inp(pretax_spouse=0.0, spouse_unlock_age=None), n_sims=500)
    assert a["success_rate"] == b["success_rate"] and a["median_final_real"] == b["median_final_real"]


def test_account_owner_and_profile_roundtrip(client):
    r = client.put("/api/profile", json={"spouse_name": "S", "spouse_birth_date": "1988-01-01", "spouse_annual_income": 90000, "social_security_monthly": 3500})
    j = r.get_json()
    assert j["spouse_birth_date"] == "1988-01-01" and j["spouse_age"] > 30
    aid = client.post("/api/accounts", json={"name": "Spouse 401k", "owner": "SPOUSE", "tax_bucket": "PRE_TAX_401K"}).get_json()["id"]
    assert client.get("/api/portfolio").get_json()["accounts"][0]["owner"] == "SPOUSE"
    assert client.put(f"/api/accounts/{aid}", json={"name": "Spouse 401k", "owner": "BAD"}).status_code == 400
    assert client.get("/api/planner/fire?sims=200").status_code == 200


def test_clear_spouse_birth_date(client):
    client.put("/api/profile", json={"spouse_birth_date": "1988-01-01"})
    j = client.put("/api/profile", json={"spouse_birth_date": None}).get_json()
    assert j["spouse_birth_date"] is None and j["spouse_age"] == 0


def test_spouse_social_security_helps_and_defaults_are_neutral():
    base = qe.simulate_fire(_inp(retirement_spend=45_000), n_sims=800)
    zero = qe.simulate_fire(_inp(retirement_spend=45_000, other_income_spouse=0.0, other_income_spouse_start=67), n_sims=800)
    with_ss = qe.simulate_fire(_inp(retirement_spend=45_000, other_income_spouse=20_000, other_income_spouse_start=55), n_sims=800)
    assert base["success_rate"] == zero["success_rate"] and base["median_final_real"] == zero["median_final_real"]
    assert with_ss["success_rate"] > base["success_rate"]


def test_spouse_ss_profile_roundtrip_and_ignored_without_spouse(client):
    j = client.put("/api/profile", json={"spouse_social_security_monthly": 1800, "spouse_target_retirement_age": 55}).get_json()
    assert j["spouse_social_security_monthly"] == 1800 and j["spouse_target_retirement_age"] == 55
    assert j["spouse_age"] == 0  # no spouse birth date -> engine ignores the benefit
    assert client.get("/api/planner/fire?sims=200").status_code == 200
